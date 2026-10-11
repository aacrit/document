"""void document: the count card (E8). A numeral card from cited data becomes
one 1920x1080 DRAWN frame in the house style, deterministically.

    python -m studio.engine.maps SPEC.json ... --geodata DIR --data DIR --out DIR

A count card is a spec with "kind": "count_card", rendered by the same command
as the maps (maps.render_map dispatches here) and recorded the same way in
maps-render.json, so make_drawn-style ledgers read one record for both.

Truth: the numeral on the card is a cell of a cited table (or a count of its
rows), checked at every render: the citation names the file, its sha256, the
sha256 of the table's doubts file beside it, its licence, the column and the
row's key (and, optionally, the line it sits on). A numeral that is not that
cell is refused; so is a year the table has no row for. A quoted number is
never a count (CoS 2026-10-11): a numeral, a line's {n} or a map figure cited to
a text is refused, and the sentence may be set as typeset text instead. Text
citations stay for what is not a count (`also`). The year is the numeral's own
row's. Every other number on the card (a sub-line such as "36 of today's
countries reporting cases") carries its own cell citation for the same year.
Captions carry no uncited digit or number word. A table's doubts live beside it
(`<table>.doubts.json`, pinned by every citation): `conflicts` and
`zero_suspect` refuse the cells they name; a spec may add doubts, never remove
the table's.

Motion: a count that changes on screen is a sequence of cards, each a cited
value, joined by cuts (`check_sequence`). The engine never draws a value
between two cited values: an intermediate numeral is a number no source
gives, and a label saying "interpolated" cannot be read on a numeral that
changes every frame. A sequence step without a citation is refused.

Brand: design/brand-kit/BRAND-KIT.md 6 and 7, and the chapter card's
composition (motion.chapter_card_frame): centred, the numeral in the data face
(JetBrains Mono, tabular by construction) in --mark-text, the year above it and
the caption below in Inter with numerals in the data face, a short centred rule,
and the frame's source line bottom left as on every DRAWN map. Colours are
tokens only, resolved by maps.palette; the ground is the maps' own ground so a
card cuts to a map without a change of black.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from . import maps as MP
from . import motion as M

W, H, SS = MP.W, MP.H, MP.SS
MapRefused = MP.MapRefused

# sizes are % of frame height; positions are fractions of the frame
CARD = dict(year=3.4, numeral=12.5, caption=2.7, line=2.5,
            year_baseline=0.355, numeral_baseline=0.525, rule_y=0.562, rule_len=0.06, rule_h=0.0019,
            caption_baseline=0.618, line_first=0.672, line_step=0.046, max_w=0.80, rule_alpha=0.6)
NUMERAL_RE = re.compile(r"^(0|[1-9]\d{0,2}(,\d{3})*)$")
YEAR_RE = re.compile(r"^(?:(?:January|February|March|April|May|June|July|August|September|October|November|"
                     r"December) )?(\d{4})$")
CAPTION_MAX = 48
LINES_MAX = 3
# licences under which a card's data obliges attribution (the frame is then CC BY 4.0)
_BY = re.compile(r"(?i)^(cc[- ]?by\b|open (parliament|government) licence)")


class SequenceRefused(MapRefused):
    """A count that would change on screen through a value no source gives."""


def _cites(card: dict) -> list:
    out = [card["cite"]] + [ln["cite"] for ln in card.get("lines", [])]
    return out + list(card.get("also", []))


def _year_of(got: dict, cite: dict) -> str | None:
    """The year a resolved citation is about: a cell's row year, a count's where year; a quote has none."""
    if got["kind"] == "cell":
        return str(got["row"].get(cite.get("year_column", "year")))
    if got["kind"] == "count":
        return str(got["where"].get(cite.get("year_column", "year")))
    return None


def _check_number(cid: str, where: str, numeral: str, year: str, got: dict, cite: dict) -> None:
    """A number and its year from one citation: a data cell or count, whose value equals the numeral
    and whose own row (or where) is the year. A quoted number is never a count (CoS 2026-10-11)."""
    if got["kind"] == "quote":
        raise MapRefused(f"{cid}: {where} ({got['text']} line {got['line']}): {MP.QUOTED_COUNT_REFUSED}")
    if not MP.numeral_supported(numeral, got):
        at = (f"{got['csv']} line {got.get('line')} column {got['column']}" if got["kind"] == "cell"
              else f"{got['csv']} count {got.get('where')}")
        raise MapRefused(f"{cid}: {where}: the card says {numeral}; the cited {at} holds {got['value']!r}. "
                         "A number on screen never differs from its data")
    y = _year_of(got, cite)
    if y != year:
        raise MapRefused(f"{cid}: {where} is cited for {y}; the card says {year}. The year stands in the "
                         "numeral's own citation, or the card is not drawn")


def _words_check(cid: str, where: str, text: str) -> None:
    bad = MP.uncited_numbers(text)
    if bad:
        raise MapRefused(f"{cid}: {where} {text!r} carries {bad} with no citation (digits and number words "
                         "stand only in a cited numeral)")


def check_card(card: dict, data_root) -> dict:
    """Every rule of a count card, resolved against its cited files. Returns the resolved
    citations; raises MapRefused naming what is wrong."""
    cid = card.get("id", "?")
    for k in ("id", "kind", "year", "numeral", "caption", "cite", "source_short", "sources"):
        if k not in card:
            raise MapRefused(f"{cid}: a count card lacks {k}")
    if card["kind"] != "count_card":
        raise MapRefused(f"{cid}: kind is {card['kind']!r}")
    if len(card["source_short"]) > MP.SOURCE_SHORT_MAX:
        raise MapRefused(f"{cid}: source_short is {len(card['source_short'])} characters; "
                         f"the plate holds {MP.SOURCE_SHORT_MAX}")
    bad = sorted(set(k.lower() for k in MP._keys(card)) & MP._COLOUR_KEYS)
    if bad:
        raise MapRefused(f"{cid}: a spec never carries a colour ({bad[0]})")
    shown = {"year": card["year"], "numeral": card["numeral"], "caption": card["caption"],
             "source_short": card["source_short"], **{f"lines[{i}]": ln.get("text", "")
                                                      for i, ln in enumerate(card.get("lines", []))}}
    for where, s in shown.items():
        if MP._COLOUR_VALUE.search(s):
            raise MapRefused(f"{cid}.{where}: colour literal in a spec")
        if "—" in s:
            raise MapRefused(f"{cid}.{where}: em dash in on-screen copy")
    src = card["sources"]
    if not src or any(not s.get("id") or not s.get("licence") for s in src):
        raise MapRefused(f"{cid}: every source needs an id and a licence")
    ids = [s["id"] for s in src]
    if not NUMERAL_RE.match(card["numeral"]):
        raise MapRefused(f"{cid}: the numeral {card['numeral']!r} is a whole count with thousands separators "
                         "(122,098), nothing else")
    ym = YEAR_RE.match(card["year"])
    if not ym:
        raise MapRefused(f"{cid}: the year {card['year']!r} is a year, or a month and a year")
    year = ym.group(1)
    if "year_cites" in card:
        raise MapRefused(f"{cid}: year_cites are not accepted: the year must stand in the numeral's own "
                         "citation (its row, or the same quoted span)")
    _words_check(cid, "the caption", card["caption"])
    if len(card["caption"]) > CAPTION_MAX:
        raise MapRefused(f"{cid}: the caption is {len(card['caption'])} characters; at most {CAPTION_MAX}")
    if len(card.get("lines", [])) > LINES_MAX:
        raise MapRefused(f"{cid}: at most {LINES_MAX} cited lines under the caption")
    for c in _cites(card):
        if c.get("source") not in ids:
            raise MapRefused(f"{cid}: a citation's source {c.get('source')!r} is not in the card's sources")
    used = {c.get("source") for c in _cites(card)}
    for s in ids:
        if s not in used:
            raise MapRefused(f"{cid}: the source {s!r} is on the frame but nothing on the card cites it")

    # the table's own doubts (its sidecar) always apply; the card may only add to them
    extra = MP.check_doubts(card, data_root)

    def resolve(cite, where):
        try:
            return MP.resolve_cite(cite, data_root, extra)
        except MapRefused as e:
            raise MapRefused(f"{cid}: {where}: {e}") from None
    got = resolve(card["cite"], "the numeral")
    _check_number(cid, "the numeral", card["numeral"], year, got, card["cite"])
    lines = []
    for i, ln in enumerate(card.get("lines", [])):
        text = ln.get("text", "")
        if text.count("{n}") != 1 or not ln.get("numeral") or not ln.get("cite"):
            raise MapRefused(f"{cid}: lines[{i}] is a template with exactly one {{n}}, its numeral and its citation")
        _words_check(cid, f"lines[{i}]", text.replace("{n}", ""))
        if not NUMERAL_RE.match(ln["numeral"]):
            raise MapRefused(f"{cid}: lines[{i}] numeral {ln['numeral']!r} is a whole count")
        r = resolve(ln["cite"], f"lines[{i}]")
        _check_number(cid, f"lines[{i}]", ln["numeral"], year, r, ln["cite"])
        lines.append(r)
    also = [MP.resolve_cite(c, data_root) for c in card.get("also", [])]

    def clean(r):
        return {k: v for k, v in r.items() if not k.startswith("_")}
    return {"numeral": clean(got), "year": [], "lines": [clean(r) for r in lines], "also": [clean(r) for r in also]}


def source_line(card: dict) -> str:
    return "Data: " + "; ".join(s["id"] for s in card["sources"])


def method(card: dict, resolved: dict | None = None) -> dict:
    def say(r):
        if r["kind"] == "cell":
            return f"{r['csv']} line {r['line']}, column {r['column']} = {r['value']} (sha256 {r['sha256'][:12]})"
        if r["kind"] == "count":
            return (f"{r['csv']}: {r['value']} {r['rule']} where {r['where']} (sha256 {r['sha256'][:12]})")
        return f"{r['text']} line {r['line']}: \"{r['quote']}\" (sha256 {r['sha256'][:12]})"
    out = {"kind": "count_card", "numeral": card["numeral"], "year": card["year"]}
    if resolved:
        out["cites"] = {"numeral": resolved["numeral"], "year": resolved["year"], "lines": resolved["lines"],
                        "also": resolved["also"]}
        parts = [f"the numeral {card['numeral']} from {say(resolved['numeral'])}"]
        parts += [f"the line \"{ln['text'].replace('{n}', ln['numeral'])}\" from {say(r)}"
                  for ln, r in zip(card.get("lines", []), resolved["lines"])]
        parts += [f"also {say(r)}" for r in resolved["also"]]
        parts.append("checked against the cited file at render; no value interpolated")
        out["text"] = "; ".join(parts)
    return out


def ledger_fields(card: dict, resolved: dict | None = None) -> dict:
    ds = "; ".join(s["id"] for s in card["sources"])
    by = [s for s in card["sources"] if _BY.match(s["licence"])]
    return {"title": f"Count card, {card['year']}: {card['numeral']} {card['caption']}".strip(),
            "data_source": ds, "source_short": card["source_short"],
            "credit": "void document studio, drawn from " + ds,
            "licence": "CC-BY-4.0" if by else "CC0",
            "licence_note": ("the card's figures come from " + "; ".join(f"{s['id']} ({s['licence']})" for s in card["sources"])
                             + ("; the frame is CC BY 4.0 for that attribution" if by else "")),
            "data_sources": card["sources"], "source_line": source_line(card),
            "method": method(card, resolved), **MP.DRAWN_CONTENT}


def render_card(card: dict, data_root, *, fonts: M.Fonts | None = None,
                tokens=MP.TOKENS) -> tuple[Image.Image, dict]:
    """Check one card against its cited files, then draw it. Returns the 1920x1080 RGB
    frame and what it drew (text boxes, the source line, the resolved citations)."""
    resolved = check_card(card, data_root)
    fonts = fonts or M.Fonts()
    pal = MP.palette(tokens)
    cv = MP.Canvas(pal, fonts)
    cx = W * SS / 2
    src = source_line(card)
    cv.text((cx, CARD["year_baseline"] * H * SS), card["year"], "structure", CARD["year"], "muted",
            anchor="ms", halo=False, kind="year")
    nb = cv.text((cx, CARD["numeral_baseline"] * H * SS), card["numeral"], "data", CARD["numeral"], "numeral",
                 anchor="ms", halo=False, kind="numeral")
    if nb[2] - nb[0] > CARD["max_w"] * W:
        raise MapRefused(f"{card['id']}: the numeral is wider than {CARD['max_w']:.0%} of the frame")
    rl, ry = CARD["rule_len"] * W * SS, CARD["rule_y"] * H * SS
    rh = max(SS, round(CARD["rule_h"] * H * SS))
    cv.shape("muted", CARD["rule_alpha"], lambda md: md.rectangle([cx - rl / 2, ry, cx + rl / 2, ry + rh], fill=255))
    cv.text((cx, CARD["caption_baseline"] * H * SS), card["caption"], "structure", CARD["caption"], "text",
            anchor="ms", halo=False, kind="caption")
    for i, ln in enumerate(card.get("lines", [])):
        cv.text((cx, (CARD["line_first"] + i * CARD["line_step"]) * H * SS), ln["text"].replace("{n}", ln["numeral"]),
                "structure", CARD["line"], "muted", anchor="ms", halo=False, kind="line")
    at = MP.source_at(card)
    cv.text((at["x"] * W * SS, at["baseline"] * H * SS), src, "structure",
            MP.SIZES["source"], "muted", halo=False, kind="source")
    warnings = []
    for b in cv.boxes:
        bx = b["box"]
        if bx[0] < 0 or bx[1] < 0 or bx[2] > W or bx[3] > H:
            raise MapRefused(f"{card['id']}: text {b['text']!r} leaves the frame")
        if b["kind"] != "source" and (bx[2] - bx[0]) > CARD["max_w"] * W:
            raise MapRefused(f"{card['id']}: {b['text']!r} is wider than {CARD['max_w']:.0%} of the frame")
        for name, z in MP.FORBIDDEN.items():
            if MP._intersects(bx, MP._zone(z)):
                raise MapRefused(f"{card['id']}: text {b['text']!r} enters the {name} zone")
        if b["kind"] != "source":                   # A31, as maps: the film's own text may cover these for a few seconds
            for name, z in MP.COVERED.items():
                if MP._intersects(bx, MP._zone(z)):
                    warnings.append(f"{b['text']!r} sits in the {name} zone")
    if cv.boxes[-1]["box"][2] > 0.96 * W:
        raise MapRefused(f"{card['id']}: the source line is wider than the frame's safe width")
    MP.source_clear_of_label(card["id"], cv.boxes[-1], W, H)
    img = cv.img.resize((W, H), Image.LANCZOS).convert("RGB")
    return img, {"id": card["id"], "source_line": src, "boxes": cv.boxes, "geodata": {}, "warnings": warnings,
                 "size": [W, H], "data": [], "cites": resolved}


def check_sequence(seq: dict, cards: dict, data_root) -> list[str]:
    """A count that changes on screen: `steps` in order, each the id of a count card (or an
    inline step), joined by cuts. Every step must be a cited card; a step with no citation,
    a step marked interpolated, or a mode other than "cut" (a counter running between two
    values) is refused. Returns the card ids in order."""
    sid = seq.get("id", "?")
    mode = seq.get("mode", "cut")
    if mode != "cut":
        raise SequenceRefused(f"{sid}: mode {mode!r}: a count changes on screen only by cutting between cited "
                              "values; a counter running between them draws numbers no source gives")
    steps = seq.get("steps") or []
    if len(steps) < 2:
        raise SequenceRefused(f"{sid}: a sequence has at least two steps")
    out = []
    for i, st in enumerate(steps):
        if isinstance(st, str):
            if st not in cards:
                raise SequenceRefused(f"{sid}: step {i} names {st!r}, which is not a count card")
            check_card(cards[st], data_root)
            out.append(st)
            continue
        if st.get("interpolated") or not st.get("cite"):
            raise SequenceRefused(f"{sid}: step {i} shows {st.get('numeral')!r} with no citation"
                                  + (" (marked interpolated)" if st.get("interpolated") else "")
                                  + ". No source gives that value: the count is shown only at cited values")
        check_card({**st, "id": f"{sid}[{i}]", "kind": "count_card"}, data_root)
        out.append(f"{sid}[{i}]")
    own = [cards[s] if s in cards else steps[i] for i, s in enumerate(out)]
    for i in range(1, len(own)):
        if own[i]["numeral"] == own[i - 1]["numeral"] and own[i]["year"] == own[i - 1]["year"]:
            raise SequenceRefused(f"{sid}: steps {i - 1} and {i} show the same value for the same year; "
                                  "a step must change the count")
    return out
