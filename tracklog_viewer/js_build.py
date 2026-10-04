"""The report's flights, rendered by the JavaScript at build time.

An uploaded track is analysed and written up in the page by `js/upload.js`. The flights
the report ships with go through the very same function — `TV.upload.compose` — run here
in Node while the page is built, so the showcase and an upload cannot come out different
and the page still opens on a finished article rather than on five seconds of analysis.
What the page would fetch for an upload, the CLI has already fetched: the ground with its
heights, Open-Meteo's answer (unparsed, so `js/meteo.js` reads it), the glider table.

The Python analysis is not involved in the article at all. It still answers the CLI's
console summary, `--json`, `--kmz`, `--map` and `--archive`, and it is the reference
`js_parity.py` checks the JavaScript against.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

RUNNER = Path(__file__).parent / "js" / "build_runner.js"


class BuildError(RuntimeError):
    """Node is missing, or the JavaScript refused a flight."""


def available() -> bool:
    return shutil.which("node") is not None


def grid(terrain) -> dict:
    """A `Terrain` in the page's grid shape, heights included."""
    return {"west": terrain.west, "east": terrain.east, "south": terrain.south,
            "north": terrain.north, "rows": terrain.rows, "cols": terrain.cols,
            "z": terrain.elevations.ravel().tolist()}


def render(jobs: list[dict], *, certification_table: dict | None, now: float) -> list[dict]:
    """Each job is {path, name, terrain, sceneTerrain, meteo, when, options}; each answer
    is {html, uid, label, meta, stat, title}."""
    if not available():
        raise BuildError("node is not on PATH; the report's articles are rendered by the "
                         "JavaScript in js/, which needs Node at build time")
    run = subprocess.run(
        ["node", str(RUNNER)],
        input=json.dumps({"jobs": jobs, "certification": certification_table, "now": now}),
        capture_output=True, text=True)
    if run.returncode != 0:
        raise BuildError(f"the JavaScript build failed:\n{run.stderr[-3000:]}")
    answers = json.loads(run.stdout)
    for job, answer in zip(jobs, answers):
        if not answer.get("ok"):
            raise BuildError(f"{job['name']}: {answer.get('error')}")
    return answers
