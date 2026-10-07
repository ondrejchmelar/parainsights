"""Every 3D panel opens the map, and the page carries what it needs to.

The map loads its libraries from a CDN, which most of the suite cannot reach, so what is
held here is the part that does not need them: every 3D panel — bundled flight and
upload alike — sits inside a host the opener can find, with no renderer switch left over,
and the page carries the mount and the loader. `test_merged_controls` drives the map
itself, from a local copy of the libraries.
"""

from pathlib import Path

from tracklog_viewer import render_html

from parainsights_map import map3d, render_map, view3d


def test_every_3d_panel_sits_in_a_renderer_host():
    # Every article is written by `js/report.js`, an upload's and a bundled flight's
    # alike.
    js = Path(render_html.__file__).parent / "js"
    assert "renderer-host" in (js / "report.js").read_text()
    for source in ((js / "scene.js").read_text(), (js / "report.js").read_text()):
        assert "data-renderer" not in source, "the renderer switch is gone"


def test_the_panel_says_what_the_map_offers():
    panel = view3d.panel({}, "t", verticals=(1, 5, 15), vertical=5)
    assert 'data-verticals="1,5,15"' in panel and 'data-vertical="5"' in panel
    assert '<canvas' not in panel


def test_the_page_carries_the_mount_and_one_loader():
    page = render_html._page("probe", [])
    assert "window.__mountMerged = function" in page
    assert "window.__mapLibs = libs" in page
    assert "window.__openMap = function" in page
    assert map3d.STYLE.strip()[:40] in page
    assert "initView3dWhenReady" in page


def test_heights_are_scaled_from_sea_level():
    # MapLibre exaggerates terrain from 0 m; scaling about the lowest ground instead sinks
    # the track into every ridge at x2 and x4.
    assert "function z(alt) { return alt * vertical; }" in map3d.SCRIPT


def test_the_map_never_shows_esri_below_its_consistent_level():
    # Esri's levels under 12 are an older, darker mosaic: blue channel 26 against 59 over
    # the same Dolomites ground. The map builds those tiles from level 12 instead.
    assert view3d.TILE_SOURCES["satellite"]["consistent_from"] == 12
    assert "maplibregl.addProtocol('m3tiles'" in map3d.SCRIPT
    assert "source.consistent_from" in map3d.SCRIPT


def test_the_loader_is_the_one_cdn_pair():
    assert render_map.MAPLIBRE in render_map.SCRIPT and render_map.DECK in render_map.SCRIPT
