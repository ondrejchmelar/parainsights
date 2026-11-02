"""The side view while the 3D replay is open, in a real browser: the replay's "now" in
words beside its bar, and a click on the chart moving the replay there rather than
pinning a cursor of the chart's own, which fought the replay's (November 2026).

The map itself needs MapLibre and a network, so a stand-in handle takes its place, with
`seekTime`, the one member the side view calls while the replay is open.
"""

from __future__ import annotations

import pytest

from tests.flights import FLIGHTS
from tests.test_analysis import build
from tests.test_merged_controls import Browser
from tests.browser import CHROME

pytest.importorskip("websocket")
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome")

ARTICLE = "document.querySelector('article[data-flight-report=\"f0\"]')"


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    from tracklog_viewer import cli

    folder = tmp_path_factory.mktemp("replay")
    a = build(folder / "a.igc", FLIGHTS["thermal-glide-thermal"]())
    assert cli.main([str(a), "--html", str(folder / "page.html")]) == 0
    browser = Browser(folder)
    try:
        browser.wait("!!document.querySelector('[data-showcase-open=\"f0\"]')")
        # Asked for when the flight is first shown, so set before the card opens it.
        browser.js("""(() => { var noop = function () {};
          window.initView3dWhenReady = () => { window.__handed = true;
            return Promise.resolve({ setCursor: noop, clearCursor: noop,
              revealCursor: noop, seekTime: t => { window.__sought = t; } }); };
          window.__openMap = noop; return 1; })()""")
        browser.js("document.querySelector('[data-showcase-open=\"f0\"]').click(); 1")
        browser.wait(f"!!{ARTICLE}.querySelector('.side-view .hit') && !!{ARTICLE}.__replayNow")
        # The handle is asked for once the flight is on screen (an IntersectionObserver,
        # `whenShown`), which can land after the charts: a click before it reaches no map.
        # An observer reports only on a rendered frame, and headless Chrome under load
        # renders none for a page with no map to repaint: a screenshot forces one.
        for _ in range(60):
            if browser.js("window.__handed === true"):
                break
            browser.screenshot()
        else:
            raise TimeoutError("the flight never asked for its map's handle")
        browser.js("new Promise(r => setTimeout(() => r(1), 0))")
        yield browser
    finally:
        browser.close()


def _side(browser, share):
    """A point on the side view's plot, `share` of the way across it, in the viewport."""
    return browser.js("""(() => { var hit = %s.querySelector('.side-view .hit');
      hit.scrollIntoView({ block: 'center' }); var r = hit.getBoundingClientRect();
      return [r.left + r.width * %f, r.top + r.height / 2]; })()""" % (ARTICLE, share))


def test_the_replay_reads_its_now_beside_its_bar_and_a_click_moves_it(page):
    end = page.js(f"(() => {{ var t = JSON.parse({ARTICLE}.querySelector('.cursor-data').textContent).t;"
                  " return t[t.length - 1]; })()")
    page.js(f"""(() => {{ var a = {ARTICLE};
      a.__rangeAtTime([0, {end} / 4, false]);
      a.__replayNow({{ clock: '12:34', rows: [{{ colour: null, alt: 1234.4, climb: 1.24 }}] }});
      return 1; }})()""")
    tag = page.js(f"{ARTICLE}.querySelector('.replay-tag').textContent")
    assert tag == "12:34 · 1,234 m · +1.2 m/s", tag
    # Several gliders: the clock over them, a line each.
    page.js(f"""{ARTICLE}.__replayNow({{ clock: '12:35', rows: [
      {{ colour: '#e0893a', alt: 1500, climb: -0.5 }}, {{ colour: '#3aa8d0', alt: 900, climb: 2 }}] }}); 1""")
    lines = page.js(f"{ARTICLE}.querySelector('.replay-tag').innerText").splitlines()
    assert lines == ["12:35", "1,500 m · -0.5 m/s", "900 m · +2.0 m/s"], lines

    # A click three quarters along the axis is three quarters through the flight, and
    # pins nothing of the chart's own: no tooltip, no second cursor.
    page.js("window.__sought = null; 1")
    page.click(*_side(page, 0.75))
    sought = page.js("window.__sought")
    assert sought == pytest.approx(end * 0.75, rel=0.03), (sought, end)
    state = page.js(f"""({{ tip: document.getElementById('tip').classList.contains('on'),
      pinned: {ARTICLE}.classList.contains('is-pinned') }})""")
    assert state == {"tip": False, "pinned": False}, state

    # Closed, the chart is its own cursor again: a click pins, and the tag is gone.
    page.js(f"{ARTICLE}.__rangeAtTime(null); 1")
    assert page.js(f"!{ARTICLE}.querySelector('.replay-tag')")
    page.js("window.__sought = null; 1")
    page.click(*_side(page, 0.5))
    assert page.js(f"{ARTICLE}.classList.contains('is-pinned')")
    assert page.js("window.__sought") is None


def test_opening_the_replay_lets_go_of_a_pinned_point(page):
    page.js(f"{ARTICLE}.__rangeAtTime(null); 1")
    page.click(*_side(page, 0.3))
    assert page.js(f"{ARTICLE}.classList.contains('is-pinned')")
    page.js(f"{ARTICLE}.__rangeAtTime([0, 60, false]); 1")
    state = page.js(f"""({{ tip: document.getElementById('tip').classList.contains('on'),
      pinned: {ARTICLE}.classList.contains('is-pinned') }})""")
    assert state == {"tip": False, "pinned": False}, state
    page.js(f"{ARTICLE}.__rangeAtTime(null); 1")
