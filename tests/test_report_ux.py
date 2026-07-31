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

    GLYPH_ACTS = ("rotate-left", "rotate-right", "tilt-up", "tilt-down",
                  "zoom-in", "zoom-out")

    def _panel(self):
        return view3d.panel({"bounds": {}}, "uid")

    def test_every_control_carries_an_aria_label(self):
        html = self._panel()
        for act in self.GLYPH_ACTS + ("basemap", "exaggerate", "fullscreen", "reset"):
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
