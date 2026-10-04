"""Run `tracklog_viewer/js/` from the test suite.

The viewer's analysis is JavaScript; these tests fly synthetic geometry in Python (the
fixtures in `tests/test_analysis.py` write IGC files) and ask the JavaScript what it
makes of them, through Node (`js_bridge.js`). `run` is the general form; `analyse` and
`flight` are the two calls almost every test makes.

What comes back is JSON wrapped for attribute access: a dict is an `NS`, and a list of
numbers is a numpy array, so a test reads `analysis.thermals[0].wind.speed` and does
arithmetic on `analysis.series.t` as it always did.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

BRIDGE = Path(__file__).with_name("js_bridge.js")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


class JSError(RuntimeError):
    """The JavaScript threw; `.message` is its own message."""

    def __init__(self, message: str, stack: str):
        super().__init__(stack)
        self.message = message


def _revive(value):
    if isinstance(value, dict):
        if set(value) == {"$num"}:
            return float(value["$num"])
        return NS({key: _revive(item) for key, item in value.items()})
    if isinstance(value, list):
        items = [_revive(item) for item in value]
        if items and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in items):
            return np.array(items, dtype=float)
        return items
    return value


class NS(dict):
    """A dict that also reads as attributes; missing keys read as None."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            return None


def run(code: str, **inputs):
    """Run `code` as the body of an async JS function; return its value."""
    paths = {k: str(v) if isinstance(v, Path) else v for k, v in inputs.items()}
    done = subprocess.run(["node", str(BRIDGE)],
                          input=json.dumps({"code": code, "inputs": paths}, default=_plain),
                          capture_output=True, text=True)
    if not done.stdout:
        raise RuntimeError(f"node produced nothing:\n{done.stderr[-3000:]}")
    answer = json.loads(done.stdout)
    if not answer["ok"]:
        raise JSError(answer["message"], answer["error"])
    return _revive(answer["value"])


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(f"cannot send {type(value)} to the JavaScript")


class Analysis(NS):
    """`TV.analysis.analyse`'s answer, with the views Python's `Analysis` offered."""

    @property
    def thermals(self):
        return [s for s in self.segments if s.phase == "thermal"]

    @property
    def glides(self):
        return [s for s in self.segments if s.phase == "glide"]

    @property
    def tow(self):
        found = [s for s in self.segments if s.phase == "tow"]
        return found[0] if found else None


ANALYSE = """
var flight = await load(input.path, input.parse || undefined);
var a = TV.analysis.analyse(flight, input.window ? { window: input.window } : undefined);
delete a.phases;
return a;
"""


BUDGET = ("thermalling", "gliding", "diving", "towing", "other")


def analyse(path, *, window=None, parse=None) -> Analysis:
    """The whole analysis of a file, as the page computes it."""
    answer = Analysis(run(ANALYSE, path=path, window=window, parse=parse))
    if answer.budget is not None:
        # Python's `TimeBudget.total`; the JavaScript keeps only the parts.
        answer.budget["total"] = sum(answer.budget[key] for key in BUDGET)
    return answer


def flight(path, **parse):
    """A parsed file: `TV.igc.parse` or `TV.kml.parseBytes`."""
    return run("return await load(input.path, input.parse);", path=path, parse=parse or None)
