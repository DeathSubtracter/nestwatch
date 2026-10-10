"""Direct Ridge forecasts for the local synthetic CGM research dataset only."""

import csv
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..schemas.glucose_forecast import (
    GlucoseForecast, GlucoseForecastPoint, SyntheticHoldoutMetrics,
)

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "maya_synthetic_cgm.csv"
CADENCE = timedelta(minutes=5)
HORIZON_STEPS = 288
LAG_STEPS = (1, 2, 3, 6, 12, 24, 288)
ROLLING_STEPS = (12, 36, 288)
HISTORY_STEPS = 288
RIDGE_ALPHA = 10.0


class GlucoseForecastError(Exception):
    """The dataset or model cannot provide a valid prototype forecast."""


@dataclass(frozen=True)
class CGMSeries:
    timestamps: tuple[datetime, ...]
    values: np.ndarray
    indicators: dict[str, np.ndarray]


def load_cgm_csv(path: Path = DATASET_PATH) -> CGMSeries:
    timestamps = []
    values = []
    try:
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            indicators = {
                key: [] for key in ("meal_indicator", "activity_indicator")
                if key in (reader.fieldnames or [])
            }
            for row in reader:
                if (
                    row["unit"] != "mg/dL" or row["patient_id"] != "maya"
                    or row["synthetic"] != "true" or row["clinically_validated"] != "false"
                ):
                    raise ValueError("Expected labeled synthetic Maya data in mg/dL")
                timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("Timestamps must have a timezone")
                timestamp = timestamp.astimezone(timezone.utc)
                if timestamps and timestamp - timestamps[-1] != CADENCE:
                    raise ValueError("Timestamps must be consecutive five-minute samples")
                value = float(row["glucose_mg_dl"])
                if not np.isfinite(value):
                    raise ValueError("Glucose must be finite")
                timestamps.append(timestamp)
                values.append(value)
                for key in indicators:
                    raw = row[key].strip().lower()
                    indicator = float({"true": "1", "false": "0"}.get(raw, raw))
                    if indicator not in (0.0, 1.0):
                        raise ValueError("Event indicators must be binary")
                    indicators[key].append(indicator)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise GlucoseForecastError("Synthetic CGM dataset is unavailable or invalid") from exc
    if not timestamps:
        raise GlucoseForecastError("Synthetic CGM dataset is empty")
    return CGMSeries(
        tuple(timestamps), np.asarray(values, dtype=float),
        {key: np.asarray(value, dtype=float) for key, value in indicators.items()},
    )


def feature_names(series: CGMSeries) -> list[str]:
    names = [f"glucose_lag_{step * 5}m" for step in LAG_STEPS]
    for step in ROLLING_STEPS:
        names.extend((f"glucose_mean_{step * 5}m", f"glucose_std_{step * 5}m"))
    for harmonic in (1, 2, 3):
        names.extend((f"time_of_day_sin_{harmonic}", f"time_of_day_cos_{harmonic}"))
    for key in series.indicators:
        names.extend((f"{key}_last", f"{key}_fraction_60m"))
    return names


def features_at_origin(series: CGMSeries, origin_index: int) -> np.ndarray:
    """Origin is the first unknown sample; all glucose/indicator indices are smaller."""
    if not HISTORY_STEPS <= origin_index <= len(series.values):
        raise GlucoseForecastError("A forecast needs at least 24 hours of preceding CGM history")
    history = series.values[:origin_index]
    features = [history[-step] for step in LAG_STEPS]
    for step in ROLLING_STEPS:
        trailing = history[-step:]
        features.extend((float(np.mean(trailing)), float(np.std(trailing, ddof=0))))
    # Calendar time is known in advance, unlike future glucose or event indicators.
    origin = series.timestamps[origin_index - 1] + CADENCE
    minutes = origin.hour * 60 + origin.minute
    phase = 2.0 * np.pi * minutes / 1440.0
    for harmonic in (1, 2, 3):
        features.extend((float(np.sin(harmonic * phase)), float(np.cos(harmonic * phase))))
    for values in series.indicators.values():
        features.extend((float(values[origin_index - 1]), float(np.mean(values[origin_index - 12:origin_index]))))
    return np.asarray(features, dtype=float)


def training_examples(series: CGMSeries, stop_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every complete 24-hour training target is strictly before stop_index."""
    if not 0 <= stop_index <= len(series.values):
        raise GlucoseForecastError("Training cutoff is outside the observed history")
    origins = np.arange(HISTORY_STEPS, stop_index - HORIZON_STEPS + 1)
    if not len(origins):
        raise GlucoseForecastError("Insufficient synthetic history for complete training trajectories")
    features = np.vstack([features_at_origin(series, int(origin)) for origin in origins])
    targets = np.vstack([series.values[origin:origin + HORIZON_STEPS] for origin in origins])
    return features, targets, origins


def fit_model(features: np.ndarray, targets: np.ndarray) -> Pipeline:
    # Both scaling and regression are fitted only to the supplied training rows.
    model = Pipeline([
        ("scale", StandardScaler()),
        ("ridge", Ridge(alpha=RIDGE_ALPHA, solver="cholesky")),
    ])
    try:
        model.fit(features, targets)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        raise GlucoseForecastError("Synthetic CGM model could not be trained") from exc
    return model


def evaluate_holdout(series: CGMSeries) -> SyntheticHoldoutMetrics:
    split = len(series.values) * 4 // 5
    features, targets, origins = training_examples(series, split)
    evaluation_origins = range(split, len(series.values) - HORIZON_STEPS + 1, HORIZON_STEPS)
    if not len(evaluation_origins):
        raise GlucoseForecastError("Synthetic holdout needs at least one complete 24-hour trajectory")
    model = fit_model(features, targets)
    evaluation_features = np.vstack([features_at_origin(series, origin) for origin in evaluation_origins])
    predictions = model.predict(evaluation_features)
    truth = np.vstack([series.values[origin:origin + HORIZON_STEPS] for origin in evaluation_origins])
    if not np.isfinite(predictions).all():
        raise GlucoseForecastError("Model produced non-finite holdout predictions")
    errors = predictions - truth
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    if not np.isfinite((mae, rmse)).all():
        raise GlucoseForecastError("Model produced non-finite synthetic holdout metrics")
    return SyntheticHoldoutMetrics(
        mae_mg_dl=round(mae, 6),
        rmse_mg_dl=round(rmse, 6),
        training_start=series.timestamps[0],
        training_end=series.timestamps[split - 1],
        holdout_start=series.timestamps[split],
        holdout_end=series.timestamps[evaluation_origins[-1] + HORIZON_STEPS - 1],
        training_samples=split,
        training_windows=len(origins),
        holdout_samples=len(series.values) - split,
        evaluation_origins=len(evaluation_origins),
        evaluated_points=len(evaluation_origins) * HORIZON_STEPS,
    )


def train_and_forecast(series: CGMSeries, forecast_origin: datetime | None = None) -> GlucoseForecast:
    if forecast_origin is None:
        forecast_origin = series.timestamps[-1] + CADENCE
    if forecast_origin.tzinfo is None:
        raise GlucoseForecastError("Forecast origin must have a timezone")
    forecast_origin = forecast_origin.astimezone(timezone.utc)
    stop = bisect_left(series.timestamps, forecast_origin)
    if stop == 0 or series.timestamps[stop - 1] + CADENCE != forecast_origin:
        raise GlucoseForecastError("Forecast origin must immediately follow consecutive observed history")
    # Crop before any training, scaling, feature construction, or evaluation.
    history = CGMSeries(
        series.timestamps[:stop], series.values[:stop],
        {key: values[:stop] for key, values in series.indicators.items()},
    )
    metrics = evaluate_holdout(history)
    # After independent evaluation, refit the same fixed model on all available history.
    features, targets, _ = training_examples(history, len(history.values))
    model = fit_model(features, targets)
    prediction = model.predict(features_at_origin(history, len(history.values)).reshape(1, -1))[0]
    if len(prediction) != HORIZON_STEPS or not np.isfinite(prediction).all():
        raise GlucoseForecastError("Model could not produce a finite 24-hour trajectory")
    return GlucoseForecast(
        forecast_origin=forecast_origin,
        last_observation_timestamp=history.timestamps[-1],
        features=feature_names(history),
        forecast_points=[
            GlucoseForecastPoint(
                timestamp=forecast_origin + index * CADENCE,
                glucose_mg_dl=round(float(value), 2),
            )
            for index, value in enumerate(prediction)
        ],
        holdout_metrics=metrics,
    )


@lru_cache(maxsize=1)
def get_glucose_forecast() -> GlucoseForecast:
    """Train lazily once per process; restart after replacing the local CSV."""
    return train_and_forecast(load_cgm_csv())
