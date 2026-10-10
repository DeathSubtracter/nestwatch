"""Combine device records and dated fixture context without analyzing either."""

from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from ..clients.open_wearables import OpenWearablesClient, OpenWearablesError
from ..schemas.patient import Patient
from ..schemas.timeline import PatientTimeline, TimelineEntry

METRICS = {
    "blood_glucose": "Blood glucose concentration reported by the source.",
    "blood_pressure_systolic": "Systolic blood pressure reported by the source.",
    "blood_pressure_diastolic": "Diastolic blood pressure reported by the source.",
    "heart_rate": "Heart rate reported by the source.",
    "resting_heart_rate": "Resting heart rate reported by the source.",
    "heart_rate_variability_sdnn": "Heart rate variability (SDNN) reported by the source.",
    "skin_temperature": "Skin temperature reported by the source.",
    "body_temperature": "Body temperature reported by the source.",
    "weight": "Body weight reported by the source.",
}


def load_maya() -> Patient:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "maya.json"
    return Patient.model_validate_json(fixture.read_text(encoding="utf-8"))


def _instant(timestamp: str) -> datetime:
    if not isinstance(timestamp, str):
        raise ValueError("Invalid timestamp")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    # Open Wearables normally supplies offsets; treat offset-less records as UTC.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _midnight(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _device_entry(record: dict[str, Any], *, sleep: bool = False) -> TimelineEntry:
    source = record.get("source")
    source = {} if source is None else source
    if not isinstance(source, dict):
        raise ValueError("Invalid source metadata")
    if sleep:
        timestamp = record["end_time"]
        _instant(record["start_time"])
        value = {
            key: record.get(key)
            for key in (
                "duration_seconds", "sleep_duration_seconds", "time_in_bed_seconds",
                "efficiency_percent", "stages", "is_nap",
            )
        }
        duration = value["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError("Missing sleep duration")
        metric_type = "sleep_summary"
        definition = "Source-reported sleep session summary, timestamped at session end."
        unit = None
    else:
        timestamp = record["timestamp"]
        value = record["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError("Invalid measurement value")
        metric_type = record["type"]
        definition = METRICS[metric_type]
        unit = record["unit"]
        if not isinstance(unit, str):
            raise ValueError("Invalid measurement unit")
    _instant(timestamp)
    return TimelineEntry(
        timestamp=timestamp,
        kind="sleep" if sleep else "measurement",
        origin="open_wearables",
        metric_type=metric_type,
        metric_definition=definition,
        value=value,
        unit=unit,
        provider=source.get("provider"),
        source=source.get("source"),
        device=source.get("device"),
        device_type=source.get("device_type"),
        details=record,
    )


def _context_entries(patient: Patient, start_date: date, end_date: date) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []

    def add(timestamp, kind, metric_type, definition, value, details=None):
        entries.append(TimelineEntry(
            timestamp=timestamp,
            kind=kind,
            origin="nestwatch",
            metric_type=metric_type,
            metric_definition=definition,
            value=value,
            provider="nestwatch",
            source="synthetic_fixture",
            details={"synthetic": True, **(details or {})},
        ))

    age = patient.gestational_age
    gestation_start = age.as_of_date - timedelta(days=age.weeks * 7 + age.days)
    snapshot_date = max(start_date, gestation_start)
    if snapshot_date <= end_date:
        total_days = (snapshot_date - gestation_start).days
        weeks, days = divmod(total_days, 7)
        stage = "first_trimester" if weeks < 14 else "second_trimester" if weeks < 28 else "third_trimester"
        add(_midnight(snapshot_date), "context", "pregnancy_stage",
            "Gestational age and stage calculated from the fixture's dated reference.",
            {"weeks": weeks, "days": days, "stage": stage},
            {"snapshot": True, "reference": age.model_dump(mode="json")})

    diabetes = patient.diabetes
    if diabetes.since_date <= end_date:
        add(_midnight(max(start_date, diabetes.since_date)), "context", "diabetes_context",
            "Ongoing fictional diabetes context; timestamp is a range snapshot.",
            diabetes.context,
            {"snapshot": True, "type": diabetes.type, "since_date": diabetes.since_date.isoformat()})

    if patient.medication_transition_date <= end_date:
        add(_midnight(max(start_date, patient.medication_transition_date)), "context", "treatment_context",
            "Fictional treatment text active after the fixture medication transition.",
            patient.current_treatment_text,
            {"snapshot": True, "effective_from": patient.medication_transition_date.isoformat()})

    add(_midnight(patient.glp1_last_dose_date), "medication", "glp1_last_dose",
        "Recorded last GLP-1 dose date in the synthetic fixture.",
        patient.glp1_last_dose_date.isoformat(), {"date_only": True})
    add(_midnight(patient.medication_transition_date), "medication", "medication_transition",
        "Recorded medication transition date in the synthetic fixture.",
        patient.current_treatment_text, {"date_only": True})
    for symptom in patient.symptoms:
        add(symptom.timestamp.isoformat(), "symptom", "symptom",
            "Dated symptom report from the synthetic fixture.",
            symptom.name, {"severity": symptom.severity, "notes": symptom.notes})
    return entries


async def build_timeline(
    patient: Patient, client: OpenWearablesClient, start_date: date, end_date: date
) -> PatientTimeline:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    samples = await client.get_timeseries(start_date, end_date, types=list(METRICS))
    sessions = await client.get_sleep(start_date, end_date)
    try:
        entries = [
            _device_entry(record) for record in samples if record["type"] in METRICS
        ]
        entries.extend(_device_entry(record, sleep=True) for record in sessions)
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenWearablesError("Open Wearables returned an invalid timeline record") from exc
    entries.extend(_context_entries(patient, start_date, end_date))

    lower = datetime.combine(start_date, time.min, timezone.utc)
    upper = datetime.combine(end_date, time.max, timezone.utc)
    entries = [entry for entry in entries if lower <= _instant(entry.timestamp) <= upper]
    entries.sort(key=lambda entry: _instant(entry.timestamp))
    return PatientTimeline(
        patient_id=patient.patient_id,
        synthetic=patient.synthetic,
        start_date=start_date,
        end_date=end_date,
        patient_context=patient,
        entries=entries,
        count=len(entries),
    )
