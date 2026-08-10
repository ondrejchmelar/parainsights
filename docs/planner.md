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

## Running it

```bash
uv run python -m planner.cli --html public/planner/index.html --online
uv run python -m planner.cli --html plan.html --no-airspace   # terrain only, faster
```

`--online` leaves the imagery to be fetched at view time, which is sharper and much
smaller; without it the page carries an embedded stitch and works with no network.

## Status

Started, and it works end to end: drop turnpoints, undo, clear, close the course, and
read the distance, the shape, the multiplier, the score and the side lengths. Five tests,
four of them driving real PointerEvents in Chrome.

Wanted next:

- **Drag a turnpoint.** Adding and undoing is enough to draw a task; moving one is what
  makes it a planning tool. It needs hit-testing the markers, which the airspace layer
  already does for rings.
- **Say which airspace the line crosses.** Both halves are on the page and neither knows
  about the other — the rings are in the scene and the legs are in the planner, and a
  segment-in-polygon test over the drawn rings is the missing piece. This is the feature
  the whole page is arranged around and it is not built yet.
- **Turnpoints by name, and a task you can share.** A URL that carries the points would
  make a plan something you can send to the people you are flying with.
- **Start from a takeoff.** The meteo view already knows 159 of them.
