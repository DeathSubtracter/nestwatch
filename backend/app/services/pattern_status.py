"""Deterministic relative-change rules, not a medical alert or disease model."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from math import isfinite
from statistics import pstdev
from typing import Literal

from ..clients.open_wearables import OpenWearablesClient
from ..config import Settings
from ..schemas.observed_change import ComparisonWindow
from ..schemas.patient import Patient
from ..schemas.pattern_status import (
    ConcurrentPatternDay, DailyPatternChange, PatternDataQuality, PatternPolicy,
    PatternSignal, PatternStatus, SignalPersistence,
)
from ..schemas.timeline import PatientTimeline, TimelineEntry
from .observed_change import compare_metric, partition_windows, validate_windows
from .timeline import _instant, build_timeline


@dataclass(frozen=True)
class SignalSpec:
    metric: str
    group: str
    direction: Literal["increase", "decrease", "either"]
    context_only: bool = False
    sleep_field: str | None = None


SIGNALS = (
    SignalSpec("blood_glucose", "glucose", "increase"),
    SignalSpec("blood_pressure_systolic", "blood_pressure", "increase"),
    SignalSpec("blood_pressure_diastolic", "blood_pressure", "increase"),
    SignalSpec("resting_heart_rate", "resting_heart_rate", "increase"),
    SignalSpec("heart_rate_variability_sdnn", "heart_rate_variability", "decrease"),
    SignalSpec("sleep_duration", "sleep", "decrease", sleep_field="sleep_duration_seconds"),
    SignalSpec("sleep_efficiency", "sleep", "decrease", sleep_field="efficiency_percent"),
    SignalSpec("skin_temperature", "temperature", "either", context_only=True),
    SignalSpec("body_temperature", "temperature", "either", context_only=True),
)


def _day(entry: TimelineEntry) -> date:
    return _instant(entry.timestamp).astimezone(timezone.utc).date()


def _runs(days: list[date]) -> tuple[int, int]:
    longest = current = 0
    previous = None
    for day in sorted(set(days)):
        current = current + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, current)
        previous = day
    return longest, current


def _directional(value: float, direction: str) -> float:
    return -value if direction == "decrease" else abs(value) if direction == "either" else value


def _entries(window: list[TimelineEntry], spec: SignalSpec) -> tuple[list[TimelineEntry], int]:
    if spec.sleep_field is None:
        return [entry for entry in window if entry.origin == "open_wearables"
                and entry.kind == "measurement" and entry.metric_type == spec.metric], 0
    entries, rejected = [], 0
    for entry in window:
        if entry.origin != "open_wearables" or entry.kind != "sleep" or entry.details.get("is_nap") is True:
            continue
        value = entry.value.get(spec.sleep_field)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
                or value < 0 or (spec.metric == "sleep_efficiency" and value > 100)):
            rejected += 1
            continue
        # Session length/time in bed is not substituted for actual sleep duration.
        entries.append(entry.model_copy(update={
            "kind": "measurement", "metric_type": spec.metric, "value": value,
            "unit": "s" if spec.metric == "sleep_duration" else "%",
        }))
    return entries, rejected


def _labels(spec: SignalSpec) -> dict[str, str]:
    if spec.metric == "sleep_duration":
        return {"metric_name": "Sleep duration", "metric_definition": "Source-reported actual sleep duration of non-nap sessions."}
    if spec.metric == "sleep_efficiency":
        return {"metric_name": "Sleep efficiency", "metric_definition": "Source-reported efficiency percentage of non-nap sessions."}
    return {}


def _analyze_signal(
    spec: SignalSpec, reference: list[TimelineEntry], recent: list[TimelineEntry],
    settings: Settings, reference_end: date, recent_end: date,
) -> PatternSignal:
    reference, rejected_reference = _entries(reference, spec)
    recent, rejected_recent = _entries(recent, spec)
    labels = _labels(spec)
    comparison = compare_metric(spec.metric, reference, recent, reference_end, recent_end, settings, **labels)
    reference_days = sorted({_day(entry) for entry in reference})
    recent_days = sorted({_day(entry) for entry in recent})
    blockers = list(comparison.reasons)
    if len(reference_days) < settings.pattern_min_days_per_window:
        blockers.append("too_few_reference_days")
    if len(recent_days) < settings.pattern_min_days_per_window:
        blockers.append("too_few_recent_days")
    if comparison.provenance_changed:
        blockers.append("source_or_device_changed")

    reference_std = scale = normalized = directional = None
    if not blockers:
        try:
            reference_std = float(pstdev(entry.value for entry in reference))
            # Temperature has an arbitrary zero in C/F: use variability only.
            floor = 0.0 if spec.context_only else abs(comparison.reference_mean) * settings.pattern_relative_scale_floor
            scale = max(reference_std, floor)
            if scale <= 0 or not isfinite(scale):
                blockers.append("zero_or_invalid_normalization_scale")
            else:
                normalized = comparison.absolute_change / scale
                directional = _directional(normalized, spec.direction)
                if not isfinite(normalized) or not isfinite(directional):
                    normalized = directional = None
                    blockers.append("non_finite_normalized_change")
        except (OverflowError, ValueError):
            blockers.append("non_finite_reference_variability")
    usable = not blockers
    changed = directional >= settings.pattern_normalized_change_threshold if usable else None
    daily_changes, qualifying_days = [], []
    if usable:
        by_day = defaultdict(list)
        for entry in recent:
            by_day[_day(entry)].append(entry)
        daily_settings = settings.model_copy(update={"observed_change_min_samples": settings.pattern_min_samples_per_day})
        for day, entries in sorted(by_day.items()):
            daily = compare_metric(spec.metric, reference, entries, reference_end, day, daily_settings, **labels)
            daily_normalized = daily_directional = None
            daily_reasons = list(daily.reasons)
            if daily.enough_data:
                daily_normalized = daily.absolute_change / scale
                daily_directional = _directional(daily_normalized, spec.direction)
                if not isfinite(daily_normalized) or not isfinite(daily_directional):
                    daily_normalized = daily_directional = None
                    daily_reasons.append("non_finite_daily_change")
            qualifying = not daily_reasons and daily_directional is not None and daily_directional >= settings.pattern_normalized_change_threshold
            if qualifying:
                qualifying_days.append(day)
            daily_changes.append(DailyPatternChange(
                date=day, sample_count=len(entries), mean=daily.recent_mean,
                normalized_change=daily_normalized, directional_normalized_change=daily_directional,
                qualifying=qualifying, reasons=daily_reasons,
            ))
    longest, latest = _runs(qualifying_days)
    last = qualifying_days[-1] if qualifying_days else None
    # A later stable or undersampled day ends the active run.
    if recent_days and last != recent_days[-1]:
        latest = 0
    persistent = latest >= settings.pattern_persistence_days and last is not None and (recent_end - last).days <= settings.observed_change_max_staleness_days
    contributing = usable and changed and persistent and not spec.context_only
    reasons = blockers.copy()
    if usable:
        if spec.context_only:
            reasons.append("context_only_not_used_for_escalation")
        elif not changed:
            reasons.append("below_directional_change_threshold")
        elif not persistent:
            reasons.append("change_not_persistent_at_window_end")
    if rejected_reference or rejected_recent:
        reasons.append("missing_or_invalid_sleep_values_excluded")
    if any(source.provider is None or source.provider == "unknown"
           for source in comparison.reference_provenance + comparison.recent_provenance):
        reasons.append("unknown_provider_provenance")
    return PatternSignal(
        metric_type=spec.metric, metric_name=comparison.metric_name, group=spec.group,
        role="context" if spec.context_only else "primary", direction=spec.direction,
        comparison=comparison, reference_std=reference_std, normalization_scale=scale,
        normalized_change=normalized, directional_normalized_change=directional,
        contribution=max(0.0, directional) if contributing else 0.0 if usable else None,
        changed=changed, contributing=bool(contributing), usable=usable,
        rejected_reference_samples=rejected_reference, rejected_recent_samples=rejected_recent,
        persistence=SignalPersistence(
            reference_observed_days=reference_days, recent_observed_days=recent_days,
            qualifying_recent_days=qualifying_days, longest_consecutive_days=longest,
            latest_consecutive_days=latest, required_consecutive_days=settings.pattern_persistence_days,
            last_qualifying_date=last, meets_persistence=persistent, daily_changes=daily_changes,
        ),
        reasons=reasons,
    )


def analyze_pattern(
    timeline: PatientTimeline, settings: Settings, reference_start: date, reference_end: date,
    recent_start: date, recent_end: date,
) -> PatternStatus:
    validate_windows(reference_start, reference_end, recent_start, recent_end)
    reference, recent = partition_windows(timeline.entries, reference_start, reference_end, recent_start, recent_end)
    signals = [_analyze_signal(spec, reference, recent, settings, reference_end, recent_end) for spec in SIGNALS]
    primary = [signal for signal in signals if signal.role == "primary"]
    available = [signal.metric_type for signal in primary if signal.usable]
    unavailable = [signal.metric_type for signal in primary if not signal.usable]
    missing_required = [metric for metric in settings.pattern_required_signals if metric not in available]
    available_groups = sorted({signal.group for signal in primary if signal.usable})
    rejected = sum(signal.rejected_reference_samples + signal.rejected_recent_samples for signal in primary)
    unknown_provenance = any("unknown_provider_provenance" in signal.reasons for signal in primary)
    insufficient = bool(missing_required) or len(available_groups) < settings.pattern_min_available_groups
    coverage = "insufficient" if insufficient else "partial" if unavailable or rejected or unknown_provenance else "complete"

    groups_by_day = defaultdict(set)
    for signal in primary:
        if signal.contributing:
            for day in signal.persistence.qualifying_recent_days:
                groups_by_day[day].add(signal.group)
    concurrent = [ConcurrentPatternDay(date=day, groups=sorted(groups)) for day, groups in sorted(groups_by_day.items())]
    qualifying = [item.date for item in concurrent if len(item.groups) >= settings.pattern_review_min_groups]
    longest, latest = _runs(qualifying)
    if concurrent and (not qualifying or qualifying[-1] != concurrent[-1].date):
        latest = 0
    concurrent_persistent = (latest >= settings.pattern_persistence_days and bool(qualifying)
                             and (recent_end - qualifying[-1]).days <= settings.observed_change_max_staleness_days)
    reasons = []
    if insufficient:
        status = "insufficient_data"
        if missing_required:
            reasons.append("required_signals_unavailable")
        if len(available_groups) < settings.pattern_min_available_groups:
            reasons.append("too_few_available_signal_groups")
        explanation = "Required signal coverage is insufficient; the detector abstains rather than inferring stability."
    elif concurrent_persistent:
        status = "change_to_review"
        reasons.append("multiple_groups_changed_together_persistently")
        explanation = "Several distinct signal groups show concurrent persistent relative changes under the prototype rules."
    elif any(signal.changed for signal in primary if signal.usable) or coverage == "partial":
        status = "watch"
        if any(signal.changed for signal in primary if signal.usable):
            reasons.append("changes_do_not_meet_concurrent_persistence_rule")
        explanation = "Changes or incomplete optional coverage warrant watching; the concurrent persistence rule is not met."
    else:
        status = "normal"
        reasons.append("no_qualifying_directional_changes")
        explanation = "Sufficient primary data shows no qualifying changes under these prototype rules; this is not a medical assessment."
    if coverage == "partial":
        reasons.append("partial_signal_coverage_or_provenance")
    return PatternStatus(
        patient_id=timeline.patient_id, synthetic=timeline.synthetic, status=status,
        reference_window=ComparisonWindow(start_date=reference_start, end_date=reference_end),
        recent_window=ComparisonWindow(start_date=recent_start, end_date=recent_end),
        policy=PatternPolicy(
            normalized_change_threshold=settings.pattern_normalized_change_threshold,
            relative_scale_floor=settings.pattern_relative_scale_floor,
            minimum_samples_per_window=settings.observed_change_min_samples,
            minimum_days_per_window=settings.pattern_min_days_per_window,
            minimum_samples_per_day=settings.pattern_min_samples_per_day,
            persistence_days=settings.pattern_persistence_days,
            review_min_groups=settings.pattern_review_min_groups,
            minimum_available_groups=settings.pattern_min_available_groups,
            max_staleness_days=settings.observed_change_max_staleness_days,
            required_signals=list(settings.pattern_required_signals),
        ),
        contributing_signals=[signal.metric_type for signal in signals if signal.contributing],
        non_contributing_signals=[signal.metric_type for signal in signals if not signal.contributing],
        signals=signals, concurrent_days=concurrent, longest_concurrent_days=longest,
        latest_concurrent_days=latest, reasons=reasons, explanation=explanation,
        data_quality=PatternDataQuality(
            coverage=coverage, available_primary_signals=available, unavailable_primary_signals=unavailable,
            missing_required_signals=missing_required, available_groups=available_groups,
            unavailable_context_signals=[signal.metric_type for signal in signals if signal.role == "context" and not signal.usable],
            reasons_by_signal={signal.metric_type: signal.reasons for signal in signals if not signal.usable
                               or "unknown_provider_provenance" in signal.reasons
                               or signal.rejected_reference_samples or signal.rejected_recent_samples},
            rejected_sleep_values=rejected,
        ),
    )


async def build_pattern_status(
    patient: Patient, client: OpenWearablesClient, settings: Settings,
    reference_start: date, reference_end: date, recent_start: date, recent_end: date,
) -> PatternStatus:
    validate_windows(reference_start, reference_end, recent_start, recent_end)
    timeline = await build_timeline(patient, client, reference_start, recent_end)
    return analyze_pattern(timeline, settings, reference_start, reference_end, recent_start, recent_end)
