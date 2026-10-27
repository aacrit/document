"""GRAMMAR A56: provenance on screen is the dot only; disclosures live in the sources data.

Pure checks, no I/O. ``meta_text_problems`` reads one on-screen string (a card's
element, a lower third's line, an overlay, a map's text) and names every
versioned pattern it matches: words that narrate a sourcing gap, a descriptor
standing in for a speaker's name, a provenance or source line, a computer-voice
or original-recording note, an explanation of the mark classes, or a shortfall
statement. Each of these is now said in the sources data (sources.json and the
screenplay's ``shortfalls``), which feeds the Sources page, never in the frame.

``lower_third_problems`` is the A56 form of a lower third: NAME plus role (or
place plus date), two lines; a third line is a provenance line and is refused.
"""
from __future__ import annotations

import re

META_TEXT_VERSION = 3           # bump on any pattern change; the fixtures in test_a56_disclosure.py pin each one

_ART = r"(?:an?|the|one|another|some)"
# (name, what it is, the roles it applies to, the pattern). Roles: card, lower_third, overlay, map, subtitle.
_ALL = ("card", "lower_third", "overlay", "map", "subtitle")
_PICTURE_TEXT = ("card", "lower_third", "overlay", "map", "subtitle")
# v2: a person the record names only by a post. A whole line that is an article, up to three words and a role noun,
# and optionally where ("a controller at Boston Center"), is a descriptor, not a name.
_ROLE_NOUNS = (r"(?:pilot|co-?pilot|controller|dispatcher|operator|officer|firefighter|fireman|passenger|"
               r"flight attendant|attendant|caller|witness|reporter|correspondent|soldier|nurse|doctor|technician|"
               r"supervisor|sergeant|trooper|spokesman|spokeswoman|spokesperson|official|survivor|man|woman|"
               r"crew member|staffer|worker|clerk|guard|agent|analyst|commander|specialist|aide|employee|"
               r"resident|bystander|student|teacher|neighbou?r|listener|speaker)s?")
_ROLE_LINE = (rf"^\[?\s*(?:an?|the|one|another)\s+(?:[\w-]+\s+){{0,3}}?{_ROLE_NOUNS}"
              r"(?:\s+(?:at|on|in|from|of|aboard|for|with)\s+[^\].;:!?]{1,60})?\s*\]?$")
# v2: an institution's name is provenance only where it stands as a credit: at the start of a line, or after a
# credit form. Elsewhere (a place drawn on a map, a sentence that names it) it is content.
_INSTITUTIONS = (r"(?:National Archives|Library of Congress|Wikimedia Commons|Natural Earth|GeoNames|Getty Images|"
                 r"Associated Press|British Pathe|Imperial War Museum|Internet Archive)")
META_TEXT = (
    ("source-gap", "narrates a gap in the record (\"no photograph survives\", \"the record keeps no\")", _ALL, re.compile(
        r"\bthe record (?:holds|keeps|has|shows) no\b"
        r"|\bno (?:open[- ]licen[cs]ed? )?(?:known |surviving )?(?:photographs?|films?|footage|recordings?|pictures?|images?|"
        r"record|sound|video|tape)\b[^.;]{0,60}\b(?:survives?|exists?|remains?|was (?:made|kept|found|taken)|is known)\b"
        r"|\b(?:was|were) (?:never|not) (?:filmed|photographed|recorded|kept)\b"
        r"|\bnothing (?:survives|was (?:filmed|kept|recorded))\b"
        r"|\bno open[- ]licen[cs]ed? (?:film|footage|photograph|recording|picture)"
        r"|^searched:", re.I)),
    ("descriptor", "a descriptor stands where a speaker's name goes (\"a woman's voice\")", ("lower_third", "subtitle"),
     re.compile(rf"^\[?\s*{_ART}\s+(?:\w+(?:'s|s')?\s+){{0,3}}voices?\b"
                rf"|^\[?\s*{_ART}\s+(?:unidentified|unnamed|unknown|anonymous)\b"
                r"|^\[?\s*(?:unidentified|unnamed|unknown|anonymous) (?:voice|speaker|man|woman|caller|controller)\b"
                r"|\b(?:man|woman|male|female|girl|boy|child)'s voice\b"
                r"|\bname (?:not given|withheld|unknown|not known)\b"
                rf"|{_ROLE_LINE}", re.I)),
    ("computer-voice", "a computer-voice note (\"read by a computer voice\")", _ALL, re.compile(
        r"\bread by (?:a )?(?:computer|synthetic|synthesi[sz]ed|text[- ]to[- ]speech)\b|\bcomputer[- ]voice\b"
        r"|\btext[- ]to[- ]speech\b|\bno recording of\b[^.]{0,60}\bwas used\b", re.I)),
    ("original-recording", "an original-recording note", _ALL, re.compile(r"\boriginal recording\b", re.I)),
    ("provenance", "a provenance or source line (an archive, a collection, a licence, a data credit)", _PICTURE_TEXT,
     re.compile(r"^\s*(?:data|source|sources|archive|archives|collection|courtesy|credit|photo|photograph|footage)\s*:"
                r"|\bcourtesy of\b|\blicen[cs]ed? under\b|\bCC[ -]BY\b|\bCC0\b|\bpublic domain\b|©"
                rf"|^\s*(?:the\s+)?{_INSTITUTIONS}\b"
                rf"|\b(?:via|collection of|held (?:by|at|in)|by permission of|reproduced from|credit(?:ed)? to)\s+"
                rf"(?:the\s+)?{_INSTITUTIONS}\b", re.I)),
    ("mark-key", "explains the mark classes (the retired mark key)", _ALL, re.compile(
        r"\bwhat the marks mean\b|\bour own titles and cards\b|\bno picture in this film is AI\b"
        r"|\b(?:the )?(?:dot|glyph|ring|square|diamond|mark)s? (?:means?|shows?|stands? for|marks?)\b[^.]{0,40}"
        r"\b(?:archive|reconstructed|drawn|AI)\b", re.I)),
    ("shortfall", "states a shortfall or a share of the film (said in the sources data, A56)", _ALL, re.compile(
        r"\{(?:readings|women|voiceless)_\w+(?::\w+)?\}"
        r"|\bthe grammar asks\b|\brather than invent\b"
        r"|\b(?:women|woman)(?:'s)? (?:voices?|words|share)\b[^.]{0,60}\b(?:percent|share|floor|of the (?:readings|film))\b", re.I)),
)
META_TEXT_NAMES = tuple(n for n, _, _, _ in META_TEXT)
# v2: a map's labels are places. An institution named at the start of a label ("Library of Congress") is a place
# drawn on the map, so on a map only the credit forms refuse ("Data: Natural Earth", "courtesy of", "via GeoNames").
# v3 (brand audit 2026-10-26, H1): an open map dataset's name is never a place, so on a map it is a credit wherever it
# stands ("Natural Earth; GeoNames", without "Data:" or a licence).
_MAP_DATASETS = r"(?:Natural Earth|GeoNames|OpenStreetMap|OSM contributors)"
_BY_ROLE = {("provenance", "map"): re.compile(
    rf"\b{_MAP_DATASETS}\b|"
    r"^\s*(?:data|source|sources|archive|archives|collection|courtesy|credit|photo|photograph|footage)\s*:"
    r"|\bcourtesy of\b|\blicen[cs]ed? under\b|\bCC[ -]BY\b|\bCC0\b|\bpublic domain\b|©"
    rf"|\b(?:via|collection of|held (?:by|at|in)|by permission of|reproduced from|credit(?:ed)? to)\s+"
    rf"(?:the\s+)?{_INSTITUTIONS}\b", re.I)}


def meta_text_problems(text: str, role: str) -> list[dict]:
    """Every A56 pattern ``text`` matches for an on-screen element of ``role``
    (card, lower_third, overlay, map or subtitle): [{pattern, what, match}]."""
    t = " ".join(str(text or "").split())
    out = []
    for name, what, roles, rx in META_TEXT:
        if role not in roles:
            continue
        m = _BY_ROLE.get((name, role), rx).search(t)
        if m:
            out.append({"pattern": name, "what": what, "match": m.group(0)})
    return out


def lower_third_problems(lines) -> list[str]:
    """A56: a lower third is NAME plus role (a speaker), or a place plus its
    date: two non-empty lines. A third line is a provenance line, refused; the
    source lives in the sources data."""
    ln = [str(x) for x in (lines or [])]
    out = []
    if len(ln) > 2:
        out.append(f"line 3 {ln[2]!r} is a provenance line: a lower third is name and role only (A56); the source, "
                   "and whether it is an original recording or read by a computer voice, is stated in the sources data")
    if len(ln) < 2 or not all(x.strip() for x in ln[:2]):
        out.append("a lower third is two non-empty lines: the name, then the role (or the place, then its date)")
    return out


def label_problems(label: str, *, forbidden=()) -> list[str]:
    """A56: the dot's label is the class word plus at most one qualifier,
    at most LABEL_MAX_CHARS characters, and never names a photographer, an
    archive, a licence or a place (``forbidden``: those names, from the item)."""
    t = str(label or "")
    out = []
    if len(t) > LABEL_MAX_CHARS:
        out.append(f"{len(t)} characters; at most {LABEL_MAX_CHARS}")
    if t.count(" · ") > 1:
        out.append("more than one qualifier: the label is the class word and at most one qualifier")
    low = t.lower()
    named = sorted({str(n) for n in forbidden if n and len(str(n)) > 2 and str(n).lower() in low})
    if named:
        out.append(f"names {named}: no photographer, archive, licence or place names in the label")
    return out


LABEL_MAX_CHARS = 32
