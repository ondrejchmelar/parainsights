"""The report's measured UX defects, pinned so they cannot come back.

`docs/ux-review.md` phase 0: three defects that are independent of everything else and
were measured in headless Chrome at a true 390 x 844 viewport rather than estimated.

These are static assertions over the generated CSS and markup rather than browser probes,
deliberately. A regression here is someone typing `font-size: 10.5px` or dropping an
`aria-label`, and a string test catches that in the fast job that runs everywhere — the
browser job is `allow_failure: true` and covers only the two view3d suites.
"""

import pathlib
import re

import pytest

from tests.js import needs_node
from tracklog_viewer import render_html
from parainsights_map import view3d


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

    def test_no_declared_font_size_is_under_eleven_pixels(self):
        sizes = [float(m) for m in re.findall(r"font-size:\s*([0-9.]+)px", render_html.STYLE)]
        assert sizes, "no font sizes found — has the stylesheet moved?"
        assert min(sizes) >= 11.0, (
            f"type floor broken: {sorted(s for s in sizes if s < 11.0)}"
        )

    def test_the_view3d_panel_holds_the_same_floor(self):
        sizes = [float(m) for m in re.findall(r"font-size:\s*([0-9.]+)px", view3d.STYLE)]
        assert all(s >= 11.0 for s in sizes), (
            f"type floor broken in the 3D panel: {sorted(s for s in sizes if s < 11.0)}"
        )

    def test_small_type_is_lifted_further_on_a_phone(self):
        """11 px desktop, 12 px mobile — SVG text ignores the reader's own preference."""
        phone = media_block(render_html.STYLE, "@media (max-width: 620px)")
        assert ".chart .axis-label" in phone
        assert "font-size: 12px" in phone


class TestTabCloseButton:
    """The worst defect on the page: the control that removes a flight, at 19 x 19 px."""

    def test_the_hit_area_reaches_forty_four_pixels_on_touch(self):
        touch = media_block(render_html.STYLE, "@media (hover: none)")
        assert ".tab-close::before" in touch
        assert "width: 44px" in touch and "height: 44px" in touch

    def test_an_inactive_tab_cannot_be_closed_by_accident_on_touch(self):
        """The pairing that makes the bigger target safe rather than worse.

        A 44 px area overlapping the tab-open button is an accidental deletion waiting to
        happen unless the tab has to be selected first.
        """
        touch = media_block(render_html.STYLE, "@media (hover: none)")
        assert ".tab:not(.is-on) .tab-close" in touch
        assert "pointer-events: none" in touch

    def test_the_glyph_itself_is_unchanged_on_a_desktop(self):
        """19 px is right with a mouse; only the touch hit area grows."""
        assert "width: 19px" in render_html.STYLE


class TestMapButtonNames:
    """Chrome's own name computation returned `name='↶' from=contents` for six of ten.

    `title` is ignored for a button, because content wins over it — and `title` never
    appears on touch at all, so on a phone those six glyphs were the entire affordance.
    """

    # The four rotate/tilt nudges are gone by design (phase 2): they duplicated a drag,
    # a ctrl-drag and a right-drag that the caption above the panel already teaches, and
    # they were the slots pushing the bar onto a second row. What remains still has to be
    # nameable — zoom and reset are glyphs, and a glyph is not an accessible name.
    GLYPH_ACTS = ("zoom-in", "zoom-out", "reset")

    def _panel(self):
        return view3d.panel({"bounds": {}}, "uid")

    def test_every_control_carries_an_aria_label(self):
        html = self._panel()
        for act in self.GLYPH_ACTS + ("fullscreen",):
            button = re.search(
                rf'<button[^>]*data-view3d-act="{act}"[^>]*>', html, re.S
            )
            assert button, f"no button for {act}"
            assert "aria-label=" in button.group(0), (
                f"{act} computes its name from its contents"
            )

    def test_the_glyph_buttons_are_not_named_by_their_glyph(self):
        html = self._panel()
        for act in self.GLYPH_ACTS:
            label = re.search(
                rf'data-view3d-act="{act}"[^>]*aria-label="([^"]+)"', html, re.S
            )
            assert label, f"{act} has no aria-label"
            assert len(label.group(1)) > 2, (
                f"{act} is still named by a glyph: {label.group(1)!r}"
            )

    def test_the_nudge_buttons_that_duplicate_gestures_are_gone(self):
        html = self._panel()
        for act in ("rotate-left", "rotate-right", "tilt-up", "tilt-down"):
            assert f'data-view3d-act="{act}"' not in html, (
                f"{act} is back; it duplicates a gesture the caption teaches"
            )

    def test_the_exaggeration_segments_are_named_individually(self):
        """`x1 height` at rest was a button announcing that nothing is happening."""
        html = self._panel()
        labels = re.findall(
            r'data-view3d-act="exaggerate-set"[^>]*aria-label="([^"]+)"', html, re.S
        )
        assert len(labels) == 3, f"expected three exaggeration segments, got {labels}"


class TestKeyboardControl:
    """Phase 2: the keyboard is what lets the nudge buttons go."""

    def test_the_canvas_is_focusable(self):
        assert 'tabindex="0"' in view3d.panel({"bounds": {}}, "uid")

    def test_keys_are_bound_to_act_names_not_camera_fields(self):
        """One code path rather than two that drift — and it is why a held arrow
        anchors through `holdGround` exactly as a held button does."""
        assert "KEY_ACTS" in view3d.SCRIPT
        assert "runAct(act)" in view3d.SCRIPT

    def test_the_view_keys_are_bound_to_the_canvas_not_the_document(self):
        """A report holds several flights, each with its own panel. A document-level
        keydown drives whichever panel the code finds first — a bug this file already
        carries a comment about for buttons.

        Escape is the one legitimate exception and it predates this: leaving full screen
        has to work wherever focus is, and it is the Fullscreen API's own contract. So the
        rule is not "no document handler", it is "the document handler does nothing but
        Escape" — which is what this asserts.
        """
        assert "canvas.addEventListener('keydown'" in view3d.SCRIPT

        for match in re.finditer(
            r"document\.addEventListener\('keydown', function \(event\) \{(.{0,120})",
            view3d.SCRIPT, re.S,
        ):
            assert "Escape" in match.group(1), (
                "a document-level keydown that is not the Escape guard: it will drive "
                f"another flight's panel — {match.group(1)!r}"
            )

    def test_arrow_keys_do_not_scroll_the_page(self):
        assert "event.preventDefault()" in view3d.SCRIPT

    def test_state_keys_address_a_state_directly(self):
        """`1 2 4` and `S M R` are what a cycle could never offer."""
        assert "KEY_STYLES" in view3d.SCRIPT
        assert "'exaggerate-set'" in view3d.SCRIPT


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

    The IA is load-bearing and easy to regress: the verdict strip goes *above* the 3D
    view and the cards *immediately below* it, so a reader meets the answer before the
    hero image and the evidence sits next to the instrument that shows it.
    """

    @pytest.fixture
    def html(self, rendered):
        return rendered

    def test_the_verdict_strip_precedes_the_findings(self, html):
        assert '<div class="verdict">' in html
        assert '<div class="findings">' in html
        assert html.index('class="verdict"') < html.index('class="findings"')

    def test_the_verdict_strip_sits_under_the_masthead(self, html):
        assert html.index("</header>") < html.index('class="verdict"')

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
        assert "show me" in html

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
        assert 'class="verdict-figure" data-key=' in html

    def test_every_figure_has_somewhere_to_put_a_delta(self, html):
        assert html.count("verdict-delta") == html.count('class="verdict-figure"')

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
        panel = view3d.panel({"bounds": {}}, "uid")
        # The lesson survives, but behind the ? button rather than above the map.
        assert "right-drag / ctrl-drag" in panel

    def test_the_controls_are_explained_behind_a_button_instead(self):
        panel = view3d.panel({"bounds": {}}, "uid")
        assert 'data-view3d-act="help"' in panel
        assert "view3d-keys" in panel
        assert "right-drag / ctrl-drag" in panel

    def test_the_terrain_facts_live_in_the_debrief(self):
        """Slope aspect and ground clearance are about the flight, not about how the
        picture was drawn, so they belong with the reading rather than under the map."""
        source = REPORT_JS.read_text(encoding="utf-8")
        assert "view3d-caption" not in source
        assert "clearanceNote(clearance) + ' ' + triggerNote(a, terrain)" in source
        assert "debrief-context" in source

    def test_the_map_and_the_charts_are_neighbours(self):
        """One instrument in two projections, sharing a cursor: nothing scrolls between
        them. Asserted on the template, because whether a debrief renders at all depends
        on whether this particular day produced any findings."""
        source = REPORT_JS.read_text(encoding="utf-8")
        layout = source[source.index("verdictStrip(result) + "):]
        view = layout.index("view3dSection")
        top = layout.index("<h2>Top view</h2>")
        debrief = layout.index("debriefSection", view)
        assert view < top < debrief, "the debrief is back between the map and the charts"

    @needs_node
    def test_the_side_view_hangs_off_the_map_itself(self, tmp_path):
        """The map and the side view are the same flight from two angles on one cursor, so
        the side view is pasted inside the map's section — no heading, no section gap.
        With no terrain there is no map, and the side view carries the section alone."""
        source = REPORT_JS.read_text(encoding="utf-8")
        panel = source.index("TV.scene.panel(payload, uid")
        assert source.index("sideView", panel) - panel < 400, (
            "the side view no longer follows the 3D panel directly")
        html = article(tmp_path, "side.igc", [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)])
        assert "The flight from the side" in html
        # The side view is drawn in the page, so the article carries its host.
        assert 'data-chart="profile"' in html


class TestBasemapSpinner:
    """Stitching a basemap over a cross-country box is slow enough that "did my click
    register" is a real question, and the credit line in the corner was the only sign."""

    def _panel(self):
        return view3d.panel({"bounds": {}}, "uid")

    def test_the_panel_carries_a_loading_overlay(self):
        panel = self._panel()
        assert "view3d-loading" in panel
        assert "view3d-spin" in panel

    def test_it_starts_hidden(self):
        assert 'class="view3d-loading" hidden' in self._panel()

    def test_it_is_shown_when_tiles_start_loading(self):
        assert "showLoading(" in view3d.SCRIPT

    def test_every_exit_from_the_load_hides_it(self):
        """Including the ones that give up: a spinner left running over terrain that is
        never going to change is worse than no spinner."""
        script = view3d.SCRIPT
        assert script.count("hideLoading()") >= 3

    def test_a_hung_request_is_given_up_on(self):
        """The failure this suite originally missed.

        A blocked host or a captive portal *hangs* rather than returning an error, so
        neither the tile `onerror` nor `finish()` ever runs and the spinner — and the
        credit line before it — sat there indefinitely. Measured against a proxy that
        drops the tile hosts: still loading after eight seconds with nothing pending.
        """
        script = view3d.SCRIPT
        assert "TILE_STALL_MS" in script
        assert "function stall()" in script
        # The watchdog and the normal finish must not both run.
        assert "if (settled) return;" in script

    def test_the_watchdog_is_a_stall_detector_not_a_deadline(self):
        """A slow connection trickling 80 tiles in is still making progress, and cutting
        it off at a fixed deadline would break exactly the case the spinner is for."""
        script = view3d.SCRIPT
        assert "function progress()" in script
        # Every tile outcome re-arms it, errors included: the host answered either way.
        assert script.count("progress();") >= 3

    def test_it_clears_after_the_stitched_image_is_shaded_not_before(self):
        """`shadedTexture` and `sampleCellColours` run after the last tile arrives, so
        hiding on tile count leaves the reader watching unchanged terrain."""
        script = view3d.SCRIPT
        stitched = script.index("var image = mosaic;")
        shaded = script.index("shadedTexture(image, box)", stitched)
        colours = script.index("sampleCellColours();", shaded)
        assert colours < script.index("hideLoading()", colours), (
            "the spinner clears before the stitched imagery is shaded and sampled")

    def test_the_label_survives_reduced_motion(self):
        """The global reduced-motion rule stops the ring, so the text beside it is what
        carries the message."""
        assert "view3d-loading-text" in self._panel()
        assert "prefers-reduced-motion" in view3d.STYLE


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
