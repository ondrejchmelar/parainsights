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
    # Below this AGL the flight is on the ground rather than near it. The lowest
    # clearance of *any* flight is its own launch or landing, so the search has to start
    # after the first and end before the last.
    "ground_margin": 100.0,
    # Share of the top altitude band's circling time before "the top band was slow" is
    # worth printing.
    "band_share": 0.20,
    "band_ratio": 0.75,
    # Ceiling use: below this fraction of the modelled cloudbase is worth a card.
    "ceiling_used": 0.85,
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
        title=f"You left the day's best climb {under:.0f} m below the height you later reached",
        sentence=(
            f"Climb {index + 1} was running at {best.average_climb:+.2f} m/s when you left "
            f"it at {_num(best.finish_altitude)} m. Later in the flight you were at "
            f"{_num(ceiling)} m. The next climb took {gap / 60:.0f} min to find and gave "
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
        title=f"Your longest search for a climb ran {gaps.longest / 60:.0f} min",
        sentence=(
            f"It began at {gaps.longest_at} and cost {_num(abs(gaps.longest_loss))} m of "
            f"height before you found the next one. Most gaps that day were about "
            f"{gaps.median / 60:.0f} min."
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

    A pilot who scraped a ridge wants this as a headline. Two things had to be right
    before it could be one, and real flights found both.

    **The launch and the landing are excluded.** The lowest ground clearance of any flight
    is the ground it started and finished on: on the reference flight the minimum is 1 m
    at t=25 s, which is the takeoff, while the lowest point actually *flown* is 441 m.
    Reporting a launch as a scrape is exactly the confidently wrong sentence the debrief
    cannot afford.

    **A negative clearance is not printed as a number.** It means the track is below the
    terrain *model*, not below the terrain. Measured on a 400 km flight: the DEM is about
    1.2 km per cell over that box, which averages a valley floor together with the ridges
    beside it, and a multi-flight document halves the budget per flight again — the same
    flight reads -36 m alone and -227 m in a shared document. The moment is real; the
    number is not, and the card says which.

    Refused entirely without `--terrain`: height above sea level is not height above the
    ground, and on an alpine flight the lowest altitude is a ridge top.
    """
    if clearance is None:
        return None
    agl = np.asarray(clearance, dtype=float)
    if agl.size != len(analysis.series) or not np.isfinite(agl).any():
        return None

    # The airborne window: from the first time the flight is properly off the ground to
    # the last, so neither end of the track can win by being on it.
    window = metrics.airborne_window(agl, THRESHOLDS["ground_margin"])
    if window is None:
        return None
    lo, hi = window

    index = lo + int(np.nanargmin(agl[lo:hi]))
    lowest = float(agl[index])
    median = float(np.nanmedian(agl[lo:hi]))
    if lowest > THRESHOLDS["low_clearance"]:
        return None

    # A negative clearance is not a low save, it is the DEM losing an argument with the
    # GPS, so there is no card at all. Printing one that explains why its own headline
    # number is wrong was worse than saying nothing: the reader met "the elevation model
    # puts you underground at 15:35:38" at the top of a ranked list of things the flight
    # did, and the disclaimer underneath could not undo the framing. The grid is about a
    # kilometre per cell over a big flight — enough to average a valley floor in with the
    # ridges beside it — which is a fact about the model, not about the day.
    if lowest < 0:
        return None

    when = analysis.flight.local_time(index).strftime("%H:%M:%S")
    return Finding(
        id="low-point",
        title=f"You came within {lowest:.0f} m of the ground",
        sentence=(
            f"That was at {when}. For most of the flight you had about {_num(median)} m "
            f"underneath you. Launch and landing are left out of this, or they would win "
            f"every time."
        ),
        cost=_metres(max(median - lowest, 0.0), analysis),
        at=when,
        cursor=index,
        evidence={"lowest": round(lowest), "median": round(median),
                  "from": lo, "to": hi},
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
            f"You spent {selection.weak_seconds / 60:.0f} of your "
            f"{selection.total_seconds / 60:.0f} min circling in the day's weaker climbs"
        ),
        sentence=(
            f"{selection.weak_climbs} of your climbs averaged under "
            f"{selection.threshold:+.2f} m/s, on a day whose best gave "
            f"{selection.best:+.2f}."
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
        title=f"Your first minute in a climb was worth {index.ratio:.0%} of the rest of it",
        sentence=(
            f"Across {index.climbs} climbs the opening minute averaged "
            f"{index.first:+.2f} m/s against {index.rest:+.2f} once you had settled in. "
            f"That is roughly {index.cost_seconds / 60:.0f} min of extra circling at the "
            f"rate those same climbs went on to give."
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
    # Every third has to be sampled, not just the top one. `best` is an argmax over three
    # mean climb rates, and a third holding a minute of circling produces a mean as
    # confidently as one holding twenty — so a band the flight barely touched could be
    # declared the best lift of the day. The guard used to read `band.seconds[2]` alone,
    # from when this finding only ever said "the top band was slow"; once it started
    # naming a winner it needed to hold for whichever third won.
    if min(band.seconds) / total < THRESHOLDS["band_share"]:
        return None
    strongest = max(band.climbs)
    if not strongest or band.climbs[2] / strongest > THRESHOLDS["band_ratio"]:
        return None

    height = band.edges[3] - band.edges[2]
    return Finding(
        id="working-band",
        title=(
            f"The lift was best "
            f"{'down low' if band.best == 0 else 'in the middle of the band' if band.best == 1 else 'up high'}"
        ),
        # Each third's circling time is quoted beside its climb rate, because a mean climb
        # rate is only as good as the minutes under it and the reader cannot otherwise
        # tell which of the three is worth believing.
        sentence=(
            f"Split into thirds between {_num(band.edges[0])} m and "
            f"{_num(band.edges[3])} m, your climbs averaged {band.climbs[0]:+.2f}, "
            f"{band.climbs[1]:+.2f} and {band.climbs[2]:+.2f} m/s, over "
            f"{band.seconds[0] / 60:.0f}, {band.seconds[1] / 60:.0f} and "
            f"{band.seconds[2] / 60:.0f} minutes of circling. The top "
            f"{_num(height)} m gave {band.climbs[2]:+.2f}."
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
        title=f"You used {use.fraction:.0%} of the height the day was offering",
        sentence=(
            f"Your highest point was {_num(use.reached)} m against a modelled "
            f"{use.source.replace('_', ' ')} of {_num(use.ceiling)} m, so "
            f"{_num(use.ceiling - use.reached)} m of the column went unused."
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
            f"{slice_.seconds / 60:.0f} min counted as neither a climb nor a glide, "
            f"and you {direction} {_num(abs(net))} m in it"
        ),
        sentence=(
            f"{slice_.straight_sink / 60:.0f} min of that was straight sink, which is "
            f"what a glide costs; {slice_.scratching / 60:.0f} min was turning without "
            f"climbing; and {slice_.rising / 60:.0f} min was rising air that no phase "
            f"counted. Over the whole stretch it worked out at "
            f"{slice_.mean_climb:+.2f} m/s."
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
    # Same rule as the verdict, for the same reason: only a route from `triangle()` has
    # sides that are a perimeter. `optimise()`'s route is a four-leg path, and asking
    # what multiplier it would have earned compares two different quantities.
    if getattr(route, "kind", "") not in ("fai_triangle", "flat_triangle"):
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
        title=f"You finished {gap / 1000:.1f} km from closing the triangle",
        sentence=(
            f"The route came back to within {gap / 1000:.1f} km of where it started, on a "
            f"{perimeter / 1000:.1f} km perimeter. Closed, it would have scored as a "
            f"{'an FAI' if category == 'fai' else 'a flat'} triangle, at "
            f"×{multiplier:.1f} instead of ×1.0."
        ),
        cost=_metres(gap, analysis),
        evidence={"gap": round(gap), "perimeter": round(perimeter),
                  "category": category, "multiplier": multiplier},
    )


# There is deliberately no detour card. "You flew 121 km to score 48.64 km" is a
# restatement of how XContest scores a flight, not something this flight did: a scored
# route is three turnpoints through a track that also had to climb, and the ratio between
# the two is near-constant for the discipline. Charging the difference as a cost in metres
# made a rule of the sport read as a mistake the pilot made. `metrics.detour` stays —
# `baseline.py` keeps the ratio per flight, where a percentile across the archive can say
# something a single flight's ratio cannot.


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
        # `route.shape`, not `xc.classify(route.sides)`. Only a route that came out of
        # `triangle()` may claim a triangle category, and `shape` is where that rule
        # lives. Classifying the sides directly called a 64 km open-distance flight a
        # "flat triangle" in the verdict while the tab three centimetres above it said
        # OPEN DISTANCE — the same mistake the optimiser notes warn about.
        category = getattr(route, "shape", "open")
        kind = (f"{'FAI' if category == 'fai' else category} triangle"
                if category in ("fai", "flat") else "cross-country flight")
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
