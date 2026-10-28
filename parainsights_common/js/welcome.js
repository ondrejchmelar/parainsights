// The welcome: the three tools, once per browser. Shown on the published site only, so a
// page built and opened locally (and every test) opens straight onto itself; `?welcome`
// shows it anywhere, to look at. Seen is remembered however it was closed — × , Esc,
// "Got it", a click beside it or a card's link — and a browser that cannot remember
// (private mode) is not shown it at all, rather than shown it on every page.
(function () {
  var KEY = 'parainsights.welcome';
  var dialog = document.getElementById('welcome');
  function seen() {
    try { return localStorage.getItem(KEY) === 'seen'; } catch (e) { return true; }
  }
  function remember() {
    try { localStorage.setItem(KEY, 'seen'); } catch (e) { /* nothing to remember in */ }
  }
  function maybe(force) {
    if (!dialog || dialog.open || seen()) return false;
    if (!force && location.hostname !== '__SITE_HOST__' && !/[?&]welcome\b/.test(location.search)) return false;
    dialog.showModal();
    // No focus ring on the × the moment it opens; Tab still starts there.
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    return true;
  }
  if (dialog) {
    dialog.addEventListener('close', remember);
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close();  // the backdrop
      else if (event.target.closest('a[href]')) remember();
    });
  }
  window.__welcome = { maybe: maybe, key: KEY };
  maybe(false);
})();
