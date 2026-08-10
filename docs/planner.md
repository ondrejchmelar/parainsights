# planner — plan, decisions and status

The fourth tool in `parainsights`. See `../CLAUDE.md` for the repository layout.

One goal: **draw a task and know what it is worth, over the ground and the airspace you
would actually fly it across.** flyxc.app is the reference for the interaction; the thing
worth adding is the map underneath, because a line that looks like a good 60 km and
crosses a TMA is not a plan and on a bare basemap you cannot see that.

## It is a layer, not a viewer

The planner draws nothing of its own. It writes into the two members of the `view3d`
scene that a flight already uses and asks for a redraw:

| what | how it is drawn |
|---|---|
| the course line | `scene.track`, at 60 m above the terrain under each point |
| the turnpoints | `scene.climbs`, the numbered markers a flight uses for its climbs |

That is why the whole feature is about two hundred lines, and it buys something better
than brevity: **a planned task and a flown flight are drawn by the same code**, so they
cannot disagree about where a line on this map is. The two things the view had to expose
are `groundLonLat` — what is under this screen point, in the coordinates a plan is
written in rather than the projection's own metric frame — and `groundAt`.

## Decisions, and the reasons behind them

- **A click is a pointerup that has not travelled.** The canvas pans, zooms, rotates and
  tilts, so a plain click handler drops a turnpoint on every drag of the map — the usual
  way this kind of tool is broken. More than 6 px between down and up is a gesture.
  `tests/test_planner.py` drags the map and asserts that nothing was left behind.

- **The scoring constants are interpolated from `tracklog_viewer/xc.py`, never typed.**
  A planner that scored a task differently from the report that later measures the flight
  would be worse than no planner. `FAI_MIN_SIDE`, `MAX_CLOSING` and the three multipliers
  come out of the module, and a test fails if the script stops containing them.

- **Two points are open distance, and that is a case worth naming.** Two points have no
  perimeter; treating them as a degenerate triangle would multiply an out-and-back by 1.2.
  There is a test for exactly that, because it is the shape of bug that only shows up as a
  number nobody checks.

- **A triangle is the closed figure, not the path walked.** Three points are its corners.
  A fourth point with *closed course* ticked is the flight coming home, and it scores the
  same three sides — with the closing gap tested against 20% of the perimeter, the way
  XContest tests it — rather than adding a fourth leg to the total.

- **The geodesy is the FAI sphere**, matching `tracklog_viewer/geo.py`, because that is
  what a scored distance is measured on. The airspace half of the same page is WGS84.
  The two are not interchangeable and the script says so where it defines its radius:
  one measures a task, the other draws a boundary.

## What the line crosses

The feature the page is arranged around, and the reason it draws on the airspace map
rather than on a basemap. Every leg — including the closing leg, which is the one a tired
pilot flies home on — is tested against every ring in the scene, and the result is a list
of what the route enters, **lowest floor first**, with how far through each one it goes.

- **Exact, not sampled.** Every crossing of the segment with a ring edge is collected as
  a parameter along the segment, the parameters are sorted, and the midpoint of each
  interval is tested for being inside. So "18.8 km through the Kbely MCTR" is a real
  distance. The cheaper way — walking the leg at some spacing and counting samples inside
  — has its worst error exactly where the answer matters: a long leg brushing a small
  zone can pass between two samples and be reported clear.
- **A bounding-box test first.** 743 airspaces of a few thousand vertices, recomputed on
  every turnpoint, is otherwise a visible pause; the box test throws away all but a
  handful.
- **Grouped by name.** One CTR is published as several rings and one okruh is two
  rectangles. A list that says "LKPR CTR" four times is a list nobody reads.
- **Lowest floor first, not most kilometres.** What a paraglider hits soonest is what it
  most needs to know. Measured on a 226 km triangle across Bohemia: 25 airspaces, led by
  MCTR Kbely at 18.8 km through from the ground.
- **A clear route says so.** "Nothing on this map is crossed by the route" and an empty
  panel look the same on screen and mean opposite things — one is an answer and the other
  is a page that has not run. It also repeats what the check does *not* cover, because a
  green result is exactly when a reader stops thinking about NOTAMs.

Finding this also found a real bug in the airspace layer underneath: the base file writes
`0 AGL` far more often than `GND`, and only the word was being read as the ground. Those
rings were being drawn at *sea level* — 200 to 1 600 m below the terrain they belong to
— and labelled "floor 0 m" for something that starts under your feet.

## Running it

```bash
uv run python -m planner.cli --html public/planner/index.html
uv run python -m planner.cli --html plan.html --no-airspace   # terrain only, faster
uv run python -m planner.cli --html plan.html --embed         # bake the imagery in
```

Imagery is fetched at view time by default, and gets sharper as the reader zooms in.

## Status

Works end to end: drop turnpoints, undo, clear, close the course, and read the distance,
the shape, the multiplier, the score, the side lengths and every airspace the route
crosses. Nine tests, eight of them driving a real browser.

Wanted next:

- **Drag a turnpoint.** Adding and undoing is enough to draw a task; moving one is what
  makes it a planning tool. It needs hit-testing the markers, which the airspace layer
  already does for rings.
- **The vertical.** The crossing list is a plan view: it says the route enters a zone,
  not that the flight would be inside it. Most of those zones have a floor, and a task
  that stays under it is legal — so the honest next step is a planned height band per leg
  and a list that separates "you must stay under 1 000 ft here" from "you cannot go".
- **Turnpoints by name, and a task you can share.** A URL that carries the points would
  make a plan something you can send to the people you are flying with.
- **Start from a takeoff.** The meteo view already knows 159 of them.
