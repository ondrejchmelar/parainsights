(function () {
  var svg = document.getElementById('asp-map');
  if (!svg) return;
  var view = { x: 0, y: 0, w: 1000, h: 667 };
  var home = { x: 0, y: 0, w: 1000, h: 667 };
  var tip = document.getElementById('asp-name');

  function apply() {
    svg.setAttribute('viewBox', view.x + ' ' + view.y + ' ' + view.w + ' ' + view.h);
  }

  function zoomAt(clientX, clientY, ratio) {
    var box = svg.getBoundingClientRect();
    // Anchor the zoom on the cursor: the world point under it must not move.
    var fx = (clientX - box.left) / box.width;
    var fy = (clientY - box.top) / box.height;
    var wx = view.x + fx * view.w, wy = view.y + fy * view.h;
    var next = Math.min(Math.max(view.w * ratio, home.w / 400), home.w);
    ratio = next / view.w;
    view.w = next; view.h = view.h * ratio;
    view.x = wx - fx * view.w; view.y = wy - fy * view.h;
    apply();
  }

  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.deltaY > 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });

  var drag = null, pinch = null;
  svg.addEventListener('pointerdown', function (e) {
    svg.setPointerCapture(e.pointerId);
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    svg.classList.add('is-dragging');
  });
  svg.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    var box = svg.getBoundingClientRect();
    view.x -= (e.clientX - drag.x) * view.w / box.width;
    view.y -= (e.clientY - drag.y) * view.h / box.height;
    drag.x = e.clientX; drag.y = e.clientY;
    apply();
  });
  function endDrag() { drag = null; svg.classList.remove('is-dragging'); }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  // Two-finger pinch, tracked off the raw touch list because pointer events give one
  // stream per finger and the midpoint is what the zoom has to anchor on.
  svg.addEventListener('touchmove', function (e) {
    if (e.touches.length !== 2) { pinch = null; return; }
    e.preventDefault();
    var a = e.touches[0], b = e.touches[1];
    var span = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    var mx = (a.clientX + b.clientX) / 2, my = (a.clientY + b.clientY) / 2;
    if (pinch) zoomAt(mx, my, pinch / span);
    pinch = span;
    drag = null;
  }, { passive: false });
  svg.addEventListener('touchend', function () { pinch = null; });

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
    var shown = 0, dimmed = 0;
    svg.querySelectorAll('.asp-zone').forEach(function (zone) {
      var visible = on[zone.dataset.klass] !== false
        && Number(zone.dataset.floor) <= limit;
      if (visible && when) {
        var schedule = zone.dataset.hours ? JSON.parse(zone.dataset.hours) : null;
        if (!window.aspHours.activeAt(schedule, when, holidays)) {
          visible = false;
          dimmed++;
        }
      }
      zone.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });
    var count = document.getElementById('asp-count');
    if (count) count.textContent = shown + ' shown';
    reportWhen(when, dimmed);
  }

  // Never silent. Hiding airspace without saying how much was hidden is the one thing
  // this control must not do, so the readout states the count even when it is zero.
  function reportWhen(when, dimmed) {
    var out = document.getElementById('asp-when-out');
    if (!out) return;
    if (!when) { out.textContent = ''; return; }
    out.textContent = dimmed
      ? dimmed + ' outside published hours at ' + window.aspHours.label(when)
      : 'every field with published hours is open at ' + window.aspHours.label(when);
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

  // The label: hover on a mouse, tap-to-pin on a touchscreen.
  //
  // A touchscreen fires pointerover on touch-down and pointerout on touch-up, so a
  // hover-driven label appears and vanishes within the same tap — which is exactly
  // what it did. On touch the label is therefore pinned by a tap and dismissed by
  // tapping somewhere else, and it is placed *above* the finger, because a label under
  // the fingertip is a label you cannot read.
  function placeTip(x, y, above) {
    var holder = tip.parentNode.getBoundingClientRect();
    var left = x - holder.left + (above ? -tip.offsetWidth / 2 : 12);
    var top = y - holder.top + (above ? -tip.offsetHeight - 16 : 12);
    // Keep it inside the map rather than letting it hang off an edge.
    left = Math.max(4, Math.min(left, holder.width - tip.offsetWidth - 4));
    top = Math.max(4, top);
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function showTip(zone, x, y, above) {
    tip.textContent = zone.dataset.label;
    tip.classList.add('is-on');
    placeTip(x, y, above);
  }
  function hideTip() { if (tip) tip.classList.remove('is-on'); }

  svg.addEventListener('pointerover', function (e) {
    if (!tip || e.pointerType === 'touch') return;
    var zone = e.target.closest('.asp-zone');
    if (zone) showTip(zone, e.clientX, e.clientY, false);
  });
  svg.addEventListener('pointermove', function (e) {
    if (!tip || e.pointerType === 'touch') return;
    if (tip.classList.contains('is-on')) placeTip(e.clientX, e.clientY, false);
  });
  svg.addEventListener('pointerout', function (e) {
    // Never on touch: pointerout there means the finger lifted, not that the label
    // stopped being wanted.
    if (!tip || e.pointerType === 'touch') return;
    if (!e.relatedTarget || !e.relatedTarget.closest('.asp-zone')) hideTip();
  });
  svg.addEventListener('pointerdown', function (e) {
    if (!tip || e.pointerType !== 'touch') return;
    var zone = e.target.closest('.asp-zone');
    if (zone) showTip(zone, e.clientX, e.clientY, true);
    else hideTip();
  });
  // A tap anywhere else in the document puts it away.
  document.addEventListener('pointerdown', function (e) {
    if (tip && e.pointerType === 'touch' && !svg.contains(e.target)) hideTip();
  });

  var reset = document.getElementById('asp-reset');
  if (reset) reset.addEventListener('click', function () {
    view = { x: home.x, y: home.y, w: home.w, h: home.h };
    apply();
  });

  refilter();
  apply();
})();
