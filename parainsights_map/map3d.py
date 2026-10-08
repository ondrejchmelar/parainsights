"""The 3D map: MapLibre's engine with deck.gl drawing over it, and the report's controls.

It began as the third of three renderers (October 2026) — the canvas view (`view3d`),
plain MapLibre, and this, merging what each was better at. From MapLibre: the whole
planet rather than one fetched rectangle, imagery and terrain streamed at every zoom,
and the replay slider. From the canvas view: the control bar, its keys, the sun and wind
rose, the climb and glide labels, the airspace boxes — and its imagery treatment: the
photograph shaded towards warm white and dark blue from the sun's real position, never
MapLibre's default black-and-white overlay that greys it. It is now the only one; the
comments in `js/map3d.js` say "the canvas" where a choice was made to match the
renderer that is gone.

It draws from the panel's scene and follows the linked cursor through the panel's handle
(`view3d.initView3d`: `handle.built`, and the wrapped `setCursor`). MapLibre and deck.gl
come from `render_map`'s loader, which also mounts this (`window.__openMap`).

Heights: MapLibre exaggerates terrain from sea level, so everything drawn above it is
scaled the same way — `alt × vertical` — or a track 500 m over a 1 000 m ridge would
sink into it at ×2.
"""

from pathlib import Path


STYLE = """
.merged-view .ml-map:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
/* The compass, the sun and the wind: one floating panel at the top right, in the page's
   type. On a phone the compass alone — the sentence would cover a third of the map. */
.merged-view .m3-rose { position: absolute; top: 10px; right: 10px; z-index: 3; display: flex;
  flex-direction: row-reverse; align-items: center; gap: 10px; padding: 4px 4px 4px 14px;
  background: var(--float); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid var(--float-edge); border-radius: 14px; box-shadow: var(--float-shadow);
  pointer-events: none; text-align: right; }
.merged-view .m3-rose[hidden] { display: none; }
.merged-view .m3-rose svg { display: block; width: 52px; height: 52px; pointer-events: auto; cursor: pointer; }
.merged-view .m3-now[hidden] { display: none; }
.merged-view .m3-now { font-variant-numeric: tabular-nums; }
.merged-view .m3-now b { font-weight: 600; }
.merged-view .m3-rose p { margin: 0; font: 600 15px/1.35 "Noto Sans", ui-sans-serif, system-ui, sans-serif;
  color: var(--ink); }
.merged-view .m3-rose p:empty { display: none; }
@media (max-width: 640px) {
  .merged-view .m3-rose { padding: 4px; }
  .merged-view .m3-rose p { display: none; }
}
.merged-view .m3-bottom { position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 3;
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px; pointer-events: none; }
.merged-view .m3-bottom > * { pointer-events: auto; }
.merged-view .m3-bottom .view3d-controls { position: static; margin-left: auto; }
.merged-view .m3-replay { display: flex; gap: 6px; align-items: center; }
.merged-view .m3-replay[hidden], .merged-view .m3-time[hidden],
.merged-view .view3d-controls[hidden] { display: none; }
.merged-view .m3-icon { display: inline-flex; align-items: center; justify-content: center; }
.merged-view .m3-cycle { min-width: 3.2em; }
.merged-view .m3-speed { display: flex; align-items: center; border-radius: 10px; box-shadow: var(--float-shadow); }
.merged-view .m3-speed button { border-radius: 0; box-shadow: none; }
.merged-view .m3-speed button:first-child { border-radius: 10px 0 0 10px; }
.merged-view .m3-speed button:last-child { border-radius: 0 10px 10px 0; }
.merged-view .m3-speed button:disabled { opacity: 0.4; cursor: default; }
.merged-view .m3-rate { height: var(--mh); box-sizing: border-box; min-width: 64px; display: inline-flex;
  align-items: center; justify-content: center; font-size: 15px; color: var(--ink);
  font-variant-numeric: tabular-nums; background: var(--float); border-top: 1px solid var(--float-edge);
  border-bottom: 1px solid var(--float-edge); padding: 0 6px; }
.merged-view .m3-time { flex: 1 1 100%; display: flex; gap: 10px; align-items: center; min-height: var(--mh);
  background: var(--float); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid var(--float-edge); border-radius: 10px; box-shadow: var(--float-shadow);
  padding: 2px 12px; font-size: 15px; color: var(--ink); font-variant-numeric: tabular-nums; }
.merged-view .m3-clock { white-space: nowrap; }
/* Two range inputs stacked on one track: each input ignores the pointer and only its
   thumb takes it, so either handle can be grabbed wherever the two sit. */
.merged-view .m3-range { position: relative; flex: 1; height: 26px; }
.merged-view .m3-range::before { content: ""; position: absolute; left: 0; right: 0; top: 11px;
  height: 4px; border-radius: 2px; background: var(--edge); }
.merged-view .m3-fill { position: absolute; top: 11px; height: 4px; border-radius: 2px; background: var(--accent); }
.merged-view .m3-range input { position: absolute; left: 0; top: 0; width: 100%; height: 26px;
  margin: 0; background: none; pointer-events: none; -webkit-appearance: none; appearance: none; }
.merged-view .m3-range input::-webkit-slider-runnable-track { background: none; height: 26px; }
.merged-view .m3-range input::-moz-range-track { background: none; }
.merged-view .m3-range input::-webkit-slider-thumb { -webkit-appearance: none; appearance: none;
  pointer-events: auto; width: 20px; height: 20px; margin-top: 3px; border-radius: 50%;
  background: #fff; border: 2px solid var(--accent); cursor: grab; }
.merged-view .m3-range input::-moz-range-thumb { pointer-events: auto; width: 16px; height: 16px;
  border-radius: 50%; background: #fff; border: 2px solid var(--accent); cursor: grab; }
@media (pointer: coarse) {
  .merged-view .m3-range input::-webkit-slider-thumb { width: 24px; height: 24px; margin-top: 1px; }
}
.merged-view .m3-measure { position: absolute; left: 50%; transform: translateX(-50%); top: 10px;
  z-index: 3; margin: 0; white-space: nowrap; padding: 8px 12px; font-size: 15px; color: var(--ink);
  background: var(--float); border: 1px solid var(--float-edge); border-radius: 10px;
  box-shadow: var(--float-shadow); font-variant-numeric: tabular-nums; }
.merged-view .m3-measure[hidden] { display: none; }
/* The flights compared with this one, under the labels at the top left. */
.merged-view .m3-others { margin: 0; pointer-events: auto; max-width: calc(100vw - 200px);
  padding: 6px 12px; list-style: none; font-size: 15px; line-height: 1.5; color: var(--ink);
  background: var(--float); border: 1px solid var(--float-edge); border-radius: 10px; box-shadow: var(--float-shadow); }
.merged-view .m3-others[hidden] { display: none; }
.merged-view .m3-others i { display: inline-block; width: 14px; height: 3px; margin: 0 7px 3px 0;
  vertical-align: middle; border-radius: 2px; }
.merged-view .m3-others li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.merged-view .m3-others .is-own { font-weight: 600; }
.merged-view .m3-others .is-far { color: var(--ink-2); }
.merged-view .m3-status { position: absolute; left: 12px; top: 56px; z-index: 3; margin: 0;
  font-size: 15px; color: var(--ink-2); }
/* MapLibre's credits. The page's footer names every source, so on the page the (i) is
   one help symbol too many; in full screen, where the footer is out of sight, it is back. */
.merged-view .maplibregl-ctrl-attrib { display: none; font-size: 13px; }
:fullscreen .merged-view .maplibregl-ctrl-attrib, .is-maximised .merged-view .maplibregl-ctrl-attrib,
.merged-view:fullscreen .maplibregl-ctrl-attrib { display: block; }
.merged-view .maplibregl-ctrl-bottom-left { z-index: 2; }
"""

SCRIPT = (Path(__file__).parent / "js/map3d.js").read_text(encoding="utf-8")
