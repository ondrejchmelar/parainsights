"""The `+ your track` panel: where a reader drops their own file.

It holds no analysis. A dropped file is read, analysed and written up by `js/upload.js` —
the same `compose` the report's own flights were rendered with at build time
(`js_build.py`) — and placed after the last flight with a tab of its own. This replaced
`quicklook.py`, which carried a second, reduced analysis in JavaScript with its own
charts, tables and DEM loader: everything an upload now gets in full.

The ids keep their `ql-` prefix from then; they are only ids.
"""


from __future__ import annotations
from pathlib import Path

STYLE = """
.ql-drop { padding: 20px 22px; display: flex; align-items: center; gap: 14px;
  flex-wrap: wrap; border-style: dashed; }
.ql-drop.is-over { border-color: var(--climb); background: var(--panel-2); }
.ql-button {
  font: inherit;
  font-size: 12.5px;
  font-family: 'NarrowDisplay', "Liberation Sans Narrow", ui-sans-serif, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 8px 16px;
  border: 1px solid var(--ink);
  border-radius: 2px;
  background: var(--ink);
  color: var(--paper);
  cursor: pointer;
}
.ql-button:hover { background: var(--climb); border-color: var(--climb); }
.ql-hint { color: var(--ink-3); font-size: 12.5px; }
.ql-note-inline { flex-basis: 100%; margin: 2px 0 0; font-size: 12.5px; color: var(--ink-3);
  max-width: 74ch; }
.ql-status { margin: 0; font-size: 12.5px; color: var(--ink-2); flex-basis: 100%; }
.ql-status.is-error { color: var(--climb); }
/* A CSS transform animation, which the compositor keeps turning while the analysis holds
   the main thread; a JavaScript-driven spinner would freeze exactly then. */
.ql-status.is-busy::before {
  content: ""; display: inline-block; width: 11px; height: 11px; margin: 0 7px -1px 0;
  border: 2px solid var(--rule, currentColor); border-top-color: var(--ink, currentColor);
  border-radius: 50%; animation: ql-spin .8s linear infinite;
}
@keyframes ql-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .ql-status.is-busy::before { animation-duration: 2.4s; } }
"""


def panel() -> str:
    """The drop panel: a fixed article the `+ your track` tab shows."""
    return """
  <article class="flight" data-flight-report="own" id="quicklook" hidden>
    <header class="masthead">
      <div>
        <p class="eyebrow">tracklog viewer</p>
        <h1>Your own tracks</h1>
      </div>
    </header>
    <div class="section-head" style="margin-top:26px">
      <h2>Read in this page</h2>
      <p>Nothing is uploaded: the file is parsed and analysed here, and gets the same
         write-up as the flights above. Each track you add gets its own tab, and the
         &times; on a tab removes that flight again.</p>
    </div>
    <div class="panel ql-drop" id="ql-drop">
      <input type="file" id="ql-file" accept=".igc,.IGC,.kml,.kmz" multiple hidden>
      <button type="button" class="ql-button" id="ql-pick">Choose track files</button>
      <span class="ql-hint"><strong>.igc preferred</strong> &middot; or drag them
        here &middot; .kml and .kmz also read</span>
      <p class="ql-note-inline">A KMZ downloaded from a scoring site is usually reduced to
        500 points — every few minutes on a long flight. Distances, height gained and turn
        counts are all measured along the track, so they come out low, and turns cannot be
        counted at all. The IGC your instrument recorded is the file to use.</p>
      <p class="ql-status" id="ql-status" role="status" aria-live="polite"></p>
    </div>
  </article>"""


SCRIPT = (Path(__file__).parent / "page/upload_panel.js").read_text(encoding="utf-8")
