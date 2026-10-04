"""The report's three-way renderer switch: canvas, MapLibre, merged.

The MapLibre and merged views load their libraries from a CDN, which the test job cannot
reach, so what is held here is the part that does not need them: every 3D panel —
bundled flight and upload template alike — carries the switch inside a host the click
handler can find, and the page carries both mounts.
"""

import re

from tracklog_viewer import render_html

from parainsights_map import map3d, render_map


def test_the_switch_offers_all_three_renderers():
    html = render_map.switch_html()
    assert re.findall(r'data-renderer="(\w+)"', html) == ["canvas", "maplibre", "merged"]
    on = re.findall(r'class="toggle-button is-on" data-renderer="(\w+)"', html)
    assert on == ["canvas"], "the canvas view is still the one a panel opens on"


def test_every_3d_panel_sits_in_a_renderer_host():
    # Every article is written by `js/report.js`, an upload's and a bundled flight's
    # alike; its panel must be switchable too.
    from pathlib import Path

    js = Path(render_html.__file__).parent / "js"
    assert "renderer-host" in (js / "report.js").read_text()
    assert 'data-renderer="merged"' in (js / "scene.js").read_text()
    assert 'data-renderer="merged"' in render_map.switch_html()


def test_the_page_carries_both_mounts_and_one_loader():
    page = render_html._page("probe", [])
    assert "window.__mountMerged = function" in page
    assert "window.__mapLibs = libs" in page
    assert map3d.STYLE.strip()[:40] in page


def test_heights_are_scaled_from_sea_level_in_both_maplibre_views():
    # MapLibre exaggerates terrain from 0 m; scaling about the lowest ground instead sinks
    # the track into every ridge at x2 and x4.
    assert "function z(alt) { return alt * vertical; }" in render_map.SWITCH_SCRIPT
    assert "function z(alt) { return alt * vertical; }" in map3d.SCRIPT


def test_the_merged_view_never_shows_esri_below_its_consistent_level():
    # Esri's levels under 12 are an older, darker mosaic: blue channel 26 against 59 over
    # the same Dolomites ground. The merged view builds those tiles from level 12 instead.
    from parainsights_map import view3d

    assert view3d.TILE_SOURCES["satellite"]["consistent_from"] == 12
    assert "maplibregl.addProtocol('m3tiles'" in map3d.SCRIPT
    assert "source.consistent_from" in map3d.SCRIPT
