(function () {
  var article = document.querySelector('.airspace-article');
  var panel = article && article.querySelector('.view3d-panel');
  if (!panel || typeof initView3d !== 'function') return;
  // Built once, and shared: the planner on this page draws on the same handle
  // (`planner/render_html.py` waits on this promise). The ground is fetched at view time,
  // so in the report — where this view starts hidden behind its tab — nothing is fetched
  // until the reader opens it.
  function visible() { return panel.getClientRects().length > 0; }
  // An IntersectionObserver where there is one: a watch on every attribute in the page
  // ran, and laid the page out, on each frame of a flight's replay and each move of its
  // chart cursor, for as long as this tab stayed closed.
  function whenVisible() {
    if (visible()) return Promise.resolve();
    return new Promise(function (resolve) {
      if (window.IntersectionObserver) {
        var seen = new IntersectionObserver(function () {
          if (visible()) { seen.disconnect(); resolve(); }
        });
        seen.observe(panel);
        return;
      }
      var watch = new MutationObserver(function () {
        if (visible()) { watch.disconnect(); resolve(); }
      });
      watch.observe(document.body, { attributes: true, subtree: true,
                                     attributeFilter: ['hidden', 'class', 'style'] });
    });
  }
  window.__airspaceMap = whenVisible().then(function () {
    return initView3dWhenReady(panel, null);
  }).then(function (handle) {
    if (handle) wire(handle);
    return handle;
  });

  function wire(handle) {
  // The filter is a predicate handed to the map, not a pass over the DOM: on the flat
  // map every airspace was an SVG element with a `display` to set, and here they are
  // entries in a payload the map draws from (`map3d` follows `setAirspaceFilter`).
  function refilter() {
    var on = {};
    document.querySelectorAll('[data-asp-class]').forEach(function (box) {
      on[box.dataset.aspClass] = box.checked;
    });
    var slider = document.getElementById('asp-floor');
    var limit = slider ? Number(slider.value) : Infinity;
    var top = slider ? Number(slider.dataset.top) : 0;
    var out = document.getElementById('asp-readout');
    if (out) out.textContent = limit >= top ? 'every floor'
      : 'floor at or below ' + limit + ' m';
    var when = window.aspHours ? window.aspHours.chosen() : null;
    var holidays = window.aspHours ? window.aspHours.holidays() : {};
    function open(space) {
      return !when || window.aspHours.activeAt(space.w, when, holidays);
    }
    var shown = 0, dimmed = 0;
    var spaces = handle.scene().airspaces || [];
    for (var i = 0; i < spaces.length; i++) {
      if (on[spaces[i].k] === false || spaces[i].f > limit) continue;
      if (open(spaces[i])) shown++; else dimmed++;
    }
    var count = document.getElementById('asp-count');
    if (count) count.textContent = shown + ' shown';
    var says = document.getElementById('asp-when-out');
    if (says) {
      says.textContent = !when ? ''
        : (dimmed ? dimmed + ' outside published hours at ' + window.aspHours.label(when)
                  : 'every field with published hours is open at '
                    + window.aspHours.label(when));
    }
    handle.setAirspaceFilter(function (space) {
      return on[space.k] !== false && space.f <= limit && open(space);
    });
  }
  document.querySelectorAll('[data-asp-class]').forEach(function (box) {
    box.addEventListener('change', refilter);
  });
  var slider = document.getElementById('asp-floor');
  if (slider) slider.addEventListener('input', refilter);
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', refilter);
  if (whenInput) whenInput.addEventListener('input', refilter);

  var reset = document.getElementById('asp-reset');
  if (reset) reset.addEventListener('click', function () {
    document.querySelectorAll('[data-asp-class]').forEach(function (box) {
      box.checked = true;
    });
    if (slider) slider.value = slider.dataset.top;
    if (whenBox) whenBox.checked = false;
    refilter();
    var act = panel.querySelector('[data-m3="reset"]');
    if (act) act.click();
  });

  refilter();

  if (window.__openMap) window.__openMap(panel.closest('.renderer-host'));
  }
})();
