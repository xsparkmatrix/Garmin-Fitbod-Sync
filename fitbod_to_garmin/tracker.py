"""JSON-based dedup tracker. Stores workout dates that have been uploaded."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d"


class Tracker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._uploaded: set[str] = self._load()

    def _load(self) -> set[str]:
        if self._path.exists():
            text = self._path.read_text().strip()
            if not text:
                return set()
            try:
                data = json.loads(text)
                return set(data.get("uploaded_dates", []))
            except Exception as exc:
                log.warning("Could not read tracker file %s: %s", self._path, exc)
        return set()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps({"uploaded_dates": sorted(self._uploaded)}, indent=2)
        )

    def already_uploaded(self, workout_date: date) -> bool:
        return workout_date.strftime(_DATE_FMT) in self._uploaded

    def mark_uploaded(self, workout_date: date) -> None:
        self._uploaded.add(workout_date.strftime(_DATE_FMT))
        self._save()
