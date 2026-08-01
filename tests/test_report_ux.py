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

from tracklog_viewer import render_html, view3d


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


class TestDebriefRendering:
    """Phase 1: the layer that changes the product.

    The IA is load-bearing and easy to regress: the verdict strip goes *above* the 3D
    view and the cards *immediately below* it, so a reader meets the answer before the
    hero image and the evidence sits next to the instrument that shows it.
    """

    def _report(self, tmp_path):
        from tests.test_debrief import a_day

        analysis = a_day(tmp_path, "render.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        return render_html._flight_body(analysis), analysis

    def test_the_verdict_strip_precedes_the_findings(self, tmp_path):
        html, _ = self._report(tmp_path)
        assert '<div class="verdict">' in html
        assert '<div class="findings">' in html
        assert html.index('class="verdict"') < html.index('class="findings"')

    def test_the_verdict_strip_sits_under_the_masthead(self, tmp_path):
        html, _ = self._report(tmp_path)
        assert html.index("</header>") < html.index('class="verdict"')

    def test_every_card_shows_its_cost(self, tmp_path):
        html, _ = self._report(tmp_path)
        cards = html.count('class="finding"')
        assert cards >= 1
        assert html.count("finding-cost") == cards

    def test_thousands_separators_do_not_eat_sentence_commas(self, tmp_path):
        """`.replace(",", thin_space)` over a finished sentence strips its prose commas
        too, and the cards read "left at 2 176 m  620 m below". The separator belongs to
        the number, not to the sentence around it."""
        from tracklog_viewer import debrief

        assert debrief._num(3656) == "3 656"
        html, _ = self._report(tmp_path)
        # A card sentence that legitimately contains a comma must still contain one.
        assert ", " in html[html.index('class="findings"'):]

    def test_a_card_with_a_cursor_offers_show_me(self, tmp_path):
        html, _ = self._report(tmp_path)
        assert "data-finding-cursor=" in html
        assert "show me" in html

    def test_show_me_is_scoped_to_the_flight_not_the_document(self, tmp_path):
        """A document holds several flights; a document-level query moves the wrong one."""
        assert "root.querySelectorAll('[data-finding-cursor]')" in render_html.SCRIPT


class TestComparison:
    """Comparison is opt-in, and the two kinds of comparison are different in kind.

    The archive rank ("among your best of 12") is about the pilot's history, is true no
    matter what else is open, and is baked in. The cross-flight delta is not: whatever
    happens to be loaded is not a set the reader chose, so it is computed in the page and
    only once two or more tabs have been marked.
    """

    def _report(self, tmp_path, name="cmp.igc"):
        from tests.test_debrief import a_day

        analysis = a_day(tmp_path, name,
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        return render_html._flight_body(analysis), analysis

    def test_no_delta_is_baked_into_the_page(self, tmp_path):
        """The old build-time version compared whichever flights happened to be loaded."""
        html, _ = self._report(tmp_path)
        assert "off the best of" not in html

    def test_each_flight_publishes_its_comparable_numbers(self, tmp_path):
        html, _ = self._report(tmp_path)
        assert "data-compare-mean-climb=" in html
        assert 'class="verdict-figure" data-key=' in html

    def test_every_figure_has_somewhere_to_put_a_delta(self, tmp_path):
        html, _ = self._report(tmp_path)
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

    def test_a_cold_archive_says_nothing(self, tmp_path):
        from tracklog_viewer import baseline

        html, _ = self._report(tmp_path, "cold.igc")
        assert "verdict-rank" not in html
        assert "verdict-rank" not in render_html._flight_body(
            self._report(tmp_path, "cold2.igc")[1], archive=baseline.Baseline([])
        )

    def test_a_usable_archive_places_the_flight_and_names_the_sample(self, tmp_path):
        import json

        from tests.test_baseline import entry
        from tests.test_debrief import a_day
        from tracklog_viewer import baseline

        directory = tmp_path / "arch"
        directory.mkdir()
        for i, rate in enumerate([0.3, 0.4, 0.5, 0.6, 0.7, 0.8]):
            (directory / f"{i}.json").write_text(
                json.dumps(entry(f"2026-01-{i + 1:02d}", mean_climb=rate)),
                encoding="utf-8",
            )
        analysis = a_day(tmp_path, "warm.igc",
                         [(300, 2.5), (300, 2.4), (300, 2.3), (300, 2.2), (300, 2.1)],
                         glide=700)
        html = render_html._flight_body(analysis, archive=baseline.build(directory))

        assert "verdict-rank" in html
        assert "of 6 flights" in html, "the sample size has to be named"


class TestPageText:
    """What the report stopped saying, and where the survivors went."""

    def test_the_tab_blurb_is_gone(self, tmp_path):
        """Its only load-bearing sentence — nothing is uploaded — is in the upload panel
        itself, where someone about to hand over a file will actually read it."""
        from tracklog_viewer import quicklook

        assert "tabs-note" not in render_html.render(
            self._analysis(tmp_path), terrain=None
        )
        assert "Nothing is uploaded" in quicklook.panel()

    def _analysis(self, tmp_path):
        from tests.test_debrief import a_day

        return a_day(tmp_path, "text.igc",
                     [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def test_the_map_no_longer_explains_its_own_gestures(self):
        """Five lines teaching drag, ctrl-drag and scroll on every page load, for
        gestures every map on the web already has."""
        body = render_html.__dict__["_flight_body"].__doc__ or ""
        assert "right-drag or ctrl-drag" not in render_html.STYLE
        panel = view3d.panel({"bounds": {}}, "uid")
        # The lesson survives, but behind the ? button rather than above the map.
        assert "right-drag / ctrl-drag" in panel

    def test_the_controls_are_explained_behind_a_button_instead(self):
        panel = view3d.panel({"bounds": {}}, "uid")
        assert 'data-view3d-act="help"' in panel
        assert "view3d-keys" in panel
        assert "right-drag / ctrl-drag" in panel

    def test_the_terrain_facts_moved_into_the_debrief(self, tmp_path):
        """Slope aspect and ground clearance are about the flight, not about how the
        picture was drawn, so they belong with the reading rather than under the map."""
        assert not hasattr(render_html, "_view3d_caption")
        # The caption element itself is gone from the template.
        html = render_html.render(self._analysis(tmp_path), terrain=None)
        assert "view3d-caption" not in html
        # And the notes it used to carry are now rendered into the debrief section.
        source = pathlib.Path(render_html.__file__).read_text(encoding="utf-8")
        assert "_clearance_note(clearance)" in source
        assert "_trigger_note(analysis, terrain)" in source
        assert "debrief-context" in source

    def test_the_map_and_the_charts_are_neighbours(self, tmp_path):
        """One instrument in two projections, sharing a cursor: nothing scrolls between
        them any more. Asserted on the template, because whether a debrief renders at all
        depends on whether this particular day produced any findings."""
        source = pathlib.Path(render_html.__file__).read_text(encoding="utf-8")
        view = source.index("{view3d_section}")
        charts = source.index("Side view and top view")
        debrief = source.index("{debrief_section}", view)
        assert view < charts < debrief, (
            "the debrief is back between the map and the charts")


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
        assert "image.onerror = hideLoading" in script

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

    def test_it_clears_after_the_stitched_image_decodes_not_before(self):
        """`shadedTexture` and `sampleCellColours` run after the last tile arrives, so
        hiding on tile count leaves the reader watching unchanged terrain."""
        script = view3d.SCRIPT
        decode = script.index("image.onload = function ()")
        assert script.index("hideLoading()", decode) < script.index(
            "image.src = mosaic.toDataURL", decode)

    def test_the_label_survives_reduced_motion(self):
        """The global reduced-motion rule stops the ring, so the text beside it is what
        carries the message."""
        assert "view3d-loading-text" in self._panel()
        assert "prefers-reduced-motion" in view3d.STYLE


class TestRendersWithTerrain:
    """The report was broken for a week and every test passed.

    `_trigger_note` and `_clearance_note` only run when there *is* terrain, and every
    other test in this file renders with `terrain=None` — so a `NameError` in the
    insolation sentence went unnoticed until a site rebuild crashed on it. Rendering the
    terrain path at least once is the cheap guard.
    """

    def _analysis(self, tmp_path):
        from tests.test_debrief import a_day

        return a_day(tmp_path, "terrain.igc",
                     [(300, 2.5), (300, 2.0), (300, 1.4), (300, 0.8)], glide=700)

    def _terrain(self, analysis):
        import numpy as np

        from tracklog_viewer.terrain import Terrain

        lat, lon = analysis.flight.lat, analysis.flight.lon
        pad = 0.02
        size = 48
        # A ridged grid, so slopes have a real aspect and the insolation sentence runs.
        rows = np.linspace(0, 1, size)
        grid = (np.sin(rows * 9)[:, None] * np.cos(rows * 7)[None, :]) * 600 + 1500
        return Terrain(
            west=float(lon.min()) - pad, east=float(lon.max()) + pad,
            south=float(lat.min()) - pad, north=float(lat.max()) + pad,
            elevations=grid,
        )

    def test_a_report_renders_with_terrain(self, tmp_path):
        analysis = self._analysis(tmp_path)
        html = render_html._flight_body(analysis, terrain=self._terrain(analysis))
        assert "<article" in html
        assert "view3d" in html

    def test_the_insolation_sentence_renders(self, tmp_path):
        """The exact line that crashed: it calls `geo.cardinal`, and `render_html` did
        not import `geo`."""
        analysis = self._analysis(tmp_path)
        note = render_html._trigger_note(analysis, self._terrain(analysis))
        assert isinstance(note, str)

    def test_the_clearance_sentence_renders(self, tmp_path):
        analysis = self._analysis(tmp_path)
        clearance = [500.0] * len(analysis.series)
        assert isinstance(render_html._clearance_note(clearance), str)
