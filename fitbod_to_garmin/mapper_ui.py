"""
Streamlit UI for mapping Fitbod exercises to Garmin equivalents.

Run:
    streamlit run fitbod_to_garmin/mapper_ui.py -- WorkoutExport.csv
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from mapper import EXERCISE_MAP, GARMIN_EXERCISES
from parser import parse_csv

_HERE = Path(__file__).parent
_USER_MAPPINGS = _HERE / "user_mappings.json"

GARMIN_OPTIONS = sorted(set(f"{name}  ({cat})" for name, cat in GARMIN_EXERCISES))
GARMIN_LOOKUP  = {f"{name}  ({cat})": (name, cat) for name, cat in GARMIN_EXERCISES}
_GARMIN_NAMES  = [name for name, _ in GARMIN_EXERCISES]
_CAT_BY_NAME   = {name: cat for name, cat in GARMIN_EXERCISES}
_SKIP = "— skip this exercise —"

_OPTIONS_WITH_SKIP = [_SKIP] + GARMIN_OPTIONS


def _normalise(s: str) -> str:
    """Uppercase, strip equipment qualifiers, replace non-alpha with underscores."""
    s = s.upper()
    # Remove common qualifiers that don't affect movement name
    for word in ("BARBELL", "DUMBBELL", "CABLE", "MACHINE", "SMITH", "ASSISTED",
                 "WEIGHTED", "SINGLE", "LEG", "SEATED", "STANDING", "LYING",
                 "INCLINE", "DECLINE", "CLOSE", "WIDE", "GRIP", "UNILATERAL"):
        s = re.sub(rf"\b{word}\b", "", s)
    return re.sub(r"[^A-Z]+", "_", s).strip("_")


def best_guess(fitbod_name: str) -> str | None:
    """Return the best Garmin option string for a Fitbod exercise name, or None."""
    norm = _normalise(fitbod_name)

    # 1. Exact normalised match
    for name in _GARMIN_NAMES:
        if _normalise(name) == norm:
            return f"{name}  ({_CAT_BY_NAME[name]})"

    # 2. Normalised substring match (fitbod core word in garmin name or vice versa)
    for name in _GARMIN_NAMES:
        n = _normalise(name)
        if norm and (norm in n or n in norm):
            return f"{name}  ({_CAT_BY_NAME[name]})"

    # 3. difflib closest match on normalised names
    normed_garmin = [_normalise(n) for n in _GARMIN_NAMES]
    matches = difflib.get_close_matches(norm, normed_garmin, n=1, cutoff=0.45)
    if matches:
        idx = normed_garmin.index(matches[0])
        name = _GARMIN_NAMES[idx]
        return f"{name}  ({_CAT_BY_NAME[name]})"

    # 4. Raw difflib on original name
    matches = difflib.get_close_matches(
        fitbod_name.upper().replace(" ", "_"),
        _GARMIN_NAMES, n=1, cutoff=0.35,
    )
    if matches:
        name = matches[0]
        return f"{name}  ({_CAT_BY_NAME[name]})"

    return None


def load_user_mappings() -> dict[str, tuple[str, str]]:
    if _USER_MAPPINGS.exists():
        try:
            raw = json.loads(_USER_MAPPINGS.read_text())
            return {k: tuple(v) for k, v in raw.items()}  # type: ignore[misc]
        except Exception:
            pass
    return {}


def save_user_mappings(mappings: dict[str, tuple[str, str]]) -> None:
    _USER_MAPPINGS.write_text(
        json.dumps({k: list(v) for k, v in mappings.items()}, indent=2)
    )


def get_all_exercises(csv_path: Path) -> list[str]:
    workouts = parse_csv(csv_path)
    seen: dict[str, None] = {}
    for w in workouts:
        for s in w.sets:
            seen[s.exercise] = None
    return list(seen.keys())


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Fitbod → Garmin Exercise Mapper", layout="wide")
st.title("Fitbod → Garmin Exercise Mapper")

# ── CSV path ──────────────────────────────────────────────────────────────────

args = [a for a in sys.argv if not a.startswith("--") and not a.endswith(".py")]
default_csv = args[-1] if args else ""

csv_input = st.text_input(
    "Fitbod CSV path",
    value=default_csv,
    placeholder="e.g. WorkoutExport.csv",
)

if not csv_input:
    st.info("Enter the path to your Fitbod CSV export above.")
    st.stop()

csv_path = Path(csv_input)
if not csv_path.exists():
    st.error(f"File not found: `{csv_path}`")
    st.stop()

# ── Load data ─────────────────────────────────────────────────────────────────

with st.spinner("Parsing CSV…"):
    all_exercises = get_all_exercises(csv_path)

user_mappings = load_user_mappings()

tier1   = {ex for ex in all_exercises if ex in EXERCISE_MAP}
tier2   = {ex for ex in all_exercises if ex in user_mappings and ex not in tier1}
unmapped = [ex for ex in all_exercises if ex not in EXERCISE_MAP and ex not in user_mappings]

# ── Summary metrics ───────────────────────────────────────────────────────────

c1, c2, c3 = st.columns(3)
c1.metric("Total exercises", len(all_exercises))
c2.metric("Already mapped", len(tier1) + len(tier2))
c3.metric("Needs review", len(unmapped))

st.divider()

if not unmapped:
    st.success("All exercises are already mapped! You can run the sync script.")
    st.stop()

# ── Pre-compute suggestions ───────────────────────────────────────────────────

suggestions: dict[str, str | None] = {}
for ex in unmapped:
    suggestions[ex] = best_guess(ex)

n_guessed = sum(1 for v in suggestions.values() if v is not None)
n_no_guess = len(unmapped) - n_guessed

st.subheader(f"Review {len(unmapped)} exercise{'s' if len(unmapped) != 1 else ''}")
st.caption(
    f"**{n_guessed}** have an auto-suggestion (🤖) · **{n_no_guess}** had no good match. "
    "Change any dropdown that looks wrong, then click Save."
)

# ── Exercise rows ─────────────────────────────────────────────────────────────

pending: dict[str, tuple[str, str] | None] = {}

# Column headers
h1, h2, h3 = st.columns([2, 3, 1])
h1.markdown("**Fitbod exercise**")
h2.markdown("**Garmin equivalent**")
h3.markdown("**Suggestion**")

st.markdown("---")

for ex in unmapped:
    guess = suggestions[ex]
    default_idx = (_OPTIONS_WITH_SKIP.index(guess) if guess in _OPTIONS_WITH_SKIP
                   else 0)

    col_name, col_select, col_badge = st.columns([2, 3, 1])

    with col_name:
        st.markdown(f"**{ex}**")

    with col_select:
        choice = st.selectbox(
            label=ex,
            options=_OPTIONS_WITH_SKIP,
            index=default_idx,
            label_visibility="collapsed",
            key=f"sel_{ex}",
        )
        pending[ex] = GARMIN_LOOKUP[choice] if choice != _SKIP else None

    with col_badge:
        if guess is not None:
            st.markdown("🤖 auto")
        else:
            st.markdown("❓ manual")

st.divider()

# ── Already-mapped (collapsible) ──────────────────────────────────────────────

with st.expander(f"Already mapped ({len(tier1) + len(tier2)} exercises)", expanded=False):
    rows = []
    for ex in sorted(tier1):
        garmin, cat = EXERCISE_MAP[ex]
        rows.append({"Fitbod exercise": ex, "Garmin name": garmin, "Category": cat, "Source": "Built-in"})
    for ex in sorted(tier2):
        garmin, cat = user_mappings[ex]
        rows.append({"Fitbod exercise": ex, "Garmin name": garmin, "Category": cat, "Source": "Saved"})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

# ── Save ──────────────────────────────────────────────────────────────────────

n_selected = sum(1 for v in pending.values() if v is not None)
n_skipped  = sum(1 for v in pending.values() if v is None)

st.write(f"**{n_selected}** will be saved · **{n_skipped}** will be skipped")

if st.button("💾 Save mappings", type="primary", disabled=n_selected == 0):
    updated = dict(user_mappings)
    for ex, mapping in pending.items():
        if mapping is not None:
            updated[ex] = mapping
    save_user_mappings(updated)
    st.success(f"Saved {n_selected} mapping{'s' if n_selected != 1 else ''} to `user_mappings.json`.")
    st.balloons()
    st.info(
        "Now run the sync:\n"
        "```\npython3 fitbod_to_garmin/main.py WorkoutExport.csv --since 2026-05-01\n```"
    )
