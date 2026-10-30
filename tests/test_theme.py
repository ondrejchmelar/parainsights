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
    var glyph = button.querySelector('.theme-glyph').innerHTML;
    var title = button.title;
    button.click();
    return { was: was, flipped: flipped, back: dark(), stored: stored,
             glyph: glyph, title: title, pressed: button.getAttribute('aria-pressed'),
             errors: errors };
    """)
    assert answer["flipped"] != answer["was"], "the button did not change the theme"
    assert answer["back"] == answer["was"], "a second press did not switch back"
    assert answer["stored"] in ("dark", "light")
    assert answer["errors"] == [], f"the handler threw: {answer['errors']}"
    # The icon says what the next press gives you, which is the convention everywhere:
    # the site's stroked sun or moon (`common.ICONS`), and the title says it in words.
    assert "svg" in answer["glyph"]  # escaped by the DOM dump the probe reads
    assert answer["title"] in ("Switch to the light theme", "Switch to the dark theme")


class TestTheWelcome:
    def test_every_page_carries_it_with_its_own_card_marked(self):
        from airspaces import cli as airspaces_cli
        from meteo import cli as meteo_cli
        from tracklog_viewer import render_html

        for module, key in ((meteo_cli, "meteo"), (airspaces_cli, "airspace"),
                            (render_html, "flights")):
            source = __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
            assert f'common.welcome("{key}")' in source, module.__name__
        page = common.welcome("airspace")
        assert page.count('<li class="w-card') == 3
        assert page.count("is-here") == 1 and "You are here" in page
        # The other two link on, relative to a page one level down.
        assert 'href="../meteo/"' in page and 'href="../flights/"' in page
        assert 'href="../planner/"' not in page

    def test_it_opens_only_on_the_published_site(self):
        """A page built and opened locally, and every browser test, opens onto itself."""
        assert f"'{common.SITE_HOST}'" in common.THEME_SCRIPT
        assert "__SITE_HOST__" not in common.THEME_SCRIPT


@needs_chrome
def test_the_welcome_shows_once_and_is_remembered():
    from tests.test_meteo_view import _probe_page

    answer = _probe_page("""
    localStorage.removeItem(window.__welcome.key);
    var dialog = document.getElementById('welcome');
    var closedAtLoad = !dialog.open;
    var opened = window.__welcome.maybe(true);
    var open = dialog.open;
    var locked = getComputedStyle(document.documentElement).overflowY;
    // The dialog's close event is queued, not dispatched inside click(), so the answer
    // waits for it: a 50 ms timer lost the race on a loaded CI runner (October 2026).
    return new Promise(function (done) {
      function answer() {
        done({ locked: locked, unlocked: getComputedStyle(document.documentElement).overflowY,
             closedAtLoad: closedAtLoad, opened: opened, open: open, after: dialog.open,
               stored: localStorage.getItem(window.__welcome.key),
               again: window.__welcome.maybe(true) });
      }
      dialog.addEventListener('close', function () { setTimeout(answer, 0); }, { once: true });
      setTimeout(answer, 5000);
      dialog.querySelector('.btn.primary').click();
    });
    """)
    assert answer["closedAtLoad"], "the welcome opened on a page off the published site"
    assert answer["opened"] and answer["open"]
    assert not answer["after"], "Got it did not close it"
    assert answer["stored"] == "seen"
    # A wheel or swipe past the dialog's end scrolled the page behind it.
    assert answer["locked"] == "hidden" and answer["unlocked"] != "hidden"
    assert answer["again"] is False, "it opened a second time"


class TestTheTabIcon:
    def test_every_page_carries_it_ahead_of_the_boot_script(self):
        """`THEME_BOOT` finds the icon by its id, so it has to be in the head first."""
        from airspaces import cli as airspaces_cli
        from meteo import cli as meteo_cli
        from tracklog_viewer import render_html

        for module in (meteo_cli, airspaces_cli, render_html):
            source = __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
            assert "{common.FAVICON}\n<script>{common.THEME_BOOT}" in source, module.__name__
        assert common.FAVICON in common.root_redirect()

    def test_it_has_a_light_and_a_dark_tile(self):
        assert common.FAVICON_LIGHT != common.FAVICON_DARK
        for uri in (common.FAVICON_LIGHT, common.FAVICON_DARK):
            assert uri.startswith("data:image/svg+xml,")
            assert "#" not in uri, "an unescaped # ends a data URI"
        assert 'id="favicon"' in common.FAVICON
        assert "favicon" in common.THEME_BOOT
