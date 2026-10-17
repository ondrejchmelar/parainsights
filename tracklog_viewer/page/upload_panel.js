(function () {
  var drop = document.getElementById('ql-drop');
  if (!drop) return;
  var input = document.getElementById('ql-file');
  var status = document.getElementById('ql-status');

  // The report's own tab controller owns the strip; this only asks it to switch or to add.
  function tabs() { return window.__flightTabs; }

  function fail(name, error) {
    if (window.console) console.warn('could not analyse ' + name, error);
    status.textContent = 'Could not read ' + name + ': ' + ((error && error.message) || String(error));
    status.classList.add('is-error');
  }

  // A tab for a flight the reader added, at the end of the strip so the order is the
  // order they were dropped in.
  function addTab(uid, label, meta, stat) {
    var strip = tabs() && tabs().strip;
    if (!strip) return;
    var tab = document.createElement('span');
    tab.className = 'tab';
    tab.dataset.flightTab = uid;
    var open = document.createElement('button');
    open.type = 'button';
    open.className = 'tab-open';
    open.setAttribute('aria-pressed', 'false');
    [['tab-date', label], ['tab-meta', meta], ['tab-stat', stat]].forEach(function (part) {
      if (!part[1]) return;
      var span = document.createElement('span');
      span.className = part[0];
      span.textContent = part[1];
      open.appendChild(span);
    });
    // The compare control, as a bundled flight's tab has (`render_html._tab`): an uploaded
    // flight is the one a reader most wants to set against the others.
    var compare = document.createElement('button');
    compare.type = 'button';
    compare.className = 'tab-compare';
    compare.setAttribute('data-compare-toggle', uid);
    compare.title = 'Add this flight to the comparison';
    compare.setAttribute('aria-pressed', 'false');
    compare.setAttribute('aria-label', 'Add this flight to the comparison');
    compare.innerHTML = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h12l-3-3M16 13H4l3 3"/></svg>';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'tab-close';
    close.title = 'Remove this flight';
    close.setAttribute('aria-label', 'Remove this flight');
    close.innerHTML = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 5l10 10M15 5 5 15"/></svg>';
    tab.appendChild(open);
    tab.appendChild(compare);
    tab.appendChild(close);
    strip.appendChild(tab);
  }

  // On while any upload is in hand: several files can be dropped at once.
  var busy = 0;
  function working(on) {
    busy = Math.max(0, busy + (on ? 1 : -1));
    status.classList.toggle('is-busy', busy > 0);
    status.setAttribute('aria-busy', busy > 0 ? 'true' : 'false');
  }
  var STAGES = {
    analysing: 'Analysing {name}…',
    fetching: 'Analysed {name}; fetching the ground and the day\'s weather…',
    writing: 'Writing the article for {name}…'
  };

  // A card in the strip while a flight is read and analysed: its file name, the stage,
  // a spinner. The analysis holds the page for seconds, and with nothing in the strip
  // it looked as if the drop had done nothing.
  var STAGE_WORDS = { reading: 'Reading…', analysing: 'Analysing…', fetching: 'Fetching ground and weather…',
                      writing: 'Writing…' };
  function pendingTab(name) {
    var strip = tabs() && tabs().strip;
    if (!strip) return { stage: function () {}, remove: function () {} };
    var tab = document.createElement('span');
    tab.className = 'tab is-loading';
    tab.setAttribute('aria-busy', 'true');
    tab.innerHTML = '<span class="tab-open"><span class="tab-date"></span><span class="tab-meta"></span></span>'
      + '<span class="tab-spin" aria-hidden="true"></span>';
    tab.querySelector('.tab-date').textContent = name.replace(/\.[^.]+$/, '').slice(0, 26);
    strip.appendChild(tab);
    var meta = tab.querySelector('.tab-meta');
    return {
      stage: function (key) { meta.textContent = STAGE_WORDS[key] || ''; },
      remove: function () { if (tab.parentNode) tab.parentNode.removeChild(tab); }
    };
  }

  function handleFile(file) {
    if (!file) return Promise.resolve();
    status.classList.remove('is-error');
    status.textContent = 'Reading ' + file.name + '…';
    working(true);
    var pending = pendingTab(file.name);
    pending.stage('reading');
    return TV.upload.read(file).then(function (flight) {
      return TV.upload.build(flight, file.name, function (stage) {
        status.textContent = STAGES[stage].replace('{name}', file.name);
        pending.stage(stage);
      });
    }).then(function (built) {
      pending.remove();
      TV.upload.place(built, document.getElementById('quicklook'));
      addTab(built.uid, built.label, built.meta, built.stat);
      if (window.__measureScrollbar) window.__measureScrollbar();
      tabs().show(built.uid);
      status.textContent = built.missing.length
        ? 'Analysed. Not available just now: ' + built.missing.join(', ') + '.' : '';
    }).then(function () { working(false); },
            function (error) { pending.remove(); working(false); fail(file.name, error); });
  }

  // Several at once: dropping a season's folder on the panel should just work. They are
  // read one at a time so the tab order matches the file order.
  function handleFiles(list) {
    var files = Array.prototype.slice.call(list || []);
    (function next() {
      var file = files.shift();
      if (!file) return;
      handleFile(file).then(next);
    })();
  }

  document.getElementById('ql-pick').addEventListener('click', function () { input.click(); });
  // The "+" tab shows the drop panel; the report's tab controller has already switched to
  // it by the time this runs, so all that is left is to open the picker.
  document.querySelectorAll('.tab[data-flight-tab="own"]').forEach(function (tab) {
    tab.addEventListener('click', function () { input.click(); });
  });
  input.addEventListener('change', function () { handleFiles(input.files); });
  // Files dropped on the panel, or on the "+" tab from any flight: the tab's loading
  // card shows the progress there, so the reader stays on the flight they were reading.
  function dropTarget(target) {
    ['dragenter', 'dragover'].forEach(function (type) {
      target.addEventListener(type, function (event) {
        event.preventDefault();
        target.classList.add('is-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (type) {
      target.addEventListener(type, function (event) {
        event.preventDefault();
        target.classList.remove('is-over');
        if (type === 'drop' && event.dataTransfer && event.dataTransfer.files.length) {
          handleFiles(event.dataTransfer.files);
        }
      });
    });
  }
  dropTarget(drop);
  document.querySelectorAll('.tab[data-flight-tab="own"]').forEach(dropTarget);
})();
