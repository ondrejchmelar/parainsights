// The top-level view switch. One level above the flight tabs: those choose which
// flight, this chooses whether you are looking at flights at all.
(function () {
  var nav = document.getElementById('views');
  if (!nav) return;
  function show(key) {
    document.querySelectorAll('[data-view]').forEach(function (section) {
      section.hidden = section.dataset.view !== key;
    });
    nav.querySelectorAll('[data-view-tab]').forEach(function (button) {
      var on = button.dataset.viewTab === key;
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    // A map inside a hidden section has a zero-sized box; the one just revealed is told
    // its size. Every map, not only the revealed one: a hidden one measures zero and
    // MapLibre leaves it as it is.
    if (window.__mergedAll) {
      Object.keys(window.__mergedAll).forEach(function (id) {
        var entry = window.__mergedAll[id];
        if (entry && entry.map) entry.map.resize();
      });
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
  }
  nav.addEventListener('click', function (event) {
    var button = event.target.closest('[data-view-tab]');
    if (button) show(button.dataset.viewTab);
  });
})();
