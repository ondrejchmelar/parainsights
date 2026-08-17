# The meteo page's UX, measured — and the rework it asked for

`docs/ux-review.md` did this for the report: measure the page, name what it costs the
reader, then change it. This is the same exercise for `public/meteo/`, and it has one
finding big enough that the rest are footnotes to it.

Everything below is measured in a real browser at 1280×900 on the real page, before and
after. The "before" is the page as of commit `94b4aa9`; the "after" is what is in the
tree now.

## The one finding

> **The page's furniture was a list nobody reads twice, and it was standing in front of
> the answer.**

159 takeoffs in a scrolling column, pinned to the top-left for as long as the page was
open. Measured:

| | before | after |
|---|---|---|
| height of the picker on the page | **571 px** (capped at 70vh, so it scaled with the window) | **37 px** — one row of chips |
| width left for the panel that answers the question | 742 px | **1 100 px** |
| the meteogram, the page's main chart | 432 × 180 px | **790 × 329 px** (+83% wide) |
| tab stops before reaching the panel | **166** | **11** |
| takeoffs comparable at once | 1 | 3 |

The tab-stop number is the one that should sting. Every one of those 159 rows was a
`<button>`, they came before the panel in the DOM, and they were all in the tab order —
so a keyboard user pressed Tab **166 times** to get from the top of the page to the
sounding. Not a rounding error and not a taste question: it is the page telling anyone
not using a mouse that the list matters more than the forecast.

And the list is a *directory*. A reader consults it when they arrive and never again in
that session — the definition of something that belongs behind a control rather than in
the layout. The space it took was charged against the only thing on the page with
numbers in it.

## What the rework does

**The list moved into a `<dialog>`.** Opened deliberately by `+ add a takeoff`,
searchable rather than scrollable, closed again. A real `<dialog>` rather than an
overlay: Escape closes it, the backdrop closes it, focus stays inside it and the page
behind it goes inert — four behaviours a hand-rolled div has to reimplement and usually
gets two of. Closed, its contents are out of the tab order, which is where the 166
becomes 11.

**Up to three takeoffs at once, and the page compares them.** This is the question the
page was already trying to answer — *is it worth driving anywhere, and where* — and the
old one could only answer it one hill at a time, by memory. Now:

* a **chip** per chosen takeoff, coloured, click to focus, `×` to drop;
* a **comparison table** at the chosen hour: verdict, wind, thermal top, cloudbase, the
  lid, and the ground each one stands on. The best thermal top and the best cloudbase
  are marked, because three numbers in a column are three numbers until one of them is
  the answer;
* a **strip carrying all three boundary layers**, one line each, so the comparison is
  *when* each hill works and not only how high it goes. That is the chart that could not
  be built while the page held one site at a time, and it is the reason the rework is
  worth more than the space it saved. It went through one bad version first: the same
  frame also carried the *focused* takeoff's cloud, ground and cloudbase, so two thirds
  of it was about three hills and one third about one, unlabelled. Everything that
  belongs to a single takeoff now lives in that takeoff's column;
* a **meteogram and a sounding each, side by side** — small multiples, not one frame with everything on
  it. Three temperature traces and three dew points on one set of axes is six crossing
  lines and no comparison; three small columns is the shape of each day, readable at a
  glance. The probe height is *shared*: point at 1 500 m over one hill and all three read
  1 500 m, which is the question being asked of all of them at once;
* **flymet's meteogram for each**, one per *station* rather than per takeoff — two hills
  15 km apart share their nearest airfield more often than not in a country this size,
  and the same picture twice under two headings reads as a bug in the page and costs
  flymet a second fetch to say the same thing.

**Three, and the number came from the palette rather than from taste.** Slots 1–3 of the
design system's categorical order — the blue, orange and aqua the report paints phases
with — pass every check in `validate_palette.js` on the all-pairs list in both themes
(CVD ΔE 9.2 light / 9.4 dark, normal vision 24.0 / 20.9, measured against this page's own
panel colour). The documented fourth slot is yellow, and yellow against this orange fails
the normal-vision floor at ΔE 13.7. Re-stepping a documented palette is not allowed and
no reordering fixes an all-pairs failure, so the honest cap is three — and a fourth line
nobody could tell from the third would have been a worse answer than a limit. The page
says *three at a time* rather than silently evicting a takeoff the reader chose.

Two of the three light-mode series sit under 3:1 against the panel, which the palette's
relief rule permits only where identity is carried by something that is not colour. Here
it is carried three times: a label at the end of each line, the legend under the chart,
and the comparison table. A browser test asserts it.

**The hour moved into the head.** It sat under the sounding, where it read as a control
for that one chart; it actually sets the hour for the ranking, the comparison and both
charts. Above everything, it looks like what it is.

**The chosen takeoffs are remembered.** A pilot checks the same two or three hills all
season; making them pick again every morning is the kind of small rudeness that makes a
tool feel like a demo. `localStorage`, validated on read — the site list is regenerated
from ParaglidingEarth and a stale index could point anywhere — and wrapped, because some
browsers throw on even reading it from a `file://` page and a page that fails to load
because it could not remember something is worse than one that forgets.

**flymet's meteogram folds.** It is a second opinion worth having in front of the reader,
and it is also 768 px of someone else's chart under 329 px of ours. It is a `<details>`,
open by default, so the default is unchanged and one click puts it away.

## Smaller things, fixed in passing

* **The cloudbase line escaped the chart.** A 4 290 m cloudbase on a chart that stops at
  4 000 drew a dashed line across the caption above it, which reads as a rendering fault
  rather than as *higher than this chart goes*. The lines are clipped to the plot box now
  and the labels are clamped into it.
* **Two lines could share a label position.** On a good day two hills top out within a few
  metres of each other; the direct labels are pushed apart and drawn on a pad, because a
  label read against a line is a label read twice.
* **A legend entry for a line that is not drawn yet** now says `fetching…` rather than
  naming a line the reader cannot find.
* **Adding a takeoff redraws immediately** rather than when its sounding lands. A control
  that does nothing for a second is a control the reader presses again.
* **The status line no longer reserves space when it is empty** (`:empty { display:none }`).

## What was deliberately left alone

* **The verdict rule.** Two gates on the site's own recorded wind rose, and no judgement
  at all for a takeoff that records none. It is the one judgement the page makes and this
  review found nothing wrong with it.
* **The sounding's size.** 260 px is small, and it is the right small: it is a shape to
  read, not a chart to measure off, and the numbers under the pointer are exact.
* **Four days.** The strip offers today, tomorrow and two more; flymet only has two, and
  the page already says so by showing nothing for the others rather than yesterday's
  picture under a Thursday heading.

## What this cost

The document got taller: 1 584 px to 1 939 px with one takeoff chosen. Almost all of it
is flymet's picture growing with the panel it sits in (708 → 1 024 px wide), which is
also the thing that now folds. The page's own charts got 83% wider in exchange, and the
reader stopped scrolling past a directory to reach them.
