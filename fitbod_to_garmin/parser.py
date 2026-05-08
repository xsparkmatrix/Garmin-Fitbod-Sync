"""Parse Fitbod CSV exports and group sets into per-date workouts."""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Column names as they appear in the Fitbod export (case-insensitive match below)
_COL_DATE = "date"
_COL_EXERCISE = "exercise"
_COL_REPS = "reps"
_COL_SETS = "sets"
_COL_WEIGHT = "weight (lbs)"
_COL_DURATION = "duration (secs)"
_COL_NOTES = "notes"


@dataclass
class ExerciseSet:
    exercise: str
    reps: int
    sets: int
    weight_lbs: float
    duration_secs: int
    notes: str = ""


@dataclass
class Workout:
    date: date
    sets: list[ExerciseSet] = field(default_factory=list)


def _parse_date(raw: str) -> date | None:
    for fmt in (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(raw: str, default: int = 0) -> int:
    try:
        return int(float(raw.strip())) if raw.strip() else default
    except (ValueError, AttributeError):
        return default


def _parse_float(raw: str, default: float = 0.0) -> float:
    try:
        return float(raw.strip()) if raw.strip() else default
    except (ValueError, AttributeError):
        return default


def _normalise_headers(headers: list[str]) -> dict[str, int]:
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def parse_csv(path: Path) -> list[Workout]:
    """Parse a Fitbod CSV and return workouts sorted by date."""
    workouts_by_date: dict[date, list[ExerciseSet]] = defaultdict(list)

    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    raw_text = None
    for enc in encodings:
        try:
            raw_text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue

    if raw_text is None:
        raise ValueError(f"Cannot decode {path} with any supported encoding")

    reader = csv.reader(raw_text.splitlines())
    try:
        headers = next(reader)
    except StopIteration:
        log.warning("CSV file is empty: %s", path)
        return []

    idx = _normalise_headers(headers)
    required = {_COL_DATE, _COL_EXERCISE}
    missing = required - idx.keys()
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    def col(row: list[str], name: str, default: str = "") -> str:
        i = idx.get(name)
        if i is None or i >= len(row):
            return default
        return row[i]

    for lineno, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        try:
            raw_date = col(row, _COL_DATE)
            workout_date = _parse_date(raw_date)
            if workout_date is None:
                log.warning("Line %d: unparseable date %r — skipping", lineno, raw_date)
                continue

            exercise = col(row, _COL_EXERCISE).strip()
            if not exercise:
                log.warning("Line %d: empty exercise name — skipping", lineno)
                continue

            s = ExerciseSet(
                exercise=exercise,
                reps=_parse_int(col(row, _COL_REPS)),
                sets=_parse_int(col(row, _COL_SETS), default=1),
                weight_lbs=_parse_float(col(row, _COL_WEIGHT)),
                duration_secs=_parse_int(col(row, _COL_DURATION)),
                notes=col(row, _COL_NOTES),
            )
            workouts_by_date[workout_date].append(s)
        except Exception as exc:
            log.warning("Line %d: unexpected error %s — skipping", lineno, exc)

    return [
        Workout(date=d, sets=sets)
        for d, sets in sorted(workouts_by_date.items())
    ]


def filter_since(workouts: list[Workout], since: date) -> list[Workout]:
    return [w for w in workouts if w.date >= since]
