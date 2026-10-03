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

  // A File (or {name, bytes}) to a flight. KMZ and KML by content as well as by name.
  function read(file) {
    return file.arrayBuffer().then(function (buffer) {
      var bytes = new Uint8Array(buffer), name = file.name || 'track.igc';
      var head = new TextDecoder('utf-8').decode(bytes.subarray(0, 2000));
      var isZip = bytes[0] === 0x50 && bytes[1] === 0x4b;
      if (isZip || /\.(kml|kmz)$/i.test(name) || /<kml/i.test(head)) return TV.kml.parseBytes(bytes, name);
      return TV.igc.parse(new TextDecoder('utf-8').decode(bytes));
    });
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
    var analysis, route, plan, now = Date.now() / 1000;
    progress('analysing');
    return paint().then(function () {
      analysis = TV.analysis.analyse(flight);
      route = TV.xc.best(flight);
      plan = TV.plan.fromFlight(flight);
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
      var uid = 'up' + (++counter);
      var html = TV.report.flightBody(analysis, {
        meteo: inputs[1], route: route, terrain: inputs[0], sceneTerrain: inputs[0], uid: uid, hidden: true,
        flightPlan: plan, certificationTable: inputs[2], now: now
      });
      var holder = document.createElement('div');
      holder.innerHTML = html;
      var shape = TV.xc.shape(route);
      return {
        article: holder.firstElementChild, uid: uid, label: analysis.summary.date,
        meta: (name || '').replace(/\.[^.]+$/, '').slice(0, 22),
        stat: (route.distance / 1000).toFixed(0) + ' km' + (shape !== 'open' ? ' · ' + (shape === 'fai' ? 'FAI' : 'flat') : ''),
        missing: ['ground', 'weather', 'glider table'].filter(function (_, i) { return !inputs[i]; })
      };
    });
  }

  // Put a built article into the page and bring it to life the way a bundled one is:
  // charts drawn, cursor and 3D view wired by `initFlight`.
  function place(built, before) {
    before.parentNode.insertBefore(built.article, before);
    if (window.__drawCharts) window.__drawCharts(built.article);
    if (typeof initFlight === 'function') initFlight(built.article);
    return built.article;
  }

  TV.upload = { read: read, build: build, place: place, paint: paint };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));
