import csv
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean

import pytest

from app.services.synthetic_cgm import generate_cgm, write_cgm_csv

DATASET = Path(__file__).resolve().parents[1] / "app" / "data" / "maya_synthetic_cgm.csv"


@pytest.fixture(scope="module")
def samples():
    return generate_cgm()


def test_default_generation_is_deterministic(samples):
    assert generate_cgm() == samples


def test_changing_seed_changes_values_and_preserves_timestamps(samples):
    different = generate_cgm(seed=43)
    assert [row.timestamp for row in different] == [row.timestamp for row in samples]
    assert [row.glucose_mg_dl for row in different] != [row.glucose_mg_dl for row in samples]


def test_generation_does_not_change_global_random_state():
    state = random.getstate()
    generate_cgm(days=1)
    assert random.getstate() == state


def test_exact_sample_count_and_date_range(samples):
    assert len(samples) == 30 * 24 * 12 == 8640
    assert samples[0].timestamp == datetime(2026, 9, 15, tzinfo=timezone.utc)
    assert samples[-1].timestamp == datetime(2026, 10, 14, 23, 55, tzinfo=timezone.utc)


def test_every_timestamp_is_utc_and_exactly_five_minutes_apart(samples):
    assert all(row.timestamp.utcoffset() == timedelta(0) for row in samples)
    assert all(second.timestamp - first.timestamp == timedelta(minutes=5)
               for first, second in zip(samples, samples[1:]))
    assert len({row.timestamp for row in samples}) == len(samples)


def test_all_values_are_present_numeric_finite_and_within_generator_bounds(samples):
    for row in samples:
        assert isinstance(row.glucose_mg_dl, float)
        assert math.isfinite(row.glucose_mg_dl)
        assert 80 <= row.glucose_mg_dl <= 220


def test_daily_structure_has_meal_rises_returns_and_overnight_behavior(samples):
    first_day = samples[:288]

    def average(start_hour, end_hour):
        return fmean(row.glucose_mg_dl for row in first_day
                     if start_hour <= row.timestamp.hour < end_hour)

    assert average(8, 9) > average(6, 7)
    assert average(13, 14) > average(11, 12)
    assert average(19, 20) > average(17, 18)
    assert average(15, 16) < average(13, 14)
    assert average(1, 5) < average(12, 20)
    assert max(abs(second.glucose_mg_dl - first.glucose_mg_dl)
               for first, second in zip(samples, samples[1:])) < 10


def test_day_to_day_variation(samples):
    means = [round(fmean(row.glucose_mg_dl for row in samples[start:start + 288]), 2)
             for start in range(0, len(samples), 288)]
    assert len(set(means)) > 20


def test_optional_activity_only_reduces_the_illustrative_curve(samples):
    disabled = generate_cgm(include_activity=False)
    assert [row.timestamp for row in samples] == [row.timestamp for row in disabled]
    assert all(enabled.glucose_mg_dl <= off.glucose_mg_dl for enabled, off in zip(samples, disabled))
    assert any(off.glucose_mg_dl - enabled.glucose_mg_dl > 1 for enabled, off in zip(samples, disabled))


def test_custom_duration_and_start_date():
    rows = generate_cgm(days=2, start_date=date(2026, 1, 1))
    assert len(rows) == 576
    assert rows[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert rows[-1].timestamp == datetime(2026, 1, 2, 23, 55, tzinfo=timezone.utc)


def test_extending_duration_preserves_the_existing_prefix(samples):
    assert generate_cgm(days=1) == samples[:288]


@pytest.mark.parametrize("days", [0, -1])
def test_invalid_duration_is_rejected(days):
    with pytest.raises(ValueError, match="days must be at least 1"):
        generate_cgm(days=days)


def test_csv_is_deterministic_and_matches_saved_dataset(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "nested" / "second.csv"
    assert write_cgm_csv(first) == 8640
    assert write_cgm_csv(second) == 8640
    assert first.read_bytes() == second.read_bytes() == DATASET.read_bytes()


def test_saved_csv_has_complete_valid_rows_and_explicit_labels(samples):
    with DATASET.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == len(samples) == 8640
    for row, sample in zip(rows, samples):
        assert all(value is not None and value != "" for value in row.values())
        assert datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) == sample.timestamp
        value = float(row["glucose_mg_dl"])
        assert math.isfinite(value)
        assert value == sample.glucose_mg_dl
        assert row["unit"] == "mg/dL"
        assert row["patient_id"] == "maya"
        assert row["synthetic"] == "true"
        assert row["clinically_validated"] == "false"
        assert row["source"] == "nestwatch_synthetic_cgm"
        assert row["generator_seed"] == "42"
        assert row["activity_enabled"] == "true"


def test_disabled_activity_is_labeled_in_csv(tmp_path):
    output = tmp_path / "no_activity.csv"
    assert write_cgm_csv(output, days=1, include_activity=False, seed=7) == 288
    with output.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert {row["activity_enabled"] for row in rows} == {"false"}
    assert {row["generator_seed"] for row in rows} == {"7"}
