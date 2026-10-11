"""GRAMMAR A0, the founding principle: show as was, not as is, and never tell.

    python -m studio.engine.aswas <film dir> [--as-of DATE] [--json]

The engine's plan-time lints for A0. ``render.build_plan`` journals every
check this module returns (``checks``), so a render refuses on any blocking
failure; the command above runs the same checks read-only on a film folder
and prints them (``--as-of`` supplies a horizon to a screenplay that has not
declared one yet, for a report; it never writes the screenplay).

The rules (films/GRAMMAR.md, A0):

- ``as-of-declared``: the screenplay declares its knowledge horizon,
  ``as_of`` (``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``: the end of its story's
  window); an ``era`` it declares ends by then.
- ``as-of``: every shot's ledger item (archive video, still, drawn map), every
  quoted card's source, every mark drawn on a sheet, every reading and every
  archival recording is dated on or before the horizon. Dates are read from
  the ledgers' ``date`` (or ``year``) field. A studio-made item (``generator``
  or ``synthetic``) is dated by the making, so it declares ``content_date``
  (the vintage of what it shows: a map's data) with ``content_basis``; an
  archive item printed after the horizon from earlier material may do the
  same, and is then a review item. A card's source date is its
  ``source_date``, else the latest year on its last line. Metadata surfaces
  are exempt: provenance marks, the credits part, the attribution card and
  the mark key. A ledger item marked ``test_fixture`` is an engine test
  stand-in and is not dated.
- ``known-by``: an element that carries fact ids (``facts: [...]``) resolves
  each in the film's fact ledger (``facts_ledger``), and each fact's
  ``known_by`` (with ``known_by_basis``, the period record that shows it was
  known) is on or before the horizon, even when the film cites a later book.
- ``hindsight-language``: narration, cards, lower thirds, overlays and part
  titles carry none of the phrases in ``studio/show-as-was.json`` and name no
  year after the horizon. Quoted period speech is exempt: testimony lines,
  text inside double quotes, and a card or text element marked
  ``quote: true`` (every line but the last is the quoted text; the last is its
  source).
- ``modern-names``: the same surfaces use no modern place name the horizon
  predates (the house map in the same file, plus the film's own
  ``period_names``).
- ``never-tell``: the same surfaces carry no first-person opinion,
  prescriptive should or must, editorial adjective, verdict adverb or
  mind-reading phrase from the same file.
- ``ending-question``: in an event film (10 minutes or more), the last voiced
  line before the brand end (the credits part) is narration and a question;
  a year after the horizon in it is a warning.

The text functions here and in ``scripts/lib/show-as-was.mjs`` match the same
way; ``tests/fixtures/a0-cases.json`` holds the cases both suites run.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path(__file__).resolve().parents[1] / "show-as-was.json"
GRAMMAR = "A0"
EVENT_FILM_MIN_S = 600.0            # as render.EVENT_FILM_MIN_S: the ending binds unless film and target are both under 10 min
LT_ATTRIBUTION = ("·  read by a computer voice", "·  original recording")
EXEMPT_CARDS = {"mark_key", "attribution", "credits"}

# --------------------------------------------------------------------------
# The lexicon
# --------------------------------------------------------------------------


@lru_cache(maxsize=4)
def lexicon(path: str | None = None) -> dict:
    return json.loads(Path(path or LEXICON_PATH).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Dates: every date is an interval [lo, hi] at the precision it states
# --------------------------------------------------------------------------

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
EARLIEST = dt.date(1, 1, 1)


def _year_span(y: int) -> tuple[dt.date, dt.date]:
    return dt.date(y, 1, 1), dt.date(y, 12, 31)


def _month_span(y: int, m: int) -> tuple[dt.date, dt.date]:
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def parse_date(value) -> tuple[dt.date, dt.date] | None:
    """A date as the interval it can mean: ``1947`` is the whole year,
    ``1947-08`` the month, ``before 1948`` anything up to 31 December 1947,
    ``the 1950s`` the decade. ``circa`` is read as stated. The leading date
    wins (``1959 (compiled 1954 from ...)`` is 1959); None when no year."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return _year_span(value) if 1 <= value <= 9999 else None
    s = str(value).strip()
    low = s.lower()
    m = re.match(r"^before\s+(.*)$", low)
    if m:
        inner = parse_date(m.group(1))
        return (EARLIEST, inner[0] - dt.timedelta(days=1)) if inner else None
    low = re.sub(r"^(circa|ca\.|c\.|about|around)\s*", "", low)
    if m := re.match(r"^(?:the\s+)?(\d{3})0s\b", low):
        d = int(m.group(1)) * 10
        return dt.date(d, 1, 1), dt.date(d + 9, 12, 31)
    try:
        if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})", low):
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d, d
        if m := re.match(r"^(\d{4})-(\d{2})(?!\d)", low):
            return _month_span(int(m.group(1)), int(m.group(2)))
        if (m := re.match(r"^(\d{1,2})\s+([a-z]+)\.?,?\s+(\d{4})", low)) and m.group(2) in MONTHS:
            d = dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
            return d, d
        if (m := re.match(r"^([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", low)) and m.group(1) in MONTHS:
            d = dt.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
            return d, d
        if (m := re.match(r"^([a-z]+)\.?,?\s+(\d{4})", low)) and m.group(1) in MONTHS:
            return _month_span(int(m.group(2)), MONTHS[m.group(1)])
    except ValueError:
        return None
    if m := re.match(r"^(\d{4})(?!\d)", low):
        return _year_span(int(m.group(1)))
    if m := re.search(r"(?<!\d)(\d{4})(?!\d)", low):
        return _year_span(int(m.group(1)))
    return None


def against(date, horizon) -> str:
    """``ok`` when everything the date can mean is on or before the horizon's
    end, ``after`` when all of it is later, ``imprecise`` when it straddles."""
    if date[1] <= horizon[1]:
        return "ok"
    return "after" if date[0] > horizon[1] else "imprecise"


def fmt(span) -> str:
    lo, hi = span
    if lo == hi:
        return lo.isoformat()
    return f"{'' if lo == EARLIEST else lo.isoformat()}..{hi.isoformat()}"


# --------------------------------------------------------------------------
# Text: quotes, phrases, period names and years (scripts/lib/show-as-was.mjs mirrors these)
# --------------------------------------------------------------------------

QUOTE_SPANS = (re.compile("“[^”]*”"), re.compile('"[^"]*"'))


def strip_quotes(text: str) -> str:
    """Text with every double-quoted span blanked: quoted period speech is exempt."""
    for rx in QUOTE_SPANS:
        text = rx.sub(" ", text)
    return text


def _phrase_rx(phrase: str, *, ignore_case: bool) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\s-]+", phrase.strip()) if w]
    edge = "a-z0-9" if ignore_case else "A-Za-z0-9"
    body = r"[\s-]+".join(words)
    return re.compile(f"(?<![{edge}])" + body + f"(?![{edge}])", re.I if ignore_case else 0)


@lru_cache(maxsize=4096)
def _rx(phrase: str, ignore_case: bool) -> re.Pattern:
    return _phrase_rx(phrase, ignore_case=ignore_case)


def _norm(text: str) -> str:
    return strip_quotes(str(text or "")).replace("’", "'").replace("‘", "'")


def phrase_hits(text: str, groups: list[dict]) -> list[dict]:
    """Every phrase of every group found in the unquoted text, in list order;
    a group's ``except`` phrases are blanked first ("two years later" is
    chronology inside the story, "years later" is not)."""
    base = _norm(text)
    out = []
    for g in groups:
        t = base
        for x in g.get("except") or []:
            t = _rx(x, True).sub(" ", t)
        for p in g["phrases"]:
            if _rx(p, True).search(t):
                out.append({"group": g["id"], "phrase": p})
    return out


UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split()) if i}
TEENS = {w: 10 + i for i, w in enumerate("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
CENTURIES = {"eighteen": 18, "nineteen": 19}
YEAR_CONTEXT = {"in", "of", "by", "since", "until", "till", "from", "to", "between", "year", "years", "summer", "winter",
                "spring", "autumn", "monsoon", "early", "late", "mid"} | {m for m in MONTHS if len(m) > 3}


def _under_100(tok: list[str], i: int) -> tuple[int, int] | None:
    if i >= len(tok):
        return None
    w = tok[i]
    if w in ("oh", "o") and i + 1 < len(tok) and tok[i + 1] in UNITS:
        return UNITS[tok[i + 1]], i + 2
    if w in TEENS:
        return TEENS[w], i + 1
    if w in TENS:
        if i + 1 < len(tok) and tok[i + 1] in UNITS:
            return TENS[w] + UNITS[tok[i + 1]], i + 2
        return TENS[w], i + 1
    if w in UNITS:
        return UNITS[w], i + 1
    return None


def spoken_years(text: str) -> list[int]:
    """Years written out as narration says them: "nineteen forty-seven" always;
    "nineteen hundred" and "two thousand and fifteen" only after a word that
    makes them a date (in, by, since, a month...), so "two thousand and
    ninety-four villages" is a count, not a year."""
    tok = re.findall(r"[a-z]+", _norm(text).lower())
    out = []
    i = 0
    while i < len(tok):
        w = tok[i]
        ctx = i > 0 and tok[i - 1] in YEAR_CONTEXT
        if w in CENTURIES and i + 1 < len(tok):
            if tok[i + 1] == "hundred":
                if ctx:
                    j = i + 2 + (1 if i + 2 < len(tok) and tok[i + 2] == "and" else 0)
                    rest = _under_100(tok, j) if j > i + 2 else None
                    out.append(CENTURIES[w] * 100 + (rest[0] if rest else 0))
                    i = rest[1] if rest else i + 2
                    continue
            else:
                rest = _under_100(tok, i + 1)
                if rest and rest[0] >= 1 and tok[i + 1] not in UNITS:
                    out.append(CENTURIES[w] * 100 + rest[0])
                    i = rest[1]
                    continue
        if w == "two" and i + 1 < len(tok) and tok[i + 1] == "thousand" and ctx:
            j = i + 2 + (1 if i + 2 < len(tok) and tok[i + 2] == "and" else 0)
            rest = _under_100(tok, j)
            out.append(2000 + (rest[0] if rest else 0))
            i = rest[1] if rest else i + 2
            continue
        i += 1
    return out


NUMERAL_YEAR = re.compile(r"(?<![\d,.])(1\d{3}|20\d{2})(?![\d,])")


def years_in(text: str) -> list[int]:
    """Every year in the unquoted text: numerals (a decade, "1950s", counts
    from its first year) and years written out."""
    t = _norm(text)
    return [int(y) for y in NUMERAL_YEAR.findall(t)] + spoken_years(t)


def name_entries(play: dict | None = None, lex: dict | None = None) -> list[dict]:
    lex = lex or lexicon()
    return list(lex["period_names"]) + list((play or {}).get("period_names") or [])


def modern_name_hits(text: str, horizon, entries: list[dict]) -> list[dict]:
    """Modern names the horizon predates (every one, with no horizon)."""
    base = _norm(text)
    out = []
    for e in entries:
        until = parse_date(e.get("until"))
        if horizon is not None and until is not None and horizon[1] >= until[0]:
            continue
        t = base
        for x in e.get("except") or []:
            t = _rx(x, False).sub(" ", t)
        if _rx(e["modern"], False).search(t):
            out.append({"modern": e["modern"], "period": e["period"], "until": e.get("until")})
    return out


# --------------------------------------------------------------------------
# The screenplay's surfaces
# --------------------------------------------------------------------------


def _card_kind(shot: dict, part: dict, first: bool) -> str:
    if shot.get("card"):
        return shot["card"]
    if shot.get("silent_record"):
        return "silent"
    if part.get("kind") in ("title", "credits"):
        return part["kind"]
    if part.get("kind") == "chapter" and first:
        return "chapter"
    return "statement"


def surfaces(play: dict) -> list[dict]:
    """Every piece of on-screen or narrated text A0's language lints read:
    ``{unit, role, text}``. Testimony, quoted lines and metadata (the credits
    part, the attribution card, the mark key, a lower third's attribution
    line) are left out."""
    out = []
    for part in play.get("parts") or []:
        if part.get("kind") == "credits":
            continue
        for k in ("title", "dates"):
            if isinstance(part.get(k), str) and part[k].strip():
                out.append({"unit": f"part {part.get('id')}", "role": "part", "text": part[k]})
        for ln in part.get("lines") or []:
            if ln.get("kind") == "narration":
                out.append({"unit": ln.get("id"), "role": "narration", "text": ln.get("text") or ""})
        for k, s in enumerate(part.get("shots") or []):
            if s.get("kind") != "card":
                continue
            ck = _card_kind(s, part, k == 0)
            if ck in EXEMPT_CARDS:
                continue
            lines = [str(x) for x in (s.get("text") or [])]
            if s.get("quote") is True:
                lines = []
            out += [{"unit": s.get("id"), "role": "card", "text": x} for x in lines]
        for t in part.get("text") or []:
            if t.get("quote") is True:
                continue
            lines = [str(x) for x in (t.get("lines") or [])]
            if t.get("kind") == "lower_third" and len(lines) >= 3 and lines[2].rstrip().endswith(LT_ATTRIBUTION):
                lines = lines[:2]
            out += [{"unit": t.get("id"), "role": t.get("kind") or "text", "text": x} for x in lines]
    return out


def _all_elements(play: dict):
    for part in play.get("parts") or []:
        for coll in ("shots", "lines", "text", "cues"):
            for x in part.get(coll) or []:
                yield part, coll, x


def _brand_end(play: dict) -> float:
    starts = [float(s.get("start_s") or 0.0) for p in play.get("parts") or [] if p.get("kind") == "credits"
              for s in p.get("shots") or []]
    return min(starts) if starts else float("inf")


def _film_end(play: dict) -> float:
    ends = [float(s.get("start_s") or 0.0) + float(s.get("dur_s") or 0.0) for p in play.get("parts") or []
            for s in p.get("shots") or []]
    return max(ends) if ends else 0.0


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def _check(rule, ok, *, unit=None, severity="block", evidence=None) -> dict:
    return {"rule": rule, "ok": bool(ok), "unit": unit, "severity": severity, "evidence": evidence, "grammar": GRAMMAR}


def _summary(rule: str, found: list[dict], checked: int) -> list[dict]:
    if any(not c["ok"] and c["severity"] == "block" for c in found):
        return found
    return found + [_check(rule, True, evidence={"checked": checked})]


def horizon_of(play: dict, as_of=None):
    return parse_date(as_of if as_of is not None else play.get("as_of"))


def item_date(item: dict, horizon) -> tuple[str, dict]:
    """(status, evidence) for one ledger item against the horizon: ok, after,
    imprecise, undated, studio-made, no-basis, exempt; status ``review`` is a
    later printing dated by its content."""
    ev = {"asset": item.get("id"), "date": item.get("date") if item.get("date") is not None else item.get("year")}
    if item.get("test_fixture"):
        return "exempt", dict(ev, why="an engine test stand-in (test_fixture) is not dated")
    if item.get("content_date") is not None:
        ev["content_date"] = item["content_date"]
        if not str(item.get("content_basis") or "").strip():
            return "no-basis", dict(ev, fix="content_date needs content_basis: what shows the content is of that date")
        span = parse_date(item["content_date"])
        if span is None:
            return "undated", dict(ev, fix="content_date is not a date")
        st = against(span, horizon)
        own = parse_date(ev["date"])
        if st == "ok" and own is not None and against(own, horizon) != "ok" and not (item.get("generator") or item.get("synthetic")):
            return "review", dict(ev, why="printed after the horizon and dated by its content: the reviewer confirms nothing on it postdates the horizon")
        return st, ev
    if item.get("generator") or item.get("synthetic"):
        return "studio-made", dict(ev, fix="a studio-made item is dated by its making; declare content_date (the vintage of the data it draws) and content_basis")
    span = parse_date(ev["date"])
    if span is None:
        return "undated", dict(ev, fix="the ledger item needs a date (or year) the engine can read")
    return against(span, horizon), ev


def as_of_checks(play: dict, assets: dict, horizon) -> list[dict]:
    found, checked = [], 0
    hz = fmt(horizon)
    era_to = ((play.get("era") or {}).get("to")) if isinstance(play.get("era"), dict) else None
    if era_to is not None:
        span = parse_date(era_to)
        ok = span is not None and against(span, horizon) == "ok"
        checked += 1
        if not ok:
            found.append(_check("as-of", False, unit="era", evidence={"era_to": era_to, "as_of": hz,
                                "fix": "the era a screenplay draws ends on or before its horizon"}))

    def judge(unit, status, ev, *, severity="block"):
        ev = dict(ev, as_of=hz)
        if status in ("ok", "exempt"):
            return
        if status == "review":
            found.append(_check("as-of", True, unit=unit, severity="review", evidence=ev))
            return
        ev.setdefault("why", {"after": "dated after the horizon", "imprecise": "its date may fall after the horizon",
                              "undated": "no date", "studio-made": "dated by the making", "no-basis": "no basis"}[status])
        found.append(_check("as-of", False, unit=unit, severity=severity, evidence=ev))

    for part in play.get("parts") or []:
        credits = part.get("kind") == "credits"
        for k, s in enumerate(part.get("shots") or []):
            item = assets.get(s.get("asset")) if s.get("asset") else None
            if s.get("kind") in ("archive_video", "archive_still", "drawn") and item is not None:
                checked += 1
                judge(s.get("id"), *item_date(item, horizon))
            for mk in s.get("marks") or []:
                for f in ("feature_year", "geometry_year"):
                    if mk.get(f) is None:
                        continue
                    checked += 1
                    span = parse_date(mk[f])
                    st = "undated" if span is None else against(span, horizon)
                    judge(f"{s.get('id')}/{mk.get('id')}", st, {"field": f, "year": mk[f]})
            if s.get("kind") == "card" and not credits and _card_kind(s, part, k == 0) not in EXEMPT_CARDS | {"chapter", "title", "silent"}:
                lines = [str(x) for x in (s.get("text") or [])]
                src = s.get("source_date")
                if src is None and len(lines) >= 2:
                    ys = [int(y) for y in NUMERAL_YEAR.findall(lines[-1])]
                    src = max(ys) if ys else None
                if src is not None:
                    checked += 1
                    span = parse_date(src)
                    judge(s.get("id"), "undated" if span is None else against(span, horizon),
                          {"source_date": src, "source_line": lines[-1] if lines else None})
                elif s.get("quote") is True:
                    checked += 1
                    judge(s.get("id"), "undated", {"fix": "a quoted card names its source's date: source_date, or a year on its last line"})
        for ln in part.get("lines") or []:
            if ln.get("kind") != "testimony":
                continue
            checked += 1
            y = ln.get("year") if ln.get("year") is not None else ln.get("date")
            clip = assets.get(ln.get("clip")) if ln.get("clip") else None
            if clip is not None and clip.get("test_fixture"):
                continue
            span = parse_date(y)
            judge(ln.get("id"), "undated" if span is None else against(span, horizon),
                  {"year": y, "speaker": ln.get("speaker"), "what": "the year of the words"})
            if clip is not None:
                checked += 1
                judge(ln.get("id"), *item_date(clip, horizon))
        for c in part.get("cues") or []:
            item = assets.get(c.get("source")) if c.get("kind") == "ambience" else None
            if item is not None:
                checked += 1
                judge(c.get("id"), *item_date(item, horizon), severity="warn")
    return _summary("as-of", found, checked)


def _load_facts(film: Path | None, play: dict) -> tuple[dict | None, str | None]:
    ref = play.get("facts_ledger")
    if not ref:
        return None, None
    path = Path(ref)
    if not path.is_absolute() and film is not None:
        path = film / path
    if not path.exists():
        return None, f"facts_ledger not found at {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else (data.get("facts") or data.get("checks") or data.get("items") or [])
    return {f["id"]: f for f in items if isinstance(f, dict) and f.get("id")}, None


def known_by_checks(play: dict, horizon, film: Path | None) -> list[dict]:
    refs = [(x.get("id"), fid) for _, _, x in _all_elements(play) for fid in (x.get("facts") or [])]
    narrated = sum(1 for _, coll, x in _all_elements(play) if coll == "lines" and x.get("kind") == "narration")
    if not refs:
        return [_check("known-by", False, severity="warn", evidence={
            "why": "no narrated or carded fact carries a fact id, so none is checked against the horizon",
            "narration_lines": narrated,
            "fix": "give each narrated fact facts: [<id>] in the film's facts_ledger, with known_by and known_by_basis"})]
    facts, problem = _load_facts(film, play)
    if facts is None:
        return [_check("known-by", False, unit="facts_ledger", evidence={
            "why": problem or "elements carry fact ids but the screenplay names no facts_ledger"})]
    found = []
    for unit, fid in refs:
        f = facts.get(fid)
        if f is None:
            found.append(_check("known-by", False, unit=unit, evidence={"fact": fid, "why": "not in the facts ledger"}))
            continue
        if not str(f.get("known_by_basis") or "").strip():
            found.append(_check("known-by", False, unit=unit, evidence={"fact": fid, "why": "known_by_basis is missing"}))
            continue
        span = parse_date(f.get("known_by"))
        if span is None:
            found.append(_check("known-by", False, unit=unit, evidence={"fact": fid, "known_by": f.get("known_by"),
                                                                        "why": "known_by is missing or not a date"}))
            continue
        st = against(span, horizon) if horizon else "ok"
        if st != "ok":
            found.append(_check("known-by", False, unit=unit, evidence={
                "fact": fid, "known_by": f.get("known_by"), "as_of": fmt(horizon),
                "why": "known only after the horizon" if st == "after" else "may have been known only after the horizon"}))
    return _summary("known-by", found, len(refs))


def language_checks(play: dict, horizon, lex: dict | None = None) -> list[dict]:
    lex = lex or lexicon()
    entries = name_entries(play, lex)
    surf = surfaces(play)
    hind, names, tell = [], [], []
    for s in surf:
        hits = phrase_hits(s["text"], lex["hindsight"])
        if horizon is not None:
            hits += [{"group": "year-after-horizon", "phrase": str(y)} for y in years_in(s["text"]) if y > horizon[1].year]
        if hits:
            hind.append(_check("hindsight-language", False, unit=s["unit"], evidence={"text": s["text"], "hits": hits}))
        mh = modern_name_hits(s["text"], horizon, entries)
        if mh:
            names.append(_check("modern-names", False, unit=s["unit"], evidence={
                "text": s["text"], "hits": mh, "as_of": fmt(horizon) if horizon else None}))
        th = phrase_hits(s["text"], lex["never_tell"])
        if th:
            tell.append(_check("never-tell", False, unit=s["unit"], evidence={"text": s["text"], "hits": th}))
    n = len(surf)
    return _summary("hindsight-language", hind, n) + _summary("modern-names", names, n) + _summary("never-tell", tell, n)


QUESTION_END = re.compile(r"\?[\s\"'”’)]*$")


def ending_checks(play: dict, horizon) -> list[dict]:
    end, target = _film_end(play), float(play.get("runtime_target_s") or 0.0)
    if end < EVENT_FILM_MIN_S and target < EVENT_FILM_MIN_S:
        return [_check("ending-question", True, evidence={"why": "not an event film (under 10 minutes): no ending is required",
                                                          "film_s": round(end, 3)})]
    brand = _brand_end(play)
    voiced = sorted((ln for p in play.get("parts") or [] for ln in p.get("lines") or []
                     if ln.get("kind") in ("narration", "testimony") and float(ln.get("start_s") or 0.0) < brand),
                    key=lambda ln: float(ln.get("start_s") or 0.0))
    if not voiced:
        return [_check("ending-question", False, evidence={"why": "the film has no voiced line"})]
    last = voiced[-1]
    narr = [ln for ln in voiced if ln.get("kind") == "narration"]
    out = []
    if last.get("kind") != "narration":
        out.append(_check("ending-question", False, unit=last.get("id"), evidence={
            "why": "the last voiced line before the brand end is not the narrator's", "text": last.get("text"),
            "last_narration": narr[-1].get("id") if narr else None}))
    elif not QUESTION_END.search(str(last.get("text") or "").rstrip()):
        out.append(_check("ending-question", False, unit=last.get("id"), evidence={
            "why": "the last narration line is not a question", "text": last.get("text")}))
    else:
        out.append(_check("ending-question", True, unit=last.get("id"), evidence={"text": last.get("text")}))
        late = [y for y in years_in(last.get("text") or "") if horizon is not None and y > horizon[1].year]
        if late:
            out.append(_check("ending-question-year", False, unit=last.get("id"), severity="warn", evidence={
                "why": "the closing question names a year after the horizon", "years": late, "as_of": fmt(horizon)}))
    return out


def checks(play: dict, assets: dict | None = None, *, film: Path | None = None, as_of=None) -> list[dict]:
    """Every A0 check for a screenplay and its ledgers (``render.load_ledgers``),
    as ``{rule, ok, unit, severity, evidence, grammar}``."""
    assets = assets or {}
    horizon = horizon_of(play, as_of)
    raw = as_of if as_of is not None else play.get("as_of")
    out = [_check("as-of-declared", horizon is not None, unit="as_of", evidence={
        "as_of": raw, "parsed": fmt(horizon) if horizon else None,
        **({} if horizon else {"fix": "declare as_of (YYYY, YYYY-MM or YYYY-MM-DD): the end of the story's window"})})]
    if horizon is not None:
        out += as_of_checks(play, assets, horizon)
    out += known_by_checks(play, horizon, film)
    out += language_checks(play, horizon)
    out += ending_checks(play, horizon)
    return out


# --------------------------------------------------------------------------
# Read-only report
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.aswas", description=__doc__.split("\n\n")[0])
    ap.add_argument("film", type=Path, help="film folder with screenplay.json and its ledgers")
    ap.add_argument("--as-of", default=None, help="a horizon for a screenplay that has not declared one (report only)")
    ap.add_argument("--json", action="store_true", help="print every check as JSON lines")
    args = ap.parse_args(argv)
    from studio.engine.render import load_ledgers     # lazy: render imports this module
    play = json.loads((args.film / "screenplay.json").read_text(encoding="utf-8"))
    assets = load_ledgers(args.film, play)
    res = checks(play, assets, film=args.film, as_of=args.as_of)
    if args.json:
        for c in res:
            print(json.dumps(c, ensure_ascii=False, default=str))
    else:
        bad = [c for c in res if not c["ok"] or c["severity"] == "review"]
        for c in bad:
            ev = c.get("evidence") or {}
            short = {k: v for k, v in ev.items() if k in ("text", "hits", "asset", "date", "content_date", "year",
                                                         "source_date", "why", "fact", "field", "era_to", "years")}
            print(f"{c['severity']:6} {c['rule']:20} {c.get('unit') or '-':14} {json.dumps(short, ensure_ascii=False)}")
        blocking = sum(1 for c in res if not c["ok"] and c["severity"] == "block")
        print(f"{blocking} blocking, {sum(1 for c in res if not c['ok'] and c['severity'] == 'warn')} warnings")
    return 1 if any(not c["ok"] and c["severity"] == "block" for c in res) else 0


if __name__ == "__main__":
    sys.exit(main())
