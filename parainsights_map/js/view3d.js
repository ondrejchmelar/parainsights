// The scrollbar's width, so a full-bleed panel can be exactly the layout viewport.
//
// This has to be innerWidth - clientWidth: an offscreen probe element reports 0 in a
// browser that gives overlay scrollbars to elements and a classic one to the document,
// which is exactly what headless Chrome does, and the panel then overhangs by the
// scrollbar's width and clips its own controls.
//
// The catch is *when* it is measured. On a phone, showing or hiding the address bar fires
// a resize during which the two numbers are briefly inconsistent, and re-measuring then
// gave the panel a phantom 10-20 px of scrollbar mid-scroll — the 3D view visibly
// shrinking as you dragged. So: only on a width change, clamped to a plausible scrollbar,
// and callable by anything that grows the page enough to introduce one.
function measureScrollbar() {
  var width = window.innerWidth - document.documentElement.clientWidth;
  document.documentElement.style.setProperty(
    '--scrollbar', Math.max(Math.min(width, 30), 0) + 'px');
}
measureScrollbar();
window.__measureScrollbar = measureScrollbar;
var scrollbarWidth = window.innerWidth;
window.addEventListener('resize', function () {
  // A height-only resize is the address bar, and must not move anything sideways.
  if (window.innerWidth === scrollbarWidth) return;
  scrollbarWidth = window.innerWidth;
  measureScrollbar();
});


// ---- terrain fetched by the page ---------------------------------------------------
//
// A scene may carry its terrain as `terrain.remote` — the box, the grid and the tile
// source, no heights — rather than as the heights themselves (`terrain.remote()` in
// Python). The page then fetches the same terrarium tiles at the same zoom and samples
// them onto the same nodes `terrain.fetch` would have: nearest pixel, a missing tile
// filled with the lowest height found, heights rounded to the metre. It is one grid built
// in two places, and everything downstream of `dem` cannot tell which — so the arithmetic
// is Python's, operation for operation: `math.radians` is lat × (π/180), numpy's
// linspace is start + i × step, `np.round` rounds a half to even, and the bounds are the
// unrounded heights'. A test builds both from the same tiles and compares every node.
function loadTerrain(dem) {
  // A page built before the move to Mapterhorn carries AWS's 256 px tiles and no size.
  var zoom = dem.remote.zoom, n = Math.pow(2, zoom), size = dem.remote.size || 256;
  function tileX(lon) { return (lon + 180) / 360 * n; }
  function tileY(lat) {
    var rad = lat * (Math.PI / 180);
    return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * n;
  }
  var x0 = Math.floor(tileX(dem.west)), x1 = Math.floor(tileX(dem.east));
  var y0 = Math.floor(tileY(dem.north)), y1 = Math.floor(tileY(dem.south));
  var width = (x1 - x0 + 1) * size, height = (y1 - y0 + 1) * size;
  var mosaic = new Float64Array(width * height).fill(NaN);
  var scratch = document.createElement('canvas');
  scratch.width = scratch.height = size;
  var sctx = scratch.getContext('2d', { willReadFrequently: true });

  function tile(x, y) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.crossOrigin = 'anonymous';
      image.onload = function () {
        sctx.clearRect(0, 0, size, size);
        sctx.drawImage(image, 0, 0);
        var px = sctx.getImageData(0, 0, size, size).data;
        var ox = (x - x0) * size, oy = (y - y0) * size;
        for (var r = 0; r < size; r++) {
          for (var c = 0; c < size; c++) {
            var k = (r * size + c) * 4;
            mosaic[(oy + r) * width + ox + c] =
              px[k] * 256 + px[k + 1] + px[k + 2] / 256 - 32768;
          }
        }
        resolve(true);
      };
      // A missing tile is a hole to fill, not a failure: the Python side does the same.
      // But a tile is asked again twice first, a moment apart: every tile of a page has
      // been seen to fail at once and succeed on reload, which with no retry is a 3D view
      // that never appears.
      var tries = 0;
      var src = dem.remote.url.replace('{z}', zoom).replace('{x}', x).replace('{y}', y);
      image.onerror = function () {
        if (++tries > 2) { resolve(false); return; }
        setTimeout(function () { image.src = src + (src.indexOf('?') < 0 ? '?' : '&') + 'r=' + tries; },
                   400 * tries);
      };
      image.src = src;
    });
  }

  var wanted = [];
  for (var ty = y0; ty <= y1; ty++) for (var tx = x0; tx <= x1; tx++) wanted.push(tile(tx, ty));
  return Promise.all(wanted).then(function (got) {
    if (got.indexOf(true) < 0) throw new Error('no elevation tile could be fetched');
    var low = Infinity;
    for (var i = 0; i < mosaic.length; i++) if (mosaic[i] < low) low = mosaic[i];
    function linspace(start, stop, count, i) {
      if (count < 2) return start;
      return i === count - 1 ? stop : i * ((stop - start) / (count - 1)) + start;
    }
    function roundHalfEven(value) {
      var down = Math.floor(value), rest = value - down;
      if (rest !== 0.5) return Math.round(value);
      return down % 2 === 0 ? down : down + 1;
    }
    var z = new Array(dem.rows * dem.cols), min = Infinity, max = -Infinity;
    for (var r = 0; r < dem.rows; r++) {
      // np.linspace(north, south, rows) and (west, east, cols), then truncated to a pixel
      // and clipped — `terrain.fetch`, step for step.
      var lat = linspace(dem.north, dem.south, dem.rows, r);
      var py = Math.min(Math.max(Math.floor((tileY(lat) - y0) * size), 0), height - 1);
      for (var c = 0; c < dem.cols; c++) {
        var lon = linspace(dem.west, dem.east, dem.cols, c);
        var px = Math.min(Math.max(Math.floor((tileX(lon) - x0) * size), 0), width - 1);
        var value = mosaic[py * width + px];
        if (value !== value) value = low;
        if (value < min) min = value;
        if (value > max) max = value;
        z[r * dem.cols + c] = roundHalfEven(value);
      }
    }
    dem.z = z;
    dem.min = Math.floor(min);
    dem.max = Math.ceil(max);
    return dem;
  });
}

// A scene as the page carries it, parsed and decoded. The track (every fix) and the
// airspace rings are delta-encoded where they are written (`js/scene.js`,
// `airspaces.scene.rings`): each value the difference from the one before, in steps of
// 1/`enc` for coordinates. Decoded here, once, so everything else reads plain arrays.
function readScene(node) {
  var scene = JSON.parse(node.textContent);
  function run(steps, scale) {
    var out = new Array(steps.length), total = 0;
    for (var i = 0; i < steps.length; i++) { total += steps[i]; out[i] = scale ? total / scale : total; }
    return out;
  }
  var t = scene.track;
  if (t && t.enc) {
    t.lon = run(t.lon, t.enc); t.lat = run(t.lat, t.enc);
    t.alt = run(t.alt); if (t.t) t.t = run(t.t);
    delete t.enc;
  }
  (scene.airspaces || []).forEach(function (ring) {
    if (!ring.enc) return;
    ring.lon = run(ring.lon, ring.enc); ring.lat = run(ring.lat, ring.enc);
    delete ring.enc;
  });
  return scene;
}

// The airspace under a flight's ground, from the layer files `airspaces/openaip.py` writes
// beside the Planner: the index once per page, then only the files whose box reaches this
// one, each fetched and decoded once however many flights share it. Never rejects — a
// map without its airspace is still a map — and fills `scene.airspaces` in place, before
// the map is built from the scene. Then `settleAirspace` says what the switch says.
var airspaceFiles = {};
function airspaceJson(url) {
  if (!airspaceFiles[url]) {
    airspaceFiles[url] = fetch(url).then(function (response) {
      if (!response.ok) throw new Error(response.status + ' ' + url);
      return response.json();
    });
    airspaceFiles[url].catch(function () { delete airspaceFiles[url]; });
  }
  return airspaceFiles[url];
}
function loadAirspace(root, scene) {
  var href = scene.airspaceRemote, dem = scene.terrain;
  if (!href || !dem || typeof fetch !== 'function') return Promise.resolve();
  function overlaps(b) {
    return b && !(b[1] < dem.west || b[0] > dem.east || b[3] < dem.south || b[2] > dem.north);
  }
  function decode(ring) {
    if (!ring.enc) return ring;
    var lon = [], lat = [], x = 0, y = 0;
    for (var i = 0; i < ring.lon.length; i++) {
      x += ring.lon[i]; y += ring.lat[i];
      lon.push(x / ring.enc); lat.push(y / ring.enc);
    }
    var out = {};
    Object.keys(ring).forEach(function (k) { if (k !== 'enc') out[k] = ring[k]; });
    out.lon = lon; out.lat = lat;
    return out;
  }
  var credits = [];
  var found = airspaceJson(href + 'index.json').then(function (index) {
    scene.airspaceColours = index.colours || {};
    scene.airspaceClasses = index.classes || [];
    var names = Object.keys(index.files || {}).filter(function (name) {
      return overlaps(index.files[name].bbox);
    });
    return Promise.all(names.map(function (name) {
      return airspaceJson(href + name).then(function (file) {
        if (!file.decoded) file.decoded = (file.airspaces || []).map(decode);
        var near = file.decoded.filter(function (ring) {
          var w = Math.min.apply(null, ring.lon), e = Math.max.apply(null, ring.lon);
          var s = Math.min.apply(null, ring.lat), n = Math.max.apply(null, ring.lat);
          return !(e < dem.west || w > dem.east || n < dem.south || s > dem.north);
        });
        if (near.length && index.files[name].credit && credits.indexOf(index.files[name].credit) < 0) {
          credits.push(index.files[name].credit);
        }
        return near;
      }, function () { return []; });
    }));
  }).then(function (parts) {
    // Back to front across files as within one: the biggest first, so the smallest thing
    // under the pointer is the one hovered (`airspaces.scene.rings`).
    function size(ring) {
      return (Math.max.apply(null, ring.lon) - Math.min.apply(null, ring.lon)) *
             (Math.max.apply(null, ring.lat) - Math.min.apply(null, ring.lat));
    }
    scene.airspaces = [].concat.apply([], parts).sort(function (a, b) { return size(b) - size(a); });
    scene.airspaceCredit = credits.join(' · ');
  }, function () { scene.airspaces = []; scene.airspaceFailed = true; });
  return found;
}

// What a flight's map draws of the airspace it loaded: only what the flight had to do
// with. Two cuts, both the pilot's (October 2026), and zones openAIP marks as active only
// by NOTAM go too. Kinds that bind nobody — danger and
// firing areas, sport and aerobatic boxes, alert and warning areas, gliding sectors — are
// not drawn; protected areas and parks are, because they do bind. And of the rest, only
// zones the track came within 10 km of sideways and 200 m of vertically: the ground box a
// flight's map covers holds a hundred zones in the Alps, and an aerobatic box or a firing
// range the flight never went near is clutter on a map about this flight. Run after the
// terrain is in, because a limit measured from the ground needs the ground.
var NON_BINDING = /^(D|Sport|Alert|Warning|Gliding)$/;
var NEAR_SIDEWAYS = 10000, NEAR_VERTICALLY = 200;   // 5 km sideways until October 2026
// The ground under a point from the scene's grid, nearest cell; the grid's lowest point
// where there is no grid.
function sceneGround(dem, lon, lat) {
  if (!dem.z || !dem.rows) return dem.min || 0;
  var gx = Math.max(0, Math.min(dem.cols - 1, (lon - dem.west) / (dem.east - dem.west) * (dem.cols - 1)));
  var gy = Math.max(0, Math.min(dem.rows - 1, (dem.north - lat) / (dem.north - dem.south) * (dem.rows - 1)));
  return dem.z[Math.round(gy) * dem.cols + Math.round(gx)];
}
// Metres from a point to a zone's ring: 0 inside, else to the nearest edge.
function ringDistance(ring, p) {
  var kx = 111320 * Math.cos(p[1] * Math.PI / 180), ky = 111320, inside = false, best = Infinity;
  var n = ring.lon.length;
  for (var a = 0, b = n - 1; a < n; b = a++) {
    var ax = (ring.lon[a] - p[0]) * kx, ay = (ring.lat[a] - p[1]) * ky;
    var bx = (ring.lon[b] - p[0]) * kx, by = (ring.lat[b] - p[1]) * ky;
    if ((ay > 0) !== (by > 0) && 0 < (bx - ax) * (0 - ay) / (by - ay) + ax) inside = !inside;
    // A band's keyhole slit (`ho`) is no edge to be near.
    if (ring.ho && ((a === ring.ho && b === ring.ho - 1) || (a === 0 && b === n - 1))) continue;
    var dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
    var t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return inside ? 0 : best;
}
// A zone's floor and top over a point, in metres: limits measured from the ground are
// measured from the ground there; a top the file caps (`t`) is unbounded.
function zoneLimits(ring, g) {
  return [ring.g ? g : (ring.fu !== undefined ? g + ring.fu : ring.f),
          ring.t ? Infinity : (ring.cu !== undefined ? g + ring.cu : ring.c)];
}
function relevantAirspace(scene) {
  var tr = scene.track, dem = scene.terrain || {};
  var all = scene.airspaces || [];
  scene.airspaceLoaded = all.length;
  if (!tr || !tr.lon || tr.lon.length < 2 || !all.length) return;
  var step = Math.max(1, Math.floor(tr.lon.length / 2000)), fixes = [];
  for (var i = 0; i < tr.lon.length; i += step) fixes.push([tr.lon[i], tr.lat[i], tr.alt[i]]);
  scene.airspaces = all.filter(function (ring) {
    if (ring.ac && NON_BINDING.test(ring.ac)) return false;
    if (ring.nt) return false;     // active only by NOTAM: the file cannot know if it is
    var mx = NEAR_SIDEWAYS / (111320 * Math.cos(ring.lat[0] * Math.PI / 180)), my = NEAR_SIDEWAYS / 111320;
    var w = Math.min.apply(null, ring.lon) - mx, e = Math.max.apply(null, ring.lon) + mx;
    var s = Math.min.apply(null, ring.lat) - my, n = Math.max.apply(null, ring.lat) + my;
    for (var k = 0; k < fixes.length; k++) {
      var p = fixes[k];
      if (p[0] < w || p[0] > e || p[1] < s || p[1] > n) continue;
      if (ringDistance(ring, p) > NEAR_SIDEWAYS) continue;
      var lim = zoneLimits(ring, sceneGround(dem, p[0], p[1]));
      if (p[2] >= lim[0] - NEAR_VERTICALLY && p[2] <= lim[1] + NEAR_VERTICALLY) return true;
    }
    return false;
  });
}

// The flight against each zone the map draws (`scene.airspaceAlong`, for the report's
// Airspace section): how long it was inside and how deep; and where it never was, how
// close it came — under the floor or over the top while over the zone's ground, or
// beside it at a height within its limits. Under a floor is *not* inside: a ring the
// track crosses at 800 m under a floor of FL 95 is no infringement and is not called one.
// Nearby is inside, within 500 m under or over, or within 2 km beside; the rest of what
// the map draws is only counted.
var ALONG_SIDEWAYS = 2000, ALONG_VERTICALLY = 500;
function airspaceAlong(scene) {
  var tr = scene.track, dem = scene.terrain || {}, zones = scene.airspaces || [];
  if (!tr || !tr.lon || tr.lon.length < 2) return null;
  var step = Math.max(1, Math.floor(tr.lon.length / 3000)), fixes = [];
  for (var i = 0; i < tr.lon.length; i += step) {
    fixes.push({ lon: tr.lon[i], lat: tr.lat[i], alt: tr.alt[i], t: tr.t ? tr.t[i] : i,
                 g: sceneGround(dem, tr.lon[i], tr.lat[i]) });
  }
  var inAny = {};
  var found = zones.map(function (ring, index) {
    var mx = (ALONG_SIDEWAYS + 1) / (111320 * Math.cos(ring.lat[0] * Math.PI / 180)), my = (ALONG_SIDEWAYS + 1) / 111320;
    var w = Math.min.apply(null, ring.lon) - mx, e = Math.max.apply(null, ring.lon) + mx;
    var s = Math.min.apply(null, ring.lat) - my, n = Math.max.apply(null, ring.lat) + my;
    var inside = null, under = null, over = null, beside = null, spans = [], span = null;
    fixes.forEach(function (p, k) {
      var near = !(p.lon < w || p.lon > e || p.lat < s || p.lat > n);
      var d = near ? ringDistance(ring, [p.lon, p.lat]) : Infinity;
      var lim = zoneLimits(ring, p.g), dt = k ? p.t - fixes[k - 1].t : 0;
      // Where the track was over the zone's ground: the stretches its box is drawn over
      // in the section's height chart.
      if (d === 0) {
        if (span && span.k === k - 1) { span.t1 = p.t; span.k = k; span.floor = Math.min(span.floor, lim[0]); span.top = Math.max(span.top, lim[1]); }
        else spans.push(span = { t0: p.t, t1: p.t, k: k, floor: lim[0], top: lim[1] });
      }
      if (d === 0 && p.alt >= lim[0] && p.alt <= lim[1]) {
        var depth = Math.min(p.alt - lim[0], lim[1] - p.alt);
        inAny[k] = true;
        if (!inside) inside = { seconds: 0, from: p.t, to: p.t, depth: depth, low: p.alt, high: p.alt, at: p };
        if (inside.last === k - 1) inside.seconds += dt;
        inside.last = k; inside.to = p.t;
        inside.low = Math.min(inside.low, p.alt); inside.high = Math.max(inside.high, p.alt);
        if (depth > inside.depth) { inside.depth = depth; inside.at = p; }
      } else if (d === 0 && p.alt < lim[0]) {
        if (!under || lim[0] - p.alt < under.m) under = { m: lim[0] - p.alt, at: p };
      } else if (d === 0) {
        if (!over || p.alt - lim[1] < over.m) over = { m: p.alt - lim[1], at: p };
      } else if (d <= ALONG_SIDEWAYS && p.alt >= lim[0] && p.alt <= lim[1]) {
        if (!beside || d < beside.m) beside = { m: d, at: p };
      }
    });
    // The nearest of the near misses, each against its own threshold.
    var closest = inside ? 'inside' : null, score = inside ? -1 : Infinity;
    [['under', under, ALONG_VERTICALLY], ['over', over, ALONG_VERTICALLY], ['beside', beside, ALONG_SIDEWAYS]]
      .forEach(function (c) {
        if (c[1] && c[1].m / c[2] < score) { score = c[1].m / c[2]; closest = c[0]; }
      });
    var at = closest === 'inside' ? inside.at : closest ? { under: under, over: over, beside: beside }[closest].at : null;
    return { index: index, ring: ring, name: ring.nm || ring.n, kind: ring.k, cls: ring.ac || null,
             limits: ring.lo && ring.hi ? ring.lo + ' – ' + ring.hi : null,
             inside: inside, under: under, over: over, beside: beside,
             closest: closest, nearby: score <= 1, at: at, spans: spans };
  });
  var nearby = found.filter(function (z) { return z.nearby; }).sort(function (a, b) {
    if (a.inside || b.inside) return (b.inside ? b.inside.seconds + 1 : 0) - (a.inside ? a.inside.seconds + 1 : 0);
    var ka = { under: ALONG_VERTICALLY, over: ALONG_VERTICALLY, beside: ALONG_SIDEWAYS };
    return a[a.closest].m / ka[a.closest] - b[b.closest].m / ka[b.closest];
  });
  // The height chart's line: the track and the ground under it, at most 600 points.
  // Inside any zone at a point if any fix it stands for was.
  var every = Math.max(1, Math.floor(fixes.length / 600)), profile = { t: [], alt: [], ground: [], inside: [] };
  for (var j = 0; j < fixes.length; j += every) {
    var any = false;
    for (var q = j; q < Math.min(j + every, fixes.length); q++) any = any || !!inAny[q];
    profile.t.push(fixes[j].t); profile.alt.push(fixes[j].alt); profile.ground.push(fixes[j].g);
    profile.inside.push(any);
  }
  return { zones: nearby, others: found.length - nearby.length, profile: profile,
           start: scene.start || null, offset: scene.utcOffset || 0,
           colours: scene.airspaceColours || {} };
}

// What the map's airspace switch says once the airspace is settled (`scene.airspaceWhy`):
// what it draws, with the credit, or why there is nothing to draw.
function settleAirspace(root, scene) {
  if (!scene.airspaceRemote) return;
  relevantAirspace(scene);
  // And the flight against them, for whatever on the page reports it (the report's
  // Airspace section), with why there is nothing when there is nothing.
  var along = airspaceAlong(scene) || { zones: [], others: 0 };
  along.status = scene.airspaceFailed ? 'failed' : scene.airspaceLoaded ? 'ok' : 'uncovered';
  root.__airspaceAlong = along;
  if (typeof CustomEvent === 'function' && root.dispatchEvent) {
    root.dispatchEvent(new CustomEvent('airspace-along', { detail: along }));
  }
  scene.airspaceWhy = scene.airspaces.length
    ? 'Draw the airspace this flight came near' + (scene.airspaceCredit ? ' (' + scene.airspaceCredit + ')' : '')
    : scene.airspaceFailed ? 'The airspace could not be loaded'
    : scene.airspaceLoaded ? 'No binding airspace within 10 km and 200 m of this flight'
    : 'No airspace here: only Europe is covered';
}

// The scene a panel carries, completed: the ground fetched where it was left to the page,
// the airspace loaded and settled. Resolves with the panel's handle, or null where there
// is no panel. Never rejects: ground that could not be fetched leaves a map whose
// heights come from MapLibre's own terrain, which is still a map.
function initView3dWhenReady(root, cursorTrack) {
  var payload = root.querySelector('.view3d-data');
  if (!payload) return Promise.resolve(null);
  var scene = readScene(payload);
  var dem = scene.terrain;
  var airspace = loadAirspace(root, scene);
  if (!dem || !dem.remote || dem.z) {
    return airspace.then(function () {
      settleAirspace(root, scene);
      return initView3d(root, cursorTrack, scene);
    });
  }
  var ground = loadTerrain(dem).then(null, function (error) {
    dem.failed = error.message;
  });
  return Promise.all([ground, airspace]).then(function () {
    settleAirspace(root, scene);
    return initView3d(root, cursorTrack, scene);
  });
}

// The handle a panel is driven through: what the map draws (`built`), the ground under a
// point, the linked cursor and the airspace filter. The map (`map3d`) wraps the cursor
// and filter members, which is how a chart hover or a table row reaches it; here they
// only remember.
function initView3d(root, cursorTrack, preset) {
  var box = root.querySelector('.view3d');
  var payload = root.querySelector('.view3d-data');
  if (!box || !payload) return null;
  var scene = preset || readScene(payload);
  // A scene need not carry a flight. The airspace map is the same widget over the same
  // terrain with no track in it, so the flight-shaped members are defaulted here once.
  if (!scene.track) scene.track = { lon: [], lat: [], alt: [], c: [] };
  if (!scene.climbs) scene.climbs = [];
  if (!scene.palette) scene.palette = [[120, 120, 120]];
  var dem = scene.terrain || {};
  var cursorIndex = null, airspaceFilter = null;
  // Bilinear over the grid; null where there is no grid (it could not be fetched).
  function groundAt(lon, lat) {
    if (!dem.z || !dem.rows) return null;
    var cols = dem.cols, rows = dem.rows;
    var gx = (lon - dem.west) / (dem.east - dem.west) * (cols - 1);
    var gy = (dem.north - lat) / (dem.north - dem.south) * (rows - 1);
    gx = Math.max(0, Math.min(cols - 1, gx));
    gy = Math.max(0, Math.min(rows - 1, gy));
    var x0 = Math.floor(gx), y0 = Math.floor(gy);
    var x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, rows - 1);
    var fx = gx - x0, fy = gy - y0;
    var top = dem.z[y0 * cols + x0] * (1 - fx) + dem.z[y0 * cols + x1] * fx;
    var bottom = dem.z[y1 * cols + x0] * (1 - fx) + dem.z[y1 * cols + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }
  var handle = {
    built: { scene: scene, cursorTrack: cursorTrack || null },
    scene: function () { return scene; },
    groundAt: groundAt,
    setCursor: function (index) { cursorIndex = index; },
    revealCursor: function (index) { cursorIndex = index; return false; },
    clearCursor: function () { cursorIndex = null; },
    cursor: function () { return cursorIndex; },
    setAirspaceFilter: function (fn) { airspaceFilter = fn || null; },
    airspaceFilter: function () { return airspaceFilter; },
    redraw: function () {},
    dispose: function () {}
  };
  window.__view3d = handle;
  // A multi-flight document builds one of these per tab, so the bare global is whichever
  // went last; keyed by the box's id as well, which is how the map and the tests find it.
  window.__view3dAll = window.__view3dAll || {};
  window.__view3dAll[box.id] = handle;
  return handle;
}
