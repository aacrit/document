"""A56: the per-film description block, generated from the film's sources.json.

The picture carries only the dot (A42); every disclosure it no longer shows (the
voices, the speakers the record names only by role, the sources and their
licences, the map notes, the gaps in the record and the shortfall statements)
is stated in the sources data. This module prints that data as plain text for
the film's video description (``<out>/description.txt``, at most 5000
characters, no markup), in the sections of document-description-block-spec.md.
Every work under a CC licence before 4.0 is credited here in full; only a 4.0
work may be left to the film's sources page (CC BY 4.0 3(a)(2)): see
description_text.
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


# The Creative Commons licences the house links to a deed, shared with the site (web/src/film-data.ts reads it too).
CC_TABLE = json.loads((Path(__file__).resolve().parents[1] / "cc-licences.json").read_text(encoding="utf-8"))
_SPELLED = re.compile(r"(?i)\bCreative\s+Commons\s+Attribution((?:[- ]?(?:Share[- ]?Alike|Non[- ]?Commercial|"
                      r"No[- ]?Deriv(?:s|atives)))*)(?:\s+Licen[cs]e)?\s+(\d\.\d)")
_CC_ID = re.compile(r"(?i)\bCC[- ]?(BY(?:[- ](?:NC|ND|SA)){0,2})[- ]?(\d\.\d)(?:[- ]([A-Za-z]{2})\b)?")
_CC0 = re.compile(r"(?i)\bCC[- ]?0\b|\bCC[- ]?ZERO\b|\bCreative\s+Commons\s+Zero\b")
_ATTRIBUTION = re.compile(r"(?i)\bCC[- ]?BY\b")      # every CC licence that asks for attribution (BY, BY-SA, ...)


class AttributionOverflow(ValueError):
    """A work under a CC licence before 4.0 cannot be credited in full within the description's cap. Before 4.0 the
    licence asks for the credit itself, so it is never replaced by the sources-page line (CC BY 4.0 3(a)(2) allows
    that for 4.0 works only)."""


def normalise_licence(text) -> str:
    """A spelled-out licence name as its id ("Creative Commons Attribution-ShareAlike 3.0 Unported" ->
    "CC BY-SA 3.0 Unported"); everything else is left as it is."""
    def short(m):
        codes = []
        for w in re.findall(r"(?i)Share[- ]?Alike|Non[- ]?Commercial|No[- ]?Deriv(?:s|atives)", m.group(1)):
            w = w.lower()
            codes.append("SA" if w.startswith("share") else "NC" if w.startswith("non") else "ND")
        return "CC BY" + "".join("-" + c for c in codes) + " " + m.group(2)
    return _SPELLED.sub(short, _s(text))


def cc_licences(text) -> list[dict]:
    """Every attribution licence a text names: its kind (by, by-sa, by-nc-sa ...), version, jurisdiction (a ported
    licence before 4.0: "CC BY 3.0 US") and deed. The deed is None when CC published no such licence (an unknown
    kind or version, a 4.0 "port")."""
    out = []
    for m in _CC_ID.finditer(normalise_licence(text)):
        kind, ver = re.sub(r"[ ]", "-", m.group(1).lower()), m.group(2)
        jur = m.group(3) if m.group(3) and m.group(3).isupper() else None
        ok = (kind in CC_TABLE["kinds"] and ver in CC_TABLE["versions"]
              and (not jur or ver in CC_TABLE["ported_versions"]))
        deed = (f"https://creativecommons.org/licenses/{kind}/{ver}/" + (f"{jur.lower()}/" if jur else "")) if ok else None
        out.append({"kind": kind, "version": ver, "jurisdiction": jur, "deed": deed})
    return out


def licence_uri(lic) -> str | None:
    """A Creative Commons licence's deed URI ("CC BY 4.0", "CC-BY-4.0" -> https://creativecommons.org/licenses/by/4.0/;
    "CC BY 3.0 US" -> .../by/3.0/us/; CC0 -> https://creativecommons.org/publicdomain/zero/1.0/), or None."""
    found = cc_licences(lic)
    if found:
        return found[0]["deed"]
    return "https://creativecommons.org/publicdomain/zero/1.0/" if _CC0.search(_s(lic)) else None


def names_cc_by(text) -> bool:
    return bool(_ATTRIBUTION.search(normalise_licence(text)))


_STUDIO = re.compile(r"(?i)^void document\b")
_STUDIO_ONLY = re.compile(r"(?i)^void document(?: studio)?\.?$")


def studio_owned(s: dict) -> bool:
    """A work the studio itself licenses (the series title masters, our cards): its creator is void document and no
    one else is named, the credit empty or itself only void document. We owe ourselves no attribution; a credit
    that names a source ("void document studio, drawn from ...") is someone else's work too."""
    credit = _s(s.get("credit"))
    return bool(_STUDIO.search(_s(s.get("creator")))) and (not credit or bool(_STUDIO_ONLY.match(credit)))


def is_map(s: dict) -> bool:
    mark = s.get("mark") if isinstance(s.get("mark"), dict) else {}
    return (bool(s.get("data_sources")) or _s(s.get("source_line")).startswith("Data:")
            or _s(mark.get("detail")) == "from map data" or _s(mark.get("label")).endswith("from map data"))


def obligated(s: dict) -> bool:
    """A source the film must attribute wherever it is credited: a CC BY-family licence held by someone else, data a
    map was drawn from, or a map whose source line or licence note names a CC BY licence. CC0 and public domain ask
    for nothing (the description still names them while there is room)."""
    if s.get("data_sources"):
        return True
    if is_map(s) and (names_cc_by(s.get("source_line")) or names_cc_by(s.get("licence_note"))):
        return True
    return names_cc_by(s.get("licence")) and not studio_owned(s)


def attribution_versions(s: dict) -> set[str]:
    """The versions of every attribution licence a shot's credit involves ("?" for one CC never published, or a CC
    BY named with no version)."""
    texts = [s.get("licence"), s.get("licence_note"), s.get("source_line")]
    for d in s.get("data_sources") or []:
        if isinstance(d, dict):
            texts += [d.get("licence"), d.get("id")]
    out: set[str] = set()
    for t in texts:
        found = cc_licences(t)
        out |= {f["version"] if f["deed"] else "?" for f in found}
        if not found and names_cc_by(t):
            out.add("?")
    return out


def tier(s: dict) -> str:
    """'full': owed attribution under a licence before 4.0 (or one not read), always printed whole; 'uri': owed
    only under 4.0 (or a courtesy to data with no CC licence), which the sources page may carry (CC BY 4.0
    3(a)(2)); 'plain': owed nothing."""
    if not obligated(s):
        return "plain"
    return "full" if any(v != "4.0" for v in attribution_versions(s)) else "uri"


def _on_commons(url) -> bool:
    return bool(re.match(r"(?i)^https://(commons|upload)\.wikimedia\.org/", _s(url)))


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
        credit = _s(s.get("credit"))
        # CC BY asks for the title, the author, the source and the licence, the licence by its URI
        # (a map's attribution is its data, printed by map_attribution below)
        cc_by = names_cc_by(lic)
        archive = _s(s.get("archive"))
        author = ""
        if cc_by and not is_map(s) and not credit and _s(s.get("creator")) not in ("", archive):
            author = f"By {_s(s.get('creator'))}"
        if archive.lower().startswith("wikimedia commons") and _on_commons(s.get("item_url")):
            archive = ""                             # the item's own link already says where it is
        uri = licence_uri(lic) if cc_by else None
        bits = [shot_name(s), author, archive, " ".join(x for x in (lic, uri) if x), _s(s.get("item_url"))]
        line = ". ".join(b for b in bits if b)
        if credit and (re.search(r"(?i)\bBY[- ]SA\b", normalise_licence(lic)) or (cc_by and not is_map(s))):
            line += f". Attribution: {credit}"
        if _s(s.get("licence_note")):
            line += f" ({_s(s.get('licence_note'))})"
        if is_map(s) and map_attribution(s):
            line += ". " + map_attribution(s)
        entries.append({"line": line, "tier": tier(s), "name": f"{s['ledger_id']} ({shot_name(s)})",
                        "ledger_id": s["ledger_id"]})
    for r in readings:
        if r.get("mark") == "ARCHIVE" and r.get("clip") and r["clip"] not in seen:
            seen.add(r["clip"])
            entries.append({"line": _s(r.get("source") or r["clip"]), "tier": "plain", "name": _s(r["clip"]),
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


def compose(src: dict, film: dict | None = None, *, site: str = SITE) -> tuple[str, list[dict]]:
    """The description block and the obligated entries it leaves to the sources page (see description_text)."""
    film = film or {}
    n = notes(src)
    slug = _s(film.get("slug") or src.get("slug"))     # the page films.json lists; else the render's own slug
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
    link = SOURCES_LINE.format(url=sources_page(slug, site))
    entries = n["source_entries"]

    def block(keep: set, data_notes: bool = True) -> str:
        """The text with the entries at these indexes, in film order. A map's data note repeats its own entry, so
        it is printed only when that entry is not, and only with data_notes (a map whose entry is left out is owed
        attribution only under 4.0: a full-tier map is always printed, so the note is a courtesy, kept when there
        is room)."""
        printed = {entries[i]["ledger_id"] for i in keep}
        a = (["", "Sources"] + [e["line"] for i, e in enumerate(entries) if i in keep] + [link]) if entries else []
        mn = [t for t in n["map_notes"] if n["map_note_owner"].get(t) is None
              or (data_notes and n["map_note_owner"][t] not in printed)]
        if mn:
            a += ["", "Notes on the maps"] + mn
        if n["gaps"] or n["statements"]:
            a += ["", "Gaps in the record"]
            a += [g["says"] + (f" {g['searched']}" if g["searched"] else "") for g in n["gaps"]] + n["statements"]
        a += ([] if entries else ["", link]) + ["", "Correct something: " + f"{site}/f/{slug}/correct/"]
        return "\n".join(out + a)

    every = set(range(len(entries)))
    if not entries or len(block(every)) <= MAX_CHARS:
        return block(every)[:MAX_CHARS], []
    by = {t: [i for i, e in enumerate(entries) if e["tier"] == t] for t in ("full", "uri", "plain")}
    keep = set(by["full"])
    floor = block(keep, data_notes=False)
    if len(floor) > MAX_CHARS:
        raise AttributionOverflow(
            f"{slug or 'this film'}: the works under a CC licence before 4.0 must be credited in full, and with every "
            f"other source cut the description is {len(floor)} characters, over the cap of {MAX_CHARS}: "
            + "; ".join(entries[i]["name"] for i in by["full"]))
    whole = True
    for i in by["uri"]:                              # 4.0 works, whole, in film order, until the next does not fit
        if len(block(keep | {i}, data_notes=False)) > MAX_CHARS:
            whole = False
            break
        keep.add(i)
    notes_on = len(block(keep)) <= MAX_CHARS         # then the data notes of maps left out, when there is room
    if whole:                                        # then plain entries, while there is room
        for i in by["plain"]:
            if len(block(keep | {i}, data_notes=notes_on)) > MAX_CHARS:
                break
            keep.add(i)
    return block(keep, data_notes=notes_on), [entries[i] for i in by["uri"] if i not in keep]


def description_text(src: dict, film: dict | None = None, *, site: str = SITE) -> str:
    """The plain-text description block for one film (no markup, at most MAX_CHARS characters).

    The Sources list ends on SOURCES_LINE, the film's sources page, which holds every credit, creator, licence deed
    and data link. Over the cap, entries are kept in this order and printed in film order: every work under a CC
    licence before 4.0, whole (title, author, link, licence and deed URI: those licences ask for the credit itself);
    then works owed attribution only under 4.0, whole, for as many as fit (CC BY 4.0 3(a)(2) lets the sources page
    carry the rest); then plain entries. AttributionOverflow is raised when the pre-4.0 credits alone do not fit.
    ``film`` is the film's films.json entry; a film not listed yet takes its slug from sources.json (the release
    step refuses it while its description leans on a sources page that is not served). A map's data note is
    printed only when its own source entry is not."""
    return compose(src, film, site=site)[0]


def release_problem(src: dict, film: dict | None) -> str | None:
    """Why the description cannot be published with this film, or None: its pre-4.0 credits do not fit, or it
    leaves 4.0 attributions to a sources page the film does not have (not in films.json)."""
    try:
        _, left = compose(src, film)
    except AttributionOverflow as e:
        return str(e)
    if left and not _s((film or {}).get("slug")):
        return (f"{_s(src.get('slug')) or 'this film'} is not in films.json, so its sources page is not served, yet "
                f"its description leaves these attributions to that page: " + "; ".join(e["name"] for e in left))
    return None


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
