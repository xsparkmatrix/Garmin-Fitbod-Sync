"""Garmin Connect auth and workout upload using python-garminconnect."""

from __future__ import annotations

import getpass
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_TOKEN_DIR = Path.home() / ".garminconnect"

# Garmin activity type for strength training
_ACTIVITY_TYPE = "strength_training"

# Garmin sport type ID for fitness equipment (strength)
_SPORT_TYPE = "FITNESS_EQUIPMENT"


def _get_client():
    """Return an authenticated Garmin client, prompting for creds if needed."""
    try:
        from garminconnect import Garmin
    except ImportError:
        raise SystemExit(
            "python-garminconnect is not installed.\n"
            "Run: pip install python-garminconnect"
        )

    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    tokenstore = str(_TOKEN_DIR)

    client = Garmin()
    try:
        client.login(tokenstore)
        log.debug("Logged in using stored tokens.")
        return client
    except Exception:
        pass

    print("Garmin Connect login required.")
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    try:
        client = Garmin(email=email, password=password)
        client.login()
    except Exception as exc:
        raise SystemExit(f"Garmin authentication failed: {exc}") from exc

    try:
        client.garth.dump(tokenstore)
        log.debug("Tokens saved to %s", tokenstore)
    except Exception as exc:
        log.warning("Could not save tokens: %s", exc)

    return client


def _build_activity_payload(
    workout_date: date,
    sets_data: list[dict],
) -> dict:
    """Build the JSON payload for a Garmin strength training activity."""
    start_dt = datetime.combine(workout_date, datetime.min.time().replace(hour=12))
    start_local = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000")

    total_sets = sum(s.get("sets", 1) for s in sets_data)
    total_duration = sum(s.get("duration_secs", 0) for s in sets_data)
    if total_duration == 0:
        total_duration = total_sets * 60  # estimate 1 min per set

    exercise_sets = []
    for item in sets_data:
        garmin_name = item.get("garmin_name", "OTHER")
        category = item.get("garmin_category", "OTHER")
        weight_kg = round(item.get("weight_lbs", 0) * 0.453592, 2)
        for _ in range(item.get("sets", 1)):
            exercise_sets.append({
                "type": "STRENGTH_TRAINING",
                "exerciseName": garmin_name,
                "exerciseCategory": category,
                "weight": weight_kg,
                "repetitionCount": item.get("reps", 0),
                "duration": item.get("duration_secs", 60),
            })

    return {
        "activityName": f"Fitbod Workout {workout_date}",
        "activityTypeDTO": {
            "typeKey": _ACTIVITY_TYPE,
            "typeId": 13,
        },
        "summaryDTO": {
            "startTimeLocal": start_local,
            "elapsedDuration": total_duration,
            "movingDuration": total_duration,
            "duration": total_duration,
        },
        "metadataDTO": {
            "isFavorite": False,
        },
        "connectIQMeasurements": [],
        "exerciseSets": exercise_sets,
    }


class Uploader:
    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self._client = None

    def _ensure_client(self):
        if self._client is None and not self._dry_run:
            self._client = _get_client()

    def upload(self, workout_date: date, sets_data: list[dict]) -> bool:
        """Upload a workout. Returns True on success."""
        self._ensure_client()

        payload = _build_activity_payload(workout_date, sets_data)

        if self._dry_run:
            print(f"  [dry-run] Would upload workout on {workout_date}:")
            for item in sets_data:
                name = item.get("garmin_name", item.get("exercise", "?"))
                print(f"    • {name}: {item.get('sets', 1)}×{item.get('reps', 0)} @ {item.get('weight_lbs', 0)} lbs")
            return True

        try:
            self._client.add_training_readiness(payload)  # type: ignore[union-attr]
            return True
        except AttributeError:
            pass

        # Fall back to generic activity upload via garth
        try:
            response = self._client.garth.post(  # type: ignore[union-attr]
                "connectapi",
                "/activity-service/activity",
                json=payload,
            )
            log.debug("Upload response: %s", response)
            return True
        except Exception as exc:
            log.error("Upload failed for %s: %s", workout_date, exc)
            return False
