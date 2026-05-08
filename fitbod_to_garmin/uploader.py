"""Garmin Connect auth and workout upload via FIT file generation."""

from __future__ import annotations

import getpass
import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_TOKEN_DIR = Path.home() / ".garminconnect"

# Map our Garmin category strings → fit_tool ExerciseCategory enum names
_CATEGORY_MAP: dict[str, str] = {
    "CHEST":      "BENCH_PRESS",
    "BACK":       "ROW",
    "SHOULDERS":  "SHOULDER_PRESS",
    "BICEPS":     "CURL",
    "TRICEPS":    "TRICEPS_EXTENSION",
    "LEGS":       "SQUAT",
    "CORE":       "CORE",
    "OLYMPIC":    "OLYMPIC_LIFT",
    "CARDIO":     "CARDIO",
    "PLYOMETRICS":"PLYO",
    "FLEXIBILITY":"UNKNOWN",
    "OTHER":      "UNKNOWN",
}

# More specific overrides: garmin_name → ExerciseCategory enum name
_NAME_CATEGORY_MAP: dict[str, str] = {
    "DEADLIFT":              "DEADLIFT",
    "ROMANIAN_DEADLIFT":     "DEADLIFT",
    "SUMO_DEADLIFT":         "DEADLIFT",
    "DUMBBELL_ROMANIAN_DEADLIFT": "DEADLIFT",
    "SINGLE_LEG_DEADLIFT":   "DEADLIFT",
    "RACK_PULL":             "DEADLIFT",
    "SQUAT":                 "SQUAT",
    "FRONT_SQUAT":           "SQUAT",
    "GOBLET_SQUAT":          "SQUAT",
    "DUMBBELL_SQUAT":        "SQUAT",
    "SUMO_SQUAT":            "SQUAT",
    "BULGARIAN_SPLIT_SQUAT": "SQUAT",
    "HACK_SQUAT":            "SQUAT",
    "BOX_SQUAT":             "SQUAT",
    "SMITH_MACHINE_SQUAT":   "SQUAT",
    "PISTOL_SQUAT":          "SQUAT",
    "BENCH_PRESS":           "BENCH_PRESS",
    "DUMBBELL_BENCH_PRESS":  "BENCH_PRESS",
    "INCLINE_CHEST_PRESS":   "BENCH_PRESS",
    "INCLINE_DUMBBELL_BENCH_PRESS": "BENCH_PRESS",
    "DECLINE_PRESS":         "BENCH_PRESS",
    "CLOSE_GRIP_BENCH_PRESS":"BENCH_PRESS",
    "MACHINE_BENCH_PRESS":   "BENCH_PRESS",
    "DUMBBELL_FLYES":        "FLYE",
    "INCLINE_DUMBBELL_FLYES":"FLYE",
    "CABLE_CROSSOVER":       "FLYE",
    "PEC_DECK_FLYES":        "FLYE",
    "PUSH_UP":               "PUSH_UP",
    "WIDE_PUSH_UP":          "PUSH_UP",
    "DIAMOND_PUSH_UP":       "PUSH_UP",
    "DIP":                   "BENCH_PRESS",
    "PULL_UP":               "PULL_UP",
    "CHIN_UP":               "PULL_UP",
    "LAT_PULLDOWN":          "PULL_UP",
    "BARBELL_ROW":           "ROW",
    "BENT_OVER_ROW":         "ROW",
    "DUMBBELL_ROW":          "ROW",
    "SEATED_CABLE_ROW":      "ROW",
    "T_BAR_ROW":             "ROW",
    "INVERTED_ROW":          "ROW",
    "FACE_PULL":             "ROW",
    "BACK_EXTENSION":        "HYPEREXTENSION",
    "GOOD_MORNING":          "HYPEREXTENSION",
    "SIDE_LATERAL_RAISE":    "LATERAL_RAISE",
    "FRONT_RAISE":           "LATERAL_RAISE",
    "REAR_DELTOID_RAISE":    "LATERAL_RAISE",
    "UPRIGHT_ROW":           "ROW",
    "BARBELL_CURL":          "CURL",
    "DUMBBELL_CURL":         "CURL",
    "HAMMER_CURL":           "CURL",
    "CABLE_CURL":            "CURL",
    "EZ_BAR_CURL":           "CURL",
    "PREACHER_CURL":         "CURL",
    "TRICEP_PUSHDOWN":       "TRICEPS_EXTENSION",
    "ROPE_PUSHDOWN":         "TRICEPS_EXTENSION",
    "SKULL_CRUSHER":         "TRICEPS_EXTENSION",
    "OVERHEAD_TRICEP_EXTENSION": "TRICEPS_EXTENSION",
    "BENCH_DIP":             "TRICEPS_EXTENSION",
    "DUMBBELL_LUNGE":        "LUNGE",
    "BARBELL_LUNGE":         "LUNGE",
    "WALKING_LUNGE":         "LUNGE",
    "LEG_PRESS":             "SQUAT",
    "LEG_EXTENSION":         "SQUAT",
    "LEG_CURL":              "LEG_CURL",
    "SEATED_LEG_CURL":       "LEG_CURL",
    "LYING_LEG_CURL":        "LEG_CURL",
    "CALF_RAISE":            "CALF_RAISE",
    "STANDING_CALF_RAISE":   "CALF_RAISE",
    "SEATED_CALF_RAISE":     "CALF_RAISE",
    "BARBELL_HIP_THRUST":    "HIP_RAISE",
    "GLUTE_BRIDGE":          "HIP_RAISE",
    "CABLE_KICKBACK":        "HIP_STABILITY",
    "PLANK":                 "PLANK",
    "SIDE_PLANK":            "PLANK",
    "CRUNCH":                "CRUNCH",
    "BICYCLE_CRUNCH":        "CRUNCH",
    "SIT_UP":                "CORE",
    "LEG_RAISE":             "LEG_RAISE",
    "HANGING_LEG_RAISE":     "LEG_RAISE",
    "HANGING_KNEE_RAISE":    "LEG_RAISE",
    "AB_WHEEL_ROLLOUT":      "CORE",
    "RUSSIAN_TWIST":         "CORE",
    "CABLE_WOOD_CHOP":       "CHOP",
    "KETTLEBELL_SWING":      "HIP_SWING",
    "FARMERS_WALK":          "CARRY",
    "POWER_CLEAN":           "OLYMPIC_LIFT",
    "HANG_POWER_CLEAN":      "OLYMPIC_LIFT",
    "CLEAN_AND_JERK":        "OLYMPIC_LIFT",
    "SNATCH":                "OLYMPIC_LIFT",
    "BURPEE":                "CARDIO",
    "JUMP_ROPE":             "CARDIO",
    "BOX_JUMP":              "PLYO",
}


def _fit_category(garmin_name: str, garmin_category: str) -> list:
    """Return [ExerciseCategory int] for the SetMessage category field."""
    from fit_tool.profile.profile_type import ExerciseCategory
    name = _NAME_CATEGORY_MAP.get(garmin_name) or _CATEGORY_MAP.get(garmin_category, "UNKNOWN")
    try:
        cat = getattr(ExerciseCategory, name)
    except AttributeError:
        cat = ExerciseCategory.UNKNOWN
    return [cat.value]


def _build_fit(workout_date: date, sets_data: list[dict]) -> bytes:
    """Generate a FIT file for a strength training workout."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.activity_message import ActivityMessage
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.messages.set_message import SetMessage
    from fit_tool.profile.profile_type import (
        Activity,
        Event,
        EventType,
        FileType,
        LapTrigger,
        Manufacturer,
        SessionTrigger,
        SetType,
        Sport,
        SubSport,
    )

    # fit_tool DATE_TIME fields expect Unix milliseconds
    # (offset=-631065600000, scale=0.001 → encoded = FIT seconds since 1989-12-31)
    def to_ms(dt: datetime) -> int:
        return int(dt.timestamp() * 1000)

    start_dt = datetime(
        workout_date.year, workout_date.month, workout_date.day,
        12, 0, 0, tzinfo=timezone.utc,
    )
    start_ts = to_ms(start_dt)

    # Expand sets_data into individual set entries
    flat: list[dict] = []
    for item in sets_data:
        for _ in range(max(item.get("sets", 1), 1)):
            flat.append(item)

    total_sets = len(flat)
    total_duration_secs = sum(max(s.get("duration_secs", 0), 30) for s in flat)
    end_ts = start_ts + total_duration_secs * 1000  # ms

    builder = FitFileBuilder(auto_define=True, min_string_size=50)

    # FILE_ID
    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.DEVELOPMENT
    file_id.product = 0
    file_id.time_created = start_ts
    file_id.serial_number = 1
    builder.add(file_id)

    # SET messages
    for i, item in enumerate(flat):
        s = SetMessage()
        offset_ms = sum(max(flat[j].get("duration_secs", 0), 30) for j in range(i)) * 1000
        s.timestamp = start_ts + offset_ms
        s.start_time = start_ts + offset_ms
        s.duration = float(max(item.get("duration_secs", 0), 30))  # seconds (scale=1000)
        s.repetitions = item.get("reps", 0)
        weight_kg = item.get("weight_lbs", 0) * 0.453592
        s.weight = round(weight_kg, 2)
        s.set_type = SetType.ACTIVE
        s.category = _fit_category(
            item.get("garmin_name", ""), item.get("garmin_category", "")
        )
        builder.add(s)

    # LAP
    lap = LapMessage()
    lap.timestamp = end_ts          # ms
    lap.start_time = start_ts       # ms
    lap.total_elapsed_time = float(total_duration_secs)   # seconds (scale=1000)
    lap.total_timer_time = float(total_duration_secs)
    lap.lap_trigger = LapTrigger.SESSION_END
    lap.event = Event.LAP
    lap.event_type = EventType.STOP
    lap.sport = Sport.TRAINING
    lap.sub_sport = SubSport.STRENGTH_TRAINING
    builder.add(lap)

    # SESSION
    session = SessionMessage()
    session.timestamp = end_ts
    session.start_time = start_ts
    session.total_elapsed_time = float(total_duration_secs)
    session.total_timer_time = float(total_duration_secs)
    session.sport = Sport.TRAINING
    session.sub_sport = SubSport.STRENGTH_TRAINING
    session.trigger = SessionTrigger.ACTIVITY_END
    session.event = Event.SESSION
    session.event_type = EventType.STOP
    session.num_laps = 1
    builder.add(session)

    # ACTIVITY
    activity = ActivityMessage()
    activity.timestamp = end_ts
    activity.total_timer_time = float(total_duration_secs)
    activity.num_sessions = 1
    activity.type = Activity.MANUAL
    activity.event = Event.ACTIVITY
    activity.event_type = EventType.STOP
    builder.add(activity)

    fit_file = builder.build()
    return fit_file.to_bytes()


def _get_client():
    """Return an authenticated Garmin client, prompting for creds on first run."""
    try:
        from garminconnect import Garmin
    except ImportError:
        raise SystemExit("garminconnect is not installed. Run: pip install garminconnect")

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


class Uploader:
    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self._client = None

    def _ensure_client(self):
        if self._client is None and not self._dry_run:
            self._client = _get_client()

    def upload(self, workout_date: date, sets_data: list[dict]) -> bool:
        """Build a FIT file and upload it. Returns True on success."""
        if self._dry_run:
            print(f"  [dry-run] Would upload workout on {workout_date}:")
            for item in sets_data:
                name = item.get("garmin_name", item.get("exercise", "?"))
                print(f"    • {name}: {item.get('sets', 1)}×{item.get('reps', 0)} @ {item.get('weight_lbs', 0)} lbs")
            return True

        self._ensure_client()

        try:
            fit_bytes = _build_fit(workout_date, sets_data)
        except Exception as exc:
            log.error("FIT file generation failed for %s: %s", workout_date, exc)
            return False

        with tempfile.NamedTemporaryFile(
            suffix=".fit",
            prefix=f"fitbod_{workout_date}_",
            delete=False,
        ) as f:
            f.write(fit_bytes)
            tmp_path = f.name

        try:
            self._client.upload_activity(tmp_path)
            return True
        except Exception as exc:
            log.error("Upload failed for %s: %s", workout_date, exc)
            return False
        finally:
            Path(tmp_path).unlink(missing_ok=True)
