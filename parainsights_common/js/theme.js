(function () {
  var root = document.documentElement;
  function dark() {
    return root.dataset.theme
      ? root.dataset.theme === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function label(button) {
    var isDark = dark();
    button.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    button.title = isDark ? 'Switch to the light theme' : 'Switch to the dark theme';
    var glyph = button.querySelector('.theme-glyph');
    glyph.innerHTML = isDark ? glyph.dataset.sun : glyph.dataset.moon;
  }
  var buttons = document.querySelectorAll('.theme-toggle');
  buttons.forEach(function (button) {
    label(button);
    button.addEventListener('click', function () {
      root.dataset.theme = dark() ? 'light' : 'dark';
      try {
        localStorage.setItem('parainsights.theme', root.dataset.theme);
      } catch (e) { /* private mode: the page still switches, it just forgets */ }
      buttons.forEach(label);
      // The canvases are painted with the tokens read at draw time, so they hold the
      // old theme until something asks them to redraw. Each tool exposes its own.
      if (window.__meteo && window.__meteo.draw) window.__meteo.draw();
      if (window.__drawCharts) {
        document.querySelectorAll('[data-flight-report]').forEach(window.__drawCharts);
      }
    });
  });
  // The system changing under a reader who has expressed no preference.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if (!root.dataset.theme) buttons.forEach(label);
  });
})();
