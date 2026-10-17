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
  // entries in a payload the map draws from (`map3d` follows `setAirspaceFilter`). The
  // kinds and the floor are the map's own menu's; this page adds the hours, whose row
  // the map moves into that menu.
  function refilter() {
    var when = window.aspHours ? window.aspHours.chosen() : null;
    var holidays = window.aspHours ? window.aspHours.holidays() : {};
    function open(space) {
      return !when || (window.aspHours.activeAt(space.w, when, holidays) &&
                       !window.aspHours.inactive(space, when));
    }
    var dimmed = 0;
    // What the map draws: with a planner, the zones near its task — and before there is a
    // task, nothing, while the hours line still speaks for every field on the page.
    var planned = handle.planned ? handle.planned() : true;
    var spaces = ((planned && handle.drawnAirspaces) ? handle.drawnAirspaces()
                                                     : handle.scene().airspaces) || [];
    for (var i = 0; i < spaces.length; i++) if (!open(spaces[i])) dimmed++;
    var says = document.getElementById('asp-when-out');
    if (says) {
      says.textContent = !when ? ''
        : (dimmed ? dimmed + ' outside published hours or season at ' + window.aspHours.label(when)
                  : 'every field with published hours is open at '
                    + window.aspHours.label(when));
    }
    handle.setAirspaceFilter(when ? open : null);
  }
  var whenBox = document.getElementById('asp-when-on');
  var whenInput = document.getElementById('asp-when');
  if (whenBox) whenBox.addEventListener('change', refilter);
  if (whenInput) whenInput.addEventListener('input', refilter);

  refilter();
  window.__aspRefilter = refilter;

  if (window.__openMap) window.__openMap(panel.closest('.renderer-host'));
  }
})();
