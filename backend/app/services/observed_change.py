"""Describe sample means across windows; no clinical interpretation."""

from collections import Counter
from datetime import date, timezone
from math import isfinite
from statistics import fmean

from ..clients.open_wearables import OpenWearablesClient
from ..config import Settings
from ..schemas.observed_change import (
    ComparisonPolicy, ComparisonWindow, MetricComparison, ObservedChange, SourceProvenance,
)
from ..schemas.patient import Patient
from ..schemas.timeline import TimelineEntry
from .timeline import METRICS, _instant, build_timeline

ANALYZED_METRICS = {
    "blood_glucose": "Blood glucose",
    "blood_pressure_systolic": "Systolic blood pressure",
    "blood_pressure_diastolic": "Diastolic blood pressure",
    "resting_heart_rate": "Resting heart rate",
    "heart_rate_variability_sdnn": "Heart rate variability (SDNN)",
    "skin_temperature": "Skin temperature",
    "body_temperature": "Body temperature",
    "weight": "Weight",
}


def validate_windows(
    reference_start: date, reference_end: date, recent_start: date, recent_end: date
) -> None:
    if reference_start > reference_end or recent_start > recent_end:
        raise ValueError("Each window's start must be on or before its end")
    if reference_end >= recent_start:
        raise ValueError("The reference window must end before the recent window starts")


def _source_key(entry: TimelineEntry) -> tuple[str | None, ...]:
    return entry.provider, entry.source, entry.device, entry.device_type


def _provenance(entries: list[TimelineEntry]) -> list[SourceProvenance]:
    counts = Counter(_source_key(entry) for entry in entries)
    return [
        SourceProvenance(
            provider=key[0], source=key[1], device=key[2], device_type=key[3], sample_count=count
        )
        for key, count in sorted(counts.items(), key=lambda item: tuple(part or "" for part in item[0]))
    ]


def _window_summary(
    entries: list[TimelineEntry], end: date, label: str, settings: Settings
) -> tuple[float | None, str | None, list[str]]:
    if not entries:
        return None, None, [f"missing_{label}_data"]
    reasons = []
    if len(entries) < settings.observed_change_min_samples:
        reasons.append(f"too_few_{label}_samples")
    latest = max(entries, key=lambda entry: _instant(entry.timestamp))
    latest_day = _instant(latest.timestamp).astimezone(timezone.utc).date()
    if (end - latest_day).days > settings.observed_change_max_staleness_days:
        reasons.append(f"stale_{label}_data")

    mean = None
    units = {entry.unit for entry in entries}
    if len(units) == 1 and next(iter(units)):
        try:
            mean = fmean(entry.value for entry in entries)
            if not isfinite(mean):
                mean = None
        except OverflowError:
            mean = None
        if mean is None:
            reasons.append(f"non_finite_{label}_mean")
    return mean, latest.timestamp, reasons


def _compare_metric(
    metric: str, reference: list[TimelineEntry], recent: list[TimelineEntry],
    reference_end: date, recent_end: date, settings: Settings,
) -> MetricComparison:
    reference_mean, reference_latest, reasons = _window_summary(reference, reference_end, "reference", settings)
    recent_mean, recent_latest, recent_reasons = _window_summary(recent, recent_end, "recent", settings)
    reasons.extend(recent_reasons)
    units = {entry.unit for entry in [*reference, *recent]}
    available_units = sorted(unit for unit in units if unit)
    if any(not unit for unit in units):
        reasons.append("missing_unit")
    if len(available_units) > 1:
        reasons.append("incompatible_units")
    unit = available_units[0] if len(available_units) == 1 and not any(not unit for unit in units) else None

    enough_data = not reasons
    change = None
    percent = None
    percent_reason = "insufficient_data"
    if enough_data:
        change = recent_mean - reference_mean
        if not isfinite(change):
            change = None
            enough_data = False
            reasons.append("non_finite_absolute_change")
        else:
            if reference_mean == 0:
                percent_reason = "zero_reference_mean"
            elif reference_mean < 0:
                percent_reason = "negative_reference_mean"
            elif metric in ("skin_temperature", "body_temperature") and unit.casefold() not in ("k", "kelvin"):
                percent_reason = "temperature_unit_not_ratio_scale"
            else:
                percent = change / reference_mean * 100
                percent_reason = None
                if not isfinite(percent):
                    percent = None
                    percent_reason = "non_finite_percent_change"

    return MetricComparison(
        metric_type=metric,
        metric_name=ANALYZED_METRICS[metric],
        metric_definition=METRICS[metric],
        unit=unit,
        available_units=available_units,
        reference_units=sorted({entry.unit for entry in reference if entry.unit}),
        recent_units=sorted({entry.unit for entry in recent if entry.unit}),
        reference_sample_count=len(reference),
        recent_sample_count=len(recent),
        reference_mean=reference_mean,
        recent_mean=recent_mean,
        absolute_change=change,
        percent_change=percent,
        percent_change_unavailable_reason=percent_reason,
        reference_latest_timestamp=reference_latest,
        recent_latest_timestamp=recent_latest,
        reference_provenance=_provenance(reference),
        recent_provenance=_provenance(recent),
        provenance_changed={_source_key(entry) for entry in reference} != {_source_key(entry) for entry in recent},
        enough_data=enough_data,
        status="compared" if enough_data else "insufficient_data",
        reasons=reasons,
    )


async def build_observed_change(
    patient: Patient, client: OpenWearablesClient, settings: Settings,
    reference_start: date, reference_end: date, recent_start: date, recent_end: date,
) -> ObservedChange:
    validate_windows(reference_start, reference_end, recent_start, recent_end)
    timeline = await build_timeline(patient, client, reference_start, recent_end)
    reference = {metric: [] for metric in ANALYZED_METRICS}
    recent = {metric: [] for metric in ANALYZED_METRICS}
    for entry in timeline.entries:
        if entry.kind != "measurement" or entry.origin != "open_wearables" or entry.metric_type not in ANALYZED_METRICS:
            continue
        day = _instant(entry.timestamp).astimezone(timezone.utc).date()
        if reference_start <= day <= reference_end:
            reference[entry.metric_type].append(entry)
        elif recent_start <= day <= recent_end:
            recent[entry.metric_type].append(entry)

    return ObservedChange(
        patient_id=patient.patient_id,
        synthetic=patient.synthetic,
        reference_window=ComparisonWindow(start_date=reference_start, end_date=reference_end),
        recent_window=ComparisonWindow(start_date=recent_start, end_date=recent_end),
        policy=ComparisonPolicy(
            minimum_samples_per_window=settings.observed_change_min_samples,
            max_staleness_days=settings.observed_change_max_staleness_days,
        ),
        metrics=[
            _compare_metric(metric, reference[metric], recent[metric], reference_end, recent_end, settings)
            for metric in ANALYZED_METRICS
        ],
    )
