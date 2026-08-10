"""When the aerodrome is open, from the VFR manual's *Provozní doba*.

The okruh is the one layer here that is genuinely time-varying. An ATZ is not: the AIP
makes it class G airspace of fixed dimensions, permanently, and what follows the
aerodrome's operating hours is the AFIS *service* and the traffic in the circuit. So the
question this module answers is "is anybody flying that circuit", and the answer is the
operating-hours line every VFR manual page carries.

**It parses for all 156 fields, and it splits along the worst possible line.** All 82
aerodromes and all 74 SLZ strips publish the field; what it says does not:

| | fields | a clock window |
|---|---|---|
| publication A, ICAO aerodromes | 82 | 66, of which 61 give season + days + hours |
| publication B, SLZ strips | 74 | **0** — every one is "Year-round", "according to the operator's needs" |

The schedule therefore exists exactly where the ATZ exists, and is missing exactly where
there is *only* an okruh — the 74 reconstructed ones marked `est`, which is the layer
least entitled to be believed and the one that can never be dimmed.

**And the published window is the paraglider's own day.** The dominant form, 61 of 82, is
`15 APR - 15 OCT SAT, SUN, HOL 0700-1400`. Times are UTC — LKSB writes it out, and the
two fields that print a bracketed second window are printing the summer equivalent — and
that season lies wholly inside DST, so it reads **0900-1600 local, weekends and holidays,
mid-April to mid-October**. That is the Czech XC season and the Czech XC day. This will
almost never dim anything on a Saturday. Where it earns its keep is a weekday.

**Everything unreadable errs towards open.** Roughly a dozen pages say things this cannot
parse — `0700-TE`, `0800UTC-SS`, `HO (Aeroklub Liberec)`, plain `O/R`. Each of those
yields no schedule at all, and no schedule means always active, because the cost of
being wrong is asymmetric: an okruh drawn over an empty airfield is clutter, and one
withheld from a field with a tow launch on it is the other thing.

Three rules do that work:

- **A period needs a season or a window.** Days alone is a sentence fragment, not a
  schedule: LKPO's `O/R ... 48 HR O/R SAT, SUN, HOL` would otherwise be read as "closed
  Monday to Friday" at a field that is on request and therefore open whenever asked.
- **The text is cut at `except`.** LKHK's `... except 24-26 DEC, 31 DEC - 1 JAN, Easter
  Monday` reads as a period rather than an exclusion, and would have shrunk its weekend
  entry to two days in December.
- **A repeated window keeps the season and the days it repeats under.** `0700-1600
  (0600-1500)` at LKCS is the winter figure and the summer one; taking both as periods
  makes the union, 0600-1600, which is the wider and so the safer reading.

`on_request` is set wherever the page says `O/R`, `HO` or "during aeroclub operation",
which is nearly everywhere. **Outside the published window never means no traffic** — it
means nobody is there unless somebody asked — and no caller should render it as "closed".
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

_MONTH = "|".join(MONTHS)
_DAY = "|".join(DAYS)

# `15 APR - 15 OCT`, and `31 DEC - 1 JAN` the same way — a season is allowed to wrap.
_SEASON = re.compile(rf"\b(\d{{1,2}})\s*({_MONTH})\s*[-–]\s*(\d{{1,2}})\s*({_MONTH})\b", re.I)
# `MON-FRI`, `THU - SUN`.
_DAYRANGE = re.compile(rf"\b({_DAY})\s*[-–]\s*({_DAY})\b", re.I)
# One day name, or the AIP's `HOL` for a public holiday.
_DAYNAME = re.compile(rf"\b({_DAY}|HOL)\b", re.I)
# `0700-1400`, `0730 - 1430`, `06:00 - 18:00`, `0700 UTC - 1700`. Four digits either
# side, so `24-26 DEC` and `48 HR` cannot be read as a window.
_WINDOW = re.compile(
    r"\b([01]\d|2[0-3])[:.]?([0-5]\d)\s*(?:UTC|Z)?\s*[-–]\s*([01]\d|2[0-3])[:.]?([0-5]\d)"
    r"(?!\d)",
    re.I,
)

# Where the AIP starts listing exclusions rather than periods.
_EXCEPT = re.compile(r"\bexcept\b", re.I)

# The phrases that mean "and at other times too". Present on nearly every page, and the
# reason "outside the window" is never "closed".
_ON_REQUEST = re.compile(
    r"\bO\s*/\s*R\b|\bHO\b|\bon request\b|aeroclub operation|operation of the aeroclub"
    r"|according to (?:the )?(?:need|operator)|operator'?s needs",
    re.I,
)

# Narrower, and only for the label. The AIP's own `O/R` means *arranged in advance*; an
# SLZ strip's "according to the operator's needs" means the opposite — flown whenever the
# operator feels like it — and writing `O/R` on those 74 okruhy would say a strip is
# quiet when what its page actually says is that it has no hours at all.
_REQUEST_ONLY = re.compile(r"\bO\s*/\s*R\b|\bHO\b|\bon request\b", re.I)

# Field ordering, and the whole of the rule for where one period ends and the next
# begins: a token whose kind is already set starts a new period, which keeps the fields
# ranked *above* the repeated one and drops the rest. A second set of days under one
# season (LKPM) keeps the season; a second window under one set of days (LKCS, LKSB)
# keeps both.
_RANK = {"season": 0, "days": 1, "window": 2}

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Period:
    """One published operating period. Every field is optional and `None` means "all":
    no season is the whole year, no days is every day, no window is the whole day."""

    season: tuple[int, int, int, int] | None = None   # from month, day, to month, day
    days: frozenset[str] | None = None                # MON…SUN, plus HOL
    window: tuple[int, int] | None = None             # minutes past midnight, UTC

    def covers_date(self, day: dt.date, holidays: frozenset[dt.date]) -> bool:
        if self.season and not _in_season(day, self.season):
            return False
        if self.days is None:
            return True
        if "HOL" in self.days and day in holidays:
            return True
        return DAYS[day.weekday()] in self.days

    def covers_time(self, minutes: int) -> bool:
        if self.window is None:
            return True
        start, end = self.window
        # No published window crosses midnight today, but one costs nothing to allow.
        return start <= minutes < end if start <= end else (minutes >= start or minutes < end)


@dataclass
class Schedule:
    """What a page says about when the field operates, and what it could not say."""

    raw: str = ""
    periods: list[Period] = field(default_factory=list)
    on_request: bool = False
    # The page says `O/R` or `HO` specifically, rather than merely implying that the
    # window is not the whole story. Only this earns the `O/R` token in a name.
    request_only: bool = False

    @property
    def known(self) -> bool:
        """Whether anything usable parsed. False means every caller treats the field as
        operating, always — see the module docstring on which way to be wrong."""
        return bool(self.periods)

    def active(self, when: dt.datetime, holidays: frozenset[dt.date] | None = None) -> bool:
        """Whether the field is inside its published hours at `when`, read as UTC.

        True whenever nothing parsed. Never read this as "and otherwise there is no
        aeroplane": `on_request` is set at almost every field for exactly that reason.
        """
        if not self.periods:
            return True
        day = when.date()
        if holidays is None:
            holidays = czech_holidays(day.year)
        minutes = when.hour * 60 + when.minute
        return any(
            period.covers_date(day, holidays) and period.covers_time(minutes)
            for period in self.periods
        )

    def short(self) -> str:
        """The compact form that goes in the airspace name, or "" when there is nothing
        to say. `Z` on the window because the AIP publishes UTC and a Czech pilot reads
        local — the two are two hours apart for the whole of the flying season."""
        if not self.periods:
            return "O/R" if self.request_only else ""
        # One period, because this is read on a phone at the end of a name that already
        # carries a runway, an altitude and a circuit direction. LKOL publishes four.
        text = _period_text(self.periods[0])
        if len(self.periods) > 1:
            text += f" +{len(self.periods) - 1} more"
        return text

    def payload(self) -> dict | None:
        """The schedule as the map and the planner carry it. `None` when nothing parsed,
        so a ring without a schedule is a ring the time filter must never touch."""
        if not self.periods:
            return None
        out = []
        for period in self.periods:
            entry: dict = {}
            if period.season:
                entry["s"] = list(period.season)
            if period.days is not None:
                entry["d"] = sorted(DAYS.index(d) for d in period.days if d in DAYS)
                if "HOL" in period.days:
                    entry["h"] = 1
            if period.window:
                entry["w"] = list(period.window)
            out.append(entry)
        return {"p": out, "r": 1 if self.on_request else 0, "t": self.short()}


def _in_season(day: dt.date, season: tuple[int, int, int, int]) -> bool:
    from_month, from_day, to_month, to_day = season
    start, end = (from_month, from_day), (to_month, to_day)
    here = (day.month, day.day)
    return start <= here <= end if start <= end else (here >= start or here <= end)


def _run_text(indices: list[int]) -> str:
    """`MON-FRI` where the days run consecutively, `SAT,SUN` where they do not."""
    parts, i = [], 0
    while i < len(indices):
        j = i
        while j + 1 < len(indices) and indices[j + 1] == indices[j] + 1:
            j += 1
        parts.append(DAYS[indices[i]] if j == i else f"{DAYS[indices[i]]}-{DAYS[indices[j]]}")
        i = j + 1
    return ",".join(parts)


def _period_text(period: Period) -> str:
    parts = []
    if period.season:
        from_month, from_day, to_month, to_day = period.season
        inverse = {number: name for name, number in MONTHS.items()}
        parts.append(f"{from_day}{inverse[from_month]}-{to_day}{inverse[to_month]}")
    if period.days is not None:
        text = _run_text(sorted(DAYS.index(d) for d in period.days if d in DAYS))
        if "HOL" in period.days:
            text = f"{text},HOL" if text else "HOL"
        parts.append(text)
    if period.window:
        start, end = period.window
        parts.append(f"{start // 60:02d}{start % 60:02d}-{end // 60:02d}{end % 60:02d}Z")
    return " ".join(parts)


def _tokens(text: str):
    """Every season, day set and window in the line, in the order they are written.

    Order matters and cannot be assumed: the usual form is season, days, window, but
    LKBU writes `15 APR - 15 OCT 0730 - 1430 SAT,SUN,HOL` and means the same thing.
    """
    found: list[tuple[int, str, object]] = []
    covered: list[tuple[int, int]] = []

    for match in _SEASON.finditer(text):
        covered.append(match.span())
        found.append((match.start(), "season", (
            MONTHS[match.group(2).upper()], int(match.group(1)),
            MONTHS[match.group(4).upper()], int(match.group(3)),
        )))
    for match in _WINDOW.finditer(text):
        if any(a <= match.start() < b for a, b in covered):
            continue
        covered.append(match.span())
        found.append((match.start(), "window", (
            int(match.group(1)) * 60 + int(match.group(2)),
            int(match.group(3)) * 60 + int(match.group(4)),
        )))

    # Day names come last, and a range swallows the two names inside it — `MON-FRI` is
    # one token, not `MON` and `FRI` with the whole week between them unstated.
    day_spans: list[tuple[int, int, set[str]]] = []
    for match in _DAYRANGE.finditer(text):
        if any(a <= match.start() < b for a, b in covered):
            continue
        first, last = DAYS.index(match.group(1).upper()), DAYS.index(match.group(2).upper())
        span = range(first, last + 1) if first <= last else [*range(first, 7), *range(last + 1)]
        day_spans.append((*match.span(), {DAYS[i] for i in span}))
    ranged = [(a, b) for a, b, _ in day_spans]
    for match in _DAYNAME.finditer(text):
        if any(a <= match.start() < b for a, b in covered + ranged):
            continue
        day_spans.append((*match.span(), {match.group(1).upper()}))

    # Adjacent day tokens separated by nothing but commas and spaces are one set:
    # `SAT, SUN, HOL` and `MON - SUN, HOL`.
    day_spans.sort()
    merged: list[tuple[int, int, set[str]]] = []
    for start, end, names in day_spans:
        if merged and re.fullmatch(r"[,\s:]*", text[merged[-1][1]:start]):
            last = merged[-1]
            merged[-1] = (last[0], end, last[2] | names)
        else:
            merged.append((start, end, names))
    found.extend((start, "days", frozenset(names)) for start, _, names in merged)

    found.sort(key=lambda item: item[0])
    return [(kind, value) for _, kind, value in found]


def parse(text: str) -> Schedule:
    """One *Provozní doba* line as a schedule."""
    raw = re.sub(r"\s+", " ", text or "").strip()
    schedule = Schedule(
        raw=raw,
        on_request=bool(_ON_REQUEST.search(raw)),
        request_only=bool(_REQUEST_ONLY.search(raw)),
    )
    if not raw:
        return schedule

    # Everything after `except` lists days the field is *shut*, and reading those as
    # periods is the one way this parser can be wrong in the dangerous direction.
    body = _EXCEPT.split(raw)[0]

    current: dict = {}
    periods: list[dict] = []
    for kind, value in _tokens(body):
        if kind in current:
            periods.append(current)
            current = {k: v for k, v in current.items() if _RANK[k] < _RANK[kind]}
        current[kind] = value
    if current:
        periods.append(current)

    schedule.periods = [
        Period(season=entry.get("season"), days=entry.get("days"),
               window=entry.get("window"))
        # A period with only days is a fragment of a sentence, not a published period.
        for entry in periods
        if entry.get("season") or entry.get("window")
    ]
    return schedule


def easter(year: int) -> dt.date:
    """Easter Sunday, by the anonymous Gregorian algorithm."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    weeks = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weeks) // 451
    month = (h + weeks - 7 * m + 114) // 31
    day = ((h + weeks - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


# Czech public holidays: the fixed ones from zákon č. 245/2000 Sb., plus Good Friday and
# Easter Monday, which move. `HOL` in the AIP means one of these.
_FIXED = ((1, 1), (5, 1), (5, 8), (7, 5), (7, 6), (9, 28), (10, 28), (11, 17),
          (12, 24), (12, 25), (12, 26))


def czech_holidays(year: int) -> frozenset[dt.date]:
    sunday = easter(year)
    return frozenset(
        [dt.date(year, month, day) for month, day in _FIXED]
        + [sunday - dt.timedelta(days=2), sunday + dt.timedelta(days=1)]
    )


def holiday_list(years) -> list[str]:
    """`YYYY-MM-DD` for every holiday in those years, for the page to carry.

    Computed here rather than reimplemented in JavaScript: the map lets a reader pick a
    date, and a second copy of the Easter algorithm is a second thing to get wrong.
    """
    return sorted(
        day.isoformat() for year in years for day in czech_holidays(year)
    )
