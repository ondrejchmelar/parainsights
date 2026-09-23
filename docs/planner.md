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

- **Closing a course is the reader's to declare, and the route has one definition.**
  Three parts of this page walk the route — the line drawn on the map, the airspace it is
  checked against, and the number under it — and they disagreed. The first two honoured
  the *closed course* box; `score()` closed a three-point route regardless, added the
  third side, reported the gap it had just invented as `0.0 km`, and applied the flat
  triangle's ×1.2. Measured on the real page: a course drawn as 164.1 + 86.3 km printed
  **397.41 km** and 476.90 points. There is now one `course()` returning the walked
  points, all three read it, and a test measures the printed distance against the
  vertices of the line the map actually drew rather than recomputing the route it thinks
  should be there — the target has to come from somewhere other than the code under test,
  or it only re-asserts the bug. The old test did exactly that: it tapped three times and
  asserted a triangle.

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

## Outside Czechia

The ground reaches past the airspace: `PLAN_BOX` is 5.5–20.5 E, 45.0–51.3 N, the Western
Alps to the Low Tatras, so a task out of Bassano or Kobala can be drawn and scored like
one out of Raná. The airspace is still Czech only. A route that leaves the border is
measured against it (the border ring ships in the page as `plan-coverage`), and the list
says how many kilometres were not checked — or, for a route wholly outside, that nothing
was. "Nothing crossed" is only ever said about ground the map has airspace for.

The terrain is **not in the page**: it ships as `terrain.remote()` — the box, the grid
and the tile zoom — and the browser fetches the terrarium tiles and samples them onto
the same 120 000 nodes `terrain.fetch` would have built (`loadTerrain` in `view3d`).
Carried, that grid was half of a 1.3 MB page. The relief is about 2.5 km a node against
1.6 on the airspace map; scoring is on coordinates, and the imagery sharpens at view
time as before.

## Whether anybody is there

A crossing list is a plan view in a second sense too: it says the route enters that
polygon *ever*, and a task is flown on a particular day at a particular hour. The clock
above the map answers the part of that question the AIP publishes.

It is the airspace map's own control, emitted by `airspaces.render_html.when_control` and
used verbatim, because a planner that answered "which fields are open" differently from
the map it is drawn on would be worse than not answering. Setting it does two things,
which are the same thing: it takes the shut fields off the map so the route is readable,
and it marks them in the list so the reader knows why the map went quiet.

- **The map declutters; the list is the answer, and stays complete.** Dropping a zone out
  of the list because a VFR manual page said `SAT, SUN, HOL` would be the tool quietly
  deciding something it does not know. Every crossing is still listed, and a marked one
  reads `outside hours` rather than *closed* — nearly every Czech field adds "otherwise
  O/R", so it means nobody is there unless somebody asked, not that nobody is.
- **Only a ring that carries hours is ever marked.** That is 68 aerodromes' worth. The
  base airspace and all 74 SLZ okruhy carry none, and marking those would be inventing an
  answer for three quarters of the map — which is the same reason the crossing list does
  not yet claim a height. The note under the control says which part it speaks for.
- **It does not reorder the list.** Lowest floor first stays the order, because what a
  paraglider hits soonest is still what it most needs to know; whether the field was
  operating is a property of the row, not a reason to rank it.

Written up in full in `airspaces.md` — the parsing, the three rules that keep it from
being wrong in the dangerous direction, and why an ATZ is not the thing with a schedule.

Finding the crossing list also found a real bug in the airspace layer underneath: the base file writes
`0 AGL` far more often than `GND`, and only the word was being read as the ground. Those
rings were being drawn at *sea level* — 200 to 1 600 m below the terrain they belong to
— and labelled "floor 0 m" for something that starts under your feet.

## The vertical — planned, not built

The crossing list above is a plan view. It says the route *enters* a zone, which is not
the same claim as the flight being *inside* it: most of these zones have a floor, and a
task that stays under it is legal. So "25 airspaces crossed" reads as a wall when a good
part of it is air you may fly through, and the number that is meant to make a reader
careful is the number that teaches them to stop reading. The fix is a planned height band
per leg, and a list that separates **stay under 1 000 ft here** from **you cannot go**.

Written up here rather than built, because the shape of the answer is the decision and it
is worth agreeing on before there is code to argue with.

### The split is three ways, not two

Measured on what the scene actually carries — 743 rings, being `CZ_low 26-04-01` (251)
plus this repository's own aerodrome overlay (492):

| | rings | what a band could say |
|---|---|---|
| air underneath | 119 | a limit: stay below this and the crossing is not a crossing |
| ground up, and closed | 62 | a wall: no band clears it — 41 R, 11 P, 10 D |
| ground up, and open with a duty | 562 | not a limit at all: 82 ATZ, 410 okruh, 70 GS/Q/E |

The third row is the one that makes the current list misleading, and it is three quarters
of it. An ATZ is class W here and an unpowered paraglider **may** fly it — the duty is a
phone call and staying out of the circuit, not a floor. An okruh is not a published
boundary at all; this tool draws it from ordinary circuit proportions. Neither belongs in
the same bucket as LKP2 Temelín, and today they are all just "crossed".

So the vertical is not one feature. It is a band for the 119, a class rule for the 62, and
an admission that for the other 562 the honest answer was never a height.

### The 13 rings the feature is named after

Every ring in the base file whose floor is quoted above ground — all thirteen of them —
is class R, and every one is a TRA or a TSA:

| floor | ceiling | count | |
|---|---|---|---|
| `300 AGL` | `1000 AGL` | 6 | LKTSA20 Ždírec, 21 Měřín, 22 Opatov, 24 Litovel, 26 Pravonín, 27 Humpolec |
| `1000 AGL` | FL 75 – FL 245 | 6 | LKTRA31, 56, 74, 76, 77, 78 |
| `300 AGL` | FL 125 | 1 | LKTRA15 Brtnice |

Two things follow, and both are sharp.

**The six TSAs are slabs.** Floor 300 ft AGL, ceiling 1 000 ft AGL: a 700 ft band of
restricted air with legal air *below it and above it*. The current list cannot express
that shape at all, and 27 rings in the file have a non-FL ceiling and so have sky above
them. A band that only ever says "stay under" would get these wrong in the direction that
costs a pilot the flight.

**`floor_metres` is wrong here, on purpose.** It treats AGL as AMSL, and
`airspaces/render_html.py` says why: the altitude slider's question is "could this be in
my way low down", and a floor quoted above ground is by definition low down. Correct for
that question. For a band it is a 500 m error on exactly these rings — `1000 AGL` becomes
305 m, and over the Vysočina at 550 m the real floor is about 855 m, so a task planned at
800 m would be reported as inside a zone it is half a kilometre beneath.

The fix is *not* to change `floor_metres`. The slider is asking a different question and
is right to. The ring has to carry its datum and the band has to resolve it, which is the
first of the three code changes below.

### What the code has to gain

- **A ceiling on the ring.** `airspaces/scene.py: rings()` emits `f` (floor, metres AMSL)
  and `g` (is-ground); the ceiling exists only inside the label string `n`, as
  `"LKTSA20  (300 AGL – 1000 AGL)"`. A band needs it as a number, so `rings()` gains `c`.
  Parsing it back out of the label would work and must not be done: the label is for a
  human to read and is free to change, and a display string load-bearing for a legal
  answer is the sort of coupling that breaks quietly.

- **The datum, alongside the number.** `f` stays what it is, and the ring gains a flag for
  "this floor was quoted above ground". Where it is set, the planner resolves the floor
  against `handle.groundAt(lon, lat)` — which it already calls, to put the course line
  60 m over the terrain. An AGL floor is a *surface*, not a height, so it has to be
  resolved along the leg rather than once.

- **Intervals, not a fraction.** `fractionInside` sorts its crossing parameters and
  collapses them to a single total. A band is a function of distance along the leg, so it
  must return the intervals `[[t0, t1], …]` and let the caller sum them for the kilometre
  figure it prints today. That is the one real refactor here, and it is safe: the existing
  tests pin the sum, so they go on pinning it.

Grouping changes with it. Today the crossings are keyed by name and the floors merged with
`seen.f = Math.min(seen.f, ring.f)`, which is fine for sorting a list and wrong for a
limit: a stepped CTR is several rings at several floors, and a task that only clips the
high-floored outer one would be told to stay under the inner one's floor. The geometry has
to stay per interval, and the grouping become presentation only.

### Whose height is it

The open decision, and the one worth taking a view on. Three ways to get the band:

1. **One planned working height for the task**, AMSL, from a slider.
2. **A hand-entered band per leg.**
3. **Derived** — the day's thermal top, less a glide from each turnpoint.

Take (1). It is how a pilot actually plans a day ("I expect to work to 1 800 m"), it is one
number rather than a form, and `meteo/render_html.py` already computes both a thermal top
and a cloudbase in metres AMSL for 159 Czech takeoffs — so the slider can *default* to the
day's number instead of to a guess. (2) is more truthful and nobody will type it. (3) is
the right end state and the ingredient is already in the repository, but it needs the meteo
view and the planner to agree on a day, which is a bigger seam than this feature.

One constraint on any of them: the number is **AMSL**. Czech terrain under a 226 km task
runs 200 to 1 600 m, so a single AGL figure would mean a different thing at each end of the
line. A single AMSL number is honest; a single AGL number is a bug with a friendly face.

### What the list becomes

Three kinds of row instead of one, ordered so the walls come first:

```
✗  MCTR Kbely            ground – 1000 ft, 18.8 km        no height clears this
▲  LKTRA62 Nymburk       below 914 m, 12.4 km of leg 2    plan is 1 800 m — you are in it
▬  LKTSA20 Ždírec        below 855 m or above 1 070 m     3.1 km of leg 3
✓  ATZ LKBE Benešov      ground up, 4.2 km                call the aerodrome, stay out of the circuit
```

The last row is the point of the whole exercise: it is not a crossing to be cleared, it is
a crossing with a duty attached, and today it is indistinguishable from the first.

### What a band still cannot say

This section needs its limits stated harder than the rest of the page, because a more
useful answer is a more trusted one.

- **The 13 are temporary, and the clock above the map does not reach them.** TRA and TSA
  are *reserved*, by AUP and by NOTAM, and the base OpenAir file carries no activation
  times — the parser reads `AC AN AH AL AF DP DB DC` and there is no time field for it to
  be dropping. The operating hours added since come off the VFR manual's aerodrome pages
  and so cover the aerodrome layers only; these 13 are exactly the rings they miss. For
  precisely the zones a band handles best, it can say "under the floor you are clear" and
  cannot say "and above it, today". That asymmetry has to be on screen, not in a footnote.
- **The terrain grid is 1.4 km a node** (320 columns over the country, `scene.py`). An AGL
  floor resolved on it is a smooth approximation of a surface that follows real ground, so
  the band wants a margin rather than a hard edge, and the margin wants to be visible.
- **The claim gets bigger.** Today the tool states a geometric fact: this line enters that
  polygon. A band states a legal one: you may fly under it. That is a different bar and a
  different kind of wrong, and it is the argument for keeping **this is a plan, not a
  clearance** loud — a green band is exactly the moment a reader stops checking NOTAMs.

### Tests it would want

In the shape the existing nine are in — a real browser, a real scene, and one asserted
sentence each:

- a leg under a floor reports clear, and the same leg 200 m higher reports the limit;
- a slab reports both bounds, and does not report "stay under" alone;
- an AGL floor over 900 m terrain is not compared against sea level — the regression for
  the error named above, which is the same class of bug as the `0 AGL` one already fixed;
- the intervals sum to the kilometres the current test asserts, so the refactor is proved
  not to have moved the number a reader already trusts;
- an ATZ crossing is never rendered as a wall.

## Running it

```bash
uv run python -m planner.cli --html public/planner/index.html
uv run python -m planner.cli --html plan.html --no-airspace   # no airspace, faster
```

There is no `--embed`: the page fetches its own terrain, so it needs a network anyway.

Imagery is fetched at view time by default, and gets sharper as the reader zooms in.

## Status

Works end to end: drop turnpoints, undo, clear, close the course, and read the distance,
the shape, the multiplier, the score, the side lengths and every airspace the route
crosses — with the aerodromes among them marked open or shut at the hour you are planning
for. Thirteen tests, twelve of them driving a real browser.

Wanted next:

- **Drag a turnpoint.** Adding and undoing is enough to draw a task; moving one is what
  makes it a planning tool. It needs hit-testing the markers, which the airspace layer
  already does for rings.
- **The vertical.** A planned height band per leg, so the list separates "stay under
  1 000 ft here" from "you cannot go". **Written up above** — the split turns out to be
  three ways rather than two, the ring has to start carrying a ceiling and a datum, and
  `fractionInside` has to return its intervals instead of their sum.
- **Turnpoints by name, and a task you can share.** A URL that carries the points would
  make a plan something you can send to the people you are flying with.
- **Start from a takeoff.** The meteo view already knows 159 of them.
