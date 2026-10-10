"""Deterministic CGM-style demo curves, not clinically validated physiology."""

import argparse
import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

DEFAULT_START_DATE = date(2026, 9, 15)
DEFAULT_DAYS = 30
DEFAULT_SEED = 42
SAMPLE_MINUTES = 5
SAMPLES_PER_DAY = 24 * 60 // SAMPLE_MINUTES
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "maya_synthetic_cgm.csv"


@dataclass(frozen=True)
class GlucoseSample:
    timestamp: datetime
    glucose_mg_dl: float


@dataclass(frozen=True)
class _DayPattern:
    baseline: float
    meals: tuple[tuple[float, float], ...]
    activity_minute: float
    activity_amplitude: float


def _pulse(elapsed_minutes: float, peak_minutes: float = 60.0) -> float:
    """An illustrative smooth rise and decay, with no effect before an event."""
    if elapsed_minutes <= 0:
        return 0.0
    position = elapsed_minutes / peak_minutes
    return position ** 2 * math.exp(2.0 * (1.0 - position))


def generate_cgm(
    *, start_date: date = DEFAULT_START_DATE, days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED, include_activity: bool = True,
) -> list[GlucoseSample]:
    """Generate complete UTC days at five-minute intervals using local RNGs.

    Curve amplitudes, timings, and bounds are artistic prototype parameters,
    not clinical thresholds or estimates of a patient's physiological response.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    structure_rng = random.Random(seed)
    noise_rng = random.Random(seed + 1)

    # Include the preceding day's meal tails and the next day's baseline.
    patterns = {}
    for day in range(-1, days + 1):
        patterns[day] = _DayPattern(
            baseline=112.0 + 4.0 * math.sin(2.0 * math.pi * day / 7.0)
            + structure_rng.uniform(-3.0, 3.0),
            meals=tuple(
                (minute + structure_rng.uniform(-25.0, 25.0),
                 amplitude * structure_rng.uniform(0.8, 1.2))
                for minute, amplitude in ((450.0, 30.0), (750.0, 42.0), (1110.0, 36.0))
            ),
            # Draw these even when disabled so toggling activity changes only its effect.
            activity_minute=960.0 + structure_rng.uniform(-30.0, 30.0),
            activity_amplitude=structure_rng.uniform(4.0, 9.0),
        )

    noise = 0.0
    for _ in range(SAMPLES_PER_DAY):
        noise = 0.92 * noise + noise_rng.gauss(0.0, 0.6)

    start = datetime.combine(start_date, time.min, timezone.utc)
    samples = []
    for index in range(days * SAMPLES_PER_DAY):
        day, slot = divmod(index, SAMPLES_PER_DAY)
        minute = slot * SAMPLE_MINUTES
        hour = minute / 60.0
        current = patterns[day]
        fraction = minute / (24.0 * 60.0)
        baseline = current.baseline * (1.0 - fraction) + patterns[day + 1].baseline * fraction
        daily_wave = 4.0 * math.sin(2.0 * math.pi * (hour - 7.0) / 24.0)
        night_distance = (hour - 3.0 + 12.0) % 24.0 - 12.0
        overnight = -6.0 * math.exp(-0.5 * (night_distance / 2.0) ** 2)
        meal_effect = sum(
            amplitude * _pulse(minute + offset - meal_minute)
            for pattern, offset in ((current, 0.0), (patterns[day - 1], 1440.0))
            for meal_minute, amplitude in pattern.meals
        )
        activity_effect = 0.0
        if include_activity:
            activity_effect = sum(
                pattern.activity_amplitude * _pulse(minute + offset - pattern.activity_minute)
                for pattern, offset in ((current, 0.0), (patterns[day - 1], 1440.0))
            )
        noise = 0.92 * noise + noise_rng.gauss(0.0, 0.6)
        glucose = baseline + daily_wave + overnight + meal_effect - activity_effect + noise
        # These are generator bounds, never normal/abnormal classifications.
        glucose = round(max(80.0, min(220.0, glucose)), 2)
        samples.append(GlucoseSample(
            timestamp=start + timedelta(minutes=index * SAMPLE_MINUTES),
            glucose_mg_dl=glucose,
        ))
    return samples


def write_cgm_csv(
    output: Path = DEFAULT_OUTPUT, *, start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS, seed: int = DEFAULT_SEED, include_activity: bool = True,
) -> int:
    samples = generate_cgm(start_date=start_date, days=days, seed=seed, include_activity=include_activity)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "timestamp", "glucose_mg_dl", "unit", "patient_id", "synthetic",
            "clinically_validated", "source", "generator_seed", "activity_enabled",
        ], lineterminator="\n")
        writer.writeheader()
        for sample in samples:
            writer.writerow({
                "timestamp": sample.timestamp.isoformat().replace("+00:00", "Z"),
                "glucose_mg_dl": f"{sample.glucose_mg_dl:.2f}",
                "unit": "mg/dL",
                "patient_id": "maya",
                "synthetic": "true",
                "clinically_validated": "false",
                "source": "nestwatch_synthetic_cgm",
                "generator_seed": seed,
                "activity_enabled": str(include_activity).lower(),
            })
    return len(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START_DATE)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--no-activity", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    count = write_cgm_csv(
        args.output, start_date=args.start_date, days=args.days, seed=args.seed,
        include_activity=not args.no_activity,
    )
    print(f"Wrote {count} synthetic, not clinically validated samples to {args.output}")


if __name__ == "__main__":
    main()
