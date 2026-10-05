/* A track the reader drops on the page, turned into the same article a bundled flight
 * gets: parsed, analysed and rendered by the modules beside this one.
 *
 * Three things are fetched for it, all optional and all in parallel — the ground (the
 * DEM box the CLI would fetch, filled by the page's own `loadTerrain`), the day's
 * profile from Open-Meteo, and the glider table (`gliders.json` beside the page). A fetch
 * that fails or runs out of time costs only what rests on it: no ground means no 3D view
 * and no clearance finding, exactly as a report built without `--terrain`. Nothing about
 * the track leaves the page; the requests carry a bounding box and an hour.
 */
(function (TV) {
  'use strict';
  var counter = 0;
  var TIMEOUTS = { terrain: 25000, meteo: 15000, gliders: 10000 };

  // Resolves to the value, or to null on failure or after `ms`: an optional input.
  function optional(promise, ms) {
    return new Promise(function (resolve) {
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(null); } }, ms);
      promise.then(function (value) { if (!done) { done = true; clearTimeout(timer); resolve(value); } },
                   function () { if (!done) { done = true; clearTimeout(timer); resolve(null); } });
    });
  }
  function json(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status + ' ' + url);
      return r.json();
    });
  }

  // Bytes to a flight: KMZ and KML by content as well as by name, IGC otherwise. The one
  // dispatch for every way a file arrives — an upload here, the report's own flights in
  // Node at build time (`build_runner.js`), and the test suite (`tests/js_bridge.js`).
  // `options` reaches the parsers; Node passes its own `inflateRaw` for a KMZ.
  // Always a promise, refused rather than thrown: a file the parser rejects has to reach
  // whoever asked as a failure they can name, not escape the chain as an exception.
  function readBytes(bytes, name, options) {
    name = name || 'track.igc';
    try {
      var head = new TextDecoder('utf-8').decode(bytes.subarray(0, 2000));
      var isZip = bytes[0] === 0x50 && bytes[1] === 0x4b;
      if (isZip || /\.(kml|kmz)$/i.test(name) || /<kml/i.test(head)) return TV.kml.parseBytes(bytes, name, options);
      return Promise.resolve(TV.igc.parse(new TextDecoder('utf-8').decode(bytes), options));
    } catch (error) {
      return Promise.reject(error);
    }
  }
  // A File to a flight.
  function read(file) {
    return file.arrayBuffer().then(function (buffer) {
      return readBytes(new Uint8Array(buffer), file.name || 'track.igc');
    });
  }

  // ---- one article, from a flight and what was fetched for it ---------------------------
  //
  // Shared by an upload (below, in the page) and by the report's own flights, which are
  // rendered by this same function at build time in Node (`js_build.py`). One function,
  // so a showcase flight and an uploaded one cannot come out different.
  //
  // inputs:  { terrain, sceneTerrain, meteo (parsed), certificationTable, now }
  // options: { uid, hidden, label ('PILOT|SITE|GLIDER', empty fields keep the file's),
  //            airspaceRemote (where the airspace layer files are, relative to the page:
  //            the map loads those under its ground when opened), plan ({ payload,
  //            source }), format }
  var SHAPE_NAMES = { fai: 'FAI triangle', flat: 'flat triangle', open: 'open distance' };
  function annotate(summary, label) {
    if (!label) return;
    var fields = (label.split('|').concat(['', '', ''])).slice(0, 3);
    ['pilot', 'site', 'glider'].forEach(function (name, i) {
      if (fields[i].trim()) summary[name] = fields[i].trim();
    });
  }
  function shapeOf(route, analysis) {
    if (!route) return '';
    var shape = TV.xc.shape(route);
    if (shape === 'open' && analysis.summary.straight_distance < 0.5 * analysis.summary.max_distance_from_takeoff) {
      return 'out and return';
    }
    return SHAPE_NAMES[shape] || 'open distance';
  }
  function firstName(pilot) { return pilot ? String(pilot).trim().split(' ')[0] : ''; }
  function planFor(flight, options) {
    if (options.plan && options.plan.payload) {
      var found = TV.plan.fromJson(options.plan.payload);
      if (found) { found.source = options.plan.source || 'sidecar'; return found; }
    }
    return TV.plan.fromFlight(flight);
  }
  function analyseFor(flight, options) {
    var analysis = TV.analysis.analyse(flight);
    annotate(analysis.summary, options.label);
    return { analysis: analysis, route: TV.xc.best(flight), plan: planFor(flight, options) };
  }
  function compose(flight, name, inputs, options, done) {
    options = options || {};
    done = done || analyseFor(flight, options);
    var analysis = done.analysis, route = done.route, summary = analysis.summary;
    var html = TV.report.flightBody(analysis, {
      meteo: inputs.meteo || null, route: route, terrain: inputs.terrain || null,
      sceneTerrain: inputs.sceneTerrain || null, uid: options.uid, hidden: !!options.hidden,
      flightPlan: done.plan, certificationTable: inputs.certificationTable || null,
      now: inputs.now, airspaceRemote: options.airspaceRemote || null
    });
    var format = (options.format || '').toUpperCase();
    return {
      html: html, uid: options.uid, label: summary.date,
      meta: [firstName(summary.pilot), summary.site].filter(Boolean).join(' · ')
        || (name || '').replace(/\.[^.]+$/, '').slice(0, 22) || '—',
      stat: [route ? (route.distance / 1000).toFixed(0) + ' km' : '', shapeOf(route, analysis),
             format && format !== 'IGC' ? 'from ' + format : ''].filter(Boolean).join(' · '),
      title: summary.date + ' · ' + (summary.site || 'flight') + ' — flight review'
    };
  }

  // Where the airspace layer files are (`airspaces/openaip.py`): the report names them in
  // a meta tag when it was built with airspace. An uploaded flight's map loads the ones
  // under its ground when opened, as a bundled flight's does.
  function airspaceLayers() {
    if (typeof document === 'undefined') return null;
    var meta = document.querySelector('meta[name="airspace-layers"]');
    return meta ? meta.getAttribute('content') : null;
  }

  // Let the page paint before a long synchronous stretch, so a stage the caller has just
  // announced is on screen while it runs. A timeout and not requestAnimationFrame: a
  // background tab never runs the latter, and the upload must not stall there.
  function paint() { return new Promise(function (resolve) { setTimeout(resolve, 30); }); }

  // The flight's article, with what could be fetched. Resolves to
  // { article, uid, label, meta, stat, missing }; the caller puts it in the page.
  // `progress(stage)` hears 'analysing', 'fetching' and 'writing' as each one starts.
  function build(flight, name, progress) {
    progress = progress || function () {};
    var done, now = Date.now() / 1000;
    progress('analysing');
    return paint().then(function () {
      done = analyseFor(flight, {});
      progress('fetching');

      var grid = TV.terrain.remoteFor(flight);
      var ground = typeof loadTerrain === 'function'
        ? optional(loadTerrain(grid).then(function () { return grid.z ? grid : null; }), TIMEOUTS.terrain)
        : Promise.resolve(null);
      var middle = TV.meteo.middleOf(flight);
      var weather = optional(json(TV.meteo.request(middle.lat, middle.lon, middle.when, now)).then(function (payload) {
        return TV.meteo.parse(payload, middle.when, now);
      }), TIMEOUTS.meteo);
      var gliders = optional(json('gliders.json'), TIMEOUTS.gliders);
      return Promise.all([ground, weather, gliders]);
    }).then(function (inputs) {
      progress('writing');
      return paint().then(function () { return inputs; });
    }).then(function (inputs) {
      var made = compose(flight, name, {
        terrain: inputs[0], sceneTerrain: inputs[0], meteo: inputs[1],
        certificationTable: inputs[2], now: now
      }, { uid: 'up' + (++counter), hidden: true, airspaceRemote: inputs[0] ? airspaceLayers() : null,
        format: /\.(kml|kmz)$/i.test(name || '') ? name.split('.').pop() : '' }, done);
      var holder = document.createElement('div');
      holder.innerHTML = made.html;
      return {
        article: holder.firstElementChild, uid: made.uid, label: made.label, meta: made.meta,
        stat: made.stat,
        missing: ['ground', 'weather', 'glider table'].filter(function (_, i) { return !inputs[i]; })
      };
    });
  }

  // Put a built article into the page and bring it to life the way a bundled one is:
  // charts drawn, cursor and 3D view wired by `initFlight`.
  function place(built, before) {
    before.parentNode.insertBefore(built.article, before);
    if (window.__drawCharts) window.__drawCharts(built.article);
    // An article written without the day's weather asks for it in the page, as a report
    // built without --meteo does; `run` saw only the articles there at load.
    if (window.__fetchAir) window.__fetchAir();
    if (typeof initFlight === 'function') initFlight(built.article);
    return built.article;
  }

  TV.upload = { read: read, readBytes: readBytes, build: build, place: place, paint: paint, compose: compose };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));
