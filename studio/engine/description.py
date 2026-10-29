"""A56: the per-film description block, generated from the film's sources.json.

The picture carries only the dot (A42); every disclosure it no longer shows (the
voices, the speakers the record names only by role, the sources and their
licences, the map notes, the gaps in the record and the shortfall statements)
is stated in the sources data. This module prints that data as plain text for
the film's video description (``<out>/description.txt``, at most 5000
characters, no markup), in the sections of document-description-block-spec.md.
description.txt exists only for publication on an outside platform with that
limit (a video platform); the site's Sources page carries every credit, creator,
deed and data link, so the description never gates a render or a site release.
Every work under a CC licence before 4.0 is credited here in full when it fits;
only a 4.0 work may be left to the film's sources page (CC BY 4.0 3(a)(2)). When
the text is over the cap for any reason (pre-4.0 credits, notes, gaps, voices),
the best description that fits is written, opening with a header saying it is
incomplete (that visible header is the guard), and its sidecar
``description.attribution.json`` says ``external_publish_ready: false`` and lists
what was left out: see compose. ``--check-external`` reports the same, advisory.
The Sources page's "Notes on this film" (web/src/film-data.ts ``filmNotes``)
reads the same fields of the same file.

``description_text`` and ``compose`` are pure (no I/O). The CLI writes the files, or checks external publication:

    python -m studio.engine.description <out>/sources.json [--films films.json] [--out description.txt]
    python -m studio.engine.description --check-external <out>/sources.json [--films films.json]   (advisory)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
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


# The Creative Commons licences the house links to a deed: the site's own table (web/src/film-data.ts imports it).
CC_TABLE = json.loads((Path(__file__).resolve().parents[2] / "web" / "src" / "cc-licences.json")
                      .read_text(encoding="utf-8"))
_SPELLED = re.compile(r"(?i)\bCreative\s+Commons\s+Attribution((?:[- ]?(?:Share[- ]?Alike|Non[- ]?Commercial|"
                      r"No[- ]?Deriv(?:s|atives)))*)(?:\s+Licen[cs]e)?\s+(\d\.\d)")
_CC_ID = re.compile(r"(?i)\bCC[- ]?(BY(?:[- ](?:NC|ND|SA)){0,2})[- ]?(\d\.\d)(?:[- ](IGO|[A-Za-z]{2})\b)?")
_CC0 = re.compile(r"(?i)\bCC[- ]?0\b|\bCC[- ]?ZERO\b|\bCreative\s+Commons\s+Zero\b")
_ATTRIBUTION = re.compile(r"(?i)\bCC[- ]?BY\b")      # every CC licence that asks for attribution (BY, BY-SA, ...)


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
              and (not jur or ver in CC_TABLE["igo_versions" if jur == "IGO" else "ported_versions"]))
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


_STUDIO_ONLY = re.compile(r"(?i)^void document(?: studio)?\.?$")


def studio_owned(s: dict) -> bool:
    """A work the studio itself licenses (the series title masters, our cards): its creator is only void document
    (no one else named beside or after it), the credit empty or itself only void document. We owe ourselves no attribution; a credit
    that names a source ("void document studio, drawn from ...") is someone else's work too."""
    credit = _s(s.get("credit"))
    return bool(_STUDIO_ONLY.match(_s(s.get("creator")))) and (not credit or bool(_STUDIO_ONLY.match(credit)))


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


_PUBLIC = re.compile(r"(?i)\bpublic[- ]domain\b")


def attribution_versions(s: dict) -> set[str]:
    """The versions of every attribution licence a shot's credit involves ("?" for one CC never published, a CC BY
    named with no version, or a map's data under a licence other than public domain, CC0 or CC: ODbL, none stated)."""
    texts = [s.get("licence"), s.get("licence_note"), s.get("source_line")]
    for d in s.get("data_sources") or []:
        if isinstance(d, dict):
            texts += [d.get("licence"), d.get("id")]
    out: set[str] = set()
    for d in s.get("data_sources") or []:
        lic = _s(d.get("licence")) if isinstance(d, dict) else ""
        if not (_PUBLIC.search(lic) or _CC0.search(lic) or cc_licences(lic)):
            out.add("?")
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
        for n in (s.get("notes") if isinstance(s.get("notes"), list) else []):   # never a string, letter by letter
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


INCOMPLETE = ("This description is incomplete: what does not fit here is left out. Full credits and notes for every "
              "shot are on the film's sources page: {url}")

# Over the cap for any reason, lines are cut in this order until the text fits (each from the end of its list): the
# gaps, the map notes, plain sources, 4.0 credits, the unnamed speakers, the voices, pre-4.0 credits, the marks key.
# The title, the INCOMPLETE header, the sources-page line and the "Correct something" line are never cut.
TRIM_ORDER = ("gaps", "map_notes", "plain", "uri", "unnamed", "voices", "full", "marks")
TRIM_NAMES = {"gaps": "gap line(s)", "map_notes": "map note(s)", "plain": "plain source(s)", "uri": "4.0 credit(s)",
              "unnamed": "unnamed speaker line(s)", "voices": "voice line(s)", "full": "pre-4.0 credit(s)",
              "marks": "marks key line(s)"}


def compose(src: dict, film: dict | None = None, *, site: str = SITE) -> dict:
    """The description block and what it leaves out, as a report. It never raises for length and its text never
    exceeds MAX_CHARS.

    ``text`` the block (see description_text); ``omitted`` the pre-4.0 credits left out; ``left`` the 4.0 credits
    left to the sources page; ``trimmed`` how many lines of each other section were cut to fit; ``incomplete`` whether
    the text opens with the INCOMPLETE header (whenever a pre-4.0 credit or a trimmed line is left out); ``listed``
    whether the film is in films.json; ``unserved_page`` whether the text leaves credits to a sources page films.json
    does not serve; ``external_publish_ready`` true only when nothing is left out that a licence asks the description
    itself to carry, nothing was cut, and no credit leans on an unserved page; ``problems`` why not, one line each."""
    film = film or {}
    n = notes(src)
    slug = _s(film.get("slug") or src.get("slug"))     # the page films.json lists; else the render's own slug
    title = _s(film.get("title") or src.get("title"))
    head = title + (f" ({_s(film['dates'])})" if film.get("dates") else "")
    page = sources_page(slug, site)
    top = [head]
    if film.get("logline"):
        lg = _s(film["logline"])
        top.append(lg[:1].upper() + lg[1:] + ("" if lg.endswith(".") else "."))
    marks = ["The mark in the corner says what you see."] + [line for _, line in MARKS]
    voices = [x for x in [n["narrator"],
                          ("Read by computer voices: " + "; ".join(n["readers"]) + ".") if n["readers"] else None,
                          ("Original recordings: " + "; ".join(n["originals"]) + ".") if n["originals"] else None] if x]
    gap_lines = [g["says"] + (f" {g['searched']}" if g["searched"] else "") for g in n["gaps"]] + n["statements"]
    link = SOURCES_LINE.format(url=page)
    correct = "Correct something: " + f"{site}/f/{slug}/correct/"
    entries = n["source_entries"]
    st = {"header": False, "cut": dict.fromkeys(("gaps", "map_notes", "unnamed", "voices", "marks"), 0), "top": top}

    def cut(lines: list, k: int) -> list:
        return lines[:len(lines) - k] if k else lines

    def map_notes(keep: set, data_notes: bool) -> list:
        printed = {entries[i]["ledger_id"] for i in keep}
        return [t for t in n["map_notes"] if n["map_note_owner"].get(t) is None
                or (data_notes and n["map_note_owner"][t] not in printed)]

    def block(keep: set, data_notes: bool = True) -> str:
        """The text with the entries at these indexes, in film order. A map's data note repeats its own entry, so
        it is printed only when that entry is not, and only with data_notes (a map whose entry is left out is owed
        attribution only under 4.0: a full-tier map is printed whenever the pre-4.0 credits fit, so the note is a
        courtesy, kept when there is room)."""
        c = st["cut"]
        out = list(st["top"]) + ([INCOMPLETE.format(url=page)] if st["header"] else [])
        mk = cut(marks, c["marks"])
        if mk:
            out += ["", "How to read the marks"] + mk
        v = cut(voices, c["voices"])
        if v:
            out += ["", "Voices"] + v
        u = cut(n["unnamed"], c["unnamed"])
        if u:
            out += ["", "Speakers not named on screen", "The record names these speakers only by role."] + u
        if entries:
            out += ["", "Sources"] + [e["line"] for i, e in enumerate(entries) if i in keep] + [link]
        mn = cut(map_notes(keep, data_notes), c["map_notes"])
        if mn:
            out += ["", "Notes on the maps"] + mn
        g = cut(gap_lines, c["gaps"])
        if g:
            out += ["", "Gaps in the record"] + g
        out += ([] if entries else ["", link]) + ["", correct]
        return "\n".join(out)

    listed = bool(_s(film.get("slug")))
    by = {t: [i for i, e in enumerate(entries) if e["tier"] == t] for t in ("full", "uri", "plain")}

    def fit(keep: set, data_notes: bool) -> tuple[str, set]:
        """The text for this selection, cut to the cap when it is over (TRIM_ORDER), with the INCOMPLETE header."""
        text = block(keep, data_notes)
        if len(text) <= MAX_CHARS:
            return text, keep
        st["header"] = True
        keep = set(keep)
        size = {"gaps": len(gap_lines), "map_notes": len(map_notes(keep, data_notes)), "unnamed": len(n["unnamed"]),
                "voices": len(voices), "marks": len(marks)}
        for sec in TRIM_ORDER:
            if sec in by:                            # source entries: from the end of the film, within the tier
                for i in reversed(by[sec]):
                    if len(text) <= MAX_CHARS:
                        break
                    if i in keep:
                        keep.discard(i)
                        st["cut"][sec] = st["cut"].get(sec, 0) + 1
                        text = block(keep, data_notes)
                continue
            while len(text) > MAX_CHARS and st["cut"][sec] < size[sec]:
                st["cut"][sec] += 1
                text = block(keep, data_notes)
        if len(text) > MAX_CHARS:                    # only the title is left to give: cut it, never the fixed lines
            over = len(text) - MAX_CHARS
            joined = "\n".join(st["top"])
            st["top"] = [joined[:max(0, len(joined) - over)].rstrip()]
            text = block(keep, data_notes)
        return text[:MAX_CHARS], keep

    def report(text: str, keep: set) -> dict:
        omitted = [e for i, e in enumerate(entries) if e["tier"] == "full" and i not in keep]
        left = [e for i, e in enumerate(entries) if e["tier"] == "uri" and i not in keep]
        trimmed = {k: v for k, v in st["cut"].items() if v}      # incl. entries cut by fit ("plain", "uri", "full")
        dropped = [e for i, e in enumerate(entries) if e["tier"] == "plain" and i not in keep]
        unserved = bool(left or omitted) and not listed
        problems = []
        if omitted:
            problems.append(f"{slug or 'this film'}: {len(omitted)} work(s) under a CC licence before 4.0 do not fit "
                            f"the description's cap of {MAX_CHARS} characters and are left out of it (the sources "
                            f"page credits them): " + "; ".join(e["name"] for e in omitted))
        if trimmed:
            problems.append(f"{slug or 'this film'}: over the cap of {MAX_CHARS} characters, lines were cut to fit "
                            f"(the sources page carries them): "
                            + ", ".join(f"{v} {TRIM_NAMES[k]}" for k, v in trimmed.items()))
        if unserved:
            problems.append(f"{slug or 'this film'} is not in films.json, so its sources page is not served, yet its "
                            f"description leaves these attributions to that page: "
                            + "; ".join(e["name"] for e in omitted + left))
        return {"text": text, "omitted": omitted, "left": left, "dropped_plain": len(dropped), "trimmed": trimmed,
                "incomplete": st["header"], "listed": listed, "unserved_page": unserved, "slug": slug,
                "sources_page": page, "external_publish_ready": not problems, "problems": problems}

    every = set(range(len(entries)))
    if not entries or len(block(every)) <= MAX_CHARS:
        return report(*fit(every, True))
    keep = set(by["full"])
    if by["full"] and len(block(keep, data_notes=False)) > MAX_CHARS:
        # the pre-4.0 credits alone do not fit: say so at the top, then keep as many of them as fit, whole, in film
        # order (one that does not fit is skipped; a shorter one after it may still fit); the sources-page line stays
        st["header"] = True
        keep = set()
        for i in by["full"]:
            if len(block(keep | {i}, data_notes=False)) <= MAX_CHARS:
                keep.add(i)
    whole = not st["header"]
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
    return report(*fit(keep, notes_on))


def description_text(src: dict, film: dict | None = None, *, site: str = SITE) -> str:
    """The plain-text description block for one film (no markup, never over MAX_CHARS characters).

    The Sources list ends on SOURCES_LINE, the film's sources page, which holds every credit, creator, licence deed
    and data link. Over the cap, entries are kept in this order and printed in film order: every work under a CC
    licence before 4.0, whole (title, author, link, licence and deed URI: those licences ask for the credit itself);
    then works owed attribution only under 4.0, whole, for as many as fit (CC BY 4.0 3(a)(2) lets the sources page
    carry the rest); then plain entries. When the pre-4.0 credits alone do not fit, or the text is over the cap for any
    other reason (a long list of notes, gaps or voices), the block opens with the INCOMPLETE header and is cut to fit
    (TRIM_ORDER); compose reports what was left out. It never raises for length: the description gates no render.
    ``film`` is the film's films.json entry; a film not listed yet takes its slug from sources.json. A map's data
    note is printed only when its own source entry is not."""
    return compose(src, film, site=site)["text"]


def release_problem(src: dict, film: dict | None) -> str | None:
    """Why the description cannot be written with this film's site release, or None: it leaves attributions to a
    sources page the film does not have (``unserved_page``: not in films.json). Its length is never a reason: the
    site's Sources page carries every credit and note."""
    r = compose(src, film)
    if not r["unserved_page"]:
        return None
    return next(p for p in r["problems"] if "not in films.json" in p)


def external_problems(src: dict, film: dict | None) -> list[str]:
    """What this film's description leaves out, for whoever publishes it on an outside platform (by hand: no script
    uploads it), or []: a pre-4.0 credit (those licences ask for the credit wherever the work is published), lines cut
    to fit the cap, or credits left to a sources page not served. Advisory: the INCOMPLETE header in the text itself
    is the guard."""
    return compose(src, film)["problems"]


SIDECAR = "description.attribution.json"


def sidecar_record(r: dict) -> dict:
    """The sidecar beside description.txt: whether it is complete enough for an outside platform, and what it leaves
    out (advisory: the founder uploads by hand, and the INCOMPLETE header in the text is the guard)."""
    def row(e):
        return {"ledger_id": e["ledger_id"], "name": e["name"], "tier": e["tier"], "line": e["line"]}
    return {"external_publish_ready": r["external_publish_ready"], "max_chars": MAX_CHARS, "chars": len(r["text"]),
            "slug": r["slug"], "sources_page": r["sources_page"], "listed": r["listed"],
            "incomplete": r["incomplete"], "unserved_page": r["unserved_page"], "trimmed": r["trimmed"],
            "omitted": [row(e) for e in r["omitted"]], "left_to_sources_page": [row(e) for e in r["left"]],
            "problems": r["problems"]}


def film_entry(films_json: Path | None, slug: str) -> dict | None:
    if not films_json or not films_json.exists():
        return None
    reg = json.loads(films_json.read_text(encoding="utf-8"))
    return next((f for f in reg.get("films", []) if isinstance(f, dict) and f.get("slug") == slug), None)


def sidecar_path(description: Path) -> Path:
    return Path(description).with_name(SIDECAR)


def write_description(sources_path: Path, films_json: Path | None = None, out: Path | None = None) -> Path:
    """Write description.txt and its sidecar (SIDECAR, beside it) from sources.json; returns the description's path.
    Never refuses for length: an overflow is written as the best description that fits, and the sidecar says so."""
    src = json.loads(Path(sources_path).read_text(encoding="utf-8"))
    out = Path(out) if out else Path(sources_path).with_name("description.txt")
    r = compose(src, film_entry(films_json, src.get("slug") or ""))
    out.write_text(r["text"] + "\n", encoding="utf-8")
    sidecar_path(out).write_text(json.dumps(sidecar_record(r), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


REPO_FILMS = Path(__file__).resolve().parents[2] / "films.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write a film's description block from its sources.json (A56).")
    ap.add_argument("sources", type=Path)
    ap.add_argument("--films", type=Path, default=REPO_FILMS, help="the film registry (default: the repo's films.json)")
    ap.add_argument("--out", type=Path, default=None, help="default: description.txt beside sources.json")
    ap.add_argument("--check-external", action="store_true",
                    help="write nothing; advisory: exit 1 and say what is left out unless the description is complete "
                         "enough for an outside platform (every pre-4.0 credit in full, nothing cut to fit)")
    a = ap.parse_args(argv)
    if a.check_external:
        src = json.loads(a.sources.read_text(encoding="utf-8"))
        r = compose(src, film_entry(a.films, src.get("slug") or ""))
        if r["external_publish_ready"]:
            print(f"outside platform: ready ({len(r['text'])} of {MAX_CHARS} characters)")
            return 0
        for p in r["problems"]:
            print(f"outside platform: not ready (advisory, GRAMMAR A56): {p}", file=sys.stderr)
        return 1
    print(write_description(a.sources, a.films, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
