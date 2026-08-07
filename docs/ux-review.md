# UX review — the tracklog report

Written 2026-07-31 against `public/index.html` (three flights, `--online`, 2.29 MB).
Everything below was measured in headless Chrome, not estimated.

**Status, 2026-08-07: phases 0, 1, 2 and most of 3 are built.** The diagnosis and the
measurements below are kept as written — they are the argument for what was done, and
the "today" column of every table is what the report was before. What actually shipped,
and where it differs from what is proposed here:

| Phase | State | Notes |
|---|---|---|
| 0 — the defects | built | tab close 19x19 → 44x44 hit area; 884 text nodes under 11 px → 0; `aria-label` on every map control |
| 1 — the debrief | built | `debrief.py`. Verdict strip above the 3D view, cards below it, *show me* pinning the linked cursor |
| 2 — the cuts | built | climbs 16 → 8 with circling detail behind a toggle, glides 7 → 6, tiles 10 → 6, segmented map controls, keyboard, table media query |
| 3 — comparison | built | cross-flight deltas on the verdict figures rather than on the stat tiles |

Four differences from the proposal, each for a measured reason:

1. **The cross-flight comparison went on the verdict strip, not the stat tiles.** Once
   the strip existed, the tiles were the wrong place: the strip already carries the four
   figures worth comparing, and repeating them below it is the redundancy this document
   complains about.
2. **The proposed tile set changed.** `XC SCORE`, `HEIGHT GAINED` and `MEAN CLIMB` moved
   *up* into the strip, so the six tiles are `AIRTIME · CEILING USED · CLIMBS · WIND ·
   MEDIAN GLIDE · XC SPEED`. `CEILING USED` still folds the `MAX ALTITUDE` / `YOU
   REACHED` duplicate, exactly as proposed.
3. **Finding 5 (drifting out of the line) and finding 8 (the time budget) were rethought.**
   The `other` slice is not a loss — see `docs/analysis-plan.md`, correction 1 — so it
   became a three-way decomposition. And the detour ratio has no honest cost, so it is a
   figure on the strip rather than a card.
4. **The nudge buttons went further than proposed on touch.** Reset goes too: it was the
   widest button in the prime thumb position for the least-used action.

**On the widths.** 390 × 844 is the iPhone 12/13/14 viewport — 15/16 are 393, Pixel 5
is 393, Galaxy S20 is 360, iPhone SE is 375. It is the most common phone width there is,
which is why it is the one to design against.

**A note on method.** The first pass used `--window-size=390`, which is *not* device
emulation: the page reported a 485 px CSS viewport, ~25% wider than a real iPhone. The
mobile numbers below were re-taken over the DevTools protocol with
`Emulation.setDeviceMetricsOverride` at 390 × 844, dpr 3, `mobile: true`, and several got
worse. Where a figure is marked ✓ it came from that run.

## What was measured

One flight article (Col Rodella, 2018-09-28):

| | |
|---|---|
| article height, desktop | 5 466 px, 9 sections |
| words | 1 504 |
| numeric tokens | 191 |
| table cells | 341 |
| stat tiles | 10 |
| explanatory prose | 3 085 characters |
| inline SVG, whole document | 351 |

## The diagnosis

**The report is an instrument panel, not a debrief.** Every number is present and
correct. Not one of them is judged. There is no sentence anywhere in the report that
says whether the flight went well, or where it went wrong.

That is the real complaint behind "too much info, little insight" — and it is worth
being precise about, because the obvious fix (delete fields) is mostly the wrong one.
The fields are cheap: they sit behind a scroll or a heading, and some pilot somewhere
wants `m/turn`. What is missing is a **layer above them**. Cut the handful that earn
nothing, demote the specialist ones, and add the layer that ranks.

Three things the report never does:

1. **Compare.** `+1.04 m/s mean climb` — against what? The document holds three
   flights and never puts them side by side. That is free insight sitting on the table.
2. **Cost.** The time budget says `other 18%`. That is 40 minutes, and it is the only
   slice with no explanation. Losses live exactly there.
3. **Counterfactual.** 121 km flown to score 48.64 km, and the triangle missed closing
   by 2 km. Both numbers are on the page. Neither is framed as what it cost.

Two smaller catches from the same cause:

- **`MAX ALTITUDE` and `YOU REACHED` are the same number** (3 774 m), printed twice,
  2 000 px apart, in two different stat rows.
- **The most interesting number in the flight is buried in a caption.** "Lowest ground
  clearance of the flight was -26 m, median 478 m" sits mid-paragraph under the 3D
  view. A pilot who scraped a ridge wants that as a headline, not as prose.

## On "recommendations" — a change of name and of voice

Call the feature **Debrief**, and call each item a **finding**. Not recommendations.
This is the one place I would argue with the brief, and the reason is the report's
own best asset.

The tool cannot see the sky, the gaggle, the airspace, the pilot's plan, the weather
ahead, or the fact that they were low and going home. Advice from a blind coach is
wrong often enough to poison everything around it — and this report has unusual
credibility to lose. "How to read this, and what to distrust" is the most trustworthy
section I have seen in a tool of this kind. One confident *"you should have stayed in
that thermal"* that happens to be wrong undoes it.

So the rule is: **a finding is a measurement plus a link. Never an imperative.**

> ✗ "You should have stayed in climb 10."
>
> ✓ "Left the day's strongest climb (+1.81 m/s) at 3 656 m, 118 m under the day's
>    best. The next climb took 9 min to find and averaged +0.49 m/s." → *show me*

Past tense, about the flight, no "should". The pilot draws the conclusion — they were
there and the tool was not. This also happens to be the honest description of what the
data supports.

Two more rules that follow:

- **Every finding carries a cost**, in metres or minutes. A finding with no cost does
  not ship — that is what stops the list becoming twelve items of trivia.
- **A finding must not fire on data that cannot support it.** The code already knows
  this: `TURN_RESOLUTION_LIMIT` at 5 s, `TOW_RESOLUTION_LIMIT` at 15 s, wind confidence,
  GPS-only flights, a 500-point KMZ from a scoring site. Any finding resting on turn
  statistics must be suppressed on a coarse track rather than computed anyway.

## The findings worth shipping

All eight are computable from dataclasses that **already exist**. This is a ranking
layer over `Analysis`, not a new analysis pass — which is what makes it cheap.

| # | Finding | Evidence it prints | Fields it needs |
|---|---|---|---|
| 1 | Left the best climb early | best `average_climb`, its `finish_altitude` vs the day's ceiling, and what the next climb cost | `Segment.average_climb`, `finish_altitude` |
| 2 | The expensive gap | longest stretch between two climbs: minutes and height lost | `TimeBudget`, `Segment` |
| 3 | The low point | lowest ground clearance, where and when | `terrain.clearance()` — already computed, currently in a caption |
| 4 | Working the core | climbs split by radius: "four flown at 40 m averaged +0.6; three at 32 m averaged +1.4" | `efficiency`, `circle_radius` |
| 5 | Drifting out of the line | climbs drifting downwind away from the course line | `Wind`, `Segment.centre` |
| 6 | The close that wasn't | distance from closing, against the score it would have bought | `Route.closed`, `legs`, `points` |
| 7 | Ceiling used | topped at 3 774 of a 3 954 m cloudbase = 95%; day's mean 78% | `meteo`, `Segment.finish_altitude` |
| 8 | Time budget outlier | the `other` slice, explained | `TimeBudget` |

Rank by cost, show the top 3–5, suppress the rest. Findings 3, 6 and 7 use numbers
already on the page — they need framing, not computation.

## Field cuts

### Climbs table: 16 columns → 8

Today: `# START TIME GAIN TOP AVG BEST EFF TURNS M/TURN DIR S/TURN RADIUS WIND RATES OVER-TIME`

At a true 390 px viewport the table is 1 023 px in a 340 px container — **3.0 screens of
horizontal scrolling** ✓, with `scrollLeft` topping out at 683. It scrolls, so no data is
lost; there is simply nothing on screen to say it does. The whole article is 6 148 px tall
on that phone ✓, about seven screens.

| Action | Columns | Why |
|---|---|---|
| **Keep** | `# START TIME GAIN TOP AVG EFF TREND` | The climb, what it gave, and whether it was flown tidily |
| **Behind a "circling detail" toggle** | `TURNS M/TURN S/TURN RADIUS DIR` | Five columns of circling mechanics — a whole sub-story, and a specialist one |
| **Drop** | `BEST M/S` | Peak of a noisy series; it is already `EFF`'s denominator |
| **Drop** | `WIND KM/H` | The wind chart is directly above, and says it better |
| **Drop** | `RATES` sparkline | Duplicate of the big histogram, at 60 px wide and unreadable |

Eight columns fit a phone without horizontal scrolling.

### Glides: 7 → 6

Drop `HEIGHT M` — it is `KM × GLIDE`, and the ratio is the point of the row.

### Stat tiles: 10 → 6, each with a comparison

Today: `AIRTIME · XC DISTANCE · MAX ALTITUDE · HEIGHT GAINED · CLIMBS · WIND`, then
`SURFACE · CLOUDBASE · BOUNDARY LAYER · YOU REACHED`.

Proposed: `AIRTIME · XC SCORE · HEIGHT GAINED · MEAN CLIMB · CEILING USED · WIND`.

`CEILING USED` folds `MAX ALTITUDE`, `YOU REACHED` and `CLOUDBASE` into the one
number that means something — 3 774 / 3 954 = **95%** — and kills the duplicate.
The rest of the sounding stays in "The air that day", where it belongs.

Every tile gets a second line comparing it to the other flights in the document,
where there is one to compare against.

## Information architecture

```
  TODAY                             PROPOSED
  ─────────────────────────         ─────────────────────────
  masthead                          masthead + VERDICT STRIP   ← the flight in one line
  3D view over the ground           3D view over the ground
  side view + top view              ▶ DEBRIEF — 3–5 findings   ← evidence, next to the
  stat tiles ×6                     side view + top view          instrument that shows it
  where the time went               numbers that matter ×6
  wind by thermal                   the day (time · wind · lift)
  lift histogram                    detail tables (collapsed on mobile)
  climbs table (16 col)             the air that day
  glides table                      how to read / what to distrust
  the air that day
  how to read / what to distrust
```

The verdict strip goes **above** the 3D view; the findings go **immediately below** it.
That is deliberate. The 3D view is the hero image and the reason people stay, so it
keeps its place — but a reader currently scrolls ~1 200 px before meeting a single
number. One compact line at the top answers the question; the cards then sit right
under the instrument they point into, so *show me* moves the marker in the view
directly above, with little or no scrolling on desktop.

### Verdict strip

```
┌────────────────────────────────────────────────────────────────────────────┐
│  A 3 h 39 m alpine triangle. Climbs were weak but the day held             │
│  to 15:30 — the flight ended 2 km short of closing.                        │
│                                                                            │
│  48.64 km  FAI          +1.04 m/s  13 climbs        95%  of cloudbase      │
│  ▲ best of the 3 here   ▼ weakest of the 3          ▲ best of the 3        │
└────────────────────────────────────────────────────────────────────────────┘
```

### A finding card

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ⬤ COST 9 MIN                                                              │
│  Left the day's strongest climb 118 m below its best                       │
│                                                                            │
│  Climb 10 ran at +1.81 m/s and you left it at 3 656 m. The next            │
│  climb took 9 min to find and averaged +0.49 m/s.                          │
│                                                                            │
│  14:28:57 · climb 10 of 13                                  show me  →     │
└────────────────────────────────────────────────────────────────────────────┘
```

Three of these across the desktop width, stacked on mobile. The dot carries the
climb/sink ramp already in the design system, so cost reads as colour before it
reads as text. *show me* drives the existing linked cursor — the mechanism is
already built and already connects the charts to the 3D view.

### Mobile, climbs

```
   ┌──────────────────────────────┐        ┌──────────────────────────────┐
   │ CLIMBS                       │        │ CLIMBS                       │
   │ ┌──┬─────┬────┬────┬───┬───┐ │        │  #   START   GAIN   AVG  EFF │
   │ │# │START│TIME│GAIN│TOP│AV…│ │        │ ─────────────────────────────│
   │ │1 │12:07│9:52│+623│294│+1.│▓│        │  1   12:07   +623  +1.05  35%│
   │ │2 │12:20│7:17│+365│320│+0.│▓│  ───▶  │  2   12:20   +365  +0.84  24%│
   │ └──┴─────┴────┴────┴───┴───┘ │        │  3   12:35   +147  +0.78  40%│
   │  ← 2.4 screens of scrolling  │        │                              │
   │    with nothing to say so    │        │  ⊕ circling detail           │
   └──────────────────────────────┘        └──────────────────────────────┘
        16 columns, 1 023 px                    6 columns, fits 390 px
```

## Size, type and touch

Measured at 390 / 768 / 1280 px.

| Finding | Measured | Recommendation |
|---|---|---|
| **Tab close button is 19 × 19 px** | 19 × 19, adjacent to the tab-open target | 44 × 44 hit area via `::before`; consider requiring the tab to be active before `×` is live |
| **18 of 22 buttons under 44 px** | 26–33 × 28 px typical | 44 px minimum on `(hover: none)` |
| **884 text nodes under 11 px** ✓ | 757 at 10.5 px, 127 at 10 px | 11 px floor, 12 px on mobile |
| Body text 13.5 px | 2 091 nodes | 14 px desktop, 15 px mobile |
| 3D control bar | wraps to two rows on a phone, covering 20% of the map | its own section below |
| Media queries | only 620 px and 780 px | add one for the tables and the 3D control bar |

Two notes on that table.

**The tab close button is the worst defect on the page.** It is the control that
*removes a flight from the document*, at 19 × 19 px — under half the minimum touch
target — sitting immediately beside the control you actually meant to press. On a
phone that is an accidental deletion waiting to happen.

**The ≤10.5 px text is mostly SVG axis labels**, which is an accessibility problem
as well as a legibility one: SVG text does not respond to the reader's font-size
preference, so a reader who has turned type up gets no relief. Where an axis is
crowded, thin the ticks out rather than shrink the type.

**Desktop is in good shape.** Measure, hierarchy, colour and rhythm are all sound,
and the type ramp (`clamp(30px, 5vw, 46px)` on the masthead) already scales properly.
The one desktop issue is scan length: 5 466 px with no in-page navigation.

## The map buttons

Ten buttons in one wrapping flex row, bottom-anchored over the terrain:

```
  ↶  ↷  ↑  ↓  +  −   [SATELLITE]  [×1 HEIGHT]  [⛶]  [RESET VIEW]
 33 33 27 27 26 26        78          77        32       87      px wide, all 28 px tall
```

Measured at 390 × 844 with real device metrics ✓.

### Six of the ten duplicate gestures that work better

`rotate-left`, `rotate-right`, `tilt-up`, `tilt-down`, `zoom-in`, `zoom-out` are all
available by drag, ctrl-drag or right-drag, and wheel or pinch — and the caption directly
above the panel *teaches exactly that*. So 60% of the button slots are a discoverability
crutch for gestures the panel already has, and they are the slots pushing the bar onto a
second row.

They are also the least legible: `↶ ↷` read fine, but `↑ ↓` meaning **tilt** is a guess —
they could as easily be pan.

### A fifth of the map is chrome, on the device with the least map

At 390 × 844 the panel is **390 × 295** and the bar is **370 × 60 — 20.2% of the panel
height** ✓, sitting on top of the terrain. The sun-and-wind rose occupies the bottom-left
of the same canvas, so the bottom fifth of a 295 px map is controls and legend.

### Six of the ten have unusable accessible names

This one is verified rather than reasoned: Chrome's own name computation, read out of
the accessibility tree, returns

```
  name='↶'  from=contents        name='+'            from=contents
  name='↷'  from=contents        name='−'            from=contents
  name='↑'  from=contents        name='Full screen'  from=attribute/title
  name='↓'  from=contents        name='RESET VIEW'   from=contents
```

The `title="Rotate left"` is **ignored**, because for a button the content wins over
`title`. A screen reader announces "button, ↶". `title` also never appears on touch, so
on a phone those six glyphs are the entire affordance.

The fix is `aria-label`, and **the codebase already knows this pattern** — the tab close
buttons carry `aria-label="Remove this flight"`, which is exactly why they compute a
sensible name. It simply was not applied to the map. An inconsistency, not an oversight
of principle.

### Mobile CSS makes the targets *smaller*

Every button is 28 px tall and six are 26–33 px wide — all ten under 44 px ✓. And the
media query at 640 px reduces padding to `5px 7px` and type to 10.5 px, shrinking the
targets on the one device where a finger replaces a mouse. That is backwards, and it is
a one-line fix.

### Three kinds of control, one undifferentiated style

| Kind | Buttons | Behaviour |
|---|---|---|
| Repeatable nudge | rotate ×2, tilt ×2, zoom ×2 | pressed many times in a row |
| State cycle | basemap (3 states), exaggerate (3 states) | carries state, gets the orange `is-on` |
| One-shot action | reset, fullscreen | happens once |

All three are styled identically and sit shoulder to shoulder. Nothing signals that
`RESET VIEW` throws away the camera you just set up while `SATELLITE` is a mode.

### A cycle that names its current state does not scale past two

The code comment defends naming what is on screen rather than what comes next, and
**for a two-state toggle that is right**. But basemap is three states and exaggeration
is three states. With a cycle you cannot see the options, cannot tell how many presses
reach the one you want, and cannot jump. `×1 HEIGHT` at rest is a button announcing that
nothing is happening.

A segmented control fixes all of it and doubles as a legend for what is available.

**And `height` is used for two different things in the same panel.** The button means
*vertical exaggeration*; the caption beneath it discusses *height above the ground*.
Label it `EXAGGERATION` — or `⇕ ×1` — and the collision goes away.

### Size is inverse to frequency

`RESET VIEW` is the **widest** button at 87 px, in the far-right corner that is the prime
thumb position on a phone, for the action taken least often. Zoom, used constantly, is
26 px. Size the targets by how often they are pressed.

### No keyboard path to the view itself

The canvas carries an `aria-label` but is not focusable and takes no arrow keys, so the
ten buttons are the only keyboard route — and tab order walks all ten before reaching the
next section. Making the canvas focusable with arrow-key pan and tilt would let the six
nudge buttons disappear on desktop as well as mobile.

### Where each corner goes

The controls stay **overlaid on the map** — they belong to it, and lifting them into a
toolbar underneath would say otherwise. What changes is which corner holds what.

Moving the rose to the top right is right, and there is a better argument for it than
Earth's precedent: **`render_map.py:274` already does it.**

```python
map.addControl(new maplibregl.NavigationControl({visualizePitch: true}), 'top-right')
```

The project's other 3D view puts navigation top-right by MapLibre's own default. Two
viewers of the same flights should not disagree about where north lives.

**But the corner is occupied.** `.view3d-credit` is at `right: 12px; top: 12px` — exactly
where the rose would land — and the Esri/Maxar attribution is required, not optional. So
the move forces a reallocation:

| Corner | Today | Proposed |
|---|---|---|
| top-left | — | **attribution** |
| top-right | attribution | **the rose** — north, sun and wind |
| bottom-left | the rose | — (free) |
| bottom-right | buttons | buttons, unchanged |

Attribution to the top left is the robust choice: on a 360 px phone the bar is 327 px of
the 340 available, so anything else along the bottom edge collides with it. Bottom-left is
the more conventional home for attribution on a web map, and it works on desktop — but it
needs a media query to lift it above the bar on a phone. Top-left needs none.

### Proposed

```
  DESKTOP                                              ┌────┐
  ┌──────────────────────────────────────────────────┤ N ↑ ├─┐
  │ Imagery © Esri, Maxar                            │ ☀ 40°│ │
  │                                                  └────┘ │
  │                      terrain                            │
  │                                                         │
  │  ┌─────┬─────┬────────┐ ┌────┬────┬────┐    ┌─┬─┐ ┌─┐ ┌─┐│
  │  │ SAT │ MAP │ RELIEF │ │ ×1 │ ×2 │ ×4 │    │−│+│ │⛶│ │↺││
  │  └─────┴─────┴────────┘ └────┴────┴────┘    └─┴─┘ └─┘ └─┘│
  └─────────────────────────────────────────────────────────┘
     what the ground is      exaggeration        view   actions

  MOBILE — one row, 46 px tall, measured at a true 360 px ✓
  ┌──────────────────────────────────┬────┐
  │ Imagery © Esri…                  │ N ↑│
  │                                  └────┤
  │             terrain                   │
  │  ┌─────┬─────┬──────┐┌───┬───┬───┐┌──┐│
  │  │ SAT │ MAP │RELIEF││×1 │×2 │×4 ││⛶ ││
  │  └─────┴─────┴──────┘└───┴───┴───┘└──┘│
  └───────────────────────────────────────┘
      153 px          108 px         46 px   = 327 of 340 available
```

**Exaggeration stays on mobile.** Dropping it was wrong — a 295 px map is exactly where
relief is hardest to read, so ×2 earns its place more on a phone than on a desktop.
Measured with real device metrics: the two segments plus fullscreen come to **327 px in
one 46 px row at a true 360 px viewport** ✓, which is **15.6% of the panel** against
today's 20.2%. Exaggeration comes back *and* the bar still shrinks.

The margin at 360 px is 13 px, which is tight — worth knowing before anyone lengthens a
label. At 390 px there are 43 px spare.

The six nudge buttons go: on mobile entirely (pinch, drag and twist are native there and
the panel supports all three), on desktop down to the zoom pair, which is the one gesture
genuinely awkward on a trackpad — and with the keyboard bound, even that is a convenience
rather than the only route.

## Keyboard control of the view

Worth doing, and it is what lets the nudge buttons go. The canvas takes `tabindex="0"`
and already carries an `aria-label`; the page's existing `:focus-visible` rule gives it a
visible ring for free.

**Bind the keys to the same `data-view3d-act` names the buttons dispatch**, so there is
one code path rather than two that drift.

| Key | Does |
|---|---|
| `←` `→` | rotate left / right |
| `↑` `↓` | tilt up / down |
| `Shift` + arrows | pan |
| `+` `=` / `−` `_` | zoom in / out |
| `1` `2` `4` | exaggeration ×1 / ×2 / ×4 — **direct** |
| `S` `M` `R` | satellite / map / relief — **direct** |
| `F` | full screen |
| `0` | reset view |
| `?` | the shortcut list |
| `Esc` | leave full screen (the real API handles it) |

The `1 2 4` and `S M R` rows are the interesting ones: **the keyboard gives direct access
to a state, which the cycle buttons cannot.** Keyboard and segmented control agree with
each other; the cycle is the odd one out. That is a second, independent argument for the
segments.

### Three traps

**Arrow keys must not scroll the page.** `preventDefault()` only while the canvas holds
focus — otherwise tilting the terrain scrolls the report out from under it.

**Handlers must be per-panel and scoped to focus, never document-level.** A document holds
several flights, each with its own panel. `view3d.py` already carries a comment about one
panel's button driving another panel's numbers; a document-level `keydown` resurrects
exactly that bug.

**Held keys should reuse `holdGround`.** The buttons already anchor their repeat through
`holdGround(buttonHold, centre.cx, centre.cy)` (`view3d.py:1801`). Binding keys to the
same act names means a held arrow anchors identically instead of drifting — and it is why
binding to acts rather than to camera fields matters.

### Discoverability

A keyboard affordance nobody knows about is worth little. Two cheap moves: show a one-line
hint in the corner when the canvas takes focus — *arrows turn and tilt · ? for keys* — and
bind `?` to a small overlay listing the table above. The caption already teaches the
gestures; it should name the keys in the same breath.

## What not to break

- **No network at view time.** Findings are computed in Python and baked in.
- **`quicklook.py` gets a reduced set.** It already duplicates thresholds with no
  shared source; do not widen that seam more than necessary.
- **Degrade, do not blank.** No meteo means the ceiling findings do not exist —
  not an empty card. Same for a coarse KMZ and the turn-based findings.
- **Keep "How to read this, and what to distrust".** The debrief raises the
  trust stakes; that section is what pays for them.

## Phasing

**The debrief comes before the cuts.** The tempting order is to tidy first and add
the new layer afterwards, and it is the wrong way round: *which fields are redundant
is not knowable until the top layer exists.* If a finding reads "the four climbs
flown at 40 m radius averaged +0.6 against +1.4 for the three at 32 m", then
`RADIUS` has earned its place in the table as that finding's receipt. If nothing
ever cites `m/turn`, it is demotable and no one need argue about it. Build the
debrief first and the cut list stops being an opinion and becomes an observation.

**Phase 0 — the defects, whenever.** The 19 × 19 px tab close button, the 11 px type
floor, and `aria-label` on the six map buttons whose accessible name is currently a
glyph. Independent of everything else, small, and the close button is a real bug
rather than polish.

**Phase 1 — the debrief.** Verdict strip and 3–5 finding cards, ranked by cost,
from fields that already exist. Findings 3, 6 and 7 first: they are framing of
numbers already on the page, not new computation. This is the phase that changes
the product — if only one thing ships, it is this.

**Phase 2 — the cuts, informed by phase 1.** Climbs 16 → 8 and glides 7 → 6, with
the column list settled by what the findings actually cite. Stat tiles 10 → 6 with
the `MAX ALTITUDE` / `YOU REACHED` duplicate killed. The map bar down to two segmented
controls, a zoom pair and two icons; the rose to the top right and attribution to the top
left; keyboard bound to the same act names, which is what lets the nudge buttons go.
A media query for the tables.

**Phase 3 — comparison and linkage.** Cross-flight deltas on the stat tiles, and
*show me* wired into the existing linked cursor and the 3D view.
