import csv
import math
import random
from datetime import datetime, timedelta, timezone
from statistics import mean

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.routes import patients
from app.schemas.bp_forecast import BPReviewThresholds
from app.services import bp_forecast as service
from app.services.synthetic_bp import fixture_episodes, generate_bp, write_bp_csv


@pytest.fixture(scope="module")
def series():
    return service.load_bp_csv()


@pytest.fixture(scope="module")
def thresholds():
    return BPReviewThresholds(systolic_mm_hg=140, diastolic_mm_hg=90)


@pytest.fixture(scope="module")
def forecast(series, thresholds):
    return service.train_and_forecast(series, thresholds)


def test_synthetic_generator_and_saved_csv_are_deterministic(tmp_path):
    state = random.getstate()
    first = generate_bp()
    assert first == generate_bp()
    assert random.getstate() == state
    assert first != generate_bp(seed=74)
    output = tmp_path / "nested" / "bp.csv"
    assert write_bp_csv(output) == 730
    assert output.read_bytes() == service.DATASET_PATH.read_bytes()


def test_synthetic_dataset_count_spacing_and_labels(series):
    assert len(series.timestamps) == 365 * 2 == 730
    assert series.timestamps[0] == datetime(2025, 10, 15, 8, tzinfo=timezone.utc)
    assert series.timestamps[-1] == datetime(2026, 10, 14, 20, tzinfo=timezone.utc)
    assert all(second - first == timedelta(hours=12) for first, second in zip(series.timestamps, series.timestamps[1:]))
    assert np.isfinite(series.systolic).all() and np.isfinite(series.diastolic).all()
    with service.DATASET_PATH.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 730
    for row in rows:
        assert row["synthetic"] == "true"
        assert row["clinically_validated"] == "false"
        assert row["source"] == "nestwatch_synthetic_bp_training"
        assert row["unit"] == "mmHg"
        assert row["fixture_episode_phase"] in {"baseline", "rise", "plateau", "return"}


def test_fixture_has_mostly_baseline_and_gradual_multi_day_rises():
    rows = generate_bp()
    assert sum(row.fixture_episode_id == "baseline" for row in rows) > len(rows) / 2
    episodes = fixture_episodes()
    assert len(episodes) == 7
    assert len({episode.start_day for episode in episodes}) == 7
    for episode in episodes:
        rise = [row for row in rows if row.fixture_episode_id == episode.episode_id
                and row.fixture_episode_phase == "rise"]
        assert len({row.timestamp.date() for row in rise}) >= 6
        assert mean(row.systolic_mm_hg for row in rise[-4:]) > mean(row.systolic_mm_hg for row in rise[:4])
        assert mean(row.diastolic_mm_hg for row in rise[-4:]) > mean(row.diastolic_mm_hg for row in rise[:4])
        phases = {row.fixture_episode_phase for row in rows if row.fixture_episode_id == episode.episode_id}
        assert phases == {"rise", "plateau", "return"}


def test_multiple_episodes_cross_review_values_on_multiple_days():
    rows = generate_bp()
    sustained_crossings = 0
    subthreshold_episodes = 0
    for episode in fixture_episodes():
        crossing_days = {row.timestamp.date() for row in rows
                         if row.fixture_episode_id == episode.episode_id
                         and (row.systolic_mm_hg >= 140 or row.diastolic_mm_hg >= 90)}
        sustained_crossings += len(crossing_days) >= 2
        subthreshold_episodes += not crossing_days
    assert sustained_crossings >= 3
    assert subthreshold_episodes >= 1


@pytest.mark.parametrize("days", [0, -1])
def test_invalid_generation_duration(days):
    with pytest.raises(ValueError):
        generate_bp(days=days)


def test_deterministic_training_and_inference(series, thresholds, forecast):
    assert service.train_and_forecast(series, thresholds).model_dump() == forecast.model_dump()


def test_probability_horizon_and_availability_status(forecast):
    assert forecast.status == "forecast_available"
    assert isinstance(forecast.probability, float) and math.isfinite(forecast.probability)
    assert 0 <= forecast.probability <= 1
    assert forecast.horizon_days == 7
    assert forecast.forecast_origin == datetime(2026, 10, 15, 8, tzinfo=timezone.utc)
    assert forecast.last_observation_timestamp == forecast.forecast_origin - timedelta(hours=12)
    assert forecast.event_window_end == forecast.forecast_origin + timedelta(days=7)
    assert forecast.synthetic is True and forecast.prototype is True and forecast.validated is False
    assert "future synthetic blood-pressure measurement" in forecast.event_definition
    assert "140 mmHg OR diastolic >= 90 mmHg" in forecast.event_definition


def test_feature_values_and_statistical_contributions_are_preserved(forecast):
    assert set(forecast.feature_values) == set(service.FEATURE_NAMES)
    assert all(math.isfinite(value) for value in forecast.feature_values.values())
    assert len(forecast.main_contributing_features) == 3
    contributions = forecast.main_contributing_features
    assert [abs(item.standardized_log_odds_contribution) for item in contributions] == sorted(
        (abs(item.standardized_log_odds_contribution) for item in contributions), reverse=True
    )
    for item in contributions:
        assert item.value == forecast.feature_values[item.feature]


def test_past_only_means_variability_and_slopes(series):
    index = 200
    actual = dict(zip(service.FEATURE_NAMES, service.features_at_origin(series, index)))
    sbp = series.systolic[index - 14:index]
    dbp = series.diastolic[index - 14:index]
    assert actual["systolic_mean_7d_mm_hg"] == pytest.approx(sbp.mean())
    assert actual["diastolic_mean_7d_mm_hg"] == pytest.approx(dbp.mean())
    assert actual["systolic_std_7d_mm_hg"] == pytest.approx(sbp.std(ddof=0))
    assert actual["last_diastolic_mm_hg"] == dbp[-1]
    assert actual["systolic_slope_7d_mm_hg_per_day"] == pytest.approx(np.polyfit(np.arange(14) / 2, sbp, 1)[0])


def test_future_values_do_not_change_features(series):
    index = 200
    sbp, dbp = series.systolic.copy(), series.diastolic.copy()
    sbp[index:] += 1000
    dbp[index:] += 1000
    changed = service.BPSeries(series.timestamps, sbp, dbp)
    np.testing.assert_array_equal(service.features_at_origin(series, index), service.features_at_origin(changed, index))


def test_fixture_annotations_never_enter_model_features(tmp_path, series, thresholds):
    with service.DATASET_PATH.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        row["fixture_episode_id"] = "unrelated_fixture_annotation"
        row["fixture_episode_phase"] = "unrelated_fixture_phase"
    path = tmp_path / "annotations.csv"
    write_rows(path, rows)
    changed = service.load_bp_csv(path)
    features, labels, _ = service.training_examples(series, 584, thresholds)
    changed_features, changed_labels, _ = service.training_examples(changed, 584, thresholds)
    assert features.shape[1] == len(service.FEATURE_NAMES) == 8
    np.testing.assert_array_equal(features, changed_features)
    np.testing.assert_array_equal(labels, changed_labels)


def test_purged_chronological_targets_and_train_only_scaling(series, thresholds):
    split = 584
    features, labels, origins = service.training_examples(series, split, thresholds)
    assert len(origins) == 279
    assert np.all(origins + 14 <= split)
    assert origins[-1] + 13 == split - 1
    sbp, dbp = series.systolic.copy(), series.diastolic.copy()
    sbp[split:] += 1000
    dbp[split:] += 1000
    changed = service.BPSeries(series.timestamps, sbp, dbp)
    changed_features, changed_labels, changed_origins = service.training_examples(changed, split, thresholds)
    np.testing.assert_array_equal(features, changed_features)
    np.testing.assert_array_equal(labels, changed_labels)
    np.testing.assert_array_equal(origins, changed_origins)
    first = service.fit_model(features, labels)
    second = service.fit_model(changed_features, changed_labels)
    np.testing.assert_allclose(first.named_steps["scale"].mean_, features.mean(axis=0))
    np.testing.assert_array_equal(first.named_steps["scale"].mean_, second.named_steps["scale"].mean_)
    np.testing.assert_array_equal(first.named_steps["logistic"].coef_, second.named_steps["logistic"].coef_)
    assert first.named_steps["logistic"].C == 1.0
    assert first.named_steps["logistic"].solver == "lbfgs"


def test_future_rows_cannot_change_historical_training_or_predictions(series, thresholds):
    index = 584
    origin = series.timestamps[index]
    sbp, dbp = series.systolic.copy(), series.diastolic.copy()
    sbp[index:] += 1000
    dbp[index:] += 1000
    changed = service.BPSeries(series.timestamps, sbp, dbp)
    original = service.train_and_forecast(series, thresholds, origin)
    altered = service.train_and_forecast(changed, thresholds, origin)
    assert original.status == "forecast_available"
    assert original.model_dump() == altered.model_dump()
    assert original.holdout_metrics.holdout_end < origin


def test_training_and_holdout_have_both_classes_with_chronological_split(forecast):
    metrics = forecast.holdout_metrics
    assert metrics.scope == "synthetic_data_only"
    assert metrics.split_method == "chronological_80_20_purged_7d"
    assert metrics.training_measurements == 584
    assert metrics.training_windows == 279
    assert metrics.training_positive_events == 58
    assert metrics.training_negative_events == 221
    assert metrics.training_end < metrics.holdout_start <= metrics.holdout_end < forecast.forecast_origin
    assert metrics.holdout_measurements == 146
    assert metrics.evaluated_windows == 10
    assert metrics.evaluated_bp_measurements == 140
    assert metrics.holdout_positive_events == 4
    assert metrics.holdout_negative_events == 6
    assert metrics.no_event_baseline_accuracy == 0.6
    assert metrics.roc_auc is not None
    assert metrics.roc_auc_unavailable_reason is None
    assert 0 <= metrics.accuracy <= 1 and 0 <= metrics.brier_score <= 1
    assert math.isfinite(metrics.log_loss)


def test_holdout_metrics_match_confusion_counts_and_constant_baseline(forecast):
    metrics = forecast.holdout_metrics
    tp, fp, tn, fn = metrics.true_positives, metrics.false_positives, metrics.true_negatives, metrics.false_negatives
    assert tp + fp + tn + fn == metrics.evaluated_windows
    assert tp + fn == metrics.holdout_positive_events
    assert tn + fp == metrics.holdout_negative_events
    assert metrics.accuracy == pytest.approx((tp + tn) / 10, abs=1e-6)
    assert metrics.precision == pytest.approx(tp / (tp + fp), abs=1e-6)
    assert metrics.recall == pytest.approx(tp / (tp + fn), abs=1e-6)
    assert metrics.specificity == pytest.approx(tn / (tn + fp), abs=1e-6)
    assert metrics.f1 == pytest.approx(2 * tp / (2 * tp + fp + fn), abs=1e-6)
    baseline = metrics.constant_no_event_baseline
    assert baseline.accuracy == metrics.no_event_baseline_accuracy == 0.6
    assert (baseline.true_positives, baseline.false_positives, baseline.true_negatives, baseline.false_negatives) == (0, 0, 6, 4)
    assert baseline.precision is None
    assert baseline.unavailable_reasons == ["precision_no_positive_predictions"]
    assert baseline.recall == baseline.f1 == 0
    assert baseline.specificity == 1
    assert baseline.brier_score == 0.4
    assert math.isfinite(baseline.log_loss)
    assert baseline.roc_auc == 0.5


def test_metric_calculations_on_known_predictions():
    metrics = service.classification_metrics(np.array([0, 1, 0, 1]), np.array([0.1, 0.9, 0.8, 0.2]))
    assert (metrics.true_positives, metrics.false_positives, metrics.true_negatives, metrics.false_negatives) == (1, 1, 1, 1)
    assert metrics.accuracy == metrics.precision == metrics.recall == metrics.specificity == metrics.f1 == 0.5
    assert metrics.brier_score == 0.325
    assert metrics.log_loss == pytest.approx((-2 * math.log(0.9) - 2 * math.log(0.2)) / 4, abs=1e-6)
    assert metrics.roc_auc == 0.75


def test_single_class_holdout_keeps_undefined_metrics_explicit(series, thresholds):
    sbp, dbp = series.systolic.copy(), series.diastolic.copy()
    sbp[584:] = 100
    dbp[584:] = 60
    controlled = service.BPSeries(series.timestamps, sbp, dbp)
    metrics = service.evaluate_holdout(controlled, thresholds)
    assert metrics.holdout_positive_events == 0
    assert metrics.roc_auc is None
    assert metrics.roc_auc_unavailable_reason == "single_class_holdout_labels"
    assert metrics.recall is None
    assert "recall_no_positive_labels" in metrics.unavailable_reasons
    assert metrics.constant_no_event_baseline.precision is None
    assert metrics.constant_no_event_baseline.f1 is None


@pytest.mark.parametrize("metric", ["systolic", "diastolic"])
def test_target_uses_either_bp_component_and_includes_threshold_equality(series, thresholds, metric):
    sbp = np.full(len(series.timestamps), 100.0)
    dbp = np.full(len(series.timestamps), 60.0)
    values = sbp if metric == "systolic" else dbp
    threshold = thresholds.systolic_mm_hg if metric == "systolic" else thresholds.diastolic_mm_hg
    values[27] = threshold  # Last sample in the future seven-day window.
    controlled = service.BPSeries(series.timestamps, sbp, dbp)
    assert service.event_label(controlled, 14, thresholds) == 1
    values[27] = threshold - 0.01
    values[13] = values[28] = threshold + 10  # Past and out-of-horizon readings do not count.
    assert service.event_label(controlled, 14, thresholds) == 0


def test_incomplete_future_window_never_becomes_a_negative_label(series, thresholds):
    with pytest.raises(service.InsufficientBPData, match="incomplete_future_target_window"):
        service.event_label(series, len(series.timestamps) - 13, thresholds)


def test_gapped_future_window_never_becomes_a_negative_label(series, thresholds):
    times = list(series.timestamps)
    times[20] += timedelta(hours=12)
    changed = service.BPSeries(tuple(times), series.systolic, series.diastolic)
    with pytest.raises(service.InsufficientBPData, match="incomplete_future_target_window"):
        service.event_label(changed, 14, thresholds)


def test_thresholds_change_labels_predictions_and_metrics(series, thresholds, forecast):
    changed = BPReviewThresholds(systolic_mm_hg=135, diastolic_mm_hg=85)
    _, original_labels, _ = service.training_examples(series, 584, thresholds)
    _, changed_labels, _ = service.training_examples(series, 584, changed)
    assert np.any(original_labels != changed_labels)
    altered = service.train_and_forecast(series, changed)
    assert altered.status == "forecast_available"
    assert altered.probability != forecast.probability
    assert altered.thresholds == changed
    assert altered.holdout_metrics.holdout_positive_events > 0
    assert altered.holdout_metrics.roc_auc is not None
    assert "135 mmHg OR diastolic >= 85 mmHg" in altered.event_definition


@pytest.mark.parametrize("length,reason", [
    (0, "missing_bp_history"), (13, "insufficient_recent_bp_history"),
    (20, "insufficient_complete_training_windows"), (60, "insufficient_complete_holdout_windows"),
])
def test_insufficient_history_returns_null_probability(series, thresholds, length, reason):
    short = service.BPSeries(series.timestamps[:length], series.systolic[:length], series.diastolic[:length])
    result = service.train_and_forecast(short, thresholds)
    assert result.status == "insufficient_data"
    assert result.probability is None
    assert result.holdout_metrics is None
    assert result.reasons == [reason]


@pytest.mark.parametrize("systolic,diastolic", [(100, 60), (150, 100)])
def test_one_class_training_is_not_reported_as_zero_or_one_probability(series, thresholds, systolic, diastolic):
    controlled = service.BPSeries(series.timestamps, np.full(730, systolic), np.full(730, diastolic))
    result = service.train_and_forecast(controlled, thresholds)
    assert result.status == "insufficient_data"
    assert result.probability is None
    assert result.reasons == ["single_class_training_labels"]


def test_stale_history_has_no_probability(series, thresholds):
    result = service.train_and_forecast(series, thresholds, series.timestamps[-1] + timedelta(days=2))
    assert result.status == "insufficient_data"
    assert result.probability is None
    assert result.reasons == ["stale_or_misaligned_bp_history"]


def test_invalid_recent_values_have_no_probability(series, thresholds):
    sbp = series.systolic.copy()
    sbp[-1] = np.nan
    result = service.train_and_forecast(service.BPSeries(series.timestamps, sbp, series.diastolic), thresholds)
    assert result.status == "insufficient_data"
    assert result.probability is None
    assert result.reasons == ["incomplete_recent_bp_history"]


def test_configuration_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("BP_REVIEW_SYSTOLIC_THRESHOLD", "135")
    monkeypatch.setenv("BP_REVIEW_DIASTOLIC_THRESHOLD", "85")
    settings = Settings(_env_file=None)
    assert settings.bp_review_systolic_threshold == 135
    assert settings.bp_review_diastolic_threshold == 85


@pytest.mark.parametrize("field,value", [
    ("bp_review_systolic_threshold", 0), ("bp_review_diastolic_threshold", -1),
    ("bp_review_systolic_threshold", float("nan")), ("bp_review_diastolic_threshold", float("inf")),
])
def test_invalid_threshold_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("systolic,diastolic", [(140, 90), (135, 85)])
def test_endpoint_schema_real_service_and_config_without_open_wearables(monkeypatch, systolic, diastolic):
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={
        "bp_review_systolic_threshold": systolic, "bp_review_diastolic_threshold": diastolic,
    }))

    async def no_upstream(*args, **kwargs):
        pytest.fail("Synthetic BP forecasts must not call Open Wearables")

    monkeypatch.setattr(httpx.AsyncClient, "get", no_upstream)
    with TestClient(app) as client:
        response = client.get("/patients/maya/forecast/bp")
    assert response.status_code == 200
    body = response.json()
    assert body["forecast_origin"] == "2026-10-15T08:00:00Z"
    assert body["horizon_days"] == 7
    assert body["model_type"] == "logistic_regression"
    assert body["status"] == "forecast_available"
    assert 0 <= body["probability"] <= 1
    assert body["thresholds"] == {"systolic_mm_hg": float(systolic), "diastolic_mm_hg": float(diastolic), "comparison": ">=", "combine": "or"}
    assert body["synthetic"] is True and body["prototype"] is True and body["validated"] is False
    assert body["holdout_metrics"]["scope"] == "synthetic_data_only"
    assert body["holdout_metrics"]["training_positive_events"] > 0
    assert body["holdout_metrics"]["training_negative_events"] > 0
    assert body["holdout_metrics"]["holdout_positive_events"] > 0
    assert body["holdout_metrics"]["holdout_negative_events"] > 0
    assert "precision" in body["holdout_metrics"]
    assert "recall" in body["holdout_metrics"]
    assert "specificity" in body["holdout_metrics"]
    assert "f1" in body["holdout_metrics"]
    assert "constant_no_event_baseline" in body["holdout_metrics"]
    assert len(body["main_contributing_features"]) == 3
    assert body["reasons"] == []


def test_endpoint_insufficient_data_schema(monkeypatch):
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={
        "bp_review_systolic_threshold": 200, "bp_review_diastolic_threshold": 150,
    }))
    with TestClient(app) as client:
        response = client.get("/patients/maya/forecast/bp")
    assert response.status_code == 200
    body = response.json()
    assert body["probability"] is None
    assert body["status"] == "insufficient_data"
    assert body["reasons"] == ["single_class_training_labels"]
    assert body["holdout_metrics"] is None
    assert body["validated"] is False


def test_dataset_unavailable_is_a_clear_503(monkeypatch):
    def failure(*args):
        raise service.BPForecastError("Synthetic BP dataset is unavailable or invalid")

    monkeypatch.setattr(patients, "get_bp_forecast", failure)
    with TestClient(app) as client:
        response = client.get("/patients/maya/forecast/bp")
    assert response.status_code == 503
    assert response.json() == {"detail": "Synthetic BP dataset is unavailable or invalid"}


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def csv_row(**fields):
    return {
        "timestamp": "2025-10-15T08:00:00Z", "systolic_mm_hg": "120",
        "diastolic_mm_hg": "80", "unit": "mmHg", "patient_id": "maya",
        "synthetic": "true", "clinically_validated": "false", **fields,
    }


@pytest.mark.parametrize("fields", [
    {"systolic_mm_hg": "NaN"}, {"diastolic_mm_hg": "inf"}, {"diastolic_mm_hg": ""},
    {"unit": "wrong"}, {"synthetic": "false"}, {"clinically_validated": "true"},
    {"timestamp": "2025-10-15T08:00:00"},
])
def test_invalid_or_unlabeled_csv_is_rejected(tmp_path, fields):
    path = tmp_path / "invalid.csv"
    write_rows(path, [csv_row(**fields)])
    with pytest.raises(service.BPForecastError):
        service.load_bp_csv(path)


@pytest.mark.parametrize("timestamp", ["2025-10-15T08:00:00Z", "2025-10-16T08:00:00Z"])
def test_gaps_and_duplicate_timestamps_are_rejected(tmp_path, timestamp):
    path = tmp_path / "gap.csv"
    write_rows(path, [csv_row(), csv_row(timestamp=timestamp)])
    with pytest.raises(service.BPForecastError):
        service.load_bp_csv(path)


def test_missing_csv_is_rejected(tmp_path):
    with pytest.raises(service.BPForecastError):
        service.load_bp_csv(tmp_path / "missing.csv")


def test_caching_is_keyed_by_the_thresholds(series, monkeypatch):
    calls = []

    def load():
        calls.append(True)
        return series

    service.get_bp_forecast.cache_clear()
    monkeypatch.setattr(service, "load_bp_csv", load)
    try:
        original = service.get_bp_forecast(140, 90)
        assert service.get_bp_forecast(140, 90) is original
        changed = service.get_bp_forecast(135, 85)
        assert changed.thresholds != original.thresholds
        assert len(calls) == 2
    finally:
        service.get_bp_forecast.cache_clear()
