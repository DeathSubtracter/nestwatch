import csv
import math
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import patients
from app.services import glucose_forecast as service


@pytest.fixture(scope="module")
def series():
    return service.load_cgm_csv()


@pytest.fixture(scope="module")
def short_series(series):
    return service.CGMSeries(series.timestamps[:1440], series.values[:1440], {})


@pytest.fixture(scope="module")
def forecast(series):
    return service.train_and_forecast(series)


def test_deterministic_training_and_inference(short_series):
    first = service.train_and_forecast(short_series)
    second = service.train_and_forecast(short_series)
    assert first.model_dump() == second.model_dump()


def test_exact_forecast_length_cadence_and_monotonic_timestamps(forecast):
    points = forecast.forecast_points
    assert len(points) == 288
    assert forecast.horizon_hours == 24
    assert forecast.cadence_minutes == 5
    assert forecast.forecast_origin == datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert forecast.last_observation_timestamp == forecast.forecast_origin - timedelta(minutes=5)
    assert points[0].timestamp == forecast.forecast_origin
    assert points[-1].timestamp == forecast.forecast_origin + timedelta(hours=24, minutes=-5)
    assert all(second.timestamp > first.timestamp and second.timestamp - first.timestamp == timedelta(minutes=5)
               for first, second in zip(points, points[1:]))
    assert len({point.timestamp for point in points}) == 288


def test_forecast_values_are_numeric_and_finite(forecast):
    assert all(isinstance(point.glucose_mg_dl, float) and math.isfinite(point.glucose_mg_dl)
               for point in forecast.forecast_points)


def test_chronological_holdout_and_synthetic_performance_labels(forecast):
    metrics = forecast.holdout_metrics
    assert metrics.scope == "synthetic_data_only"
    assert metrics.split_method == "chronological_80_20"
    assert metrics.evaluation_method == "non_overlapping_24h_forecasts"
    assert metrics.training_samples == 6912
    assert metrics.training_windows == 6337
    assert metrics.holdout_samples == metrics.evaluated_points == 1728
    assert metrics.evaluation_origins == 6
    assert metrics.training_end == datetime(2026, 10, 8, 23, 55, tzinfo=timezone.utc)
    assert metrics.holdout_start == datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert metrics.holdout_end < forecast.forecast_origin
    assert metrics.training_end < metrics.holdout_start
    assert math.isfinite(metrics.mae_mg_dl) and metrics.mae_mg_dl >= 0
    assert math.isfinite(metrics.rmse_mg_dl) and metrics.rmse_mg_dl >= metrics.mae_mg_dl


def test_future_glucose_and_indicator_values_cannot_affect_features(series):
    index = 400
    indicators = {"meal_indicator": np.zeros(len(series.values)), "activity_indicator": np.zeros(len(series.values))}
    original = service.CGMSeries(series.timestamps, series.values, indicators)
    values = series.values.copy()
    values[index:] += 1000
    changed_indicators = {key: value.copy() for key, value in indicators.items()}
    for value in changed_indicators.values():
        value[index:] = 1
    changed = service.CGMSeries(series.timestamps, values, changed_indicators)
    np.testing.assert_array_equal(service.features_at_origin(original, index), service.features_at_origin(changed, index))


def test_features_have_expected_past_lags_and_trailing_statistics(series):
    index = 400
    features = dict(zip(service.feature_names(series), service.features_at_origin(series, index)))
    assert features["glucose_lag_5m"] == series.values[index - 1]
    assert features["glucose_lag_1440m"] == series.values[index - 288]
    assert features["glucose_mean_60m"] == pytest.approx(np.mean(series.values[index - 12:index]))
    assert features["glucose_std_60m"] == pytest.approx(np.std(series.values[index - 12:index], ddof=0))
    assert features["glucose_std_1440m"] == pytest.approx(np.std(series.values[index - 288:index], ddof=0))
    assert series.indicators == {}
    assert not any("meal_indicator" in name or "activity_indicator" in name for name in features)


def test_all_training_targets_end_before_holdout_and_scaler_is_train_only(short_series):
    split = len(short_series.values) * 4 // 5
    features, targets, origins = service.training_examples(short_series, split)
    assert np.all(origins + 288 <= split)
    assert origins[-1] + 287 == split - 1
    np.testing.assert_array_equal(targets[-1], short_series.values[split - 288:split])
    changed_values = short_series.values.copy()
    changed_values[split:] += 1000
    changed = service.CGMSeries(short_series.timestamps, changed_values, {})
    changed_features, changed_targets, changed_origins = service.training_examples(changed, split)
    np.testing.assert_array_equal(features, changed_features)
    np.testing.assert_array_equal(targets, changed_targets)
    np.testing.assert_array_equal(origins, changed_origins)
    first = service.fit_model(features, targets)
    second = service.fit_model(changed_features, changed_targets)
    np.testing.assert_allclose(first.named_steps["scale"].mean_, features.mean(axis=0))
    np.testing.assert_array_equal(first.named_steps["scale"].mean_, second.named_steps["scale"].mean_)
    np.testing.assert_array_equal(first.named_steps["ridge"].coef_, second.named_steps["ridge"].coef_)


def test_future_rows_do_not_change_historical_training_metrics_or_forecasts(series):
    index = 1440
    origin = series.timestamps[index]
    values = series.values.copy()
    values[index:] += 1000
    changed = service.CGMSeries(series.timestamps, values, {})
    first = service.train_and_forecast(series, origin)
    second = service.train_and_forecast(changed, origin)
    assert first.model_dump() == second.model_dump()
    assert first.last_observation_timestamp < origin
    assert first.holdout_metrics.holdout_end < origin


def test_holdout_metrics_measure_complete_24h_trajectories(short_series, monkeypatch):
    class ZeroModel:
        def predict(self, features):
            return np.zeros((len(features), 288))

    monkeypatch.setattr(service, "fit_model", lambda features, targets: ZeroModel())
    metrics = service.evaluate_holdout(short_series)
    truth = short_series.values[1152:1440]
    assert metrics.evaluation_origins == 1
    assert metrics.evaluated_points == 288
    assert metrics.mae_mg_dl == pytest.approx(np.mean(np.abs(truth)), abs=1e-6)
    assert metrics.rmse_mg_dl == pytest.approx(np.sqrt(np.mean(truth ** 2)), abs=1e-6)


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def csv_row(timestamp="2026-09-15T00:00:00Z", **fields):
    return {
        "timestamp": timestamp, "glucose_mg_dl": "110", "unit": "mg/dL",
        "patient_id": "maya", "synthetic": "true", "clinically_validated": "false", **fields,
    }


def test_optional_event_indicators_use_only_observed_events(tmp_path, series):
    rows = [csv_row(timestamp=stamp.isoformat(), meal_indicator="0", activity_indicator="0")
            for stamp in series.timestamps[:289]]
    rows[287]["meal_indicator"] = "1"
    rows[288]["meal_indicator"] = rows[288]["activity_indicator"] = "1"
    path = tmp_path / "indicators.csv"
    write_rows(path, rows)
    loaded = service.load_cgm_csv(path)
    features = dict(zip(service.feature_names(loaded), service.features_at_origin(loaded, 288)))
    assert features["meal_indicator_last"] == 1
    assert features["meal_indicator_fraction_60m"] == pytest.approx(1 / 12)
    assert features["activity_indicator_last"] == 0
    assert features["activity_indicator_fraction_60m"] == 0


@pytest.mark.parametrize("fields", [
    {"glucose_mg_dl": "NaN"}, {"glucose_mg_dl": "inf"}, {"glucose_mg_dl": ""},
    {"unit": "mmol/L"}, {"synthetic": "false"}, {"clinically_validated": "true"},
    {"timestamp": "2026-09-15T00:00:00"}, {"meal_indicator": "2"},
])
def test_invalid_or_unlabeled_dataset_is_rejected(tmp_path, fields):
    path = tmp_path / "invalid.csv"
    write_rows(path, [csv_row(**fields)])
    with pytest.raises(service.GlucoseForecastError, match="unavailable or invalid"):
        service.load_cgm_csv(path)


@pytest.mark.parametrize("second", ["2026-09-15T00:00:00Z", "2026-09-15T00:10:00Z", "2026-09-14T23:55:00Z"])
def test_missing_duplicate_or_out_of_order_samples_are_rejected(tmp_path, second):
    path = tmp_path / "gap.csv"
    write_rows(path, [csv_row(), csv_row(timestamp=second)])
    with pytest.raises(service.GlucoseForecastError):
        service.load_cgm_csv(path)


def test_missing_and_empty_dataset_fail_cleanly(tmp_path):
    with pytest.raises(service.GlucoseForecastError):
        service.load_cgm_csv(tmp_path / "missing.csv")
    path = tmp_path / "empty.csv"
    path.write_text("timestamp,glucose_mg_dl\n", encoding="utf-8")
    with pytest.raises(service.GlucoseForecastError, match="empty"):
        service.load_cgm_csv(path)


def test_insufficient_training_or_holdout_history_fails_cleanly(series):
    for length in (288, 864):
        short = service.CGMSeries(series.timestamps[:length], series.values[:length], {})
        with pytest.raises(service.GlucoseForecastError):
            service.train_and_forecast(short)


@pytest.mark.parametrize("origin", [
    datetime(2026, 9, 20), datetime(2026, 9, 20, 0, 1, tzinfo=timezone.utc),
    datetime(2026, 10, 15, 0, 5, tzinfo=timezone.utc),
])
def test_naive_misaligned_or_stale_origin_is_rejected(series, origin):
    with pytest.raises(service.GlucoseForecastError):
        service.train_and_forecast(series, origin)


def test_non_finite_predictions_are_rejected(short_series, monkeypatch):
    class InvalidModel:
        def predict(self, features):
            return np.full((len(features), 288), np.nan)

    monkeypatch.setattr(service, "fit_model", lambda features, targets: InvalidModel())
    with pytest.raises(service.GlucoseForecastError, match="non-finite"):
        service.train_and_forecast(short_series)


def test_endpoint_schema_and_synthetic_labels_without_open_wearables(forecast, monkeypatch):
    async def no_upstream(*args, **kwargs):
        pytest.fail("The synthetic forecasting endpoint must not call Open Wearables")

    monkeypatch.setattr(httpx.AsyncClient, "get", no_upstream)
    with TestClient(app) as client:
        response = client.get("/patients/maya/forecast/glucose")
    assert response.status_code == 200
    body = response.json()
    assert body["forecast_origin"] == "2026-10-15T00:00:00Z"
    assert body["model_type"] == "ridge_regression"
    assert body["forecast_strategy"] == "direct_multi_output"
    assert body["horizon_hours"] == 24
    assert body["cadence_minutes"] == 5
    assert body["validated"] is False
    assert body["synthetic"] is True
    assert body["prototype"] is True
    assert body["unit"] == "mg/dL"
    assert len(body["forecast_points"]) == 288
    assert body["holdout_metrics"]["scope"] == "synthetic_data_only"
    assert body == forecast.model_dump(mode="json")


def test_endpoint_missing_dataset_is_a_clear_503(monkeypatch):
    def failure():
        raise service.GlucoseForecastError("Synthetic CGM dataset is unavailable or invalid")

    monkeypatch.setattr(patients, "get_glucose_forecast", failure)
    with TestClient(app) as client:
        response = client.get("/patients/maya/forecast/glucose")
    assert response.status_code == 503
    assert response.json() == {"detail": "Synthetic CGM dataset is unavailable or invalid"}


def test_default_forecast_is_cached_after_lazy_training(short_series, monkeypatch):
    calls = []

    def load():
        calls.append(True)
        return short_series

    service.get_glucose_forecast.cache_clear()
    monkeypatch.setattr(service, "load_cgm_csv", load)
    try:
        first = service.get_glucose_forecast()
        assert service.get_glucose_forecast() is first
        assert len(calls) == 1
    finally:
        service.get_glucose_forecast.cache_clear()
