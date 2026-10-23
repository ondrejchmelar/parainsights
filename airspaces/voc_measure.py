"""Measure each published traffic circuit off its AIP VOC chart, and write `voc.py`.

Not part of the build: it reads 157 chart JPEGs and wants pillow, numpy and scipy, none
of which the package depends on. Run it when the charts change:

    uv run --with pillow,numpy,scipy python -m airspaces.voc_measure fetch
    uv run --with pillow,numpy,scipy python -m airspaces.voc_measure scale
    uv run --with pillow,numpy,scipy python -m airspaces.voc_measure fit
    uv run --with pillow,numpy,scipy python -m airspaces.voc_measure sheets
    # look at every sheet; correct airspaces/voc_verdicts.txt
    uv run --with pillow,numpy,scipy python -m airspaces.voc_measure write

**How a chart is read.** Every `{ident}_voc.jpg` is north-up — the bearing between two
ATZ centres on one chart matches the true bearing to 0.01° — and centred on the field's
reference point. It is drawn at one of three scales: 16.85, 21.17 or 26.8 m a pixel,
steps of 1.26, the same base map enlarged. **The scale is not constant**, which is what
the first measurement (LKCAST against an ATZ ring it does not have) got wrong. It is
read here from the map's village marks, a fixed symbol whose size steps with the scale
(about 20, 16 and 12 px), and checked wherever another airfield's symbol is on the chart
at a known bearing and distance; the two agree to 3% everywhere both exist. Ten charts
have no village marks to read and keep the standard box.

**How a circuit is found.** The chart is resampled into the runway's own frame — along
it from the midpoint, across it — and the circuit's dark blue (the colour is the chart's
own, shared only with labels and some airspace boundaries) is summed along rows and
columns. A leg is a peak; a rectangle is four legs whose edges are actually drawn over
70% of their middle. That rejects the labels, which are blue too but not lines. The
frame may turn a few degrees (twelve where the runway is reconstructed) to the angle
that makes the legs sharpest, because at an SLZ strip the chart knows the runway's
direction better than its rounded designator does.

**Every fit was looked at.** `sheets` draws each runway's chart with the fit on it;
`voc_verdicts.txt` records, runway by runway, `ok` (the fit is the circuit), `manual`
(read off the gridded sheet by eye, to about 50 m), `none` (no circuit of its own: a
parallel or duplicate runway whose sibling carries it) or `default` (no rectangle).

**Anything not a rectangle is traced by hand** (`voc_shapes.txt`, October 2026): the
chart's blue lines thinned to their centrelines on a 100 m grid, and the outline read
off corner by corner — a slanted leg (LKKRAM), a teardrop (LKMB, LKLB), crossing boxes
(LKCH, LKPN), a hook a one-way strip publishes instead of a loop (LKCHOR, LKHATH). A
traced runway overrides its rectangle fit. A chart that draws no circuit at all gets no
band (LKBYNO, LKCDUB, LKLIBA, LKLOUC, LKNUCI, LKNVCE, LKPOCA, LKPOLE, LKPRIM, LKTRBH:
`none`, October 2026, the pilot's call). What is still on the standard box: the ten with no scale to read (village marks), and LKMI and
LKPC, whose drawn circuit is kilometres from the runway.
"""

from __future__ import annotations

import itertools
import json
import math
import pprint
import sys
import urllib.request
from pathlib import Path

WORK = Path.home() / ".cache" / "parainsights" / "voc"
VERDICTS = Path(__file__).with_name("voc_verdicts.txt")
SHAPES = Path(__file__).with_name("voc_shapes.txt")
OUTPUT = Path(__file__).with_name("voc.py")
CHART = "https://aim.rlp.cz/vfrmanual/actual/ad/{ident}_voc.jpg"

# Village-mark size in pixels → metres a pixel. Measured against charts whose scale
# is known from a fitted ATZ ring or two neighbouring airfields.
LEVELS = {20.0: 16.85, 16.0: 21.17, 12.5: 26.8}
OUT_M = 10.0                      # the runway-frame panel's metres a pixel
HALF_ALONG, HALF_ACROSS = 4500, 3500


def fields() -> dict:
    """Every aerodrome the build knows, with its runways, keyed by lowercase ident."""
    from . import build

    overlay = build.build(with_circuits=False)
    out = {}
    for icao, f in overlay.fields.items():
        if f.lat is None:
            continue
        out[icao.lower()] = dict(
            lat=f.lat, lon=f.lon,
            runways=[dict(name=r.name, low=(r.low_lat, r.low_lon),
                          high=(r.high_lat, r.high_lon), est=r.estimated)
                     for r in f.runways])
    return out


def _en(lat, lon, lat0, lon0):
    return ((lon - lon0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 110574)


def _image(ident):
    from PIL import Image

    return Image.open(WORK / f"{ident}.jpg").convert("RGB")


def fetch(known):
    WORK.mkdir(parents=True, exist_ok=True)
    for ident in known:
        path = WORK / f"{ident}.jpg"
        if path.exists():
            continue
        try:
            path.write_bytes(urllib.request.urlopen(CHART.format(ident=ident), timeout=60).read())
        except OSError as error:
            print(ident, "no chart:", error)


def _village_marks(ident):
    """Median diameter of the dark rings with a white centre that mark villages."""
    import numpy as np
    from scipy import ndimage

    a = np.asarray(_image(ident)).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dark = (r < 110) & (g < 110) & (b < 110) & (abs(r - g) < 25) & (abs(g - b) < 25)
    lab, _ = ndimage.label(dark)
    sizes = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (8 <= h <= 40 and abs(h - w) <= 2):
            continue
        comp = lab[sl] == i
        filled = ndimage.binary_fill_holes(comp)
        if filled.sum() - comp.sum() > 0.15 * filled.sum():
            sizes.append((h + w) / 2)
    return float(np.median(sizes)) if sizes else None


def _symbol_scale(ident, known):
    """Metres a pixel from other SLZ fields' dark red symbols at their known places."""
    import numpy as np
    from scipy import ndimage

    a = np.asarray(_image(ident)).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lab, _ = ndimage.label(ndimage.binary_closing(
        (r > 70) & (r < 150) & (g < 70) & (b < 70), np.ones((3, 3))))
    H, W = r.shape
    c = known[ident]
    found = []
    for sl in ndimage.find_objects(lab):
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (30 <= h <= 70 and 30 <= w <= 70 and abs(h - w) < 10):
            continue
        dx = (sl[1].start + sl[1].stop) / 2 - W / 2
        dy = (sl[0].start + sl[0].stop) / 2 - H / 2
        dp = math.hypot(dx, dy)
        if dp < 100:
            continue
        for other, v in known.items():
            if other == ident:
                continue
            e, n = _en(v["lat"], v["lon"], c["lat"], c["lon"])
            turn = (math.degrees(math.atan2(e, n)) - math.degrees(math.atan2(dx, -dy)) + 180) % 360 - 180
            if abs(turn) < 0.8 and 12 < math.hypot(e, n) / dp < 30:
                found.append(math.hypot(e, n) / dp)
    return float(np.median(found)) if found else None


def scale(known):
    out = {}
    for ident in known:
        if not (WORK / f"{ident}.jpg").exists():
            continue
        mark = _village_marks(ident)
        by_marks = LEVELS[min(LEVELS, key=lambda k: abs(k - mark))] if mark else None
        by_symbols = _symbol_scale(ident, known)
        if by_symbols and (not by_marks or abs(by_symbols - by_marks) / by_symbols < 0.05):
            out[ident] = round(by_symbols, 2)
        else:
            out[ident] = by_marks
        print(ident, mark, by_marks, by_symbols)
    (WORK / "scale.json").write_text(json.dumps(out, indent=1))


def panel(ident, runway, mpx, turn=0.0):
    """The chart resampled into the runway frame, low end left, its left side up."""
    from PIL import Image

    src = _image(ident)
    W, H = src.size
    f = runway["_field"]
    le, ln = _en(*runway["low"], f["lat"], f["lon"])
    he, hn = _en(*runway["high"], f["lat"], f["lon"])
    me, mn = (le + he) / 2, (ln + hn) / 2
    length = math.hypot(he - le, hn - ln)
    t = math.radians(math.degrees(math.atan2(he - le, hn - ln)) + turn)
    ue, un = math.sin(t), math.cos(t)
    ve, vn = -un, ue
    w, h = int(2 * HALF_ALONG / OUT_M), int(2 * HALF_ACROSS / OUT_M)

    def source(x, y):
        a = (x - w / 2) * OUT_M
        c = (h / 2 - y) * OUT_M
        return W / 2 + (me + a * ue + c * ve) / mpx, H / 2 - (mn + a * un + c * vn) / mpx

    x0, y0 = source(0, 0)
    xa, ya = source(1, 0)
    xb, yb = source(0, 1)
    image = src.transform((w, h), Image.AFFINE, (xa - x0, xb - x0, x0, ya - y0, yb - y0, y0),
                          resample=Image.BILINEAR, fillcolor="white")
    return image, length


def _blue(image):
    import numpy as np

    a = np.asarray(image).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r < 70) & (g < 70) & (b > 110) & (b < 235)


def _peaks(profile, minimum, apart=12):
    import numpy as np

    p = np.convolve(profile, np.ones(3), "same")
    out = []
    for i in np.argsort(p)[::-1]:
        if p[i] < minimum:
            break
        if all(abs(i - j) > apart for j in out):
            out.append(int(i))
    return sorted(out)


def _drawn(m, x0, x1, y0, y1):
    """The least-drawn of the four edges: the fraction of its middle 70% that is blue."""
    xs0, xs1 = int(x0 + 0.15 * (x1 - x0)), int(x1 - 0.15 * (x1 - x0))
    ys0, ys1 = int(y0 + 0.15 * (y1 - y0)), int(y1 - 0.15 * (y1 - y0))
    edges = [m[max(0, y - 2):y + 3, xs0:xs1].any(axis=0) for y in (y0, y1)]
    edges += [m[ys0:ys1, max(0, x - 2):x + 3].any(axis=1) for x in (x0, x1)]
    return min(e.mean() if e.size else 0 for e in edges)


def fit(ident, runway, mpx):
    """Rectangles in the runway frame, metres: along a0..a1, across c0..c1 (+ = left)."""
    import numpy as np

    best = None
    turns = np.arange(-12, 12.01, 1.0) if runway["est"] else np.arange(-4, 4.01, 0.5)
    for turn in turns:
        image, length = panel(ident, runway, mpx, turn)
        m = _blue(image)
        sharp = float((m.sum(axis=1).astype(float) ** 2).sum() + (m.sum(axis=0).astype(float) ** 2).sum())
        if best is None or sharp > best[0]:
            best = (sharp, float(turn), m)
    _, turn, m = best
    h, w = m.shape
    rows, cols = _peaks(m.sum(axis=1), 40), _peaks(m.sum(axis=0), 30)
    found = []
    for y0, y1 in itertools.combinations(rows, 2):
        if not 60 <= y1 - y0 <= 300:
            continue
        for x0, x1 in itertools.combinations(cols, 2):
            if 150 <= x1 - x0 <= 800 and _drawn(m, x0, x1, y0, y1) >= 0.55:
                found.append(dict(a0=round((x0 - w / 2) * OUT_M), a1=round((x1 - w / 2) * OUT_M),
                                  c0=round((h / 2 - y1) * OUT_M), c1=round((h / 2 - y0) * OUT_M),
                                  drawn=round(_drawn(m, x0, x1, y0, y1), 2)))
    kept = []
    for q in sorted(found, key=lambda q: -q["drawn"]):
        def overlap(p):
            ix = max(0, min(p["a1"], q["a1"]) - max(p["a0"], q["a0"]))
            iy = max(0, min(p["c1"], q["c1"]) - max(p["c0"], q["c0"]))
            return ix * iy / ((q["a1"] - q["a0"]) * (q["c1"] - q["c0"]))
        if all(overlap(p) < 0.3 for p in kept) and (
                min(abs(q["c0"]), abs(q["c1"])) < 600 or q["c0"] < 0 < q["c1"]):
            kept.append(q)
    return dict(runway=runway["name"], turn=turn, rects=kept[:3])


def _runways(known):
    for ident, f in sorted(known.items()):
        for k, r in enumerate(f["runways"]):
            yield ident, k, dict(r, _field=f)


def fit_all(known):
    scales = json.loads((WORK / "scale.json").read_text())
    out = {}
    for ident, k, r in _runways(known):
        if scales.get(ident):
            out[f"{ident}:{k}"] = fit(ident, r, scales[ident])
            print(ident, k, out[f"{ident}:{k}"])
    (WORK / "fits.json").write_text(json.dumps(out, indent=1))


def sheets(known, per=9):
    from PIL import Image, ImageDraw

    scales = json.loads((WORK / "scale.json").read_text())
    fits = json.loads((WORK / "fits.json").read_text())
    keys = list(fits)
    for n in range(0, len(keys), per):
        tiles = []
        for key in keys[n:n + per]:
            ident, k = key.split(":")
            r = dict(known[ident]["runways"][int(k)], _field=known[ident])
            q = fits[key]
            image, length = panel(ident, r, scales[ident], q["turn"])
            w, h = image.size
            d = ImageDraw.Draw(image, "RGBA")
            for m in range(-4000, 4001, 500):
                d.line([(w / 2 + m / OUT_M, 0), (w / 2 + m / OUT_M, h)], fill=(0, 0, 0, 70 if m % 1000 else 140))
            for m in range(-3000, 3001, 500):
                d.line([(0, h / 2 - m / OUT_M), (w, h / 2 - m / OUT_M)], fill=(0, 0, 0, 70 if m % 1000 else 140))
            d.line([(w / 2 - length / 2 / OUT_M, h / 2), (w / 2 + length / 2 / OUT_M, h / 2)],
                   fill=(255, 0, 0, 230), width=5)
            for x in q["rects"]:
                d.rectangle([w / 2 + x["a0"] / OUT_M, h / 2 - x["c1"] / OUT_M,
                             w / 2 + x["a1"] / OUT_M, h / 2 - x["c0"] / OUT_M],
                            outline=(0, 200, 0, 220), width=4)
            d.rectangle([0, 0, 360, 22], fill=(255, 255, 255, 230))
            d.text((4, 4), f"{key} {r['name']} turn {q['turn']:+g}", fill=(0, 0, 0))
            tiles.append(image)
        w, h = tiles[0].size
        sheet = Image.new("RGB", (3 * w, ((len(tiles) + 2) // 3) * h), "black")
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % 3) * w, (i // 3) * h))
        sheet.save(WORK / f"sheet-{n // per:02d}.png")


def _frame(known, ident, name, turn):
    """The runway's midpoint and its along / right unit vectors, in the chart's metres
    (east, north from the reference point, which is the chart's centre)."""
    f = known[ident]
    r = next(r for r in f["runways"] if r["name"] == name)
    le, ln = _en(*r["low"], f["lat"], f["lon"])
    he, hn = _en(*r["high"], f["lat"], f["lon"])
    t = math.atan2(he - le, hn - ln) + math.radians(turn)
    return ((le + he) / 2, (ln + hn) / 2), (math.sin(t), math.cos(t)), (math.cos(t), -math.sin(t))


def write(known):
    """`voc.py` from the fits, the verdicts and the traced shapes: every circuit as an
    outline in metres from the reference point."""
    fits = json.loads((WORK / "fits.json").read_text())
    scales = json.loads((WORK / "scale.json").read_text())
    data: dict[str, dict] = {}

    def put(ident, name, shape):
        entry = data.setdefault(ident.upper(), {"scale": round(scales.get(ident) or 0, 2),
                                                "runways": {}})
        runway = entry["runways"].setdefault(name, [])
        if shape is not None:
            runway.append(shape)

    traced: dict[tuple[str, str], list] = {}
    shifts: dict[str, tuple[float, float]] = {}
    for line in SHAPES.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        ident, name, kind, *rest = line.split()
        if ident == "shift":
            # `shift lkbr 150,-850`: the chart draws the strip that far from the real
            # one; every outline of the field is moved by it.
            shifts[name] = tuple(float(v) for v in kind.split(","))
            continue
        if kind == "none":
            traced.setdefault((ident, name), [])
            continue
        where, *coords = rest
        points = [tuple(float(v) for v in c.split(",")) for c in coords]
        if where.startswith("rw"):
            turn = float(where.split(":")[1]) if ":" in where else 0.0
            (mx, my), (ux, uy), (rx, ry) = _frame(known, ident, name, turn)
            # Traced with + across to the left.
            points = [(mx + a * ux - c * rx, my + a * uy - c * ry) for a, c in points]
        traced.setdefault((ident, name), []).append(
            {"closed": kind == "closed", "points": [(round(e), round(n)) for e, n in points]})

    by_runway: dict[str, list[list[str]]] = {}
    for line in VERDICTS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, *rest = line.split()
            by_runway.setdefault(key, []).append(rest)
    for key, verdicts in sorted(by_runway.items()):
        ident, k = key.split(":")
        name = known[ident]["runways"][int(k)]["name"]
        if (ident, name) in traced:
            continue
        kind = verdicts[0][0]
        if kind == "default":
            continue
        if kind == "none":
            put(ident, name, None)
            continue
        q = fits[key]
        if kind == "ok":
            rects = [(x["a0"], x["a1"], -x["c1"], -x["c0"]) for x in q["rects"]]
        else:
            rects = [(int(a0), int(a1), -int(c1), -int(c0)) for _, a0, a1, c0, c1 in verdicts]
        (mx, my), (ux, uy), (rx, ry) = _frame(known, ident, name, q["turn"])
        for a0, a1, c0, c1 in rects:
            corners = [(a0, c0), (a1, c0), (a1, c1), (a0, c1)]
            put(ident, name, {"closed": True, "points": [
                (round(mx + a * ux + c * rx), round(my + a * uy + c * ry)) for a, c in corners]})
    for (ident, name), shapes in traced.items():
        put(ident, name, None)
        for shape in shapes:
            put(ident, name, shape)

    for ident, (de, dn) in shifts.items():
        for shapes in data.get(ident.upper(), {}).get("runways", {}).values():
            for shape in shapes:
                shape["points"] = [(round(e + de), round(n + dn)) for e, n in shape["points"]]
    body = pprint.pformat(data, width=96, sort_dicts=True)
    OUTPUT.write_text(f'''"""Traffic circuits off the AIP's VOC charts — generated, do not edit.

Written by `airspaces.voc_measure write` from the chart fits, the hand review in
`voc_verdicts.txt` and the outlines traced by hand in `voc_shapes.txt`; that module says
how a chart is read. Per aerodrome: `scale`, the chart's metres a pixel, and per runway
(keyed by `Runway.name`) a list of outlines, each `closed` (a loop) or not (a hook or a
U a one-way strip publishes), as points in metres east and north of the reference
point — the chart's centre. **An empty list means the runway has no circuit of its
own**: a parallel or duplicate runway, whose sibling's circuit is the one flown.

A runway that is not here keeps the standard box (`circuits.BESIDE_M`/`BEYOND_M`): its
chart has no readable scale, or one that disagrees with the runway data. A chart that
draws no circuit at all is here with an empty list.
"""

CHARTS = {body}
''')
    print("wrote", OUTPUT, len(data), "aerodromes")


def main(argv=None):
    step = (argv or sys.argv[1:] or ["write"])[0]
    known = fields()
    {"fetch": fetch, "scale": scale, "fit": fit_all, "sheets": sheets, "write": write}[step](known)


if __name__ == "__main__":
    main()
