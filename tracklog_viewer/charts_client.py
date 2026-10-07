"""The side view and the top view, drawn in the browser instead of baked into the article.

These two were the report's biggest charts and its biggest bytes: nine profile SVGs at
577 KB and three plan views at 153 KB on the published three-flight report, 24% of it,
nine because the axis toggle shipped all three modes and hid two. What replaces them is
the payload `js/charts.js` writes into each article (about 20 KB a flight) and the one
renderer here.

Two rules keep it honest:

* **It builds the DOM the report is written against.** Same element order, class names
  and `data-` attributes as the SVG it replaced, so the linked cursor, the tooltip, the
  band highlight, "show me" from a debrief card and both themes work on it unchanged.
* **One sample, shared.** The trace is drawn through the same indices the cursor is
  indexed by; two independently decimated samples put the marker on a different moment
  than the one under the pointer.

This module is only the stylesheet and the script (`page/charts.js`); the payload is
`TV.charts.payload`.
"""


from __future__ import annotations
from pathlib import Path


STYLE = """
/* The two big charts are drawn into these when the page loads. The height is reserved
   from the payload's own aspect ratio, so the page does not jump when they appear —
   a chart that lands 400 px tall into a 0 px box moves everything under it. */
.chart-host { display: block; width: 100%; }
.chart-host > svg { display: block; width: 100%; height: auto; }
.chart-missing { padding: 22px 16px; color: var(--ink-3); font-size: 13.5px; }
"""

SCRIPT = (Path(__file__).parent / "page/charts.js").read_text(encoding="utf-8")
