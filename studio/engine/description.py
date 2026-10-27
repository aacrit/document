"""A56: the per-film description block, generated from the film's sources.json.

The picture carries only the dot (A42); every disclosure it no longer shows (the
voices, the speakers the record names only by role, the sources and their
licences, the map notes, the gaps in the record and the shortfall statements)
is stated in the sources data. This module prints that data as plain text for
the film's video description (``<out>/description.txt``, at most about 5000
characters, no markup), in the sections of document-description-block-spec.md.
The Sources page's "Notes on this film" (web/src/film-data.ts ``filmNotes``)
reads the same fields of the same file.

``description_text`` is pure (no I/O). The CLI writes the file:

    python -m studio.engine.description <out>/sources.json [--films films.json] [--out description.txt]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SITE = "https://document.voidvision.org"
MAX_CHARS = 5000
PLACEHOLDER = re.compile(r"\{[a-z_]+(?::\w+)?\}")

# The player's Marks legend, one line per class: the glyph and its colour (motion.GLYPH_SHAPE, motion.MARK_HUE)
MARKS = (
    ("ARCHIVE", "Amber dot, Archive: real film or photograph from the archive, unaltered beyond trims, crops and slow "
                "moves."),
    ("RECONSTRUCTED", "Bone dot, Reconstructed: archive film or photographs changed in a way that matters "
                      "(colourised, re-timed, stabilised or enlarged by a computer model); the label names the change."),
    ("AI-GENERATED", "Blue diamond, AI-generated: made by a computer model (places, weather, objects); never people, "
                     "never a recorded event."),
    ("DRAWN", "Blue square, Drawn: a map or diagram drawn by us from named data."),
    ("CARD", "Bone ring, void document: our own text on black, the titles and chapter cards."),
)


def _s(x) -> str:
    return " ".join(str(x or "").split())


def clock(s) -> str:
    try:
        t = int(round(float(s)))
    except (TypeError, ValueError):
        return ""
    h, m, sec = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


_CC = re.compile(r"(?i)\bCC[- ]?(BY(?:[- ]SA)?)[- ]?(\d\.\d)\b")
_CC0 = re.compile(r"(?i)\bCC[- ]?0\b|\bCC[- ]?ZERO\b")
_ATTRIBUTION = re.compile(r"(?i)\bCC[- ]?BY\b")      # every CC licence that asks for attribution (BY, BY-SA, ...)


class AttributionOverflow(ValueError):
    """Even the sources-page line cannot fit the description's cap, or the film has no public sources page (no slug
    in films.json) for the attribution to point to (CC BY 4.0 3(a)(2): a URI to a resource holding it)."""


def licence_uri(lic) -> str | None:
    """A Creative Commons licence's deed URI ("CC BY 4.0", "CC-BY-4.0" -> https://creativecommons.org/licenses/by/4.0/;
    CC0 -> https://creativecommons.org/publicdomain/zero/1.0/)."""
    m = _CC.search(_s(lic))
    if not m:
        return "https://creativecommons.org/publicdomain/zero/1.0/" if _CC0.search(_s(lic)) else None
    return f"https://creativecommons.org/licenses/{m.group(1).lower().replace(' ', '-').replace('--', '-')}/{m.group(2)}/"


_STUDIO = re.compile(r"(?i)^void document\b")


def studio_owned(s: dict) -> bool:
    """A work the studio itself licenses (the series title masters, our cards): its creator, credit or archive is void
    document. We owe ourselves no attribution."""
    return any(_STUDIO.search(_s(s.get(k))) for k in ("creator", "credit", "archive"))


def obligated(s: dict) -> bool:
    """A source the film must attribute wherever it is credited: a CC BY or BY-SA licence held by someone else, or data
    it was drawn from (a studio map that names its data owes that data its credit). CC0 and public domain ask for
    nothing (the description still names them while there is room)."""
    if s.get("data_sources"):
        return True
    return bool(_ATTRIBUTION.search(_s(s.get("licence")))) and not studio_owned(s)


def is_map(s: dict) -> bool:
    return bool(s.get("data_sources")) or _s(s.get("source_line")).startswith("Data:")


def shot_name(s: dict) -> str:
    """What the description calls a shot's item: its title, else a plain description; never the internal ledger id
    for a map (CC BY attribution names the work, not the studio's file)."""
    if _s(s.get("title")):
        return _s(s.get("title"))
    if is_map(s):
        return "A drawn map"
    return _s(s.get("ledger_id"))


def map_attribution(s: dict) -> str:
    """A map's data, each source with its url and licence, a CC licence by its URI (CC BY 4.0 asks for both)."""
    bits = []
    for d in s.get("data_sources") or []:
        if not isinstance(d, dict) or not _s(d.get("id")):
            continue
        name = re.sub(r"\s*\([^)]*\)", "", _s(d["id"])).strip() or _s(d["id"])
        lic = _s(d.get("licence"))
        uri = licence_uri(lic)
        bits.append(", ".join(x for x in (name, _s(d.get("url")), lic, uri) if x))
    if not bits and licence_uri(s.get("licence")):
        bits.append(licence_uri(s.get("licence")))
    return ("Data: " + "; ".join(bits)) if bits else ""


def _voice(v) -> str:
    """'kokoro:am_onyx' or {engine, voice} -> "Kokoro 'am_onyx'"."""
    if isinstance(v, dict):
        eng, name = _s(v.get("engine")), _s(v.get("voice"))
    else:
        eng, _, name = _s(v).partition(":")
    if not name:
        return eng.capitalize()
    return f"{eng.capitalize()} '{name}'" if eng else f"'{name}'"


def statement_text(sf: dict) -> str | None:
    """A shortfall's statement as printed: the filled sentence, else the
    statement when it holds no placeholder. An unfilled statement is never
    printed (its numbers would be false)."""
    if not isinstance(sf, dict):
        return None
    for k in ("filled", "statement"):
        t = _s(sf.get(k))
        if t and not PLACEHOLDER.search(t):
            return t
    return None


def notes(src: dict) -> dict:
    """The disclosures the picture no longer shows, from sources.json: the
    fields the description block and the Sources page's "Notes on this film"
    print. Every list is in the film's order; nothing is invented."""
    readings = [r for r in src.get("readings") or [] if isinstance(r, dict)]
    nv = src.get("narrator") if isinstance(src.get("narrator"), dict) else None
    narrator = None
    if nv and (nv.get("engine") or nv.get("voice")):
        shift = nv.get("pitch_shift_st")
        narrator = f"Narration: a computer voice, {_voice(nv)}" + (
            f", pitched {shift:+g} semitones" if isinstance(shift, (int, float)) and shift else "") + "."
    readers, seen = [], set()
    for r in readings:
        if r.get("mark") == "ARCHIVE" or not r.get("reader"):
            continue
        key = (r.get("name"), r.get("reader"))
        if key not in seen:
            seen.add(key)
            readers.append(f"{_s(r.get('name') or r.get('speaker'))} ({_voice(r['reader'])})")
    originals, seen = [], set()
    for r in readings:
        if r.get("mark") != "ARCHIVE":
            continue
        line = ", ".join(x for x in (_s(r.get("name")), _s(r.get("source") or r.get("clip"))) if x)
        if line and line not in seen:
            seen.add(line)
            originals.append(line)
    unnamed = []
    for u in src.get("unnamed_speakers") or []:
        if not isinstance(u, dict):
            continue
        at = ", ".join(f"{ln.get('id')} ({clock(ln.get('start_s'))})" for ln in u.get("lines") or [] if isinstance(ln, dict))
        unnamed.append(_s(u.get("name")) + (f": {at}" if at else ""))
    entries, seen = [], set()
    for s in src.get("shots") or []:
        if not isinstance(s, dict) or not s.get("ledger_id") or (s.get("mark") or {}).get("class") == "CARD":
            continue
        if s["ledger_id"] in seen:
            continue
        seen.add(s["ledger_id"])
        lic = _s(s.get("licence"))
        must = obligated(s)
        credit = _s(s.get("credit"))
        # CC BY asks for the title, the author, the source and the licence, the licence by its URI
        # (a map's attribution is its data, printed by map_attribution below)
        cc_by = bool(_ATTRIBUTION.search(lic))
        author = ""
        if cc_by and not is_map(s) and not credit and _s(s.get("creator")) not in ("", _s(s.get("archive"))):
            author = f"By {_s(s.get('creator'))}"
        uri = licence_uri(lic) if cc_by else None
        bits = [shot_name(s), author, _s(s.get("archive")), " ".join(x for x in (lic, uri) if x), _s(s.get("item_url"))]
        line = ". ".join(b for b in bits if b)
        if credit and (re.search(r"(?i)\bBY[- ]SA\b", lic) or (cc_by and not is_map(s))):
            line += f". Attribution: {credit}"
        if _s(s.get("licence_note")):
            line += f" ({_s(s.get('licence_note'))})"
        if is_map(s) and map_attribution(s):
            line += ". " + map_attribution(s)
        entries.append({"line": line, "obligated": must, "name": f"{s['ledger_id']} ({shot_name(s)})",
                        "ledger_id": s["ledger_id"]})
    for r in readings:
        if r.get("mark") == "ARCHIVE" and r.get("clip") and r["clip"] not in seen:
            seen.add(r["clip"])
            entries.append({"line": _s(r.get("source") or r["clip"]), "obligated": False, "name": _s(r["clip"]),
                            "ledger_id": None})
    map_notes, map_dups = [], {}
    for s in src.get("shots") or []:
        if not isinstance(s, dict):
            continue
        for n in s.get("notes") or []:
            t = f"{shot_name(s)}: {_s(n)}"
            if _s(n) and t not in map_notes:
                map_notes.append(t)
        # the data credit, with each source's url and its licence's URI when the map names its data; it repeats the
        # map's own source entry, so description_text prints it only when that entry is not printed in full
        data = map_attribution(s) if s.get("data_sources") else ""
        line = data or _s(s.get("source_line"))
        t = f"{shot_name(s)}: {line}"
        if line and t not in map_notes:
            map_notes.append(t)
            if data and s.get("ledger_id"):
                map_dups[t] = s["ledger_id"]
    gaps = [{"says": _s(g.get("says")), "searched": _s(g.get("searched"))}
            for g in src.get("gaps") or [] if isinstance(g, dict) and _s(g.get("says"))]
    statements = [t for t in (statement_text(sf) for sf in src.get("shortfalls") or []) if t]
    return {"narrator": narrator, "readers": readers, "originals": originals, "unnamed": unnamed,
            "sources": [e["line"] for e in entries], "source_entries": entries, "map_notes": map_notes,
            "map_note_owner": map_dups,
            "gaps": gaps, "statements": statements}


SOURCES_LINE = "Full sources, credits and licences for every shot: {url}"


def sources_page(slug: str, site: str = SITE) -> str:
    """The film's public sources page, as the build serves it (scripts/lib/films.mjs: f/<slug>/sources/index.html)."""
    return f"{site}/f/{slug}/sources/"


def description_text(src: dict, film: dict | None = None, *, site: str = SITE) -> str:
    """The plain-text description block for one film (no markup, at most MAX_CHARS characters).

    Over the cap, the sources list is cut first: plain entries go before any entry with an attribution obligation
    (obligated()). When the obligated entries alone do not fit, as many as fit are printed whole, in film order, and
    the fixed SOURCES_LINE points to the film's sources page, which holds every credit, creator, licence deed and
    data link (CC BY 4.0 3(a)(2)). That needs the film's slug from films.json (``film``); without one, or when even
    that line cannot fit, AttributionOverflow is raised. A map's data note is printed only when its own source
    entry is not."""
    film = film or {}
    n = notes(src)
    slug = _s(src.get("slug") or film.get("slug"))
    title = _s(film.get("title") or src.get("title"))
    head = title + (f" ({_s(film['dates'])})" if film.get("dates") else "")
    out = [head]
    if film.get("logline"):
        lg = _s(film["logline"])
        out.append(lg[:1].upper() + lg[1:] + ("" if lg.endswith(".") else "."))
    out += ["", "How to read the marks", "The mark in the corner says what you see."]
    out += [line for _, line in MARKS]
    voices = [x for x in [n["narrator"],
                          ("Read by computer voices: " + "; ".join(n["readers"]) + ".") if n["readers"] else None,
                          ("Original recordings: " + "; ".join(n["originals"]) + ".") if n["originals"] else None] if x]
    if voices:
        out += ["", "Voices"] + voices
    if n["unnamed"]:
        out += ["", "Speakers not named on screen", "The record names these speakers only by role."] + n["unnamed"]

    def after(printed: set) -> list:
        """The sections after the sources list, with only the map notes whose map's full entry is not printed."""
        a = []
        mn = [t for t in n["map_notes"] if n["map_note_owner"].get(t) is None or n["map_note_owner"][t] not in printed]
        if mn:
            a += ["", "Notes on the maps"] + mn
        if n["gaps"] or n["statements"]:
            a += ["", "Gaps in the record"]
            a += [g["says"] + (f" {g['searched']}" if g["searched"] else "") for g in n["gaps"]] + n["statements"]
        return a + ["", "Every shot, reading and licence: " + sources_page(slug, site),
                    "Correct something: " + f"{site}/f/{slug}/correct/"]

    entries = n["source_entries"]
    if not entries:
        return "\n".join(out + after(set()))[:MAX_CHARS]
    every = {e["ledger_id"] for e in entries}
    text = "\n".join(out + ["", "Sources"] + [e["line"] for e in entries] + after(every))
    if len(text) <= MAX_CHARS:
        return text
    must = [e for e in entries if e["obligated"]]
    printed_must = {e["ledger_id"] for e in must}

    def compose(keep: list, tail: str, printed: set) -> str:
        return "\n".join(out + ["", "Sources"] + [e["line"] for e in keep] + [tail] + after(printed))

    more = "The full list is on the sources page."
    if len(compose(must, more, printed_must)) <= MAX_CHARS:
        # every obligated entry fits whole: plain entries fill the room left, a prefix in film order
        room = MAX_CHARS - len(compose(must, more, printed_must))
        keep, cutting = [], False
        for e in entries:
            if e["obligated"]:
                keep.append(e)
            elif not cutting and len(e["line"]) + 1 <= room:
                keep.append(e)
                room -= len(e["line"]) + 1
            else:
                cutting = True
        return compose(keep, more, printed_must)
    # the obligated entries alone overflow: the sources page carries the attribution (CC BY 4.0 3(a)(2))
    film_slug = _s(film.get("slug"))
    if not film_slug:
        raise AttributionOverflow(
            f"{slug or 'this film'}: the attributed sources do not fit the cap of {MAX_CHARS} characters and the film "
            f"has no slug in films.json, so there is no public sources page to point to; these are owed attribution: "
            + "; ".join(e["name"] for e in must))
    link = SOURCES_LINE.format(url=sources_page(film_slug, site))
    floor = compose([], link, set())
    if len(floor) > MAX_CHARS:
        raise AttributionOverflow(
            f"{film_slug}: even with no source entry the description is {len(floor)} characters, over the cap of "
            f"{MAX_CHARS}, so the sources-page line cannot be printed")
    keep, printed = [], set()
    for e in must:                                   # whole entries only, in film order, until the next does not fit
        if len(compose(keep + [e], link, printed | {e["ledger_id"]})) > MAX_CHARS:
            break
        keep.append(e)
        printed.add(e["ledger_id"])
    return compose(keep, link, printed)


def film_entry(films_json: Path | None, slug: str) -> dict | None:
    if not films_json or not films_json.exists():
        return None
    reg = json.loads(films_json.read_text(encoding="utf-8"))
    return next((f for f in reg.get("films", []) if isinstance(f, dict) and f.get("slug") == slug), None)


def write_description(sources_path: Path, films_json: Path | None = None, out: Path | None = None) -> Path:
    src = json.loads(Path(sources_path).read_text(encoding="utf-8"))
    out = Path(out) if out else Path(sources_path).with_name("description.txt")
    out.write_text(description_text(src, film_entry(films_json, src.get("slug") or "")) + "\n", encoding="utf-8")
    return out


REPO_FILMS = Path(__file__).resolve().parents[2] / "films.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write a film's description block from its sources.json (A56).")
    ap.add_argument("sources", type=Path)
    ap.add_argument("--films", type=Path, default=REPO_FILMS, help="the film registry (default: the repo's films.json)")
    ap.add_argument("--out", type=Path, default=None, help="default: description.txt beside sources.json")
    a = ap.parse_args(argv)
    print(write_description(a.sources, a.films, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
