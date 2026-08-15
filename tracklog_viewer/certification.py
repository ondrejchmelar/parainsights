"""The glider's certification class, from a published database rather than from memory.

An IGC header carries the wing as free text — ``HFGTYGLIDERTYPE:OZONE Zeolite 2`` — and
nothing about certification. The class is what a reader of someone else's flight most
wants beside it: 400 km on an EN A is a different flight from 400 km on a CCC wing, and
the report has no way to know which it is looking at.

**Nothing here is written from memory, and that is the whole design.** Putting an
unverifiable certification claim in front of a pilot is the one kind of error this report
must not make, so every class in `gliders.py` comes with the *Musterprüfnummer* it was
published under and the date this table was fetched. If the match is not certain, the
answer is "unknown" and the report says nothing.

**Two registers, because neither is complete.**

* The **DHV Geräteportal** is the German association's type-approval database — the
  register a German approval is actually recorded in, carrying LTF classes (1, 1-2, 2,
  2-3, 3) and EN classes (A–D) side by side, back to the 1980s. Its weakness is recency
  for manufacturers who stopped seeking a German approval: its newest Ozone is a Buzz Z6
  from 2018, and Ozone is most of the XC field.
* **Air Turquoise** is the Swiss test house that runs most EN 926-2 flight testing, and
  its published report list is where a current wing's EN class appears. Its weakness is
  that it is one test house: a wing tested elsewhere is not in it, and it goes back only
  as far as its own reports.

Merged, they cover the archive's wings; separately, neither did. Every row records which
register it came from and the reference to look it up under, so a class printed in a
report can be checked in the register it came from and not merely believed.

Where the two disagree it is almost always because one is quoting LTF and the other EN
for the same wing. `lookup` prefers the EN class and falls back to LTF, and **never
translates between them**: LTF 1-2 is *about* EN B and every pilot knows it, but "about"
is not a certification.

Re-fetching is one command, and it rewrites the data module with a fresh date:

    uv run python -m tracklog_viewer.certification --refresh

Two things it does not attempt. It does not guess a class from a manufacturer's own
marketing ("high-end B" is not a certification), and it does not fall back to a similar
name — see `lookup`, where an ambiguous match is refused rather than resolved.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PORTAL = "https://service.dhv.de/db3/muster/liste"
REPORTS = "https://para-test.com/reports"
CREDIT = ("Certification data from the DHV Geräteportal (service.dhv.de/db3/muster) "
          "and the Air Turquoise report list (para-test.com/reports)")
PAGE = 100
TIMEOUT = 40
# The portal answers a bare urllib request, but a request with no agent string is the
# kind of traffic a public service is right to block later. Name the tool.
AGENT = "parainsights/1.0 (+https://gitlab.com/parainsights) glider certification table"

# The sizes a wing is sold in, as they appear at the end of a type name. Stripped when
# matching a header that carries no size — see `_model`. Numbers are handled separately:
# a paraglider's flat area is 15–40 m², so a trailing number in that range is a size and
# a trailing "2" is part of the model name ("Zeolite 2", "Aonic 2").
#
# "Light", "lite" and "tandem" are deliberately **not** here. A lightweight version of a
# wing is a separate certification, usually but not always the same class, and treating
# it as a size would fold it into the standard one — which is a claim about a different
# wing that happens to be usually right. `Apollo 2 Light` stays its own model.
SIZE_WORDS = {
    "xxxs", "xxs", "xs", "s", "sm", "ms", "m", "ml", "mm", "l", "ls", "xl", "xxl",
    "xxxl", "small", "medium", "large",
}
SIZE_MIN, SIZE_MAX = 15, 40

# Company words that follow a brand and are not part of a wing's name. Only ever dropped
# *immediately after* a token that is already known to be a brand, and at most three of
# them — "Ozone Gliders LTD VIBE GT XXS" has three, and a longer run is more likely to be
# a model name than a company name. Air Turquoise publishes the manufacturer's legal name
# inside the type name, which is what makes this necessary at all.
COMPANY_WORDS = {
    "ag", "and", "aviation", "co", "company", "corp", "design", "distribution", "e",
    "family", "flugsport", "flugsportgerate", "flugsportgeräte", "gbr", "gesellschaft",
    "glider", "gliders", "gmbh", "group", "inc", "international", "kft", "kg", "korea",
    "ltd", "ltda", "llc", "m", "mbh", "oy", "para", "paragliders", "paragliding",
    "parapentes", "products", "s", "sa", "sarl", "sas", "spa", "sports", "sport", "sro",
    "srl", "technology", "technologies", "usa", "vertrieb", "vertriebsgesellschaft",
}
MAX_COMPANY_WORDS = 3


@dataclass(frozen=True)
class Certification:
    """One row of the register, and the number it was published under."""

    name: str
    manufacturer: str
    source: str         # which register — "DHV" or "Air Turquoise"
    klass: str          # "A".."D", or LTF "1", "1-2", "2", "2-3", "3"
    # The register's *Klassenzusatz*: the conditions the class was granted under —
    # "GH" and "G" are harness restrictions, "Biplace" is a tandem, "E" and "e" mark a
    # limitation on the approval. Kept separate from the class rather than glued to it,
    # because "1-2 GH" is not a class anyone would recognise on a report, and thrown
    # away it would be the report quietly widening someone else's certification.
    addendum: str
    weight: str         # the certified take-off weight range, as published
    certificate: str    # the Musterprüfnummer, or the Air Turquoise report reference
    date: str

    @property
    def en(self) -> str | None:
        """The EN class, or None for a wing whose class is LTF-only.

        The two scales are not the same scale and are not translated here. LTF 1-2 is
        *about* EN B and every pilot knows it, but "about" is not a certification, and
        printing a B beside a wing certified 1-2 would be exactly the invented claim
        this module exists to avoid. The LTF class is printed as an LTF class.
        """
        return self.klass if self.klass in ("A", "B", "C", "D") else None

    @property
    def label(self) -> str:
        """What a report prints: the class, its scale, and any condition on it."""
        scale = "EN" if self.en else "LTF"
        return f"{scale} {self.klass}" + (f" {self.addendum}" if self.addendum else "")


def normalise(text: str) -> str:
    """A glider name reduced to what two spellings of it have in common.

    Loggers, pilots and the register disagree about case, punctuation and spacing:
    ``OZONE Zeolite 2``, ``Ozone Zeolite2`` and ``Ozone  Zeolite  2`` are one wing. What
    is *not* normalised away is the digits — "Mentor 7" and "Mentor 6" are different
    wings with different classes, and a normaliser that dropped the number would answer
    confidently about the wrong one.
    """
    text = html.unescape(text or "").lower()
    text = text.replace("&", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    # A letter running into a digit is a word boundary the two spellings disagree about:
    # the DHV writes "GIN Bonanza2" and the logger writes "GIN GLIDERS Bonanza 2". Split
    # both and they are the same wing. This is also what makes "XC4" and "XC 4" one name.
    text = re.sub(r"(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
    return " ".join(text.split())


def _is_size(token: str) -> bool:
    if token in SIZE_WORDS:
        return True
    return token.isdigit() and SIZE_MIN <= int(token) <= SIZE_MAX


def _model(name: str) -> str:
    """The normalised name with its size stripped off the end.

    A header usually names the wing and not the size ("OZONE Zeolite 2"), while both
    registers list every size separately ("Ozone Zeolite 2 MS"). Stripping from the end
    only: "M" in the middle of a name is a word, not a size.
    """
    tokens = normalise(name).split()
    while len(tokens) > 1 and _is_size(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def _split_brand(name: str, brands: set, company: set = COMPANY_WORDS) -> tuple:
    """(brand, model) — the wing's maker and what is left once it and its size are gone.

    Three spellings of one wing have to land on one key: the logger's
    ``GIN GLIDERS Bonanza 2``, the DHV's ``GIN Bonanza2`` under manufacturer
    "GIN Gliders Inc.", and Air Turquoise's ``Gin Gliders Bonanza 2 M``, which puts the
    company's legal name inside the type name. So the first token is looked up in the
    brands the registers themselves name, and up to three company words after it are
    dropped.

    An unrecognised first token leaves the brand empty rather than guessing that the
    first word of a name is a maker — plenty of models are one word.
    """
    tokens = _model(name).split()
    if not tokens or tokens[0] not in brands:
        return "", " ".join(tokens)
    brand, tokens = tokens[0], tokens[1:]
    dropped = 0
    # A single letter in this position is always a legal form and never a model: the
    # normaliser turns "a.s." into "a s", "s.r.o." into "s r o" and "m.b.H." into
    # "m b h". Without this, "Sky Paragliders a.s. Apollo XL" is a wing called
    # "a s apollo", which then fails to collide with Edel's Apollo — and a collision
    # that does not happen is a refusal that does not happen either.
    while (tokens and dropped < MAX_COMPANY_WORDS
           and (tokens[0] in company or len(tokens[0]) == 1)):
        tokens.pop(0)
        dropped += 1
    # A name that is *only* a brand ("OZONE", which the DHV register does carry as a
    # type name) has no model, and matching on an empty model would match everything.
    return brand, " ".join(tokens)


def _pick(candidates: list) -> "Certification | None":
    """One answer from several rows, or none — where the honesty lives.

    The rows are every certified size of one model, from both registers. They can
    legitimately disagree in three ways, and only one of them has an answer:

    * **EN against LTF.** The same wing is often in the DHV register under LTF 1-2 and
      in Air Turquoise's under EN B. The EN class is what a reader means by "the class",
      so it wins — and the LTF row is not translated into it, it is simply not used.
    * **Size against size.** A model certified B in every size but C in the smallest has
      no single class, and answering B for a pilot who might be on the small one is the
      error this module exists to avoid. No answer.
    * **Condition against condition.** Same rule for the *Klassenzusatz*: a class granted
      only with a particular harness is not the same claim as one granted outright.
    """
    en = [entry for entry in candidates if entry.en]
    pool = en or candidates
    if len({entry.klass for entry in pool}) != 1:
        return None
    if len({entry.addendum for entry in pool}) != 1:
        return None
    # The newest row of the winning class, because a wing recertified after a change is
    # better cited by the later certificate.
    return max(pool, key=lambda entry: entry.date.split(".")[::-1])


def lookup(header: str, table=None) -> "Certification | None":
    """The certification for a glider named in an IGC header, or None.

    Two attempts, both stricter than a guess:

    1. **brand and model.** The header's maker and the register's have to be the same
       maker, and every row for that model has to agree — see `_pick`.
    2. **model alone**, for a header that names no maker this recognises ("Zeolite 2").
       It answers only when one maker in the register makes a wing by that name: two
       makers with an "Apollo" is not a question this can answer, and picking the more
       popular one would be a coin toss printed as a certification.

    There is deliberately no fuzzy match. "Rush 6" against "Rush 5" is one character and
    a whole class of wing, and a report that is usually right about certification is
    worse than one that admits it does not know: a pilot checks a claim that surprises
    them and trusts one that does not.
    """
    table = _table() if table is None else table
    brand, model = _split_brand(header, table["brands"], table["company"])
    if not model:
        return None
    if brand:
        # A named maker that has no wing by this name is an answer of "no", **not** an
        # invitation to look at other makers. Sky Paragliders make an Apollo and so does
        # Edel; a header saying "SKY PARAGLIDERS Apollo" that fell through to Edel's row
        # would print a class from the wrong wing and cite a certificate to prove it.
        return _pick(table["by_brand"][(brand, model)]) \
            if (brand, model) in table["by_brand"] else None
    loose = table["by_model"].get(model)
    if not loose:
        return None
    if len({maker for maker, _ in loose}) != 1:
        return None
    return _pick([entry for _, entry in loose])


_CACHE: dict | None = None


def vocabulary(entries: list) -> tuple[set, set]:
    """(brands, company words) — both read out of the registers, neither typed here.

    A hand-kept list of makers is one more thing to go stale, and it fails silently: it
    stops matching the wing it forgot rather than saying so. So:

    * a **brand** is the first word of any manufacturer the DHV names, plus the first
      word of any type name whose *second* word is a company word — which is how Air
      Turquoise's rows are read, since they carry the maker's legal name inside the type
      name and no manufacturer column at all ("BGD GmbH Base2 L");
    * a **company word** is any word after the first in a manufacturer's name, on top of
      the fixed set. That is what picks up "Thun" in "ADVANCE Thun AG", which is neither
      a generic corporate suffix nor part of any wing's name — and without it the whole
      Advance range reads as models called "thun ag sigma 10".
    """
    brands, company = set(), set(COMPANY_WORDS)
    for entry in entries:
        maker = normalise(entry.manufacturer).split()
        if maker:
            brands.add(maker[0])
            company.update(maker[1:])
    for entry in entries:
        tokens = normalise(entry.name).split()
        if len(tokens) > 2 and tokens[1] in company:
            brands.add(tokens[0])
    return brands, company


def index(entries: list) -> dict:
    """The lookup tables, keyed by (brand, model) and by model alone."""
    brands, company = vocabulary(entries)
    by_brand: dict[tuple, list] = {}
    by_model: dict[str, list] = {}
    for entry in entries:
        brand, model = _split_brand(entry.name, brands, company)
        if not brand:
            maker = normalise(entry.manufacturer).split()
            brand = maker[0] if maker else ""
        if not model:
            continue
        by_brand.setdefault((brand, model), []).append(entry)
        by_model.setdefault(model, []).append((brand, entry))
    return {"entries": entries, "brands": brands, "company": company,
            "by_brand": by_brand, "by_model": by_model}


def _table() -> dict:
    """The committed table, indexed, built once."""
    global _CACHE
    if _CACHE is None:
        from .gliders import GLIDERS

        _CACHE = index([Certification(*row) for row in GLIDERS])
    return _CACHE


# ---------------------------------------------------------------------------
# Fetching. Only `--refresh` runs any of this; the report reads the committed table.
# ---------------------------------------------------------------------------

_ROW = re.compile(r'<div class="mu_listRow">(.*?)(?=<div class="mu_listRow">|\Z)', re.S)


def _field(block: str, pattern: str) -> str:
    found = re.search(pattern, block, re.S)
    return html.unescape(found.group(1)).strip() if found else ""


def parse_dhv(raw: str) -> list[Certification]:
    """Every paraglider on one page of the DHV portal's list.

    The portal's own device-type filter does not narrow the result set, so the kind is
    read off each row instead: "Gleitschirm" is a wing and "Gleitschirm-Gurtzeug" is a
    harness, and a prefix test that missed that difference would file harnesses as
    gliders — with a certification class of their own, which is the sort of wrong answer
    that looks perfectly plausible.
    """
    out = []
    for match in _ROW.finditer(raw):
        block = match.group(1)
        title = _field(block, r'<h2 title="([^"]+)"')
        if not title.startswith("Gleitschirm "):
            continue
        name = title[len("Gleitschirm "):].strip()
        klass = _field(block, r"<strong>Klasse:</strong>\s*([^<]*)")
        if not name or not klass:
            continue
        # The `</a>` is optional: a wing with no DHV detail page — an EAPR or Air
        # Turquoise approval the portal only lists — prints the label unlinked. Requiring
        # the anchor silently dropped the certificate number from 815 of 3 887 rows,
        # which is the one field that makes the class checkable.
        stamp = _field(block, r"Musterprüfung:\s*(?:</a>)?\s*</strong>\s*([^<]*)")
        number, _, when = stamp.partition("(")
        base, _, addendum = klass.strip().partition(" ")
        out.append(Certification(
            name=name,
            manufacturer=_field(block, r"<b>Hersteller:\s*</b>([^<]*)"),
            source="DHV",
            klass=base.strip(),
            addendum=addendum.strip(),
            weight=_field(block, r"<strong>Startgewicht:</strong>\s*([^<]*)"),
            certificate=number.strip(),
            date=when.strip(") "),
        ))
    return out


def fetch_dhv(*, pause: float = 0.5, limit: int | None = None) -> list:
    """Every paraglider in the DHV register, one page of 100 at a time.

    A pause between pages, and a named agent: this is a public service run by a
    volunteer association, and the whole table is fetched once and committed precisely
    so that no reader of a report ever asks it for anything.
    """
    found: list = []
    seen: set = set()
    start = 1
    total = None
    while True:
        url = f"{PORTAL}?count={PAGE}&start={start}"
        raw = _get(url)
        if total is None:
            count = re.search(r"von (\d+)", raw)
            total = int(count.group(1)) if count else 0
            print(f"DHV: {total} entries in the register", file=sys.stderr)
        page = parse_dhv(raw)
        for entry in page:
            # The register lists a type once, but a paged read of a list that is being
            # written to can repeat one across a page boundary.
            if entry.certificate and entry.certificate in seen:
                continue
            seen.add(entry.certificate)
            found.append(entry)
        print(f"  DHV {start:5d}: {len(page):3d} gliders, {len(found)} so far",
              file=sys.stderr)
        start += PAGE
        if start > (total or 0) or (limit and start > limit):
            break
        time.sleep(pause)
    return found


# Air Turquoise publishes one row per report: date, type name, classification, category.
# The name carries the manufacturer's legal name in front of the model, which is what
# `_split_brand` is written to survive.
_AT_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_AT_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# What a paraglider's EN class can be. Everything else on that list is a load test, a
# harness, a reserve or an uncertified prototype, and "No classification" most of all:
# a row that says the wing has no class must never become a row that claims one.
EN_CLASSES = ("A", "B", "C", "D")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_airturquoise(raw: str) -> list:
    """Every glider report on one page of the Air Turquoise list."""
    out = []
    for match in _AT_ROW.finditer(raw):
        cells = [_text(cell) for cell in _AT_CELL.findall(match.group(1))]
        if len(cells) < 4:
            continue
        date, name, klass, category = cells[0], cells[1], cells[2], cells[3]
        if category != "Gliders" or klass not in EN_CLASSES or not name:
            continue
        reference = re.search(r"id=(\d+)", match.group(1))
        out.append(Certification(
            name=name,
            manufacturer="",
            source="Air Turquoise",
            klass=klass,
            addendum="",
            weight="",
            certificate=f"para-test report {reference.group(1)}" if reference else "",
            date=date,
        ))
    return out


def fetch_airturquoise(*, pause: float = 0.5, limit: int | None = None) -> list:
    """Every glider report Air Turquoise lists, one page of twenty at a time."""
    found: list = []
    seen: set = set()
    page = 1
    last = None
    while True:
        raw = _get(f"{REPORTS}?category=Glider_PG_&page={page}")
        if last is None:
            pages = {int(n) for n in re.findall(r"reports\?[^\"]*page=(\d+)", raw)}
            last = max(pages) if pages else 1
            print(f"Air Turquoise: {last} pages of glider reports", file=sys.stderr)
        rows = parse_airturquoise(raw)
        for entry in rows:
            key = (entry.name.lower(), entry.klass)
            if key in seen:
                continue
            seen.add(key)
            found.append(entry)
        print(f"  AT {page:4d}/{last}: {len(rows):3d} gliders, {len(found)} so far",
              file=sys.stderr)
        page += 1
        if page > last or (limit and page > limit):
            break
        time.sleep(pause)
    return found


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return answer.read().decode("utf-8", "replace")


def fetch(*, pause: float = 0.5, limit: int | None = None) -> list:
    """Both registers, merged.

    Neither is dropped where they overlap. A wing in both is usually there as LTF in one
    and EN in the other, and `lookup` needs to see both to prefer the EN class — and a
    reader who wants to check the claim wants the register it came from named.
    """
    return (fetch_dhv(pause=pause, limit=limit)
            + fetch_airturquoise(pause=pause, limit=limit))


def write(entries: list[Certification], path: Path, *, fetched: str) -> None:
    """Rewrite `gliders.py`, in the same generated-data shape `meteo/sites.py` uses."""
    rows = "\n".join(
        "    ({}, {}, {}, {}, {}, {}, {}, {}),".format(
            *(repr(value) for value in
              (e.name, e.manufacturer, e.source, e.klass, e.addendum, e.weight,
               e.certificate, e.date))
        )
        for e in sorted(entries, key=lambda e: (e.manufacturer.lower(), e.name.lower()))
    )
    path.write_text(
        f'''"""Glider type approvals, as committed data.

Generated by `tracklog_viewer.certification.write` from the DHV Geräteportal on
{fetched}:
    {PORTAL}
    {REPORTS}?category=Glider_PG_

One row per certified *size* of a wing, which is how both registers publish it, because
sizes of one model are not always certified the same. Fields: name, manufacturer,
register, class, class addendum, certified take-off weight, reference, approval date.

The class is the register's own — LTF (1, 1-2, 2, 2-3) from the DHV for a wing tested to
LTF, EN (A–D) from either for one tested to EN 926-2 — and the two are **never
translated into each other**. The addendum is the condition the class was granted under
(a harness restriction, a tandem, a limited approval) and is carried with it, because
dropping it widens someone else's approval. The reference is what makes the claim
checkable: a Musterprüfnummer in the DHV register, a report number in Air Turquoise's.

A wing appearing twice, once per register, is normal and not a duplicate: the DHV row is
usually its LTF class and Air Turquoise's its EN class.

Do not edit by hand. `python -m tracklog_viewer.certification --refresh` rewrites it.
"""

SOURCE = {PORTAL!r}
REPORTS = {REPORTS!r}
FETCHED = {fetched!r}
ATTRIBUTION = {CREDIT!r}

# (name, manufacturer, class, weight, certificate, date)
GLIDERS = [
{rows}
]
''',
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracklog_viewer.certification",
        description="The glider certification table: look one up, or re-fetch the lot.",
    )
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch the register and rewrite gliders.py")
    parser.add_argument("glider", nargs="?", help="a glider name to look up")
    args = parser.parse_args(argv)

    if args.refresh:
        import datetime as dt

        entries = fetch()
        target = Path(__file__).with_name("gliders.py")
        write(entries, target, fetched=dt.date.today().isoformat())
        print(f"wrote {len(entries)} gliders to {target}")
        return 0

    if not args.glider:
        parser.error("give a glider name, or --refresh")
    found = lookup(args.glider)
    if found is None:
        print(f"{args.glider}: not in the register, or the match is not certain")
        return 1
    print(f"{found.name} — {found.manufacturer}")
    print(f"  class {found.klass}{'' if found.en else ' (LTF)'}"
          f"{'  ' + found.weight if found.weight else ''}")
    print(f"  {found.certificate}, {found.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
