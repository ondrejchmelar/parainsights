"""The `+ your track` panel: where a reader drops their own file.

It holds no analysis. A dropped file is read, analysed and written up by `js/upload.js` —
the same `compose` the report's own flights were rendered with at build time
(`js_build.py`) — and placed after the last flight with a tab of its own. This replaced
`quicklook.py`, which carried a second, reduced analysis in JavaScript with its own
charts, tables and DEM loader: everything an upload now gets in full.

The ids keep their `ql-` prefix from then; they are only ids.

**It is also the page's start** (November 2026): the Flights page opens on no flight, with
this panel where the map would be and the showcase flights offered beside it. Opened on a
showcase flight the reader had not chosen, the page did not say that their own was the
point. On a desktop the showcase is a row of cards under the band, so it grows by rows as
flights are added; on a phone it sits inside the band, both doors on the first screen —
the pilot's pick of the two mocks for each.
"""


from __future__ import annotations
import base64
from html import escape
from pathlib import Path

# The band's ground: a blurred photograph of the Dolomites, so the empty slot reads as
# where the map will be. 14 KB inlined, as the page carries everything it needs.
GROUND = base64.b64encode((Path(__file__).parent / "assets" / "start-ground.jpg").read_bytes()).decode()

STYLE = """
/* The start: a heading, the band where the map will be, the showcase. ------------ */
.start-head { margin: 28px 0 22px; }
.start-head h1 { font-size: 40px; line-height: 1.15; }
.start-head p { margin: 8px 0 0; color: var(--ink-2); font-size: 17px; max-width: 46em; }
/* The ground's colours are fixed, whatever the theme: it is a photograph, as the map is. */
.start-ground { padding: 88px 16px; box-sizing: border-box; display: flex; justify-content: center;
  background: linear-gradient(rgba(10,12,10,.62), rgba(10,12,10,.72)),
    url(data:image/jpeg;base64,__GROUND__) center / cover, #1f2a1f; }
.start-drop { width: min(520px, 100%); box-sizing: border-box; text-align: center; color: #f2f0ea;
  border: 2px dashed rgba(255,255,255,.45); border-radius: 18px; padding: 36px 28px 28px;
  background: rgba(20,20,18,.55); }
.start-drop.is-over { border-color: var(--climb); background: rgba(20,20,18,.8); }
.start-icon { display: inline-grid; place-items: center; width: 64px; height: 64px; border-radius: 50%;
  background: rgba(232,105,44,.18); color: #f08a55; margin-bottom: 14px; }
.start-drop h2 { font-size: 26px; color: #fff; }
.start-drop p { margin: 6px 0 0; color: #d6d2c8; font-size: 16px; }
.start-pick { margin-top: 20px; font: inherit; font-weight: 650; font-size: 17px; padding: 12px 26px;
  border: 0; border-radius: 12px; background: #e8692c; color: #141412; cursor: pointer; min-height: 48px; }
.start-pick:hover { background: #f08a55; }
.start-pick:focus-visible { outline: 2px solid #fff; outline-offset: 3px; }
.start-drop .start-small { margin-top: 16px; font-size: 14px; color: #b9b5ab; }
.start-drop .ql-status { margin-top: 12px; font-size: 15px; color: #f2f0ea; }
.start-drop .ql-status:empty { display: none; }
.start-drop .ql-status.is-error { color: #f08a55; }
.start-drop details { margin-top: 12px; font-size: 14px; color: #b9b5ab; text-align: left; }
.start-drop summary { cursor: pointer; text-align: center; }
.start-drop details p { font-size: 14px; color: #b9b5ab; }
.showcase { max-width: 1180px; margin: 0 auto; padding: 0 28px; box-sizing: border-box; }
.showcase h2 { font-size: 22px; margin: 36px 0 14px; }
.showcase-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.showcase-card { position: relative; display: flex; flex-direction: column; gap: 2px; text-align: left;
  font: inherit; color: var(--ink); background: var(--panel); border: 1px solid var(--edge);
  border-radius: 14px; padding: 14px 44px 14px 16px; cursor: pointer; }
.showcase-card:hover { border-color: var(--accent); background: var(--panel-2); }
.showcase-site { font-size: 18px; font-weight: 650; }
.showcase-meta { font-size: 15px; color: var(--ink-2); }
.showcase-stat { font-size: 15px; font-weight: 600; margin-top: 4px; }
.showcase-go { position: absolute; right: 14px; top: 50%; transform: translateY(-50%); color: var(--ink-2); }
.showcase-go svg { display: block; }
/* A phone: the showcase moves into the band, under the drop, both on the first screen. */
@media (max-width: 640px) {
  .start-head { margin: 18px 0 16px; }
  .start-head h1 { font-size: 30px; }
  .start-band { background: linear-gradient(rgba(10,12,10,.62), rgba(10,12,10,.72)),
    url(data:image/jpeg;base64,__GROUND__) center / cover, #1f2a1f; padding-bottom: 24px; }
  .start-ground { background: none; padding: 24px 14px 0; }
  .start-drop { padding: 26px 18px 20px; }
  .showcase { padding: 0 14px; }
  .showcase h2 { color: #fff; font-size: 20px; margin: 24px 0 10px; }
  .showcase-list { grid-template-columns: 1fr; gap: 10px; }
  .showcase-card { background: rgba(20,20,18,.78); border-color: rgba(255,255,255,.22); color: #f2f0ea; }
  .showcase-card:hover { background: rgba(20,20,18,.9); }
  .showcase-meta, .showcase-go { color: #c9c5bb; }
}
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
.start-drop .ql-status.is-busy::before { border-color: rgba(255,255,255,.3); border-top-color: #fff; }
""".replace("__GROUND__", GROUND)

UPLOAD_ICON = ('<svg width="34" height="34" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
               'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
               '<path d="M10 13V3M6 7l4-4 4 4M3 13v3h14v-3"/></svg>')
GO_ICON = ('<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
           'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
           '<path d="M7 4l6 6-6 6"/></svg>')


def showcase_card(uid: str, site: str, meta: str, stat: str) -> str:
    """One showcase flight on the start: a press opens it, with its tab."""
    return (f'<button type="button" class="showcase-card" data-showcase-open="{uid}">'
            f'<span class="showcase-site">{escape(site)}</span>'
            f'<span class="showcase-meta">{escape(meta)}</span>'
            f'<span class="showcase-stat">{escape(stat)}</span>'
            f'<span class="showcase-go">{GO_ICON}</span></button>')


def group_card(uids: list[str], site: str, meta: str, stat: str) -> str:
    """Several showcase flights as one card: a press opens them all, compared."""
    return (f'<button type="button" class="showcase-card" '
            f'data-showcase-group="{" ".join(uids)}">'
            f'<span class="showcase-site">{escape(site)}</span>'
            f'<span class="showcase-meta">{escape(meta)}</span>'
            f'<span class="showcase-stat">{escape(stat)}</span>'
            f'<span class="showcase-go">{GO_ICON}</span></button>')


def panel(showcase: list[str] = ()) -> str:
    """The start: the drop where the map will be, and the showcase flights (`showcase_card`).
    The `+ your track` tab comes back to it."""
    cards = (f'<div class="showcase"><h2>Or open a showcase flight</h2>'
             f'<div class="showcase-list">{"".join(showcase)}</div></div>') if showcase else ""
    return f"""
  <article class="flight" data-flight-report="own" id="quicklook">
    <header class="start-head">
      <h1>How did your flight go?</h1>
      <p>Climbs, glides, the route as scored, and what could be improved, from your own track.</p>
    </header>
    <div class="flight-map start-band">
      <div class="start-ground">
        <div class="start-drop" id="ql-drop">
          <input type="file" id="ql-file" accept=".igc,.IGC,.kml,.kmz" multiple hidden>
          <div class="start-icon">{UPLOAD_ICON}</div>
          <h2>Drop your flight here</h2>
          <p>IGC, KML or KMZ from your vario or XContest</p>
          <button type="button" class="start-pick" id="ql-pick">Choose a file</button>
          <p class="ql-status" id="ql-status" role="status" aria-live="polite"></p>
          <p class="start-small">Nothing is uploaded: the file is read and analysed in your browser.</p>
          <details><summary>Why IGC rather than KMZ</summary>
            <p>A KMZ downloaded from a scoring site is usually reduced to 500 points — every
            few minutes on a long flight. Distances, height gained and turn counts are all
            measured along the track, so they come out low, and turns cannot be counted at
            all. The IGC your instrument recorded is the file to use.</p></details>
        </div>
      </div>
      {cards}
    </div>
  </article>"""


SCRIPT = (Path(__file__).parent / "page/upload_panel.js").read_text(encoding="utf-8")
