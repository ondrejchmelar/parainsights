(function () {
  // The published hours are UTC and the reader thinks in Czech local time — two hours
  // apart for the whole flying season, which is a big enough error to be the very thing
  // this control exists to prevent. So the input is wall-clock Prague and the comparison
  // is UTC, with `Intl` doing the conversion rather than a hand-rolled DST rule.
  function pragueOffset(instant) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Prague', hour12: false, year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit'
    }).formatToParts(instant).forEach(function (part) { parts[part.type] = part.value; });
    var wall = Date.UTC(+parts.year, +parts.month - 1, +parts.day,
                        +parts.hour % 24, +parts.minute);
    return (wall - instant.getTime()) / 60000;
  }

  // Prague wall-clock to the instant it names. Twice round, because the first offset is
  // sampled at an instant that is wrong by the offset itself — which only matters within
  // an hour of a DST change, and the second pass lands.
  function fromPrague(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text || '');
    if (!m) return null;
    var wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    var instant = wall;
    for (var i = 0; i < 2; i++) instant = wall - pragueOffset(new Date(instant)) * 60000;
    return new Date(instant);
  }

  function toPrague(instant) {
    var shifted = new Date(instant.getTime() + pragueOffset(instant) * 60000);
    return shifted.toISOString().slice(0, 16);
  }

  function inSeason(month, day, season) {
    var here = month * 100 + day;
    var from = season[0] * 100 + season[1], to = season[2] * 100 + season[3];
    return from <= to ? (here >= from && here <= to) : (here >= from || here <= to);
  }

  // True whenever nothing is known, which is the entire point: a ring with no schedule
  // is a ring this filter must not touch, and that is 251 base airspaces plus every one
  // of the 74 SLZ circuits. No instant answers the same way — the filter is off — and
  // every caller guards for that already, so this is one line to stop the next one
  // having to. The date is read in UTC, which is the AIP's own frame: its operating days
  // go with its operating hours, and both are published Zulu.
  function activeAt(schedule, instant, holidays) {
    if (!instant) return true;
    if (!schedule || !schedule.p || !schedule.p.length) return true;
    var month = instant.getUTCMonth() + 1, day = instant.getUTCDate();
    var weekday = (instant.getUTCDay() + 6) % 7;      // 0 = Monday, as the payload counts
    var minutes = instant.getUTCHours() * 60 + instant.getUTCMinutes();
    var stamp = instant.toISOString().slice(0, 10);
    var holiday = !!(holidays && holidays[stamp]);
    for (var i = 0; i < schedule.p.length; i++) {
      var period = schedule.p[i];
      if (period.s && !inSeason(month, day, period.s)) continue;
      if (period.d && period.d.indexOf(weekday) < 0 && !(period.h && holiday)) continue;
      if (period.w) {
        var from = period.w[0], to = period.w[1];
        var within = from <= to ? (minutes >= from && minutes < to)
                                : (minutes >= from || minutes < to);
        if (!within) continue;
      }
      return true;
    }
    return false;
  }

  var cachedHolidays = null;
  function holidays() {
    if (cachedHolidays) return cachedHolidays;
    var input = document.getElementById('asp-when');
    cachedHolidays = {};
    if (input && input.dataset.holidays) {
      input.dataset.holidays.split(',').forEach(function (day) {
        cachedHolidays[day] = true;
      });
    }
    return cachedHolidays;
  }

  // The instant the controls are asking about, or null when the filter is off.
  function chosen() {
    var box = document.getElementById('asp-when-on');
    var input = document.getElementById('asp-when');
    if (!box || !input || !box.checked) return null;
    return fromPrague(input.value);
  }

  function label(instant) {
    if (!instant) return '';
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Prague', weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).format(instant);
  }

  window.aspHours = { activeAt: activeAt, holidays: holidays, chosen: chosen,
                      toPrague: toPrague, label: label };

  // Open on the reader's own clock. The page is static and may be read months after it
  // was built, so a build-time default would be a date nobody asked about.
  var input = document.getElementById('asp-when');
  if (input && !input.value) input.value = toPrague(new Date());
  var now = document.getElementById('asp-when-now');
  if (now && input) now.addEventListener('click', function () {
    input.value = toPrague(new Date());
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
})();
