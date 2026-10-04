"""The report's own flights are written by the JavaScript an upload goes through.

`cli --html` renders each article with `js/upload.js`'s `compose`, run in Node at build
time (`js_build.py`). The Python renderer is still there behind `--python-articles`, and
it is the reference: the two must give the same article, the same tab and the same page
around them. No network here — no ground and no weather — so this holds the shape; the
real inputs were compared by hand on the showcase flights (identical, CLAUDE.md).
"""

import re

import pytest

from tests.test_analysis import build
from tests.test_js_parity import FLIGHTS, needs_node
from tracklog_viewer import cli, js_build, js_parity


def _articles(page: str) -> dict:
    out = {}
    starts = list(re.finditer(r'<article class="flight[^"]*"[^>]*data-flight-report="(f\d)"', page))
    for m in starts:
        rest = page[m.end():]
        end = re.search(r'<article class="flight[^"]*"[^>]*data-flight-report="(f\d|own)"', rest)
        out[m.group(1)] = page[m.start(): m.end() + (end.start() if end else len(rest))]
    return out


def _tabs(page: str) -> str:
    return re.search(r'<nav class="tabs".*?</nav>', page, re.S).group(0)


@needs_node
def test_the_report_is_written_by_the_uploads_javascript(tmp_path):
    flights = [build(tmp_path / f"{name}.igc", FLIGHTS[name]())
               for name in ("thermal-glide-thermal", "tow-then-thermal")]
    js_page, py_page = tmp_path / "js.html", tmp_path / "py.html"
    labels = ["--label", "Ana Bell|Ridge|", "--label", ""]
    assert cli.main([*map(str, flights), *labels, "--html", str(js_page)]) == 0
    assert cli.main([*map(str, flights), *labels, "--python-articles",
                     "--html", str(py_page)]) == 0
    js_text, py_text = js_page.read_text(), py_page.read_text()
    assert "TV.upload" in js_text
    js_articles, py_articles = _articles(js_text), _articles(py_text)
    assert sorted(js_articles) == ["f0", "f1"] == sorted(py_articles)
    for uid in js_articles:
        (js_html, js_json), (py_html, py_json) = (js_parity.normalise_html(js_articles[uid]),
                                                  js_parity.normalise_html(py_articles[uid]))
        assert js_html == py_html, js_parity._first_difference(py_html, js_html)
        for (name, a), (_, b) in zip(py_json, js_json):
            assert not js_parity.differences(a, b), (uid, name)
    assert _tabs(js_text) == _tabs(py_text)
    # The label override reached the article, not only the tab.
    assert "Ana Bell" in js_articles["f0"] and "Ridge" in js_articles["f0"]


@needs_node
def test_a_flight_the_javascript_refuses_stops_the_build(tmp_path):
    """Not a quiet fallback to the Python renderer: a build that cannot render a flight
    the way an upload would is a build that would publish something else."""
    bad = tmp_path / "bad.igc"
    bad.write_text("AXXX\nHFDTE010120\n", encoding="utf-8")
    with pytest.raises(js_build.BuildError):
        js_build.render([{"path": str(bad), "name": "bad.igc", "terrain": None,
                          "sceneTerrain": None, "meteo": None, "when": None,
                          "options": {"uid": "f0"}}], certification_table=None, now=0)
