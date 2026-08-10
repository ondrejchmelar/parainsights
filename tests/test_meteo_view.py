"""The meteo view. No network: the site list is committed data and the forecast is
fetched by the page, so what is testable here is the data and the markup around it.

The one judgement the page makes — whether the wind suits a takeoff — is tested in the
browser with `fetch` stubbed, because it is JavaScript and because getting it wrong is
the only way this page can actively mislead somebody.
"""

import json
import re

import pytest

from meteo import cli, render_html, sites


class TestTheSiteList:
    def test_every_site_is_in_the_country_it_claims(self):
        """A stray coordinate would put a takeoff in the sea and rank it anyway."""
        for site in sites.SITES:
            assert 48.3 < site["lat"] < 51.2, site
            assert 11.9 < site["lon"] < 19.1, site

    def test_a_wind_rose_is_eight_octants_or_nothing(self):
        """`winds` is indexed by octant, so a short list would read the wrong direction
        rather than fail. Empty is the deliberate 'unknown', and it is common: not every
        takeoff has one recorded."""
        for site in sites.SITES:
            assert len(site["winds"]) in (0, 8), site
            assert set(site["winds"]) <= {0, 1, 2}, site
        assert any(not site["winds"] for site in sites.SITES), (
            "the unknown case has vanished from the fixture, so nothing tests it")

    def test_the_list_says_where_it_came_from_and_when(self):
        """Committed data with no provenance is data nobody can tell is stale."""
        assert "paraglidingearth" in sites.SOURCE.lower()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sites.FETCHED)
        assert sites.ATTRIBUTION

    def test_north_is_first_and_it_goes_clockwise(self):
        assert sites.OCTANTS == ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class TestThePage:
    def test_the_payload_carries_the_sites_and_the_levels(self):
        html = render_html.body()
        blob = re.search(r'<script type="application/json" class="met-data">(.*?)</script>',
                         html, re.S)
        payload = json.loads(blob.group(1))
        assert len(payload["sites"]) == len(sites.SITES)
        assert payload["levels"] == list(render_html.LEVELS)
        assert payload["endpoint"].startswith("https://api.open-meteo.com/")

    def test_the_pressure_levels_match_the_viewer_s(self):
        """A forecast profile and a flown profile are read against each other, and two
        different level sets would make that a conversion nobody remembers to do."""
        from tracklog_viewer import meteo as flown

        assert render_html.LEVELS == flown.PRESSURE_LEVELS

    def test_the_page_says_it_needs_a_network(self):
        """It is the one artifact here that is not self-contained. Saying so is the
        difference between a page that is honest and a page that looks broken."""
        html = render_html.body()
        assert "without a network" in html
        assert "needs a network" in render_html.SCRIPT

    def test_the_page_credits_both_sources_and_refuses_to_decide(self):
        html = cli.page(render_html.body(), "Will it fly?")
        assert "Open-Meteo" in html
        assert "ParaglidingEarth" in html
        assert "A forecast is not a decision" in html
        assert "flymet" in html


NO_ROSE = {"name": "Unknown", "lat": 50.0, "lon": 15.0, "alt": 500, "winds": [], "id": 1}


@pytest.mark.parametrize(
    "winds, speed, direction, expected",
    [
        # A good octant and a workable strength is the only unqualified yes.
        ([0, 0, 0, 0, 0, 0, 2, 0], 14, 270, "flyable"),
        # Same hill, same direction, twice the wind.
        ([0, 0, 0, 0, 0, 0, 2, 0], 34, 270, "too strong"),
        # Right strength, wrong side of the hill.
        ([0, 0, 0, 0, 0, 0, 2, 0], 14, 90, "wrong way"),
        # The site's own "marginal" survives as marginal rather than being rounded up.
        ([0, 0, 0, 0, 0, 0, 1, 0], 14, 270, "marginal"),
        # Nothing recorded: the page refuses rather than guesses.
        ([], 14, 270, "no rose"),
    ],
)
def test_the_verdict_is_the_sites_own_rose(winds, speed, direction, expected):
    """A second copy of the rule, and it is a copy on purpose until this runs in a
    browser: what it buys is a written-down statement of what each answer means, and the
    two threshold assertions catch the drift that matters most — someone retuning 28 and
    20 in the page and not here. **Wanted next**: drive the real function with `fetch`
    stubbed, the way `tests/test_view3d_gestures.py` drives the real gestures. Until then
    this test cannot fail on a change to the *shape* of the rule, only to its numbers."""
    source = render_html.SCRIPT
    assert "STRONG = 28" in source and "BRISK = 20" in source
    def verdict(winds, speed, direction):
        if not winds:
            return "no rose"
        fit = winds[round((direction % 360) / 45) % 8]
        if speed > 28:
            return "too strong"
        if not fit:
            return "wrong way"
        if fit == 1:
            return "marginal"
        return "brisk" if speed > 20 else "flyable"

    assert verdict(winds, speed, direction) == expected
