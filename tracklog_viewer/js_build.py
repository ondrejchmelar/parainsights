"""The report's flights, through the JavaScript an uploaded track goes through.

The viewer's analysis and its article are `tracklog_viewer/js/`, and nothing else: an
upload is read, analysed and written up in the page by `js/upload.js`, and the flights the
report ships with go through the very same `TV.upload.compose`, run here in Node while the
page is built — so the page opens on a finished article rather than on five seconds of
analysis, and a showcase flight and an upload cannot come out different.

Two passes, because Node cannot be relied on to fetch (Node 16 has no `fetch`) and the
CLI already knows how, with a cache: `inspect` asks the JavaScript what each flight needs
— the ground box and the weather request, the date and site a plan is filed under — and
`render` hands back what was fetched.
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


def _run(mode: str, jobs: list[dict], **extra) -> list[dict]:
    if not available():
        raise BuildError("node is not on PATH; the report's articles are written by the "
                         "JavaScript in js/, which needs Node at build time")
    run = subprocess.run(["node", str(RUNNER)],
                         input=json.dumps({"mode": mode, "jobs": jobs, **extra}),
                         capture_output=True, text=True)
    if run.returncode != 0 or not run.stdout:
        raise BuildError(f"the JavaScript build failed:\n{run.stderr[-3000:]}")
    answers = json.loads(run.stdout)
    for job, answer in zip(jobs, answers):
        if not answer.get("ok"):
            raise BuildError(f"{job['name']}: {answer.get('error')}")
    return answers


def inspect(jobs: list[dict], *, now: float) -> list[dict]:
    """Each job is {path, name, label}; each answer is {ground, meteo: {url, when}, date,
    site, pilot, warnings, dropped}."""
    return _run("inspect", jobs, now=now)


def render(jobs: list[dict], *, certification_table: dict | None, now: float) -> list[dict]:
    """Each job is {path, name, terrain, sceneTerrain, meteo, when, options}; each answer
    is {html, uid, label, meta, stat, title}."""
    return _run("render", jobs, certification=certification_table, now=now)
