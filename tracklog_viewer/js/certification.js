/* The glider's class, from its name in the tracklog: `certification.lookup`, ported.
 * The Python is retired; it is in git at `ada5e5b`.
 *
 * Only the half that turns a header into a key lives here — `normalise`, the size and
 * company-word stripping, the brand split. The answers are decided by the Python
 * (`certification.compact()`), because the answer for a key depends only on the register
 * rows under it: one class across every certified size, or a refusal. No fuzzy match,
 * as there: "Rush 6" against "Rush 5" is one character and a whole class of wing.
 *
 * `table` is that compact form — fetched by the page beside the report when an upload
 * needs it, so the 720 KB register never rides in a page.
 */
(function (TV) {
  'use strict';

  var SIZE_WORDS = { xxxs: 1, xxs: 1, xs: 1, s: 1, sm: 1, ms: 1, m: 1, ml: 1, mm: 1, l: 1, ls: 1, xl: 1,
                     xxl: 1, xxxl: 1, small: 1, medium: 1, large: 1 };
  var SIZE_MIN = 15, SIZE_MAX = 40, MAX_COMPANY_WORDS = 3;
  var NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

  // html.unescape for what a glider name can carry.
  function unescape(text) {
    return text.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);?/g, function (all, code) {
      if (code[0] === '#') {
        var n = code[1] === 'x' || code[1] === 'X' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
        return isFinite(n) ? String.fromCodePoint(n) : all;
      }
      return NAMED[code] !== undefined ? NAMED[code] : all;
    });
  }

  function normalise(text) {
    text = unescape(text || '').toLowerCase().replace(/&/g, ' ');
    text = text.replace(/[^a-z0-9]+/g, ' ');
    text = text.replace(/([a-z])(?=\d)/g, '$1 ').replace(/(\d)(?=[a-z])/g, '$1 ');
    return text.split(/\s+/).filter(Boolean).join(' ');
  }

  function isSize(token) {
    if (SIZE_WORDS[token]) return true;
    return /^\d+$/.test(token) && +token >= SIZE_MIN && +token <= SIZE_MAX;
  }

  function model(name) {
    var tokens = normalise(name).split(' ').filter(Boolean);
    while (tokens.length > 1 && isSize(tokens[tokens.length - 1])) tokens.pop();
    return tokens.join(' ');
  }

  function splitBrand(name, brands, company) {
    var tokens = model(name).split(' ').filter(Boolean);
    if (!tokens.length || !brands[tokens[0]]) return ['', tokens.join(' ')];
    var brand = tokens[0], dropped = 0;
    tokens = tokens.slice(1);
    while (tokens.length && dropped < MAX_COMPANY_WORDS && (company[tokens[0]] || tokens[0].length === 1)) {
      tokens.shift();
      dropped++;
    }
    return [brand, tokens.join(' ')];
  }

  function prepared(table) {
    if (!table.__sets) {
      var sets = { brands: {}, company: {} };
      table.brands.forEach(function (b) { sets.brands[b] = 1; });
      table.company.forEach(function (c) { sets.company[c] = 1; });
      Object.defineProperty(table, '__sets', { value: sets, enumerable: false });
    }
    return table.__sets;
  }

  // { label, name, certificate, source, note } or null; `note` names sizes certified otherwise.
  function lookup(header, table) {
    if (!table) return null;
    var sets = prepared(table), split = splitBrand(header, sets.brands, sets.company);
    var brand = split[0], m = split[1], at;
    if (!m) return null;
    if (brand) {
      at = table.by_brand[brand + '\t' + m];
      if (at === undefined || at < 0) return null;
    } else {
      at = table.by_model[m];
      if (at === undefined || at < 0) return null;
    }
    var a = table.answers[at];
    return { label: a[0], name: a[1], certificate: a[2], source: a[3], note: a[4] || '' };
  }

  TV.certification = { normalise: normalise, model: model, splitBrand: splitBrand, lookup: lookup };
})(typeof window !== 'undefined' ? (window.TV = window.TV || {}) : (globalThis.TV = globalThis.TV || {}));
