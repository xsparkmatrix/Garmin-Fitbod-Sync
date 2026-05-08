# Garmin–Fitbod Sync

By [xsparkmatrix](https://github.com/xsparkmatrix)

Sync your [Fitbod](https://fitbod.me) workout history to [Garmin Connect](https://connect.garmin.com) as strength training activities.

Fitbod does not natively integrate with Garmin Connect. This tool bridges that gap by reading a Fitbod CSV export and uploading each workout as a `FitnessEquipment` strength activity, including exercise names, sets, reps, and weight.

---

## Features

- Parses Fitbod CSV exports and groups sets into per-date workouts
- Maps Fitbod exercise names to Garmin equivalents via a built-in dictionary (~150 exercises)
- **Streamlit UI** for reviewing and confirming any exercises not in the built-in map, with fuzzy auto-suggestions
- Remembers every custom mapping you confirm so you are never prompted for the same exercise twice
- Tracks which workouts have already been uploaded — re-running never creates duplicates
- `--dry-run` mode to preview exactly what would be uploaded before touching Garmin
- `--since YYYY-MM-DD` to sync only workouts after a given date

---

## Requirements

- Python 3.9+
- A Garmin Connect account
- A Fitbod CSV export (`Settings → Export Data` in the Fitbod app)

---

## Installation

```bash
git clone https://github.com/xsparkmatrix/Garmin-Fitbod-Sync.git
cd Garmin-Fitbod-Sync
python3 -m venv .venv
source .venv/bin/activate
pip install -r fitbod_to_garmin/requirements.txt
```

---

## Credentials

Garmin Connect authentication is handled automatically on first run. The script will prompt for your email and password, then store a session token in `~/.garminconnect` so you only need to log in once.

If you prefer to store credentials in a file (optional), copy the example and fill it in:

```bash
cp .env.example .env
# edit .env with your Garmin email and password
```

> `.env` is listed in `.gitignore` and will never be committed to the repository.

---

## Usage

### 1. Dry run first

Always do a dry run before uploading to see exactly what will be sent to Garmin:

```bash
python3 fitbod_to_garmin/main.py WorkoutExport.csv --dry-run
```

Output shows each workout date, exercises, sets, reps, and weight. Nothing is uploaded.

### 2. Sync since a specific date

```bash
python3 fitbod_to_garmin/main.py WorkoutExport.csv --since 2026-01-01
```

### 3. Full sync

```bash
python3 fitbod_to_garmin/main.py WorkoutExport.csv
```

On first run you will be prompted for your Garmin credentials. After that, the session token is reused automatically.

### 4. Re-classify skipped exercises

```bash
python3 fitbod_to_garmin/main.py WorkoutExport.csv --reclassify
```

### Summary output

After each run the script prints:

```
✅ Uploaded: 4 workouts
⏭️  Skipped (already synced): 2 workouts
❓ Classified interactively: 3 exercises (saved to user_mappings.json)
⚠️  Still unmapped: 1 exercise (see unmapped_exercises.txt)
```

---

## Exercise Mapping UI

Fitbod supports any exercise name including custom gym machine names. Garmin Connect has a fixed list of recognised exercises. Before running a large sync, use the Streamlit mapper UI to review and confirm any exercises that are not in the built-in map:

```bash
streamlit run fitbod_to_garmin/mapper_ui.py -- WorkoutExport.csv
```

A browser page opens at `http://localhost:8501`. Each unmapped exercise is shown with a searchable dropdown pre-filled with the closest auto-suggestion. Review the suggestions, correct any that are wrong, and click **Save mappings**. The confirmed mappings are written to `user_mappings.json` and used silently on all future runs.

---

## Exercise Mapping — How It Works

Exercise mapping is resolved in three tiers:

| Tier | Source | Behaviour |
|------|--------|-----------|
| 1 | `mapper.py` built-in dictionary | Silent, ~150 common exercises |
| 2 | `user_mappings.json` | Silent, grows as you confirm exercises |
| 3 | Interactive / UI | Prompts once, saves result permanently |

### Why some exercises are difficult to map

Garmin Connect's exercise library is based on standard movement patterns. Fitbod exercises are often named after specific equipment, gym machines, or coaching cues that do not correspond one-to-one with any Garmin entry.

The following exercises have no exact Garmin equivalent. The mapping listed was the closest available option based on the primary movement pattern:

| Fitbod exercise | Garmin mapping | Reason |
|-----------------|---------------|--------|
| Pendulum Squat Machine | `HACK_SQUAT` | Pendulum squat is a machine variant of the hack squat pattern; no dedicated entry exists in Garmin |
| Assisted Pull-Up | `PULL_UP` | Garmin has no assisted variant; the movement is identical |
| Assisted Chin-Up | `CHIN_UP` | Same as above |
| Smith Machine Squat | `SMITH_MACHINE_SQUAT` | Direct match |
| Crab Pose | *(skipped)* | Flexibility/mobility hold with no strength equivalent in Garmin |
| Cable Pull Through | `CABLE_PULL_THROUGH` | Direct match |
| Glute Kickback | `CABLE_KICKBACK` | Garmin's nearest hip-extension movement |

Exercises with no reasonable Garmin equivalent are logged to `unmapped_exercises.txt` and skipped during upload. They do not affect other exercises in the same workout.

### Sharing your mappings

The `user_mappings.json` file grows over time as you classify gym-specific exercises. Sharing this file with others means they benefit from your classifications without being prompted. See `fitbod_to_garmin/user_mappings.example.json` for the expected format.

---

## Project Structure

```
fitbod_to_garmin/
├── main.py                    # CLI entry point
├── parser.py                  # CSV parsing and date grouping
├── mapper.py                  # Built-in exercise map + Garmin exercise list
├── mapper_ui.py               # Streamlit review UI
├── classifier.py              # Interactive classification (fuzzy match)
├── uploader.py                # Garmin Connect auth and upload
├── tracker.py                 # Dedup tracking (upload_tracker.json)
├── requirements.txt
└── user_mappings.example.json # Format reference for custom mappings
```

---

## Troubleshooting

**`command not found: python`** — use `python3` instead, or activate the virtual environment with `source .venv/bin/activate`.

**`Garmin authentication failed`** — delete `~/.garminconnect` and re-run to trigger a fresh login.

**All exercises showing as unmapped** — run the Streamlit mapper UI first to classify exercises before syncing.

**Duplicate workouts on Garmin** — the script tracks uploads in `upload_tracker.json`. If this file is deleted, re-running will re-upload everything. Do a `--dry-run` first to confirm before proceeding.
