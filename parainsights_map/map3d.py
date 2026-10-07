"""The 3D map: MapLibre's engine with deck.gl drawing over it, and the report's controls.

It began as the third of three renderers (October 2026) — the canvas view (`view3d`),
plain MapLibre, and this, merging what each was better at. From MapLibre: the whole
planet rather than one fetched rectangle, imagery and terrain streamed at every zoom,
and the replay slider. From the canvas view: the control bar, its keys, the sun and wind
rose, the climb and glide labels, the airspace boxes — and its imagery treatment: the
photograph shaded towards warm white and dark blue from the sun's real position, never
MapLibre's default black-and-white overlay that greys it. It is now the only one; the
comments below still say "the canvas" where a choice was made to match it.

It draws from the panel's scene and follows the linked cursor through the panel's handle
(`view3d.initView3d`: `handle.built`, and the wrapped `setCursor`). MapLibre and deck.gl
come from `render_map`'s loader, which also mounts this (`window.__openMap`).

Heights: MapLibre exaggerates terrain from sea level, so everything drawn above it is
scaled the same way — `alt × vertical` — or a track 500 m over a 1 000 m ridge would
sink into it at ×2.
"""

from pathlib import Path


STYLE = """
.merged-view .ml-map:focus-visible { outline: 2px solid var(--climb); outline-offset: -2px; }
.merged-view .m3-rose { position: absolute; top: 12px; right: 12px; z-index: 3;
  pointer-events: none; text-align: right; }
.merged-view .m3-rose svg { display: block; margin-left: auto; pointer-events: auto;
  cursor: pointer; }
.merged-view .m3-now[hidden] { display: none; }
.merged-view .m3-now { font-variant-numeric: tabular-nums; }
.merged-view .m3-now b { font-weight: 600; }
.merged-view .m3-rose p { margin: 4px 0 0; font-size: 11px; line-height: 1.3; color: #fff;
  /* A dark halo, several deep, so the text holds over the light relief as well as over
     the photograph: one soft shadow vanished against the pale ground. */
  text-shadow: 0 0 2px rgba(8,10,14,1), 0 0 3px rgba(8,10,14,1), 0 0 5px rgba(8,10,14,0.9),
    1px 1px 1px rgba(8,10,14,1), -1px -1px 1px rgba(8,10,14,1); }
.merged-view .m3-bottom { position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 3;
  display: flex; flex-wrap: wrap; align-items: center; gap: 5px; pointer-events: none; }
.merged-view .m3-bottom > * { pointer-events: auto; }
.merged-view .m3-bottom .view3d-controls { position: static; margin-left: auto; }
.merged-view .m3-replay { display: flex; gap: 5px; align-items: center; }
.merged-view .m3-replay[hidden], .merged-view .m3-time[hidden],
.merged-view .view3d-controls[hidden] { display: none; }
.merged-view .m3-bottom button, .merged-view .m3-rate { height: 30px; box-sizing: border-box; }
.merged-view .m3-icon { display: inline-flex; align-items: center; justify-content: center; }
.merged-view .m3-replay button { font: inherit; font-size: 11px; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 6px 9px; cursor: pointer; color: var(--ink-2);
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px; }
.merged-view .m3-replay button:hover { color: var(--ink); background: var(--panel-2); }
.merged-view .m3-replay button.is-on { background: var(--climb); border-color: var(--climb);
  color: var(--paper); }
.merged-view .m3-icon svg { display: block; }
.merged-view .m3-cycle { min-width: 3.2em; }
.merged-view .view3d-controls { flex-wrap: wrap; }
.merged-view .m3-speed { display: flex; align-items: center; }
.merged-view .m3-speed button { border-radius: 0; }
.merged-view .m3-speed button:first-child { border-radius: 2px 0 0 2px; }
.merged-view .m3-speed button:last-child { border-radius: 0 2px 2px 0; }
.merged-view .m3-speed button:disabled { opacity: 0.4; cursor: default; }
.merged-view .m3-rate { min-width: 64px; text-align: center; font-size: 12px; color: var(--ink);
  font-variant-numeric: tabular-nums; background: var(--panel); border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); padding: 5px 4px; }
.merged-view .m3-time { flex: 1 1 100%; display: flex; gap: 8px; align-items: center;
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px;
  padding: 3px 9px; font-size: 12px; color: var(--ink); font-variant-numeric: tabular-nums; }
.merged-view .m3-clock { white-space: nowrap; }
/* Two range inputs stacked on one track: each input ignores the pointer and only its
   thumb takes it, so either handle can be grabbed wherever the two sit. */
.merged-view .m3-range { position: relative; flex: 1; height: 22px; }
.merged-view .m3-range::before { content: ""; position: absolute; left: 0; right: 0; top: 9px;
  height: 4px; border-radius: 2px; background: var(--rule); }
.merged-view .m3-fill { position: absolute; top: 9px; height: 4px; border-radius: 2px;
  background: var(--climb); }
.merged-view .m3-range input { position: absolute; left: 0; top: 0; width: 100%; height: 22px;
  margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
.merged-view .m3-range input::-webkit-slider-runnable-track { background: none; height: 22px; }
.merged-view .m3-range input::-moz-range-track { background: none; }
.merged-view .m3-range input::-webkit-slider-thumb { -webkit-appearance: none; appearance: none;
  pointer-events: auto; width: 16px; height: 16px; margin-top: 3px; border-radius: 50%;
  background: var(--paper, #fff); border: 2px solid var(--climb); cursor: grab; }
.merged-view .m3-range input::-moz-range-thumb { pointer-events: auto; width: 12px; height: 12px;
  border-radius: 50%; background: var(--paper, #fff); border: 2px solid var(--climb); cursor: grab; }
@media (pointer: coarse) {
  .merged-view .m3-range input::-webkit-slider-thumb { width: 22px; height: 22px; margin-top: 0; }
}
.merged-view .m3-measure { position: absolute; left: 50%; transform: translateX(-50%); top: 12px;
  z-index: 3; margin: 0; white-space: nowrap;
  padding: 4px 9px; font-size: 12px; color: var(--ink); background: var(--panel);
  border: 1px solid var(--rule); border-radius: 2px; font-variant-numeric: tabular-nums; }
.merged-view .m3-measure[hidden] { display: none; }
.merged-view .m3-others { float: left; margin: 10px 0 0 10px; pointer-events: auto;
  max-width: calc(100vw - 200px);
  padding: 3px 8px; list-style: none; font-size: 11.5px; line-height: 1.5; color: var(--ink);
  background: var(--panel); border: 1px solid var(--rule); border-radius: 2px; }
.merged-view .m3-others[hidden] { display: none; }
.merged-view .m3-others i { display: inline-block; width: 14px; height: 3px; margin: 0 7px 3px 0;
  vertical-align: middle; border-radius: 2px; }
.merged-view .m3-others li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.merged-view .m3-others .is-own { font-weight: 600; }
.merged-view .m3-others .is-far { color: var(--ink-3); }
.merged-view .m3-status { position: absolute; left: 12px; top: 34px; z-index: 3; margin: 0;
  font-size: 12px; color: var(--ink-2); }
/* MapLibre's own credits, the openable kind: an (i) at the top left that opens to name
   every source on screen, after the legend of compared flights in the same row. At the
   bottom left it never lined up with the bar beside it. */
.merged-view .maplibregl-ctrl-top-left { z-index: 4; }
/* MapLibre stacks each corner control on a line of its own (`clear: both`); the (i) sits
   beside the legend instead. */
.merged-view .maplibregl-ctrl-top-left .maplibregl-ctrl { clear: none; }
.merged-view .maplibregl-ctrl-attrib { font-size: 11px; }
/* Last, so it wins over the rules above it at equal specificity. */
/* A phone: the bar stays one row; where it and the replay buttons do not fit side by
   side, the bar wraps under them, still at the right. */
@media (max-width: 640px) {
  .merged-view .view3d-controls { flex-wrap: nowrap; justify-content: flex-end; }
}
"""

SCRIPT = (Path(__file__).parent / "js/map3d.js").read_text(encoding="utf-8")
