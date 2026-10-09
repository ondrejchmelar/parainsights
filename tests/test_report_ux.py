"""The report's measured UX defects, pinned so they cannot come back.

`docs/ux-review.md` phase 0: three defects that are independent of everything else and
were measured in headless Chrome at a true 390 x 844 viewport rather than estimated.

These are static assertions over the generated CSS and markup rather than browser probes,
deliberately. A regression here is someone typing `font-size: 10.5px` or dropping an
`aria-label`, and a string test catches that in the fast job that runs everywhere — the
browser job drives the map itself (`test_merged_controls`).
"""

import pathlib
import re

import pytest

from tests.js import needs_node
from tracklog_viewer import render_html
from parainsights_map import map3d, view3d


def media_block(css: str, query: str) -> str:
    """The body of every `@media <query>` block in `css`, concatenated.

    Brace-matched rather than `split(query)[-1]`, which silently reads only the last
    block and breaks the moment a second one is added elsewhere in the sheet — as it did
    when the debrief's own `(hover: none)` rule landed after the tab's.
    """
    bodies = []
    for match in re.finditer(re.escape(query), css):
        opening = css.index("{", match.end())
        depth, index = 0, opening
        while index < len(css):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        bodies.append(css[opening:index])
    return "\n".join(bodies)


class TestTypeFloor:
    """884 text nodes under 11 px, 757 of them at 10.5. Mostly SVG axis labels."""

    def test_no_declared_font_size_is_under_fifteen_pixels(self):
        """The redesign's floor (October 2026): nothing a reader must read under 15 px.
        The one exception is the numbers inside the climbs' circles on the side view and
        the wind chart: at 15 px two digits overflowed the circle, and the reader chose
        smaller numbers over bigger circles (October 2026). The climbs table says the same."""
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", render_html.STYLE)
        sizes, numbers = [], []
        for selector, body in rules:
            for m in re.findall(r"font-size:\s*([0-9.]+)px", body):
                in_circle = selector.split("*/")[-1].strip() in (".chart .mark-label", ".chart-wind .wind-number")
                (numbers if in_circle else sizes).append(float(m))
        assert sizes, "no font sizes found — has the stylesheet moved?"
        assert min(sizes) >= 15.0, (
            f"type floor broken: {sorted(s for s in sizes if s < 15.0)}"
        )
        assert numbers and min(numbers) >= 11, f"circle numbers too small: {numbers}"

    def test_the_view3d_panel_holds_the_same_floor(self):
        """The map's buttons are the one exception: 14 px on a phone, where seven of them
        share one row of a 390 px screen."""
        sizes = [float(m) for m in re.findall(r"font-size:\s*([0-9.]+)px", view3d.STYLE)]
        assert all(s >= 14.0 for s in sizes), (
            f"type floor broken in the 3D panel: {sorted(s for s in sizes if s < 14.0)}"
        )

    def test_chart_text_is_page_sized_and_lifted_on_a_phone(self):
        """SVG text ignores the reader's own preference and shrinks with its chart: 15 px
        on a desktop, and the half-width charts larger in their own units on a phone."""
        assert ".chart .axis-label" in render_html.STYLE
        phone = media_block(render_html.STYLE, "@media (max-width: 640px)")
        assert ".two .chart .axis-label" in phone
        assert "font-size: 19px" in phone


class TestTabCloseButton:
    """The worst defect on the page: the control that removes a flight, at 19 x 19 px."""

    def test_the_button_is_forty_four_pixels(self):
        """44 x 44 everywhere since the redesign, with an icon in the middle."""
        assert ".tab-compare, .tab-close { position: relative; width: 44px; height: 44px;" in render_html.STYLE

    def test_an_inactive_tab_cannot_be_closed_by_accident_on_touch(self):
        """The pairing that makes the bigger target safe rather than worse.

        A 44 px area overlapping the tab-open button is an accidental deletion waiting to
        happen unless the tab has to be selected first.
        """
        touch = media_block(render_html.STYLE, "@media (hover: none)")
        assert ".tab:not(.is-on) .tab-close" in touch
        assert "pointer-events: none" in touch

    def test_the_tab_buttons_are_icons_with_names(self):
        tab = render_html._tab("f1", "Site", "2026-07-01")
        assert tab.count("<svg") == 2
        assert 'aria-label="Remove this flight"' in tab


class TestMapButtonNames:
    """Chrome's own name computation returned `name='↶' from=contents` for six of ten.

    `title` is ignored for a button, because content wins over it — and `title` never
    appears on touch at all, so on a phone those six glyphs were the entire affordance.
    """

    # The four rotate/tilt nudges are gone by design (phase 2): they duplicated a drag,
    # a ctrl-drag and a right-drag that the caption above the panel already teaches, and
    # they were the slots pushing the bar onto a second row. What remains still has to be
    # nameable — zoom and reset are glyphs, and a glyph is not an accessible name.
    GLYPH_ACTS = ("zoom-in", "zoom-out", "reset", "help")

    def test_every_glyph_button_is_named_by_more_than_its_glyph(self):
        for act in self.GLYPH_ACTS + ("fullscreen", "slower", "faster"):
            label = re.search(
                rf"data-m3=\"{act}\"[^>]*aria-label=\"([^\"]+)\"", map3d.SCRIPT, re.S
            )
            assert label, f"{act} has no aria-label"
            assert len(label.group(1)) > 2, (
                f"{act} is still named by a glyph: {label.group(1)!r}"
            )

    def test_the_nudge_buttons_that_duplicate_gestures_are_gone(self):
        for act in ("rotate-left", "rotate-right", "tilt-up", "tilt-down"):
            assert f'data-m3="{act}"' not in map3d.SCRIPT, (
                f"{act} is back; it duplicates a gesture"
            )


class TestKeyboardControl:
    """The keyboard is what lets the nudge buttons go."""

    def test_the_map_is_focusable(self):
        assert 'class="ml-map" tabindex="0"' in map3d.SCRIPT

    def test_the_view_keys_are_bound_to_the_map_not_the_document(self):
        """A report holds several flights, each with its own map. A document-level
        keydown drives whichever map the code finds first."""
        assert "view.addEventListener('keydown'" in map3d.SCRIPT
        assert "document.addEventListener('keydown'" not in map3d.SCRIPT

    def test_arrow_keys_do_not_scroll_the_page(self):
        assert "event.preventDefault()" in map3d.SCRIPT


REPORT_JS = pathlib.Path(render_html.__file__).parent / "js" / "report.js"
DAY = [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)]


def article(tmp_path, name, climbs=DAY, **options):
    """One flight's article as `js/report.js` writes it."""
    from tests import js
    from tests.test_debrief import a_day

    path = a_day(tmp_path, name, climbs, glide=700)
    return js.run("""var a = TV.analysis.analyse(await load(input.path));
      var o = Object.assign({ uid: 'f0', now: Date.now() / 1000 }, input.options);
      return TV.report.flightBody(a, o);""", path=path, options=options)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """One day's article, written once for the classes that only read it."""
    return article(tmp_path_factory.mktemp("render"), "render.igc")


@needs_node
class TestDebriefRendering:
    """Phase 1: the layer that changes the product.

    The IA is load-bearing and easy to regress: the key numbers go *above* the 3D view
    and the cards *immediately below* it, so a reader meets the answer before the hero
    image and the evidence sits next to the instrument that shows it. (The verdict strip
    and the stat tiles said the same numbers twice; since the redesign they are one band.)
    """

    @pytest.fixture
    def html(self, rendered):
        return rendered

    def test_the_key_numbers_precede_the_findings(self, html):
        assert '<div class="figs keys">' in html
        assert '<div class="findings">' in html
        assert html.index('class="figs keys"') < html.index('class="findings"')

    def test_the_key_numbers_sit_under_the_masthead(self, html):
        assert html.index("</header>") < html.index('class="figs keys"')

    def test_every_card_shows_its_cost(self, html):
        cards = html.count('class="finding"')
        assert cards >= 1
        assert html.count("finding-cost") == cards

    def test_thousands_separators_do_not_eat_sentence_commas(self, html):
        """`.replace(",", thin_space)` over a finished sentence strips its prose commas
        too, and the cards read "left at 2 176 m  620 m below". The separator belongs to
        the number, not to the sentence around it."""
        from tests import js

        assert js.run("return TV.debrief.num(3656);") == "3\u00a0656"
        # A card sentence that legitimately contains a comma must still contain one.
        assert ", " in html[html.index('class="findings"'):]

    def test_a_card_with_a_cursor_offers_show_me(self, html):
        assert "data-finding-cursor=" in html
        assert "Show on the map" in html

    def test_show_me_is_scoped_to_the_flight_not_the_document(self):
        """A document holds several flights; a document-level query moves the wrong one."""
        assert "root.querySelectorAll('[data-finding-cursor]')" in render_html.SCRIPT


@needs_node
class TestComparison:
    """Comparison is opt-in: whatever happens to be loaded is not a set the reader chose,
    so it is computed in the page and only once two or more tabs have been marked."""

    @pytest.fixture
    def html(self, rendered):
        return rendered

    def test_no_delta_is_baked_into_the_page(self, html):
        """The old build-time version compared whichever flights happened to be loaded."""
        assert "off the best of" not in html

    def test_each_flight_publishes_its_comparable_numbers(self, html):
        assert "data-compare-mean-climb=" in html
        assert 'class="fig" data-key="mean_climb"' in html

    def test_every_figure_has_somewhere_to_put_a_delta(self, html):
        assert html.count("verdict-delta") == html.count('class="fig" data-key=')

    def test_the_tab_carries_an_opt_in_control(self):
        tab = render_html._tab("f1", "2026-07-01", "Test")
        assert "data-compare-toggle=" in tab
        assert 'aria-pressed="false"' in tab

    def test_marking_a_tab_does_not_switch_to_it(self):
        """The control lives inside the tab, which opens the flight; without stopping the
        event, marking a flight for comparison would also select it."""
        assert "event.stopPropagation()" in render_html.SCRIPT

    def test_under_two_flights_nothing_is_compared(self):
        assert "picked.length < 2" in render_html.SCRIPT


class TestPageText:
    """What the report stopped saying, and where the survivors went."""

    def test_the_upload_panel_says_nothing_is_uploaded(self):
        """The tab blurb's only load-bearing sentence lives in the upload panel itself,
        where someone about to hand over a file will actually read it."""
        from tracklog_viewer import upload_panel

        assert "tabs-note" not in render_html._page("t", [])
        assert "Nothing is uploaded" in upload_panel.panel()

    def test_the_map_no_longer_explains_its_own_gestures(self):
        """Five lines teaching drag, ctrl-drag and scroll on every page load, for
        gestures every map on the web already has."""
        assert "right-drag or ctrl-drag" not in render_html.STYLE

    def test_the_controls_are_explained_behind_a_button_instead(self):
        assert 'data-m3="help"' in map3d.SCRIPT
        assert "view3d-keys" in map3d.SCRIPT
        assert "right-drag / ctrl-drag" in map3d.SCRIPT

    def test_the_terrain_facts_live_in_the_debrief(self):
        """Slope aspect and ground clearance are about the flight, not about how the
        picture was drawn, so they belong with the reading rather than under the map."""
        source = REPORT_JS.read_text(encoding="utf-8")
        assert "view3d-caption" not in source
        assert "contextFacts(a, clearance, terrain)" in source
        assert "debrief-context" in source

    def test_the_map_and_the_charts_are_neighbours(self):
        """One instrument in two projections, sharing a cursor: nothing scrolls between
        them. Asserted on the template, because whether a debrief renders at all depends
        on whether this particular day produced any findings."""
        source = REPORT_JS.read_text(encoding="utf-8")
        layout = source[source.index("figs.join('') + '</div>\\n' + mapSection"):]
        view = layout.index("mapSection")
        debrief = layout.index("debriefSection", view)
        # The top view, where there is one (no ground to draw a map on), comes after the
        # tables and charts: a map looking straight down replaces it.
        top = layout.index("topView", debrief)
        assert view < debrief < top, "something is back between the map and the debrief"

    @needs_node
    def test_the_side_view_hangs_off_the_map_itself(self, tmp_path):
        """The map and the side view are the same flight from two angles on one cursor, so
        the side view is part of the map's own block (`.flight-map`) — right under the 3D
        panel, going full screen with it — and its axis buttons and legend sit below the
        block. With no terrain there is no map, and the side view carries the section alone."""
        source = REPORT_JS.read_text(encoding="utf-8")
        panel = source.index("TV.scene.panel(payload, uid")
        block = source.rindex('<div class="flight-map">', 0, panel)
        assert panel - block < 300, "the 3D panel is not inside the map block"
        assert source.index("sideChart", panel) - panel < 120, (
            "the side view no longer follows the 3D panel directly")
        chart = source.index("var sideChart")
        assert source.index("sideBar", chart) < source.index("chart-host", chart), (
            "the axis switch and legend sit on a bar over the chart, inside its panel")
        html = article(tmp_path, "side.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)])
        assert '<div class="flight-map">' in html
        # The side view is drawn in the page, so the article carries its host.
        assert 'data-chart="profile"' in html


@needs_node
class TestRendersWithTerrain:
    """The report was broken for a week and every test passed.

    The insolation and clearance sentences only run when there *is* terrain, and a test
    that only ever renders without it lets a crash in them through — which is how a
    site rebuild once died on a `NameError`. Rendering the terrain path is the guard.
    """

    def _ridged(self, tmp_path):
        """A flight and a ridged grid around it, so slopes have a real aspect."""
        import numpy as np

        from tests import js
        from tests.test_debrief import a_day

        path = a_day(tmp_path, "terrain.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)
        box = js.run("""var f = await load(input.path);
          return [Math.min.apply(null, f.lon), Math.max.apply(null, f.lon),
                  Math.min.apply(null, f.lat), Math.max.apply(null, f.lat)];""", path=path)
        size, pad = 48, 0.02
        rows = np.linspace(0, 1, size)
        z = (np.sin(rows * 9)[:, None] * np.cos(rows * 7)[None, :]) * 600 + 1500
        grid = {"west": box[0] - pad, "east": box[1] + pad, "south": box[2] - pad,
                "north": box[3] + pad, "rows": size, "cols": size, "z": z.ravel().tolist()}
        return path, grid

    def test_a_report_renders_with_terrain(self, tmp_path):
        from tests import js

        path, grid = self._ridged(tmp_path)
        out = js.run("""var a = TV.analysis.analyse(await load(input.path));
          return { html: TV.report.flightBody(a, { uid: 'f0', now: Date.now() / 1000,
                                                  terrain: input.grid, sceneTerrain: input.grid }),
                   trigger: TV.report.parts.triggerNote(a, input.grid),
                   clearance: TV.report.parts.clearanceNote(TV.terrain.clearance(input.grid, a)) };""",
                     path=path, grid=grid)
        assert "<article" in out.html and "view3d" in out.html
        assert isinstance(out.trigger, str) and isinstance(out.clearance, str)
