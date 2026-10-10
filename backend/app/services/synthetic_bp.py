"""Deliberate BP-rise software/model testing fixtures, not validated physiology."""

import argparse
import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

DEFAULT_START_DATE = date(2025, 10, 15)
DEFAULT_DAYS = 365
DEFAULT_SEED = 73
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "maya_synthetic_bp_training.csv"


@dataclass(frozen=True)
class BPMeasurement:
    timestamp: datetime
    systolic_mm_hg: float
    diastolic_mm_hg: float
    fixture_episode_id: str = "baseline"
    fixture_episode_phase: str = "baseline"


@dataclass(frozen=True)
class BPRiseEpisode:
    episode_id: str
    start_day: int
    rise_days: int
    plateau_days: int
    return_days: int
    systolic_rise: float
    diastolic_rise: float

    @property
    def end_day(self) -> int:
        return self.start_day + self.rise_days + self.plateau_days + self.return_days


def fixture_episodes(seed: int = DEFAULT_SEED) -> tuple[BPRiseEpisode, ...]:
    """Fixed calendar positions; strengths vary with seed, never model scores.

    Seven deliberately scheduled episodes vary in strength and duration. The
    schedule spans the year, including its final quarter, to exercise both
    event classes in software tests. No diagnosis or physiological claim is made.
    """
    rng = random.Random(seed + 1000)
    templates = (
        (28, 8, 3, 9, 28.0, 14.0),
        (76, 10, 2, 8, 18.0, 9.0),
        (128, 7, 3, 10, 34.0, 17.0),
        (182, 9, 2, 9, 25.0, 12.0),
        (236, 6, 3, 8, 16.0, 8.0),
        (298, 10, 3, 9, 38.0, 20.0),
        (337, 7, 2, 9, 33.0, 16.0),
    )
    return tuple(
        BPRiseEpisode(
            f"bp_rise_{index}", start, rise, plateau, recovery,
            sbp * rng.uniform(0.9, 1.1), dbp * rng.uniform(0.9, 1.1),
        )
        for index, (start, rise, plateau, recovery, sbp, dbp) in enumerate(templates, 1)
    )


def _episode_effect(position: float, episodes: tuple[BPRiseEpisode, ...]) -> tuple[float, float, str, str]:
    for episode in episodes:
        if not episode.start_day <= position < episode.end_day:
            continue
        elapsed = position - episode.start_day
        if elapsed < episode.rise_days:
            fraction = 0.5 * (1.0 - math.cos(math.pi * elapsed / episode.rise_days))
            phase = "rise"
        elif elapsed < episode.rise_days + episode.plateau_days:
            fraction, phase = 1.0, "plateau"
        else:
            recovery = elapsed - episode.rise_days - episode.plateau_days
            fraction = 0.5 * (1.0 + math.cos(math.pi * recovery / episode.return_days))
            phase = "return"
        return episode.systolic_rise * fraction, episode.diastolic_rise * fraction, episode.episode_id, phase
    return 0.0, 0.0, "baseline", "baseline"


def generate_bp(
    *, start_date: date = DEFAULT_START_DATE, days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
) -> list[BPMeasurement]:
    """Mostly baseline measurements with gradual, deliberately scripted rises."""
    if days < 1:
        raise ValueError("days must be at least 1")
    rng = random.Random(seed)
    episodes = fixture_episodes(seed)
    level = diastolic_variation = 0.0
    for _ in range(120):
        level = 0.985 * level + rng.gauss(0.0, 1.5)
        diastolic_variation = 0.96 * diastolic_variation + rng.gauss(0.0, 0.8)
    start = datetime.combine(start_date, time(8), timezone.utc)
    rows = []
    for day in range(days):
        level = 0.985 * level + rng.gauss(0.0, 1.5)
        diastolic_variation = 0.96 * diastolic_variation + rng.gauss(0.0, 0.8)
        wave = 5.0 * math.sin(2.0 * math.pi * day / 50.0)
        for reading in range(2):
            daily_offset = 1.5 if reading == 0 else -1.5
            sbp_rise, dbp_rise, episode_id, phase = _episode_effect(day + reading / 2.0, episodes)
            systolic = 124.0 + level + wave + daily_offset + rng.gauss(0.0, 2.0) + sbp_rise
            diastolic = 78.0 + 0.45 * (level + wave) + diastolic_variation + 0.5 * daily_offset + rng.gauss(0.0, 1.4) + dbp_rise
            # Artificial generator bounds, not normal/abnormal classifications.
            rows.append(BPMeasurement(
                start + timedelta(days=day, hours=12 * reading),
                round(max(90.0, min(175.0, systolic)), 2),
                round(max(55.0, min(115.0, diastolic)), 2),
                episode_id, phase,
            ))
    return rows


def write_bp_csv(
    output: Path = DEFAULT_OUTPUT, *, start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS, seed: int = DEFAULT_SEED,
) -> int:
    rows = generate_bp(start_date=start_date, days=days, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "timestamp", "systolic_mm_hg", "diastolic_mm_hg", "unit", "patient_id",
            "synthetic", "clinically_validated", "source", "generator_seed",
            "fixture_episode_id", "fixture_episode_phase",
        ], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "timestamp": row.timestamp.isoformat().replace("+00:00", "Z"),
                "systolic_mm_hg": f"{row.systolic_mm_hg:.2f}",
                "diastolic_mm_hg": f"{row.diastolic_mm_hg:.2f}",
                "unit": "mmHg", "patient_id": "maya", "synthetic": "true",
                "clinically_validated": "false", "source": "nestwatch_synthetic_bp_training",
                "generator_seed": seed,
                "fixture_episode_id": row.fixture_episode_id,
                "fixture_episode_phase": row.fixture_episode_phase,
            })
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START_DATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    count = write_bp_csv(args.output, start_date=args.start_date, days=args.days, seed=args.seed)
    print(f"Wrote {count} synthetic, not clinically validated BP measurements to {args.output}")


if __name__ == "__main__":
    main()
