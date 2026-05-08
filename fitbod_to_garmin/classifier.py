"""
Interactive exercise classification: browser picker + fuzzy match fallback.

Resolution order per exercise:
  1. mapper.EXERCISE_MAP   (Tier 1 — built-in, silent)
  2. user_mappings.json    (Tier 2 — user-confirmed, silent)
  3. Interactive prompt    (Tier 3 — this module)
"""

from __future__ import annotations

import difflib
import http.server
import json
import logging
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from mapper import GARMIN_EXERCISES, lookup as tier1_lookup

log = logging.getLogger(__name__)

_SKIP_ALL_SENTINEL = "__SKIP_ALL__"


def _build_html(fitbod_name: str, port: int) -> str:
    exercises_json = json.dumps(
        [{"name": name, "category": cat} for name, cat in GARMIN_EXERCISES]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Map exercise: {fitbod_name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
  h2 {{ color: #333; }}
  #search {{ width: 100%; padding: .5rem; font-size: 1rem; margin-bottom: 1rem; box-sizing: border-box; }}
  ul {{ list-style: none; padding: 0; margin: 0; max-height: 60vh; overflow-y: auto; border: 1px solid #ccc; border-radius: 4px; }}
  li {{ padding: .5rem 1rem; cursor: pointer; display: flex; justify-content: space-between; }}
  li:hover {{ background: #eef; }}
  .cat {{ color: #888; font-size: .85em; }}
  #done {{ display: none; font-size: 1.4rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h2>Map Fitbod exercise:</h2>
<p><strong>{fitbod_name}</strong></p>
<input id="search" type="text" placeholder="Search Garmin exercises…" autofocus>
<ul id="list"></ul>
<div id="done">✅ Selected — you can close this tab.</div>
<script>
const exercises = {exercises_json};
const list = document.getElementById('list');
const search = document.getElementById('search');

function render(items) {{
  list.innerHTML = '';
  items.forEach(ex => {{
    const li = document.createElement('li');
    li.innerHTML = `<span>${{ex.name}}</span><span class="cat">${{ex.category}}</span>`;
    li.addEventListener('click', () => select(ex.name, ex.category));
    list.appendChild(li);
  }});
}}

function select(name, category) {{
  fetch('http://localhost:{port}/select', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{fitbod_name: '{fitbod_name}', garmin_name: name, garmin_category: category}})
  }}).then(() => {{
    list.style.display = 'none';
    search.style.display = 'none';
    document.getElementById('done').style.display = 'block';
  }});
}}

search.addEventListener('input', () => {{
  const q = search.value.toLowerCase();
  render(q ? exercises.filter(e => e.name.toLowerCase().includes(q) || e.category.toLowerCase().includes(q)) : exercises);
}});

render(exercises);
</script>
</body>
</html>"""


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class _PickerResult:
    def __init__(self) -> None:
        self.value: Optional[tuple[str, str]] = None
        self._event = threading.Event()

    def set(self, garmin_name: str, garmin_category: str) -> None:
        self.value = (garmin_name, garmin_category)
        self._event.set()

    def wait(self) -> None:
        self._event.wait()


def _serve_browser_picker(fitbod_name: str) -> Optional[tuple[str, str]]:
    """Spin up a local HTTP server, open browser, block until user picks."""
    try:
        port = _find_free_port()
    except OSError as exc:
        log.warning("Cannot find free port for browser picker: %s", exc)
        return None

    result = _PickerResult()
    html = _build_html(fitbod_name, port)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence server logs
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self):
            if self.path != "/select":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            result.set(body["garmin_name"], body["garmin_category"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        log.warning("Failed to start browser picker server: %s", exc)
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    webbrowser.open(f"http://127.0.0.1:{port}/")
    result.wait()
    server.shutdown()
    return result.value


def _prompt(prompt_text: str) -> str:
    """Read a line from stdin; return empty string on EOF (non-interactive)."""
    try:
        return input(prompt_text).strip()
    except EOFError:
        return ""


def _fuzzy_match(query: str) -> Optional[tuple[str, str]]:
    """Fuzzy-match query against Garmin exercise names, return user-confirmed result."""
    names = [name for name, _ in GARMIN_EXERCISES]
    cat_by_name = {name: cat for name, cat in GARMIN_EXERCISES}

    while True:
        matches = difflib.get_close_matches(query.upper().replace(" ", "_"), names, n=5, cutoff=0.0)
        if not matches:
            print("  No matches found.")
            matches = []

        print(f"\n  Top matches for '{query}':")
        for i, m in enumerate(matches, 1):
            print(f"    [{i}] {m}  ({cat_by_name[m]})")
        print(f"    [r] Try a different search term")
        print(f"    [s] Skip this exercise")

        choice = _prompt("  Your choice: ").lower()
        if not choice:
            print("  No input — skipping.")
            return None
        if choice == "s":
            return None
        if choice == "r":
            query = _prompt("  New search term: ")
            if not query:
                return None
            continue
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                name = matches[idx]
                return name, cat_by_name[name]
        except ValueError:
            pass
        print("  Invalid choice, try again.")


class Classifier:
    def __init__(
        self,
        user_mappings_path: Path,
        unmapped_path: Path,
        reclassify: bool = False,
    ) -> None:
        self._path = user_mappings_path
        self._unmapped_path = unmapped_path
        self._reclassify = reclassify
        self._user_mappings: dict[str, tuple[str, str]] = self._load()
        self._skip_all = False
        self._classified_count = 0
        self._skipped: list[str] = []

    def _load(self) -> dict[str, tuple[str, str]]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                return {k: tuple(v) for k, v in raw.items()}  # type: ignore[misc]
            except Exception as exc:
                log.warning("Could not load user_mappings.json: %s", exc)
        return {}

    def _save(self) -> None:
        self._path.write_text(
            json.dumps({k: list(v) for k, v in self._user_mappings.items()}, indent=2)
        )

    def resolve(self, fitbod_name: str) -> Optional[tuple[str, str]]:
        """Return (garmin_name, category) or None (skip)."""
        # Tier 1
        result = tier1_lookup(fitbod_name)
        if result:
            return result

        # Tier 2
        if fitbod_name in self._user_mappings and not self._reclassify:
            return self._user_mappings[fitbod_name]

        # Tier 3
        if self._skip_all:
            self._skipped.append(fitbod_name)
            return None

        return self._interactive(fitbod_name)

    def _interactive(self, fitbod_name: str) -> Optional[tuple[str, str]]:
        print(f"\n❓ Unknown exercise: \"{fitbod_name}\"")
        print("   How would you like to classify this?\n")
        print("   [1] Search Garmin exercise list in browser")
        print("   [2] Type a Garmin exercise name manually (fuzzy match)")
        print("   [3] Skip this exercise for now")
        print("   [4] Skip ALL unknown exercises this run")

        choice = _prompt("\n   Choice: ")

        result: Optional[tuple[str, str]] = None

        if not choice:
            print("   No input detected (non-interactive) — skipping all unknowns.")
            self._skip_all = True
            self._log_skipped(fitbod_name)
            return None
        elif choice == "1":
            result = _serve_browser_picker(fitbod_name)
            if result is None:
                print("   ⚠️  Browser picker failed — falling back to fuzzy match.")
                result = _fuzzy_match(fitbod_name)
        elif choice == "2":
            query = _prompt("   Enter exercise name to search: ")
            if not query:
                self._log_skipped(fitbod_name)
                return None
            result = _fuzzy_match(query)
        elif choice == "3":
            self._log_skipped(fitbod_name)
            return None
        elif choice == "4":
            self._skip_all = True
            self._log_skipped(fitbod_name)
            return None
        else:
            print("   Invalid choice — skipping.")
            self._log_skipped(fitbod_name)
            return None

        if result:
            self._user_mappings[fitbod_name] = result
            self._save()
            self._classified_count += 1
            print(f"   ✅ Mapped to {result[0]} ({result[1]}) and saved.")
        else:
            self._log_skipped(fitbod_name)

        return result

    def _log_skipped(self, fitbod_name: str) -> None:
        self._skipped.append(fitbod_name)
        with self._unmapped_path.open("a") as f:
            f.write(fitbod_name + "\n")

    @property
    def classified_count(self) -> int:
        return self._classified_count

    @property
    def skipped_exercises(self) -> list[str]:
        return list(set(self._skipped))
