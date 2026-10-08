// aA, Help and the ⓘ — every page, beside the theme switch.
(function () {
  var root = document.documentElement;
  function store(key, value) {
    try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); }
    catch (e) { /* private mode: it switches, it just forgets */ }
  }
  function paint() {
    document.querySelectorAll('.text-toggle').forEach(function (b) {
      b.setAttribute('aria-pressed', root.dataset.text === 'large' ? 'true' : 'false');
    });
    document.querySelectorAll('.help-toggle').forEach(function (b) {
      b.setAttribute('aria-pressed', root.dataset.help === 'off' ? 'false' : 'true');
    });
  }
  document.addEventListener('click', function (event) {
    var t = event.target.closest && event.target.closest('.text-toggle, .help-toggle');
    if (!t) return;
    if (t.classList.contains('text-toggle')) {
      if (root.dataset.text === 'large') { delete root.dataset.text; store('parainsights.text', null); }
      else { root.dataset.text = 'large'; store('parainsights.text', 'large'); }
      // The maps measure their box; a page that grew under them needs telling.
      window.dispatchEvent(new Event('resize'));
    } else {
      if (root.dataset.help === 'off') { delete root.dataset.help; store('parainsights.help', null); }
      else { root.dataset.help = 'off'; store('parainsights.help', 'off'); }
    }
    paint();
  });
  paint();

  // The ⓘ. Hover shows it on a desktop (CSS); a click or tap pins it open, a second one,
  // Esc or a click anywhere else closes it. Before it shows, it is kept on screen: a
  // bubble centred on an ⓘ near an edge would hang off it.
  function place(wrap) {
    wrap.classList.remove('to-left', 'to-right');
    var r = wrap.getBoundingClientRect(), half = Math.min(320, window.innerWidth * 0.86) / 2;
    if (r.left + r.width / 2 + half > window.innerWidth - 8) wrap.classList.add('to-left');
    else if (r.left + r.width / 2 - half < 8) wrap.classList.add('to-right');
  }
  function closeAll(except) {
    document.querySelectorAll('.info[aria-expanded="true"]').forEach(function (b) {
      if (b !== except) b.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('mouseover', function (event) {
    var w = event.target.closest && event.target.closest('.info-wrap');
    if (w) place(w);
  });
  document.addEventListener('click', function (event) {
    var b = event.target.closest && event.target.closest('.info');
    if (b) {
      event.preventDefault();
      event.stopPropagation();
      place(b.parentNode);
      var open = b.getAttribute('aria-expanded') !== 'true';
      closeAll(b);
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      return;
    }
    if (!(event.target.closest && event.target.closest('.info-pop'))) closeAll(null);
  }, true);
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeAll(null); });
})();
