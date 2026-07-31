"""The report's measured UX defects, pinned so they cannot come back.

`docs/ux-review.md` phase 0: three defects that are independent of everything else and
were measured in headless Chrome at a true 390 x 844 viewport rather than estimated.

These are static assertions over the generated CSS and markup rather than browser probes,
deliberately. A regression here is someone typing `font-size: 10.5px` or dropping an
`aria-label`, and a string test catches that in the fast job that runs everywhere — the
browser job is `allow_failure: true` and covers only the two view3d suites.
"""

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
    """Phase 3: the document held three flights and never put them side by side.

    Two different comparisons, answering two different questions: the other flights in
    *this document*, and the pilot's own archive across time. Both are omitted rather
    than faked when there is nothing to compare against.
    """

    def test_a_lone_flight_gets_no_delta(self):
        """Ranking a flight against itself is worse than silence."""
        assert render_html._peer_delta(1.5, [], "climb") == ""
        assert render_html._peer_delta(None, [1.0, 2.0], "climb") == ""

    def test_the_leading_flight_is_named_as_the_best(self):
        """The leader used to read as trailing the runner-up by its own margin, because
        the test was `value == max(others)` rather than `value >= max(others)`."""
        html = render_html._peer_delta(2.0, [1.0, 1.5], "climb", unit=" m/s")
        assert "best of 3 here" in html
        assert "off the best" not in html

    def test_a_trailing_flight_reports_its_gap(self):
        html = render_html._peer_delta(1.0, [1.5, 2.0], "climb", unit=" m/s")
        assert "off the best of 3" in html
        assert "1.00" in html

    def test_a_lower_is_better_metric_inverts(self):
        html = render_html._peer_delta(1.0, [1.5, 2.0], "gap", higher_is_better=False)
        assert "best of 3 here" in html

    def test_a_cold_archive_says_nothing(self, tmp_path):
        from tests.test_debrief import a_day
        from tracklog_viewer import baseline

        analysis = a_day(tmp_path, "cold.igc",
                         [(300, 2.5), (300, 0.4), (300, 0.4), (300, 0.4), (300, 0.5)],
                         glide=700)
        html = render_html._flight_body(analysis, archive=baseline.Baseline([]))
        assert "verdict-rank" not in html

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
