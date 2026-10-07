"""Comparing flights, in a real browser: a two-flight report built from synthetic
tracklogs, and the compare buttons tapped the way a phone taps them.

Headless Chrome reports no hover, which is the touch layout — and that is where it broke:
the close button's 44 px touch area grows inward over the compare button beside it, so a
tap meant to add a flight to the comparison removed the flight instead.
"""

from __future__ import annotations

import json
import time

import pytest

from tests.flights import FLIGHTS
from tests.test_analysis import build
from tests.test_merged_controls import Browser, _box  # noqa: F401  (Browser is reused)
from tests.test_view3d_gl import CHROME

pytest.importorskip("websocket")
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome")


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    from tracklog_viewer import cli

    folder = tmp_path_factory.mktemp("compare")
    a = build(folder / "a.igc", FLIGHTS["thermal-glide-thermal"]())
    b = build(folder / "b.igc", FLIGHTS["thermal-glide-thermal"]())
    assert cli.main([str(a), str(b), "--html", str(folder / "page.html")]) == 0
    browser = Browser(folder)
    try:
        browser.wait("document.querySelectorAll('[data-compare-toggle]').length === 2")
        yield browser
    finally:
        browser.close()


def _tap(browser, selector):
    x, y = browser.js(
        "(() => { var r = document.querySelector(%s).getBoundingClientRect();"
        " return [r.left + r.width / 2, r.top + r.height / 2]; })()" % json.dumps(selector))
    browser.click(x, y)
    time.sleep(0.4)


def test_tapping_compare_adds_the_flight_and_never_removes_it(page):
    assert page.js("matchMedia('(hover: none)').matches"), "the touch layout is under test"
    _tap(page, '[data-flight-tab="f0"] .tab-open')
    _tap(page, '[data-compare-toggle="f0"]')
    _tap(page, '[data-flight-tab="f1"] .tab-open')
    _tap(page, '[data-compare-toggle="f1"]')
    state = page.js("""({
      tabs: Array.from(document.querySelectorAll('[data-flight-tab]')).map(t => t.dataset.flightTab),
      pressed: Array.from(document.querySelectorAll('[data-compare-toggle]')).map(b => b.getAttribute('aria-pressed')),
      comparing: document.documentElement.classList.contains('is-comparing'),
      lines: Array.from(document.querySelectorAll('[data-flight-report="f1"] .verdict-delta'))
                  .filter(d => !d.hidden).map(d => d.textContent) })""")
    assert state["tabs"] == ["own", "f0", "f1"], "a tap on compare removed a flight"
    assert state["pressed"] == ["true", "true"]
    assert state["comparing"]
    assert state["lines"] and all("of 2" in line for line in state["lines"]), state


def test_removing_a_compared_flight_leaves_the_comparison(page):
    _tap(page, '[data-flight-tab="f0"] .tab-open')
    _tap(page, '[data-flight-tab="f0"] .tab-close')
    time.sleep(0.4)
    assert page.js("document.querySelectorAll('[data-flight-report=\"f0\"]').length") == 0
    assert not page.js("document.documentElement.classList.contains('is-comparing')")


def test_the_side_view_tooltip_is_shown_in_full_screen(page):
    """In full screen only the full-screen element is drawn, so a tooltip left in the page
    body is never seen. The full-screen element is *inside* the flight's article; the check
    once asked it the other way round and the tooltip stayed behind."""
    _tap(page, '[data-flight-tab="f1"] .tab-open')
    full = page.call("Runtime.evaluate", userGesture=True, awaitPromise=True, returnByValue=True,
                     expression="document.querySelector('[data-flight-report=\"f1\"] .side-view')"
                                ".closest('section').requestFullscreen().then(() => true)")
    assert full["result"].get("value"), full
    try:
        x, y = page.js("(() => { var r = document.querySelector('[data-flight-report=\"f1\"]"
                       " .side-view .hit').getBoundingClientRect();"
                       " return [r.left + r.width * 0.4, r.top + r.height / 2]; })()")
        page.click(x, y)
        time.sleep(0.4)
        state = page.js("""(() => { var t = document.getElementById('tip');
          return { on: t.classList.contains('on'),
                   inside: document.fullscreenElement.contains(t) }; })()""")
        assert state == {"on": True, "inside": True}, state
    finally:
        page.js("document.exitFullscreen().then(() => true)")
