"""The light/dark switch, and the tokens behind it.

Every page carries the same button in the same strip, and it has to do four things: flip
the theme, remember the choice, apply it *before the first paint* on the next visit, and
get the canvases repainted — a canvas keeps the tokens it was drawn with, so a page whose
charts are canvas stays half in the old theme until something asks it to draw again.

The last one is why this file exists rather than a line in another. It broke on exactly
one page — the report — because `window.__view3dAll` is an object keyed by canvas id and
the handler called `Array.forEach` on it. A listener's exception never reaches the
`click()` that dispatched it, so the button looked like it worked: the theme changed, and
the 3D views quietly kept the old sky.
"""

import re


import parainsights_common as common
from tests.browser import needs_chrome


class TestTheTokensAreSharedAndScopedBothWays:
    def test_dark_answers_the_system_and_the_button(self):
        """The media query is the operating system; `[data-theme]` is the reader. Either
        can win, so a light stamp has to beat OS-dark — which is what the zero-specificity
        `:where(:not(...))` around the media block is for."""
        assert "@media (prefers-color-scheme: dark)" in common.TOKENS
        assert ':root:where(:not([data-theme="light"]))' in common.TOKENS
        assert ':root[data-theme="dark"]' in common.TOKENS

    def test_the_three_tool_shells_no_longer_carry_their_own_copy(self):
        """`meteo`, `airspaces` and `planner` each had an identical token block — three
        chances for the site to disagree with itself about what grey means."""
        from airspaces import cli as airspaces_cli
        from meteo import cli as meteo_cli
        from planner import cli as planner_cli

        # The planner's is a redirect now, and still themed: it may be on screen a frame.
        for module in (meteo_cli, airspaces_cli, planner_cli):
            source = __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
            assert "common.TOKENS" in source, module.__name__
            assert "--paper:#fff" not in source, (
                f"{module.__name__} still carries its own copy of the tokens")

    def test_the_theme_is_applied_before_the_page_is_painted(self):
        """Reading it after the first paint is a white flash on a dark page, every open.
        So the boot script goes in the head, and it is three lines for that reason."""
        from meteo import cli as meteo_cli

        source = __import__("pathlib").Path(meteo_cli.__file__).read_text(encoding="utf-8")
        head = source[:source.index("<style>")]
        assert "common.THEME_BOOT" in head
        assert "localStorage" in common.THEME_BOOT


class TestTheButton:
    def test_it_is_in_the_strip_on_every_page(self):
        for key, _label, _where in common.PAGES:
            assert "theme-toggle" in common.nav(key, depth=1)

    def test_it_says_what_it_is_for_without_a_visible_label(self):
        button = common.theme_button()
        assert 'aria-label="Switch between the light and dark theme"' in button
        assert 'aria-pressed' in button

    def test_the_report_has_one_even_with_nothing_to_switch_between(self):
        """A report of one flight with no airspace view still gets read at night."""
        from tracklog_viewer import render_html

        assert "theme-toggle" in render_html._view_nav([])


class TestTheOrderIsTheSameEverywhere:
    def test_the_site_strip_is_the_days_own_order(self):
        assert [key for key, _, _ in common.PAGES] == [
            "meteo", "airspace", "flights"]

    def test_the_report_follows_it_too(self):
        """The report listed its in-document views first and its links after, so it read
        *Flights, Airspace, Meteo, Planner* while every other page read the other way
        round. Which entries are buttons is an implementation detail of one document."""
        from tracklog_viewer import render_html

        extra = render_html.Extra(uid="airspace", label="Planner", body="", style="",
                                  script="")
        nav = render_html._view_nav([extra])
        labels = [re.sub(r"<[^>]+>", "", chunk).strip()
                  for chunk in re.findall(r"<(?:a|button)[^>]*>[^<]*</(?:a|button)>", nav)]
        labels = [label for label in labels if label]
        assert labels == ["Meteo", "Planner", "Flights"]


@needs_chrome
def test_the_switch_flips_remembers_and_relabels():
    from tests.test_meteo_view import _probe_page

    answer = _probe_page("""
    var root = document.documentElement, button = document.querySelector('.theme-toggle');
    var errors = [];
    window.addEventListener('error', function (e) { errors.push(String(e.message)); });
    function dark() { return getComputedStyle(root).colorScheme.indexOf('dark') >= 0; }
    var was = dark();
    button.click();
    var flipped = dark();
    var stored = localStorage.getItem('parainsights.theme');
    var glyph = button.querySelector('.theme-glyph').textContent;
    button.click();
    return { was: was, flipped: flipped, back: dark(), stored: stored,
             glyph: glyph, pressed: button.getAttribute('aria-pressed'),
             errors: errors };
    """)
    assert answer["flipped"] != answer["was"], "the button did not change the theme"
    assert answer["back"] == answer["was"], "a second press did not switch back"
    assert answer["stored"] in ("dark", "light")
    assert answer["errors"] == [], f"the handler threw: {answer['errors']}"
    # The glyph says what the next press gives you, which is the convention everywhere.
    assert answer["glyph"] in ("☀", "☽")
