"""The debrief: a verdict, and findings ranked by what they cost.

`docs/ux-review.md` diagnoses the report as an instrument panel — 191 numeric tokens in
one flight article and not one sentence saying whether the flight went well. This module
is the layer above the numbers. It computes nothing new; it ranks and phrases what
`analysis.py` and `metrics.py` already measured.

Four rules are enforced here, not left to the renderer:

* **A finding is a measurement plus a link, never an imperative.** Past tense, about the
  flight, no "should". The tool cannot see the sky, the gaggle, the airspace or the
  pilot's plan, so it states what happened and lets the pilot draw the conclusion. This is
  not politeness — one confident *"you should have stayed in that thermal"* that happens
  to be wrong undoes the credibility the rest of the report earned.
* **Every finding carries a cost, in metres or minutes.** A finding with no cost does not
  ship. That is what stops the list becoming twelve items of trivia — and it is why the
  day envelope and the concentration of gain, which are real measurements but not costs,
  go to the verdict strip rather than becoming cards.
* **A finding must not fire on data that cannot support it.** Every builder below returns
  `None` rather than a plausible number, and the gating lives in `metrics.py` where the
  measurement is.
* **Degrade, do not blank.** No meteo means the ceiling finding does not exist. Not an
  empty card.

Ranking is by `Cost.share` — the cost measured against the flight's *own* budget, so a
nine-minute gap ranks differently on a ninety-minute flight than on a six-hour one. A
constant would have to be argued about; this is the same "the day's own median rather
than a round number" habit the metrics use.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from . import metrics
from .analysis import Analysis

# Every threshold in the debrief, in one dict, deliberately.
#
# It is serialised into the page so `quicklook.py` reads these numbers instead of holding
# a second copy — a direct hit on the documented known gap, *"if the Python thresholds
# change, change them there too; there is no shared source"*. Cheap enough to be worth
# doing on the first finding rather than the tenth.
#
# **These values are provisional and the plan says why.** `docs/analysis-plan.md`:
# *"A metric that fires on most flights is not a finding, it is a constant. Thresholds
# come from the distribution over the archive, not from a round number that sounds
# right."* Calibrating them needs the 50-file archive, which is `--archive` (see
# `baseline.py`) and is not in this repository — `*.igc` is gitignored. Until then these
# are seeded from the three flights measured in `docs/analysis-plan.md` and are the first
# thing `--archive` should be pointed at.
THRESHOLDS = {
    # Fraction of circling time in climbs under half the day's best before it is worth
    # saying. Measured: 32% Rodella, 58% flatland, 56% tow day.
    "weak_climb_share": 0.45,
    # A gap this many times the day's own median is the expensive one.
    "gap_over_median": 2.0,
    "gap_minimum_seconds": 300,
    # First minute against the rest. Measured: 0.86 Rodella, 0.48 flatland, 0.99 tow day.
    "centring_ratio": 0.75,
    # Ground clearance under this, in metres, is a headline rather than a caption.
    "low_clearance": 100.0,
    # Share of the top altitude band's circling time before "the top band was slow" is
    # worth printing.
    "band_share": 0.20,
    "band_ratio": 0.75,
    # Ceiling use: below this fraction of the modelled cloudbase is worth a card.
    "ceiling_used": 0.85,
    # Track distance over scored distance.
    "detour_ratio": 2.0,
    # How close the triangle came to closing, as a fraction of its perimeter, before the
    # near miss is worth printing. `xc.MAX_CLOSING` is the rule; this is "nearly".
    "near_close": 0.35,
    # Minimum cost share before a finding is worth a card at all.
    "minimum_share": 0.02,
    "cards": 5,
}


def _num(value: float) -> str:
    """A metre count with a thin thousands gap: 3656 -> "3 656".

    A helper rather than `.replace(",", " ")` on the finished sentence, which is what this
    replaced: applied to the whole string it eats the sentence's own commas too, and the
    cards read "left at 2 176 m  620 m below the 2 796 m reached later". The separator has
    to be applied to the number, not to the prose around it.
    """
    return f"{value:,.0f}".replace(",", " ")


@dataclass
class Cost:
    """What a finding cost, and how big that is against this flight.

    `share` is what the ranking uses: minutes against airtime, or metres against the
    height the flight actually gained. Ranking on the raw number would put every metre
    finding above every minute finding.
    """

    value: float
    unit: str  # "min" or "m"
    share: float

    @property
    def label(self) -> str:
        if self.unit == "min":
            return f"{self.value:.0f} min"
        return f"{_num(self.value)} m"


@dataclass
class Finding:
    """One ranked observation about the flight."""

    id: str
    title: str  # the headline: what happened, in one line
    sentence: str  # the evidence, in one or two sentences
    cost: Cost
    at: str | None = None  # local clock time, for the card's footer
    cursor: int | None = None  # fix index, for "show me"
    confidence: float = 1.0
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**asdict(self), "cost": {**asdict(self.cost), "label": self.cost.label}}


@dataclass
class Verdict:
    """The flight in one line, plus the three numbers that carry it."""

    sentence: str
    headline: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Debrief:
    verdict: Verdict | None
    findings: list[Finding]
    suppressed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "findings": [f.to_dict() for f in self.findings],
            "suppressed": self.suppressed,
            "thresholds": THRESHOLDS,
        }


def _minutes(seconds: float, analysis: Analysis) -> Cost:
    airtime = analysis.summary.duration or 1
    return Cost(round(seconds / 60.0), "min", min(seconds / airtime, 1.0))


def _metres(value: float, analysis: Analysis) -> Cost:
    gained = analysis.summary.total_gain or 1
    return Cost(round(value), "m", min(abs(value) / gained, 1.0))


# ---------------------------------------------------------------------------
# The findings
# ---------------------------------------------------------------------------


def _best_climb_left(analysis: Analysis) -> Finding | None:
    """UX finding 1. Two measurements and no counterfactual.

    Deliberately *not* "you should have stayed": what the abandoned climb would have gone
    on to give is not in the data. What is in the data is where the climb was left, how
    far under the day's ceiling that was, and what the next one cost.
    """
    thermals = sorted(analysis.thermals, key=lambda s: s.start)
    if len(thermals) < 3:
        return None
    best = max(thermals, key=lambda s: s.average_climb)
    if best.average_climb <= 0:
        return None
    ceiling = max(s.finish_altitude for s in thermals)
    under = ceiling - best.finish_altitude
    if under < 50:
        return None

    index = thermals.index(best)
    if index + 1 >= len(thermals):
        return None
    following = thermals[index + 1]
    series = analysis.series
    gap = float(series.t[following.start] - series.t[best.stop - 1])
    if gap <= 0:
        return None

    return Finding(
        id="best-climb-left",
        title=f"Left the day's strongest climb {under:.0f} m under the day's best height",
        sentence=(
            f"Climb {index + 1} ran at {best.average_climb:+.2f} m/s and it was left at "
            f"{_num(best.finish_altitude)} m, {under:.0f} m below the {_num(ceiling)} m "
            f"reached later. The next climb took {gap / 60:.0f} min to find and averaged "
            f"{following.average_climb:+.2f} m/s."
        ),
        cost=_minutes(gap, analysis),
        at=best.finish_time,
        cursor=best.stop - 1,
        evidence={
            "climb": index + 1,
            "average_climb": best.average_climb,
            "finish_altitude": best.finish_altitude,
            "ceiling": ceiling,
            "next_climb": following.average_climb,
            "gap_seconds": int(gap),
        },
    )


def _expensive_gap(analysis: Analysis) -> Finding | None:
    """UX finding 2, with the day's own median as the comparison."""
    gaps = metrics.climb_gaps(analysis)
    if gaps is None:
        return None
    if gaps.longest < THRESHOLDS["gap_minimum_seconds"]:
        return None
    if gaps.longest < gaps.median * THRESHOLDS["gap_over_median"]:
        return None

    return Finding(
        id="expensive-gap",
        title=f"{gaps.longest / 60:.0f} min between climbs, against a median of {gaps.median / 60:.0f}",
        sentence=(
            f"The longest stretch without a climb started at {gaps.longest_at} and ran "
            f"{gaps.longest / 60:.0f} min, losing {_num(abs(gaps.longest_loss))} m. The "
            f"day's median gap was {gaps.median / 60:.0f} min."
        ),
        cost=_minutes(gaps.longest - gaps.median, analysis),
        at=gaps.longest_at,
        cursor=gaps.longest_index,
        evidence={
            "longest_seconds": gaps.longest,
            "median_seconds": gaps.median,
            "loss": gaps.longest_loss,
        },
    )


def _low_point(analysis: Analysis, clearance) -> Finding | None:
    """UX finding 3 — currently buried mid-paragraph in a caption under the 3D view.

    A pilot who scraped a ridge wants this as a headline. Refused without `--terrain`:
    height above sea level is not height above the ground, and on Rodella the lowest
    altitude of the flight is a ridge top.
    """
    if clearance is None:
        return None
    agl = np.asarray(clearance, dtype=float)
    if agl.size != len(analysis.series) or not np.isfinite(agl).any():
        return None

    index = int(np.nanargmin(agl))
    lowest = float(agl[index])
    median = float(np.nanmedian(agl))
    if lowest > THRESHOLDS["low_clearance"]:
        return None

    when = analysis.flight.local_time(index).strftime("%H:%M:%S")
    return Finding(
        id="low-point",
        title=f"Lowest ground clearance of the flight was {lowest:.0f} m",
        sentence=(
            f"At {when} the track passed {lowest:.0f} m above the terrain, against a "
            f"median of {_num(median)} m for the flight."
        ),
        cost=_metres(max(median - lowest, 0.0), analysis),
        at=when,
        cursor=index,
        evidence={"lowest": round(lowest), "median": round(median)},
    )


def _climb_selection(analysis: Analysis) -> Finding | None:
    """Tier 1. Time spent in the day's weaker half."""
    selection = metrics.climb_selection(analysis)
    if selection is None or selection.fraction < THRESHOLDS["weak_climb_share"]:
        return None

    # Link to the longest of the weak climbs rather than the weakest: it is the one that
    # actually spent the time the cost is measured in, so it is the one worth looking at.
    weak = [s for s in analysis.thermals if s.average_climb < selection.threshold]
    worst = max(weak, key=lambda s: s.duration) if weak else None

    return Finding(
        id="climb-selection",
        title=(
            f"{selection.weak_seconds / 60:.0f} min of circling was in the day's weaker climbs"
        ),
        sentence=(
            f"{selection.weak_seconds / 60:.0f} min of {selection.total_seconds / 60:.0f} min "
            f"circling was spent in {selection.weak_climbs} climbs under "
            f"{selection.threshold:+.2f} m/s, on a day that offered {selection.best:+.2f}."
        ),
        cost=_minutes(selection.weak_seconds, analysis),
        at=worst.start_time if worst else None,
        cursor=worst.start if worst else None,
        evidence={
            "weak_seconds": selection.weak_seconds,
            "total_seconds": selection.total_seconds,
            "threshold": selection.threshold,
            "best": selection.best,
        },
    )


def _centring(analysis: Analysis) -> Finding | None:
    """Tier 1. The first minute of a climb against the rest of it."""
    index = metrics.centring(analysis)
    if index is None or index.ratio > THRESHOLDS["centring_ratio"]:
        return None
    if index.cost_seconds < 60:
        return None

    return Finding(
        id="centring",
        title=f"The first minute of a climb averaged {index.ratio:.0%} of the rest of it",
        sentence=(
            f"Over {index.climbs} climbs the first minute averaged {index.first:+.2f} m/s "
            f"against {index.rest:+.2f} m/s for the remainder — about "
            f"{index.cost_seconds / 60:.0f} min of extra circling at the rate those same "
            f"climbs went on to give."
        ),
        cost=_minutes(index.cost_seconds, analysis),
        evidence={
            "ratio": index.ratio,
            "first": index.first,
            "rest": index.rest,
            "climbs": index.climbs,
        },
    )


def _working_band(analysis: Analysis) -> Finding | None:
    """Tier 1. Where in the column the lift actually was."""
    band = metrics.working_band(analysis)
    if band is None:
        return None
    total = sum(band.seconds) or 1
    top_share = band.seconds[2] / total
    if top_share < THRESHOLDS["band_share"]:
        return None
    strongest = max(band.climbs)
    if not strongest or band.climbs[2] / strongest > THRESHOLDS["band_ratio"]:
        return None

    height = band.edges[3] - band.edges[2]
    return Finding(
        id="working-band",
        title=(
            f"The top {_num(height)} m gave {band.climbs[2]:+.2f} m/s for "
            f"{band.seconds[2] / 60:.0f} min of circling"
        ),
        sentence=(
            f"Between {_num(band.edges[0])} m and {_num(band.edges[3])} m the climbs "
            f"averaged {band.climbs[0]:+.2f}, {band.climbs[1]:+.2f} and "
            f"{band.climbs[2]:+.2f} m/s by altitude third. The best band was the "
            f"{'lowest' if band.best == 0 else 'middle' if band.best == 1 else 'top'} "
            f"one."
        ),
        # The cost is the circling done in the weakest band, which is the time the shape
        # of this profile actually charged for.
        cost=_minutes(band.seconds[band.worst], analysis),
        evidence={"edges": list(band.edges), "climbs": list(band.climbs),
                  "seconds": list(band.seconds)},
    )


def _ceiling_used(analysis: Analysis, weather) -> Finding | None:
    """UX finding 7. Framing of numbers already on the page. Refused without `--meteo`."""
    use = metrics.ceiling_use(analysis, weather)
    if use is None or use.fraction >= THRESHOLDS["ceiling_used"]:
        return None

    return Finding(
        id="ceiling-used",
        title=f"Topped out at {use.fraction:.0%} of the modelled {use.source.replace('_', ' ')}",
        sentence=(
            f"The highest point of the flight was {_num(use.reached)} m against a modelled "
            f"{_num(use.ceiling)} m — {_num(use.ceiling - use.reached)} m of the column was "
            f"never used."
        ),
        cost=_metres(use.ceiling - use.reached, analysis),
        evidence={"reached": use.reached, "ceiling": use.ceiling,
                  "fraction": use.fraction, "source": use.source},
    )


def _other_slice(analysis: Analysis) -> Finding | None:
    """UX finding 8, corrected.

    The review says of `other`: *"That is 40 minutes, and it is the only slice with no
    explanation. Losses live exactly there."* Half right — it is unexplained, and on the
    reference flight it is **profitable**. So the card publishes the three parts and names
    the cost as the genuinely lossy two, never the whole slice.
    """
    slice_ = analysis.other
    if slice_ is None or slice_.seconds < 300:
        return None
    lossy = slice_.straight_sink + slice_.scratching
    if lossy < 300:
        return None

    net = slice_.net_altitude
    direction = "gained" if net > 0 else "lost"
    return Finding(
        id="other-slice",
        title=(
            f"{slice_.seconds / 60:.0f} min was neither climbing nor gliding, and it "
            f"{direction} {_num(abs(net))} m"
        ),
        sentence=(
            f"{slice_.straight_sink / 60:.0f} min of it was straight sink — the price of "
            f"the glide — {slice_.scratching / 60:.0f} min was turning without climbing, "
            f"and {slice_.rising / 60:.0f} min was rising air no phase counted, worth "
            f"{slice_.mean_climb:+.2f} m/s over the whole slice."
        ),
        cost=_minutes(lossy, analysis),
        evidence={
            "seconds": slice_.seconds,
            "straight_sink": slice_.straight_sink,
            "scratching": slice_.scratching,
            "rising": slice_.rising,
            "net_altitude": slice_.net_altitude,
        },
    )


def _close_that_wasnt(analysis: Analysis, route) -> Finding | None:
    """UX finding 6. Both numbers are already on the page; neither is framed as a cost."""
    from . import geo, xc

    if route is None or getattr(route, "closed", False):
        return None
    points = getattr(route, "points", None) or []
    if len(points) < 3:
        return None
    sides = getattr(route, "sides", None)
    if not sides:
        return None

    gap = float(geo.distance(points[0].lat, points[0].lon, points[-1].lat, points[-1].lon))
    perimeter = float(sum(sides))
    if perimeter <= 0 or gap / perimeter > THRESHOLDS["near_close"]:
        return None

    category = xc.classify(sides)
    multiplier = xc.MULTIPLIER.get(category, 1.0)
    return Finding(
        id="near-close",
        title=f"The triangle came within {gap / 1000:.1f} km of closing",
        sentence=(
            f"The route's finish was {gap / 1000:.1f} km from its start, against a "
            f"{perimeter / 1000:.1f} km perimeter. Closed, it would have scored as a "
            f"{category} triangle at ×{multiplier:.1f}."
        ),
        cost=_metres(gap, analysis),
        evidence={"gap": round(gap), "perimeter": round(perimeter),
                  "category": category, "multiplier": multiplier},
    )


def _detour(analysis: Analysis, route) -> Finding | None:
    """Tier 1. Both numbers are on the page and neither is framed as a cost."""
    ratio = metrics.detour(analysis, route)
    if ratio is None or ratio.ratio < THRESHOLDS["detour_ratio"]:
        return None

    extra = (ratio.track_km - ratio.scored_km) * 1000.0
    return Finding(
        id="detour",
        title=f"{ratio.track_km:.0f} km flown to score {ratio.scored_km:.2f} km",
        sentence=(
            f"The track is {ratio.ratio:.2f}× the scored route — every scored kilometre "
            f"cost {ratio.ratio:.2f} km of flying."
        ),
        cost=_metres(extra, analysis),
        evidence={"ratio": ratio.ratio, "track_km": ratio.track_km,
                  "scored_km": ratio.scored_km},
    )


def _plan_departure(analysis: Analysis, flight_plan) -> Finding | None:
    """The decision point: where the flight left the line the pilot drew.

    This is the finding the whole plan feature exists for, and it is the clearest example
    of what a plan buys: with no plan, "the flight turned early" is advice from a blind
    coach. With one, it is two measurements and a link.
    """
    from . import plan as plan_module

    followed = plan_module.adherence(analysis, flight_plan)
    if followed is None or followed.departed_index is None:
        return None

    series = analysis.series
    height = float(series.alt[followed.departed_index])
    remaining = (
        f" — {followed.departed_distance / 1000:.0f} km short of the planned goal"
        if followed.departed_distance
        else ""
    )
    caveat = (
        " This plan carries no timestamp, so it is recorded as reconstructed intent."
        if followed.reconstructed
        else ""
    )
    return Finding(
        id="plan-departure",
        title=(
            f"The track left the planned line at {followed.departed_at}"
            f"{remaining}"
        ),
        sentence=(
            f"The first sustained departure beyond "
            f"{plan_module.DEPARTURE_METRES / 1000:.0f} km from the plan was at "
            f"{followed.departed_at}, from {_num(height)} m. Median distance from the "
            f"planned line over the flight was {_num(followed.median_off)} m.{caveat}"
        ),
        # The cost is the distance the plan still had to run when the track left it. That
        # is a measurement of the plan, not a claim that the distance was achievable.
        cost=_metres(followed.departed_distance or followed.max_off, analysis),
        at=followed.departed_at,
        cursor=followed.departed_index,
        confidence=0.6 if followed.reconstructed else 1.0,
        evidence={
            "median_off": followed.median_off,
            "max_off": followed.max_off,
            "reconstructed": followed.reconstructed,
        },
    )


def _plan_turnpoints(analysis: Analysis, flight_plan) -> Finding | None:
    """Turnpoint accounting against the declared task."""
    from . import plan as plan_module

    marks = plan_module.turnpoints(analysis, flight_plan)
    if marks is None or marks.reached >= marks.total:
        return None
    missed = marks.total - marks.reached

    return Finding(
        id="plan-turnpoints",
        title=f"{marks.reached} of {marks.total} planned turnpoints were reached",
        sentence=(
            f"The first not reached was {charts_escape(marks.first_missed)}."
            if marks.first_missed
            else f"{missed} planned turnpoints were not reached."
        ),
        # One turnpoint short of a task is a different flight from five short, and the
        # honest scale here is the share of the task that went unflown.
        cost=Cost(missed, "m", min(missed / max(marks.total, 1), 1.0)),
        confidence=0.6 if marks.reconstructed else 1.0,
        evidence={"reached": marks.reached, "total": marks.total,
                  "first_missed": marks.first_missed},
    )


def charts_escape(value):
    """Local escape so this module keeps its "no renderer" rule.

    `debrief.py` must not import a renderer, and a turnpoint name comes from a file the
    tool did not write. Escaping here keeps the sentence safe wherever it is rendered.
    """
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# The verdict strip
# ---------------------------------------------------------------------------


def _verdict(analysis: Analysis, route, weather) -> Verdict | None:
    """The flight in one line: shape, how the day went, and how it ended.

    Everything here is a measurement. The only judgement is which measurements are worth
    one line, and the day envelope earns its place precisely because it has no cost and so
    cannot be a card.
    """
    summary = analysis.summary
    thermals = analysis.thermals
    if not summary.duration:
        return None

    hours, minutes = divmod(summary.duration // 60, 60)
    shape = f"{hours} h {minutes:02d} m" if hours else f"{minutes} m"

    kind = "flight"
    if route is not None and getattr(route, "distance", 0):
        from . import xc

        sides = getattr(route, "sides", None)
        category = xc.classify(sides) if sides else "open"
        kind = f"{category} triangle" if category in ("fai", "flat") else "cross-country flight"
    parts = [f"A {shape} {kind}."]

    envelope = metrics.day_envelope(analysis)
    if envelope is not None and envelope.slope < -0.05:
        parts.append(
            f"The day decayed {abs(envelope.slope):.2f} m/s per hour, from "
            f"{envelope.first:+.2f} to {envelope.last:+.2f}."
        )
    elif envelope is not None and envelope.slope > 0.05:
        parts.append(
            f"The day built {envelope.slope:.2f} m/s per hour, from "
            f"{envelope.first:+.2f} to {envelope.last:+.2f}."
        )

    share = metrics.concentration(analysis)
    if share is not None and share.share >= 0.6:
        parts.append(
            f"{share.share:.0%} of the height came from {share.top} of "
            f"{share.climbs} climbs."
        )

    headline: list[dict] = []
    if route is not None and getattr(route, "distance", 0):
        headline.append({"value": f"{route.distance / 1000:.2f} km", "label": "scored",
                         "key": "scored_km"})
    if thermals:
        mean = float(np.mean([s.average_climb for s in thermals]))
        headline.append(
            {"value": f"{mean:+.2f} m/s",
             "label": f"mean of {len(thermals)} climbs",
             "key": "mean_climb"}
        )
    use = metrics.ceiling_use(analysis, weather)
    if use is not None:
        headline.append({"value": f"{use.fraction:.0%}", "label": "of cloudbase",
                         "key": "ceiling_used"})
    else:
        headline.append(
            {"value": f"{_num(summary.max_altitude)} m",
             "label": "highest"}
        )

    return Verdict(sentence=" ".join(parts), headline=headline)


def build(
    analysis: Analysis,
    *,
    route=None,
    weather=None,
    clearance=None,
    flight_plan=None,
    limit: int | None = None,
) -> Debrief:
    """Rank the findings this flight's data supports.

    `route`, `weather` and `clearance` are optional by design: absent, the findings that
    rest on them do not exist. They are named in `suppressed` so the renderer can say
    *why* the debrief is short — which is a different thing from an empty card.
    """
    builders = [
        ("best-climb-left", lambda: _best_climb_left(analysis)),
        ("expensive-gap", lambda: _expensive_gap(analysis)),
        ("low-point", lambda: _low_point(analysis, clearance)),
        ("climb-selection", lambda: _climb_selection(analysis)),
        ("centring", lambda: _centring(analysis)),
        ("working-band", lambda: _working_band(analysis)),
        ("ceiling-used", lambda: _ceiling_used(analysis, weather)),
        ("other-slice", lambda: _other_slice(analysis)),
        ("near-close", lambda: _close_that_wasnt(analysis, route)),
        ("detour", lambda: _detour(analysis, route)),
        # Plan findings fire only when there is a plan, which is the whole point: no
        # plan means today's debrief, unchanged.
        ("plan-departure", lambda: _plan_departure(analysis, flight_plan)),
        ("plan-turnpoints", lambda: _plan_turnpoints(analysis, flight_plan)),
    ]

    found: list[Finding] = []
    for _, builder in builders:
        finding = builder()
        if finding is not None and finding.cost.share >= THRESHOLDS["minimum_share"]:
            found.append(finding)

    found.sort(key=lambda f: f.cost.share, reverse=True)
    cards = limit if limit is not None else THRESHOLDS["cards"]

    suppressed = []
    if clearance is None:
        suppressed.append("terrain")
    if weather is None:
        suppressed.append("meteo")
    if route is None:
        suppressed.append("route")
    if analysis.thermals and any(s.turns is None for s in analysis.thermals):
        suppressed.append("sampling")
    if flight_plan is None:
        suppressed.append("plan")

    return Debrief(
        verdict=_verdict(analysis, route, weather),
        findings=found[:cards],
        suppressed=suppressed,
    )
