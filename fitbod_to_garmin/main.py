"""fitbod-to-garmin — sync Fitbod CSV exports to Garmin Connect."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# Allow running from the package directory directly
sys.path.insert(0, str(Path(__file__).parent))

from classifier import Classifier
from parser import ExerciseSet, Workout, filter_since, parse_csv
from tracker import Tracker
from uploader import Uploader

_HERE = Path(__file__).parent
_USER_MAPPINGS = _HERE / "user_mappings.json"
_UNMAPPED = _HERE / "unmapped_exercises.txt"
_TRACKER = _HERE / "upload_tracker.json"


def _build_sets_data(
    workout: Workout,
    classifier: Classifier,
) -> tuple[list[dict], set[str]]:
    """Resolve exercise names and return (sets_payload, unmapped_exercises)."""
    result: list[dict] = []
    unmapped: set[str] = set()

    # Deduplicate exercises that need classification within a single workout
    resolved_cache: dict[str, tuple[str, str] | None] = {}

    for s in workout.sets:
        if s.exercise not in resolved_cache:
            resolved_cache[s.exercise] = classifier.resolve(s.exercise)

        mapping = resolved_cache[s.exercise]
        if mapping is None:
            unmapped.add(s.exercise)
            continue

        garmin_name, garmin_category = mapping
        result.append({
            "exercise": s.exercise,
            "garmin_name": garmin_name,
            "garmin_category": garmin_category,
            "reps": s.reps,
            "sets": s.sets,
            "weight_lbs": s.weight_lbs,
            "duration_secs": s.duration_secs,
        })

    return result, unmapped


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fitbod-to-garmin",
        description="Sync Fitbod CSV workouts to Garmin Connect.",
    )
    parser.add_argument("csv", type=Path, help="Path to Fitbod CSV export")
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only sync workouts on or after this date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without uploading",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-prompt for previously skipped or guessed exercises",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload workouts even if already synced (delete old ones from Garmin first to avoid duplicates)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show debug logs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    if not args.csv.exists():
        sys.exit(f"CSV file not found: {args.csv}")

    since: date | None = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").date()
        except ValueError:
            sys.exit(f"Invalid --since date: {args.since!r} (expected YYYY-MM-DD)")

    print(f"Parsing {args.csv} …")
    workouts = parse_csv(args.csv)
    if not workouts:
        sys.exit("No workouts found in CSV.")

    if since:
        workouts = filter_since(workouts, since)
        if not workouts:
            print(f"No workouts found after {since}.")
            return

    tracker = Tracker(_TRACKER)
    classifier = Classifier(_USER_MAPPINGS, _UNMAPPED, reclassify=args.reclassify)
    uploader = Uploader(dry_run=args.dry_run)

    uploaded = 0
    skipped_dup = 0
    all_unmapped: set[str] = set()

    for workout in workouts:
        if tracker.already_uploaded(workout.date) and not args.force:
            print(f"  ⏭️  {workout.date} — already synced, skipping.")
            skipped_dup += 1
            continue

        sets_data, unmapped = _build_sets_data(workout, classifier)
        all_unmapped.update(unmapped)

        if not sets_data:
            print(f"  ⚠️  {workout.date} — no mappable exercises, skipping.")
            continue

        print(f"  {'[dry-run] ' if args.dry_run else ''}Uploading {workout.date} ({len(sets_data)} exercise(s)) …")
        success = uploader.upload(workout.date, sets_data)
        if success:
            if not args.dry_run:
                tracker.mark_uploaded(workout.date)
            uploaded += 1
        else:
            print(f"  ❌ Upload failed for {workout.date}.")

    # Summary
    print()
    print(f"✅ Uploaded: {uploaded} workout{'s' if uploaded != 1 else ''}")
    print(f"⏭️  Skipped (already synced): {skipped_dup} workout{'s' if skipped_dup != 1 else ''}")
    if classifier.classified_count:
        print(f"❓ Classified interactively: {classifier.classified_count} exercise{'s' if classifier.classified_count != 1 else ''} (saved to user_mappings.json)")
    if all_unmapped:
        print(f"⚠️  Still unmapped: {len(all_unmapped)} exercise{'s' if len(all_unmapped) != 1 else ''} (see unmapped_exercises.txt)")


if __name__ == "__main__":
    main()
