"""The report's three-way renderer switch: canvas, MapLibre, merged.

The MapLibre and merged views load their libraries from a CDN, which the test job cannot
reach, so what is held here is the part that does not need them: every 3D panel —
bundled flight and upload template alike — carries the switch inside a host the click
handler can find, and the page carries both mounts.
"""

import re

from tracklog_viewer import map3d, render_html, render_map


def test_the_switch_offers_all_three_renderers():
    html = render_map.switch_html()
    assert re.findall(r'data-renderer="(\w+)"', html) == ["canvas", "maplibre", "merged"]
    on = re.findall(r'class="toggle-button is-on" data-renderer="(\w+)"', html)
    assert on == ["canvas"], "the canvas view is still the one a panel opens on"


def test_every_3d_panel_sits_in_a_renderer_host():
    page = render_html._page("probe", [])
    # The upload template is in every report; its panel must be switchable too.
    template = page[page.index('id="ql-template"'):]
    assert "renderer-host" in template and 'data-renderer="merged"' in template


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
