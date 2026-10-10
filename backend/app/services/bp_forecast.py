"""Logistic regression for a synthetic BP threshold-measurement event only."""

import csv
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..schemas.bp_forecast import (
    BPClassificationMetrics, BPFeatureContribution, BPForecast, BPReviewThresholds, SyntheticBPHoldoutMetrics,
)

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "maya_synthetic_bp_training.csv"
CADENCE = timedelta(hours=12)
HISTORY_STEPS = HORIZON_STEPS = 14
FEATURE_NAMES = (
    "systolic_mean_7d_mm_hg", "diastolic_mean_7d_mm_hg",
    "systolic_slope_7d_mm_hg_per_day", "diastolic_slope_7d_mm_hg_per_day",
    "systolic_std_7d_mm_hg", "diastolic_std_7d_mm_hg",
    "last_systolic_mm_hg", "last_diastolic_mm_hg",
)


class BPForecastError(Exception):
    """Invalid dataset or a model failure, safe to expose without file details."""


class InsufficientBPData(Exception):
    """A reason code for returning no probability rather than an implied negative."""


@dataclass(frozen=True)
class BPSeries:
    timestamps: tuple[datetime, ...]
    systolic: np.ndarray
    diastolic: np.ndarray


def load_bp_csv(path: Path = DATASET_PATH) -> BPSeries:
    timestamps, systolic, diastolic = [], [], []
    try:
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            required = {"timestamp", "systolic_mm_hg", "diastolic_mm_hg", "unit",
                        "patient_id", "synthetic", "clinically_validated"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("Missing BP columns")
            for row in reader:
                if (row["unit"] != "mmHg" or row["patient_id"] != "maya"
                        or row["synthetic"] != "true" or row["clinically_validated"] != "false"):
                    raise ValueError("Expected labeled synthetic Maya BP measurements")
                timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("Timestamps need a timezone")
                timestamp = timestamp.astimezone(timezone.utc)
                if timestamps and timestamp - timestamps[-1] != CADENCE:
                    raise ValueError("BP measurements must be consecutive at 12-hour cadence")
                sbp, dbp = float(row["systolic_mm_hg"]), float(row["diastolic_mm_hg"])
                if not np.isfinite((sbp, dbp)).all() or sbp <= 0 or dbp <= 0:
                    raise ValueError("BP measurements must be positive finite numbers")
                timestamps.append(timestamp)
                systolic.append(sbp)
                diastolic.append(dbp)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise BPForecastError("Synthetic BP dataset is unavailable or invalid") from exc
    return BPSeries(tuple(timestamps), np.asarray(systolic, dtype=float), np.asarray(diastolic, dtype=float))


def features_at_origin(series: BPSeries, origin_index: int) -> np.ndarray:
    """Use only the 14 measurements strictly preceding the first unknown sample."""
    if not HISTORY_STEPS <= origin_index <= len(series.timestamps):
        raise InsufficientBPData("insufficient_recent_bp_history")
    start = origin_index - HISTORY_STEPS
    times = series.timestamps[start:origin_index]
    sbp, dbp = series.systolic[start:origin_index], series.diastolic[start:origin_index]
    if (len(sbp) != HISTORY_STEPS or len(dbp) != HISTORY_STEPS
            or not np.isfinite(sbp).all() or not np.isfinite(dbp).all()
            or any(second - first != CADENCE for first, second in zip(times, times[1:]))):
        raise InsufficientBPData("incomplete_recent_bp_history")
    days = np.arange(HISTORY_STEPS, dtype=float) / 2.0
    centered = days - days.mean()
    denominator = np.dot(centered, centered)
    return np.asarray([
        sbp.mean(), dbp.mean(),
        np.dot(centered, sbp - sbp.mean()) / denominator,
        np.dot(centered, dbp - dbp.mean()) / denominator,
        sbp.std(ddof=0), dbp.std(ddof=0), sbp[-1], dbp[-1],
    ], dtype=float)


def event_label(series: BPSeries, origin_index: int, thresholds: BPReviewThresholds) -> int:
    """Labels use complete future windows, only for supervised training/evaluation."""
    end = origin_index + HORIZON_STEPS
    if origin_index < 0 or end > len(series.timestamps):
        raise InsufficientBPData("incomplete_future_target_window")
    sbp, dbp = series.systolic[origin_index:end], series.diastolic[origin_index:end]
    times = series.timestamps[origin_index:end]
    if (len(sbp) != HORIZON_STEPS or len(dbp) != HORIZON_STEPS
            or not np.isfinite(sbp).all() or not np.isfinite(dbp).all()
            or any(second - first != CADENCE for first, second in zip(times, times[1:]))
            or (origin_index > 0 and times[0] - series.timestamps[origin_index - 1] != CADENCE)):
        raise InsufficientBPData("incomplete_future_target_window")
    return int(np.any(sbp >= thresholds.systolic_mm_hg) or np.any(dbp >= thresholds.diastolic_mm_hg))


def training_examples(
    series: BPSeries, stop_index: int, thresholds: BPReviewThresholds,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not 0 <= stop_index <= len(series.timestamps):
        raise BPForecastError("Training cutoff is outside observed BP history")
    # One training origin per day. Purge targets that could extend into holdout.
    origins = np.arange(HISTORY_STEPS, stop_index - HORIZON_STEPS + 1, 2)
    if not len(origins):
        raise InsufficientBPData("insufficient_complete_training_windows")
    features = np.vstack([features_at_origin(series, int(origin)) for origin in origins])
    labels = np.asarray([event_label(series, int(origin), thresholds) for origin in origins])
    return features, labels, origins


def fit_model(features: np.ndarray, labels: np.ndarray) -> Pipeline:
    if len(np.unique(labels)) < 2:
        raise InsufficientBPData("single_class_training_labels")
    model = Pipeline([
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, tol=1e-8)),
    ])
    try:
        model.fit(features, labels)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        raise BPForecastError("Synthetic BP event model could not be trained") from exc
    return model


def _probabilities(model: Pipeline, features: np.ndarray) -> np.ndarray:
    probabilities = model.predict_proba(features)[:, 1]
    if not np.isfinite(probabilities).all() or np.any(probabilities < 0) or np.any(probabilities > 1):
        raise BPForecastError("Synthetic BP event model returned invalid probabilities")
    return probabilities


def classification_metrics(truth: np.ndarray, probabilities: np.ndarray) -> BPClassificationMetrics:
    """Score event labels; mathematically undefined ratios stay null with reasons."""
    if (not len(truth) or truth.shape != probabilities.shape
            or not np.isin(truth, (0, 1)).all() or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0) or np.any(probabilities > 1)):
        raise BPForecastError("Invalid synthetic event evaluation inputs")
    predicted = probabilities >= 0.5
    positive = truth == 1
    tp = int(np.sum(positive & predicted))
    fp = int(np.sum(~positive & predicted))
    tn = int(np.sum(~positive & ~predicted))
    fn = int(np.sum(positive & ~predicted))
    unavailable = []

    def ratio(numerator: int, denominator: int, reason: str) -> float | None:
        if not denominator:
            unavailable.append(reason)
            return None
        return round(numerator / denominator, 6)

    both_classes = len(np.unique(truth)) == 2
    return BPClassificationMetrics(
        accuracy=round((tp + tn) / len(truth), 6),
        precision=ratio(tp, tp + fp, "precision_no_positive_predictions"),
        recall=ratio(tp, tp + fn, "recall_no_positive_labels"),
        specificity=ratio(tn, tn + fp, "specificity_no_negative_labels"),
        f1=ratio(2 * tp, 2 * tp + fp + fn, "f1_no_positive_labels_or_predictions"),
        brier_score=round(float(brier_score_loss(truth, probabilities)), 6),
        log_loss=round(float(log_loss(truth, probabilities, labels=[0, 1])), 6),
        roc_auc=round(float(roc_auc_score(truth, probabilities)), 6) if both_classes else None,
        roc_auc_unavailable_reason=None if both_classes else "single_class_holdout_labels",
        true_positives=tp, false_positives=fp, true_negatives=tn, false_negatives=fn,
        unavailable_reasons=unavailable,
    )


def evaluate_holdout(series: BPSeries, thresholds: BPReviewThresholds) -> SyntheticBPHoldoutMetrics:
    # Split at a complete daily boundary, rather than between paired daily readings.
    split = (len(series.timestamps) // 2 * 4 // 5) * 2
    features, labels, training_origins = training_examples(series, split, thresholds)
    evaluation_origins = range(split, len(series.timestamps) - HORIZON_STEPS + 1, HORIZON_STEPS)
    if not len(evaluation_origins):
        raise InsufficientBPData("insufficient_complete_holdout_windows")
    model = fit_model(features, labels)
    evaluation_features = np.vstack([features_at_origin(series, origin) for origin in evaluation_origins])
    truth = np.asarray([event_label(series, origin, thresholds) for origin in evaluation_origins])
    probabilities = _probabilities(model, evaluation_features)
    metrics = classification_metrics(truth, probabilities)
    baseline = classification_metrics(truth, np.zeros(len(truth), dtype=float))
    return SyntheticBPHoldoutMetrics(
        **metrics.model_dump(),
        no_event_baseline_accuracy=baseline.accuracy,
        constant_no_event_baseline=baseline,
        training_start=series.timestamps[0], training_end=series.timestamps[split - 1],
        holdout_start=series.timestamps[split],
        holdout_end=series.timestamps[evaluation_origins[-1] + HORIZON_STEPS - 1],
        training_measurements=split, training_windows=len(training_origins),
        training_positive_events=int(labels.sum()), training_negative_events=int(len(labels) - labels.sum()),
        holdout_measurements=len(series.timestamps) - split,
        evaluated_windows=len(evaluation_origins), evaluated_bp_measurements=len(evaluation_origins) * HORIZON_STEPS,
        holdout_positive_events=int(truth.sum()), holdout_negative_events=int(len(truth) - truth.sum()),
    )


def train_and_forecast(
    series: BPSeries, thresholds: BPReviewThresholds, forecast_origin: datetime | None = None,
) -> BPForecast:
    if forecast_origin is None and series.timestamps:
        forecast_origin = series.timestamps[-1] + CADENCE
    if forecast_origin is not None:
        if forecast_origin.tzinfo is None:
            raise BPForecastError("Forecast origin must have a timezone")
        forecast_origin = forecast_origin.astimezone(timezone.utc)
    stop = bisect_left(series.timestamps, forecast_origin) if forecast_origin is not None else 0
    # Crop before label generation, fitting, scaling, evaluation, or inference.
    history = BPSeries(series.timestamps[:stop], series.systolic[:stop], series.diastolic[:stop])
    result = BPForecast(
        forecast_origin=forecast_origin,
        last_observation_timestamp=history.timestamps[-1] if stop else None,
        event_window_end=forecast_origin + timedelta(days=7) if forecast_origin is not None else None,
        event_definition=(
            "Whether at least one future synthetic blood-pressure measurement reaches "
            "the configured BP review threshold within the next 7 days: "
            f"systolic >= {thresholds.systolic_mm_hg:g} mmHg OR "
            f"diastolic >= {thresholds.diastolic_mm_hg:g} mmHg."
        ),
        status="insufficient_data", thresholds=thresholds,
    )
    if not stop:
        result.reasons = ["missing_bp_history"]
        return result
    if history.timestamps[-1] + CADENCE != forecast_origin:
        result.reasons = ["stale_or_misaligned_bp_history"]
        return result
    try:
        current_features = features_at_origin(history, stop)
        result.feature_values = dict(zip(FEATURE_NAMES, (round(float(value), 6) for value in current_features)))
        result.holdout_metrics = evaluate_holdout(history, thresholds)
        # Refit the same fixed model on complete windows from all pre-origin history.
        features, labels, _ = training_examples(history, stop, thresholds)
        model = fit_model(features, labels)
    except InsufficientBPData as exc:
        result.reasons = [str(exc)]
        return result
    result.probability = round(float(_probabilities(model, current_features.reshape(1, -1))[0]), 6)
    result.status = "forecast_available"
    scaled = model.named_steps["scale"].transform(current_features.reshape(1, -1))[0]
    contributions = model.named_steps["logistic"].coef_[0] * scaled
    ranked = sorted(zip(FEATURE_NAMES, current_features, contributions), key=lambda item: abs(item[2]), reverse=True)
    result.main_contributing_features = [
        BPFeatureContribution(feature=name, value=round(float(value), 6),
                              standardized_log_odds_contribution=round(float(contribution), 6))
        for name, value, contribution in ranked[:3]
    ]
    return result


@lru_cache(maxsize=8)
def get_bp_forecast(systolic_threshold: float, diastolic_threshold: float) -> BPForecast:
    """Cache by target-defining thresholds; restart after replacing the CSV."""
    thresholds = BPReviewThresholds(systolic_mm_hg=systolic_threshold, diastolic_mm_hg=diastolic_threshold)
    return train_and_forecast(load_bp_csv(), thresholds)
