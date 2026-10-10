"""Compose existing services; section failures never imply normal measurements."""

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import TypeVar

from starlette.concurrency import run_in_threadpool

from ..clients.open_wearables import OpenWearablesClient, OpenWearablesError
from ..config import Settings
from ..schemas.dashboard import (
    DashboardDataQuality, DashboardSectionQuality, DashboardSleepSummary,
    LatestMeasurement, PatientDashboard,
)
from ..schemas.observed_change import ComparisonWindow
from ..schemas.patient import Patient
from ..schemas.timeline import PatientTimeline, TimelineEntry
from .bp_forecast import BPForecastError, get_bp_forecast
from .glucose_forecast import GlucoseForecastError, get_glucose_forecast
from .observed_change import (
    ANALYZED_METRICS, analyze_observed_change, sample_age_days, validate_windows,
)
from .pattern_status import analyze_pattern
from .timeline import METRICS, _instant, assemble_timeline, normalize_device_records

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _failure(section: str, exc: Exception) -> DashboardSectionQuality:
    if isinstance(exc, (OpenWearablesError, GlucoseForecastError, BPForecastError)):
        reason = str(exc)
    else:
        logger.error("Dashboard section %s failed", section,
                     exc_info=(type(exc), exc, exc.__traceback__))
        reason = "unexpected_section_failure"
    return DashboardSectionQuality(status="unavailable", reasons=[reason])


async def _optional_service(
    section: str, operation: Callable[..., T], *args,
) -> tuple[T | None, DashboardSectionQuality]:
    try:
        # Existing cached forecasting functions may perform CPU work on first use.
        result = await run_in_threadpool(operation, *args)
        return result, DashboardSectionQuality(status="available")
    except Exception as exc:
        return None, _failure(section, exc)


async def _wearable_entries(
    client: OpenWearablesClient, start: date, end: date, *, sleep: bool = False,
) -> tuple[list[TimelineEntry], DashboardSectionQuality]:
    try:
        records = (await client.get_sleep(start, end) if sleep else
                   await client.get_timeseries(start, end, types=list(METRICS)))
        return normalize_device_records(records, sleep=sleep), DashboardSectionQuality(status="available")
    except Exception as exc:
        return [], _failure("open_wearables_sleep" if sleep else "open_wearables_timeseries", exc)


def _latest_measurements(
    timeline: PatientTimeline, quality: DashboardSectionQuality, settings: Settings,
) -> tuple[dict[str, LatestMeasurement], DashboardSectionQuality]:
    latest = {}
    for entry in timeline.entries:
        if entry.origin == "open_wearables" and entry.kind == "measurement" and entry.metric_type in ANALYZED_METRICS:
            previous = latest.get(entry.metric_type)
            if previous is None or _instant(entry.timestamp) > _instant(previous.timestamp):
                latest[entry.metric_type] = entry
    measurements = {}
    for metric in ANALYZED_METRICS:
        entry = latest.get(metric)
        if quality.status == "unavailable":
            status, reasons = "unavailable", quality.reasons
        elif entry is None:
            status, reasons = "missing", ["missing_measurement_in_requested_range"]
        elif sample_age_days(entry.timestamp, timeline.end_date) > settings.observed_change_max_staleness_days:
            status, reasons = "stale", ["stale_measurement_relative_to_end_date"]
        else:
            status, reasons = "available", []
        measurements[metric] = LatestMeasurement(
            metric_type=metric, metric_definition=METRICS[metric], status=status, reasons=reasons,
            **({field: getattr(entry, field) for field in
                ("value", "unit", "timestamp", "provider", "source", "device", "device_type")}
               if entry is not None else {}),
        )
    if quality.status == "unavailable":
        return measurements, quality
    issues = {metric: row.reasons for metric, row in measurements.items() if row.status != "available"}
    return measurements, DashboardSectionQuality(
        status="available" if not issues else "partial" if len(issues) < len(measurements) else "insufficient_data",
        reasons=["missing_or_stale_latest_measurements"] if issues else [], metric_reasons=issues,
    )


def _sleep_summary(
    timeline: PatientTimeline, quality: DashboardSectionQuality, settings: Settings,
) -> tuple[DashboardSleepSummary, DashboardSectionQuality]:
    # The timeline already applies the existing session-end timestamp convention.
    entries = [entry for entry in timeline.entries if entry.kind == "sleep" and entry.origin == "open_wearables"]
    latest = max(entries, key=lambda entry: _instant(entry.timestamp), default=None)
    if quality.status == "unavailable":
        status, reasons = "unavailable", quality.reasons
    elif latest is None:
        status, reasons = "missing", ["missing_recent_sleep_data"]
    elif sample_age_days(latest.timestamp, timeline.end_date) > settings.observed_change_max_staleness_days:
        status, reasons = "stale", ["stale_sleep_relative_to_recent_end"]
    else:
        status, reasons = "available", []
    summary = DashboardSleepSummary(
        window=ComparisonWindow(start_date=timeline.start_date, end_date=timeline.end_date), status=status,
        latest_session=latest, session_count=None if status == "unavailable" else len(entries), reasons=reasons,
    )
    return summary, DashboardSectionQuality(
        status="available" if status == "available" else "unavailable" if status == "unavailable" else "insufficient_data",
        reasons=reasons,
    )


async def build_dashboard(
    patient: Patient, client: OpenWearablesClient, settings: Settings,
    start_date: date, end_date: date,
    reference_start: date, reference_end: date, recent_start: date, recent_end: date,
) -> PatientDashboard:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    validate_windows(reference_start, reference_end, recent_start, recent_end)
    fetch_start, fetch_end = min(start_date, reference_start), max(end_date, recent_end)
    timeseries_result, sleep_result, glucose_result, bp_result = await asyncio.gather(
        _wearable_entries(client, fetch_start, fetch_end),
        _wearable_entries(client, fetch_start, fetch_end, sleep=True),
        _optional_service("glucose_forecast", get_glucose_forecast),
        _optional_service("bp_forecast", get_bp_forecast,
                          settings.bp_review_systolic_threshold, settings.bp_review_diastolic_threshold),
    )
    measurements, measurement_quality = timeseries_result
    sessions, sleep_quality = sleep_result
    glucose, glucose_quality = glucose_result
    bp, bp_quality = bp_result
    device_entries = [*measurements, *sessions]
    timeline = assemble_timeline(patient, device_entries, start_date, end_date)
    analysis_timeline = assemble_timeline(patient, device_entries, reference_start, recent_end)
    recent_timeline = assemble_timeline(patient, device_entries, recent_start, recent_end)
    latest, latest_quality = _latest_measurements(timeline, measurement_quality, settings)
    sleep_summary, summary_quality = _sleep_summary(recent_timeline, sleep_quality, settings)

    if measurement_quality.status == "unavailable":
        observed = pattern = None
        observed_quality = pattern_quality = measurement_quality
    else:
        args = (analysis_timeline, settings, reference_start, reference_end, recent_start, recent_end)
        (observed, observed_quality), (pattern, pattern_quality) = await asyncio.gather(
            _optional_service("observed_change", analyze_observed_change, *args),
            _optional_service("pattern_status", analyze_pattern, *args),
        )
    if observed is not None:
        issues = {row.metric_type: row.reasons for row in observed.metrics if not row.enough_data}
        observed_quality = DashboardSectionQuality(
            status="available" if not issues else "partial" if len(issues) < len(observed.metrics) else "insufficient_data",
            reasons=["metrics_have_insufficient_comparison_data"] if issues else [], metric_reasons=issues,
        )
    if pattern is not None:
        pattern_quality = DashboardSectionQuality(
            status="insufficient_data" if pattern.status == "insufficient_data" else
                   "partial" if pattern.data_quality.coverage == "partial" or sleep_quality.status == "unavailable" else "available",
            reasons=(pattern.reasons if pattern.data_quality.coverage != "complete" else []) +
                    (sleep_quality.reasons if sleep_quality.status == "unavailable" else []),
            metric_reasons=pattern.data_quality.reasons_by_signal,
        )
    if bp is not None and bp.status == "insufficient_data":
        bp_quality = DashboardSectionQuality(status="insufficient_data", reasons=bp.reasons)
    upstream_reasons = measurement_quality.reasons + sleep_quality.reasons
    sections = {
        "patient": DashboardSectionQuality(status="available"),
        "latest_measurements": latest_quality,
        "timeline": DashboardSectionQuality(status="partial" if upstream_reasons else "available", reasons=upstream_reasons),
        "observed_change": observed_quality, "pattern_status": pattern_quality,
        "glucose_forecast": glucose_quality, "bp_forecast": bp_quality, "sleep_summary": summary_quality,
    }
    if all(sections[name].status in ("insufficient_data", "unavailable")
           for name in ("latest_measurements", "observed_change", "pattern_status")):
        overall = "insufficient_data"
    else:
        overall = "complete" if all(row.status == "available" for row in sections.values()) else "partial"
    return PatientDashboard(
        patient=patient, latest_measurements=latest, timeline=timeline,
        observed_change=observed, pattern_status=pattern, glucose_forecast=glucose,
        bp_forecast=bp, sleep_summary=sleep_summary,
        data_quality=DashboardDataQuality(
            status=overall, max_staleness_days=settings.observed_change_max_staleness_days,
            missing_measurements=[metric for metric, row in latest.items() if row.status == "missing"],
            stale_measurements=[metric for metric, row in latest.items() if row.status == "stale"],
            sections=sections,
            unavailable_sections={name: row.reasons for name, row in sections.items()
                                  if row.status in ("unavailable", "insufficient_data")},
        ),
    )
