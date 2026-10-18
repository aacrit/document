"""A45: the rulebook (founder ruling 2), pure.

Measurements in, ledger fields out: ``class``, ``people``, ``roi`` (the
primary region named ``subject``), ``caption_names``, ``whole`` and
``compose``. Nothing here reads a file, calls a model or keeps state, so the
same measurements and the same item always give the same fields. No model
writes framing: the camera (studio/engine/tour.py, A41 and A43) reads these
fields as it reads a person's.

A correction to what the pipeline finds goes here, as a rule or a threshold
with a regression test, never as a hand-drawn box (founder ruling 2). Every
change to what this module returns bumps ``RULEBOOK_VERSION``, which is part
of every cached result's key.

The measurements (``studio.engine.vision``): MediaPipe person boxes with a
score, faces, the pose landmarks that give a person's facing, and a
spectral-residual saliency box with its concentration; and, when cached, the
local VL's normalized place and object regions (``vl_subject``: a region the
ledger's own words or a ``subject_at`` cue name; never a person). A
picture's class reads the ledger's own words (its title, caption and
``seen``) and the people found, deterministically; the VL's class is not
read.
"""

from __future__ import annotations

import re

from studio.engine import motion as M

RULEBOOK_VERSION = "8"     # 2: a bare title is one name; 3: a run is a place by its first or last word only;
                           # 4: a VL place or object region named by a cue or the caption is the subject
                           # 5: people words that are only names count one person per name
                           # 6: a cue and a VL label match through SYNONYMS (plume and smoke, A47)
                           # 7: a still seen from above (AERIAL) is marked ``aerial`` and never sweeps rising;
                           #    a VL region that is the whole picture is never the subject; car, van and
                           #    vehicle are one word (SYNONYMS)
                           # 8: a VL label that names people (vl_person_like, read at use, whatever the cache holds) is
                           #    never a candidate; a VL box of 0.70 of the picture's area or more is never the subject
CLASSES = ("person", "crowd", "place", "document", "map", "painting", "object")
RECORDS = ("document", "map", "painting", "object")       # composed centred: the picture is a record
FLOOR = M.CINE["auto_confidence_floor"]                   # a box under it is not a subject (A43)
PERSON_SUBJECT_H = 0.2       # a figure this share of the picture's height or taller can be what it is about
CROWD_MIN = 4                # this many located people make a crowd
DOMINANT_AREA = 2.0          # one figure this many times the next one's area is the subject alone
DOMINANT_CLASS = 4.0         # ... and this many times makes it a person picture, whoever is behind them
FACING_CAMERA_DX = 0.2       # nose within this share of the shoulder width of their middle: facing the camera
FACING_NOSE_VIS = 0.35       # a nose less visible than this: facing away


# --------------------------------------------------------------------------
# Caption names
# --------------------------------------------------------------------------

# Words that start a sentence or a caption and are not names (a capital there is the sentence's)
FUNCTION = {
    "a", "an", "the", "one", "two", "three", "four", "both", "out", "from", "in", "on", "at", "of", "and", "with",
    "to", "toward", "towards", "over", "under", "by", "this", "that", "these", "those", "its", "his", "her",
    "their", "our", "after", "before", "during", "near", "inside", "outside", "above", "below", "across", "into",
    "smoke", "empty", "onlookers", "men", "women", "children", "people", "view", "photographed", "captured",
    "taken", "depicted", "shown", "seen", "here", "there", "some", "several", "many", "all", "no", "not",
    "january", "february", "march", "september", "october", "november", "december",
}
# A capitalised run that STARTS with one of these is a place, an institution or a thing ("New York", "White House",
# "Air Force One"); one that starts with a given name, a title or an initial stays a name, even when a later word is
# here too ("Frank Church", "General White", "Barbara Hall", "Edward Park", "Sergeant John West")
THING = {
    "street", "st", "avenue", "ave", "road", "square", "park", "school", "elementary", "university", "college",
    "center", "centre", "tower", "towers", "station", "bridge", "river", "harbour", "harbor", "island", "bay",
    "lake", "mount", "city", "county", "state", "states", "united", "village", "hall", "house", "office",
    "building", "church", "temple", "hospital", "airport", "base", "force", "navy", "naval", "army", "corps",
    "guard", "coast", "department", "ministry", "company", "railway", "port", "district", "province", "region",
    "north", "south", "east", "west", "northern", "southern", "eastern", "western", "lower", "upper", "new",
    "york", "jersey", "manhattan", "brooklyn", "hoboken", "pentagon", "sarasota", "anacostia", "facility",
    "support", "statue", "liberty", "hurricane", "boat", "ship", "patrol", "airlines", "airline", "flight",
    "program", "programme", "campaign", "team", "organization", "organisation", "centers", "control",
    "eradication", "bazaar", "market", "valley", "desert", "sea", "ocean", "gulf", "india", "nigeria",
    "bangladesh", "pakistan", "america", "american", "international", "space", "earth", "world", "trade",
    "emergency", "operations", "presidential", "white", "plaza", "fort", "camp", "museum", "library",
    "air", "ground", "greenwich", "union", "doric",
}
# A run that ENDS with one of these is an institution or a place: words that are not surnames
SUFFIX = {
    "school", "elementary", "university", "college", "hospital", "airport", "airlines", "airline", "avenue",
    "facility", "station", "centre", "center", "department", "ministry", "program", "programme", "campaign",
    "organization", "organisation", "district", "province", "plaza", "museum", "library", "bazaar", "office",
    "building", "harbour", "harbor", "island", "village", "city", "county", "states", "railway", "eradication",
}
# Offices and titles: joined to the name they precede ("President Bush"); bare, they are one name themselves
OFFICES = {"president", "pope", "king", "queen", "emperor", "empress", "shah", "kaiser", "viceroy", "tsar", "czar",
           "chancellor", "premier", "governor-general"}
# A title that joins the name it precedes ("President Bush")
TITLES = OFFICES | {"vice", "secretary", "general", "colonel", "major", "captain", "lieutenant", "sergeant",
                    "admiral", "governor", "mayor", "senator", "minister", "prime", "dr", "dr.", "mr", "mr.",
                    "mrs", "mrs.", "ms", "ms.", "sir", "lord", "lady", "prince", "princess", "chief", "director",
                    "commander", "judge", "justice", "reverend", "rev", "father", "sister", "brother"}
CONNECT = {"of", "de", "del", "della", "da", "van", "von", "der", "den", "al", "bin", "ibn", "la", "le", "du"}
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")
_EDGE = "\"'()[]“”‘’,.;:!?"


def _is_cap(tok: str) -> bool:
    """A capitalised word that can be (part of) a name: a capital then lower
    case or an initial ("E."). An acronym (NASA, UTC, NONFICTION) or a word
    with a digit (GOES-8, F-16) is not a name."""
    w = tok.strip(_EDGE)
    if not w or any(c.isdigit() for c in w) or not w[0].isupper():
        return False
    letters = [c for c in w if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return False
    return True


def caption_names(text: str) -> list[str]:
    """The people a caption names, deterministically (A45).

    A name is a run of capitalised words (an initial such as "E." included,
    joined across "of", "de", "van" and the like). A run is dropped when its
    first word starts a place, institution or thing (``THING``: "New York",
    "White House", "Air Force One") or its last word ends one and is no
    surname (``SUFFIX``: "Emma E. Booker Elementary School"). A run that starts
    with a given name, a title or an initial stays a name though a later word
    is a place word ("Frank Church", "General White", "Edward Park"). A leading
    function word ("The", "A") is dropped from a run. A title before a name
    stays with it and resolves to the titled person: "President Bush at the
    school" gives ["President Bush"] (so the narration's "Bush" or "President
    Bush" both match it). A bare title or honorific with no name after it
    ("The President", "the Mayor", "Captain") still counts as one name, the
    title itself (["President"]): it may be someone, so it errs toward a
    binding being checked, never toward a face bound unchecked. Quoted text is
    words in the picture, not the caption naming anyone, and is skipped.

    The direction of error is chosen: a word the lists do not know is taken
    as a name (a place such as "Barksdale" may be listed as one). A name too
    many only stops a binding (A43 binds only when the caption names exactly
    one person), while a name missed could bind the wrong face; so the lists
    hold only words that are not surnames."""
    text = _QUOTED.sub(" , ", str(text or ""))
    toks = text.split()
    runs: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    at = 0
    for i, tok in enumerate(toks):
        w = tok.strip(_EDGE)
        if _is_cap(tok):
            if not cur:
                at = i
            cur.append(w + "." if len(w) == 1 and tok.rstrip(",;:").endswith(".") else w)
        elif w.lower() in CONNECT and cur and i + 1 < len(toks) and _is_cap(toks[i + 1]):
            cur.append(w)
        elif cur:
            runs.append((at, cur))
            cur = []
        if cur and (tok.rstrip("\"'”’)").endswith((",", ";", ":", "!", "?")) or (tok.endswith(".") and len(w) > 1
                                                                                  and w.lower() not in TITLES)):
            runs.append((at, cur))
            cur = []
    if cur:
        runs.append((at, cur))
    # a route ("Sarasota to Barksdale"): what follows "<known place> to" is a place too
    route = {a for a, _ in runs if a >= 2 and toks[a - 1].lower() == "to" and toks[a - 2].strip(_EDGE).lower() in THING}
    runs = [(a, ws) for a, ws in runs if a not in route]
    out: list[str] = []
    for _, words in runs:
        while words and words[0].lower() in FUNCTION:
            words = words[1:]
        while words and words[-1].lower() in CONNECT:
            words = words[:-1]
        if not words or words[0].lower() in THING or words[-1].lower() in SUFFIX:
            continue
        name = " ".join(words)
        if name not in out:
            out.append(name)
    return out


# --------------------------------------------------------------------------
# People: the ledger's own count and the detector's boxes
# --------------------------------------------------------------------------

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1, "the": 1, "single": 1}
COLLECTIVE = {"crowd", "group", "few", "number", "line", "family", "team", "crew", "pair", "couple", "row",
              "column", "procession", "several", "many", "some", "about", "dozens", "hundreds"}
PERSON_NOUNS = {
    "man", "men", "woman", "women", "boy", "boys", "girl", "girls", "child", "children", "baby", "infant",
    "person", "people", "figure", "figures", "crew", "crewman", "crewmen", "firefighter", "firefighters",
    "rescuer", "rescuers", "driver", "drivers", "onlooker", "onlookers", "staff", "president", "official",
    "officials", "medic", "medics", "civilian", "civilians", "pedestrian", "pedestrians", "teacher", "teachers",
    "pupil", "pupils", "crowd", "soldier", "soldiers", "family", "team", "worker", "workers", "officer",
    "officers", "policeman", "policemen", "patient", "patients", "villager", "villagers", "refugee", "refugees",
    "guardsman", "student", "students", "passenger", "passengers", "survivor", "survivors", "volunteer",
    "volunteers", "vaccinator", "vaccinators", "physician", "physicians", "doctor", "doctors", "nurse", "nurses",
}
NOBODY = ("none", "none visible", "none resolvable", "nobody", "no one")


def count_people(people) -> int | None:
    """How many people the ledger's own ``people`` says are in the picture:
    a number, or None when it does not say exactly (a crowd, "crew on deck",
    "the President and staff"). Absent is None; false, [] and "none ..." are 0;
    a list is its length; true is None."""
    if people is None or people is True:
        return None
    if people is False or people == 0 or people == []:
        return 0
    if isinstance(people, list):
        return len(people)
    if not isinstance(people, str):
        return None
    if people.strip().lower().rstrip(".") in NOBODY:
        return 0
    total = 0
    for clause in people.split(";"):
        words = [w.strip(_EDGE).lower() for w in clause.split()]
        words = [w for w in words if w]
        if not words:
            continue
        if words[0] in ("no", "none", "nobody"):
            continue
        # a clause that is only names ("President Bush", "Bush and Card") counts one person per name
        names = caption_names(clause)
        name_words = {w.strip(_EDGE).lower() for n in names for w in n.split()}
        if names and all(w in name_words or w == "and" for w in words):
            total += len(names)
            continue
        has_person = any(w in PERSON_NOUNS for w in words)
        first = words[0]
        if first in NUMBERS or first.isdigit():
            if "and" in words or any(w in COLLECTIVE for w in words[1:2]):
                return None
            n = int(first) if first.isdigit() else NUMBERS[first]
            if n == 1 and first in ("a", "an", "the", "single"):
                plural = {"people", "children", "staff", "crew", "onlookers", "figures", "men", "women",
                          "officials", "medics", "civilians", "pedestrians", "teachers", "pupils"}
                if any(w in plural for w in words) or any(w in COLLECTIVE for w in words):
                    return None
            total += n
        elif has_person:
            return None
    return total


def _area(b: dict) -> float:
    return b["w"] * b["h"]


def _union(bs: list[dict]) -> dict:
    x0, y0 = min(b["x"] for b in bs), min(b["y"] for b in bs)
    x1, y1 = max(b["x"] + b["w"] for b in bs), max(b["y"] + b["h"] for b in bs)
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}


def facing_of(pose: dict | None, face_kp=None) -> str | None:
    """Which way a figure faces, from its pose landmarks (crop fractions):
    the nose against the middle of the shoulders, in shoulder widths. A
    hidden nose is ``away``; a nose near the middle is ``camera``; else the
    side of the picture the nose points to (``left`` or ``right``, as the
    picture is seen). None when the pose is too weak to say."""
    if not pose:
        return None
    nose, ls, rs = pose.get("nose"), pose.get("l_sh"), pose.get("r_sh")
    if not (nose and ls and rs):
        return None
    if min(ls[2], rs[2]) < 0.5:
        return None
    sw = abs(ls[0] - rs[0])
    if nose[2] < FACING_NOSE_VIS:
        return "away"
    if sw < 1e-3:
        return None
    dx = (nose[0] - (ls[0] + rs[0]) / 2.0) / sw
    if abs(dx) <= FACING_CAMERA_DX:
        return "camera"
    return "right" if dx > 0 else "left"


def located(meas: dict, model: str) -> list[dict]:
    """The detector's people at or over the floor, as ledger ``people``
    entries (named person-1, person-2, ... by score, then position)."""
    ps = [p for p in meas.get("people") or [] if p["score"] >= FLOOR]
    ps = sorted(ps, key=lambda p: (-p["score"], p["x"], p["y"]))
    out = []
    for k, p in enumerate(ps, 1):
        e = {"name": f"person-{k}", "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"], "source": "auto",
             "confidence": p["score"], "model": model}
        f = facing_of(p.get("pose"))
        if f:
            e["facing"] = f
        out.append(e)
    return out


def merge_people(human, auto: list[dict]) -> tuple[object, int, str]:
    """The people the camera reads: the detector's boxes, never fewer people
    than the ledger's own words say (a miss stays an unlocated person, so the
    A41 guard shows the whole picture: never cropped out). Returns (value,
    unlocated added, why).

    - The ledger says nobody (false, [], "none visible"): it stands; the
      boxes are set aside (a person's word wins).
    - The ledger locates people itself (a list with boxes): it stands.
    - A list without boxes (named people): kept, and the boxes are added (the
      named entries stay unlocated, so no face is ever bound by guesswork).
    - Words: the boxes, plus one unlocated person for each the words count
      past the boxes, or one when the words give no exact count.
    - Nothing (absent, or true): the boxes plus one unlocated person, since a
      detector that misses an 8 px figure cannot say the picture is empty."""
    n = count_people(human)
    if n == 0:
        return human, 0, "the ledger says nobody is in the picture: its word stands" + (
            f"; {len(auto)} machine box(es) set aside" if auto else "")
    if isinstance(human, list):
        if any(isinstance(p, dict) and all(k in p for k in ("x", "y", "w", "h")) for p in human):
            return human, 0, "the ledger locates its people itself: its boxes stand"
        return list(human) + auto, 0, "the ledger's people are named, not located: they stay unlocated beside the boxes"
    extra = 1 if n is None else max(0, n - len(auto))
    holders = [{"name": f"unlocated-{k}"} for k in range(1, extra + 1)]
    why = ("the ledger does not give an exact count: one unlocated person keeps the whole picture shown"
           if n is None else f"the ledger counts {n}, the detector located {len(auto)}"
           + (f": {extra} unlocated" if extra else ""))
    return auto + holders, extra, why


# --------------------------------------------------------------------------
# Class, subject, composition
# --------------------------------------------------------------------------

CLASS_WORDS = {   # the ledger's own words (title, caption, seen) for a record class, first match in this order
    "map": ("map", "chart", "satellite", "plan of", "atlas"),
    "painting": ("painting", "drawing", "engraving", "lithograph", "woodcut", "watercolour", "watercolor",
                 "etching", "illustration", "cartoon", "print rendering", "japanese print", "poster"),
    "document": ("document", "letter", "telegram", "newspaper", "page", "front page", "handbill", "notice",
                 "manuscript", "typescript", "memo", "certificate"),
    "object": ("door", "effigy", "container", "badge", "object name", "artefact", "artifact"),
}


def _words(item: dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title", "caption", "seen")).lower()


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text) is not None


def text_class(item: dict) -> str | None:
    t = _words(item)
    for cls, words in CLASS_WORDS.items():
        if any(_has(t, w) for w in words):
            return cls
    return None


def picture_class(item: dict, people: list[dict], n_text: int | None) -> tuple[str, str]:
    """(class, why). A record the ledger's words name (a map, a painting, a
    document, an object) is that, whoever is in it; else people make it a
    person or a crowd picture when they are big enough to be its subject;
    else a place."""
    tc = text_class(item)
    if tc in ("map", "painting", "document"):
        return tc, f"the ledger's words name a {tc}"
    big = [p for p in people if p["h"] >= PERSON_SUBJECT_H]
    ranked = sorted(people, key=lambda p: (-_area(p), p["x"], p["y"]))
    if ranked and ranked[0]["h"] >= PERSON_SUBJECT_H and (
            len(ranked) == 1 or _area(ranked[0]) >= DOMINANT_CLASS * _area(ranked[1])):
        return "person", "one figure dominates the picture" if len(ranked) > 1 else "one figure"
    if len(people) >= CROWD_MIN and (big or len(people) >= 2 * CROWD_MIN):
        return "crowd", f"{len(people)} people located"
    if big:
        return "person", f"{len(big)} figure(s) at least {PERSON_SUBJECT_H:g} of the picture's height"
    if tc == "object":
        return "object", "the ledger's words name an object"
    return "place", "no figure is big enough to be the subject" if people else "nobody located"


def fill_box(size, x: float, y: float, aspect: float = 16 / 9) -> dict:
    """The z 1 window (the largest of the frame's aspect inside the picture)
    about (x, y), clamped inside, in picture fractions."""
    iw, ih = float(size[0]), float(size[1])
    if iw / ih >= aspect:
        w, h = (ih * aspect) / iw, 1.0
    else:
        w, h = 1.0, (iw / aspect) / ih
    x0 = min(max(0.0, x - w / 2), 1.0 - w)
    y0 = min(max(0.0, y - h / 2), 1.0 - h)
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(w, 4), "h": round(h, 4)}


def _no_zoom(box: dict, size) -> dict:
    """``no_zoom``: drift only. The subject box grows to the z 1 window about
    its centre, so a stop on it never pushes in."""
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    fb = fill_box(size, cx, cy)
    if box["w"] <= fb["w"] and box["h"] <= fb["h"]:
        return fb
    return box


def subject(cls: str, people: list[dict], meas: dict, unlocated: int) -> tuple[dict | None, str]:
    """The primary region and why, or None (the picture is held whole).

    - person: the one figure, or one that dominates the others (twice the
      area), as ``kind: person``; two or three of a size are a ``group``.
    - crowd: the located people together, a ``group``.
    - place and the records: the saliency box when its concentration reaches
      the floor (``kind: place``, ``text`` for a document or map, ``object``
      for a painting or an object); a picture whose saliency is spread is
      held whole.
    An unlocated person never stops a group or a place subject: the guards
    show the whole picture at some point (A41), so they are never cropped out.
    """
    if cls in ("person", "crowd") and people:
        ranked = sorted(people, key=lambda p: (-_area(p), -p["confidence"], p["x"], p["y"]))
        if cls == "person" and (len(ranked) == 1 or _area(ranked[0]) >= DOMINANT_AREA * _area(ranked[1])):
            p = ranked[0]
            e = {"x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"], "kind": "person",
                 "confidence": p["confidence"]}
            if p.get("facing"):
                e["facing"] = p["facing"]
            return e, "one figure" if len(ranked) == 1 else "one figure dominates"
        g = _union(people)
        return dict(g, kind="group", confidence=round(min(p["confidence"] for p in people), 4)), \
            f"{len(people)} people together"
    sal = meas.get("saliency") or {}
    conc = float(sal.get("concentration") or 0.0)
    if conc < FLOOR:
        return None, f"saliency concentration {conc:.2f} is under the floor {FLOOR:g}: nothing to single out"
    kind = {"document": "text", "map": "text", "painting": "object", "object": "object"}.get(cls, "place")
    return ({"x": sal["x"], "y": sal["y"], "w": sal["w"], "h": sal["h"], "kind": kind, "confidence": round(conc, 4)},
            f"saliency concentration {conc:.2f}")


# --------------------------------------------------------------------------
# VL place and object regions (founder ruling (b), 2026-10-17)
# --------------------------------------------------------------------------

VL_KINDS_USED = ("place", "object", "text")          # the VL never creates or names a person
VL_CONFIDENCE = 0.8          # a VL region the ledger's own words name; above the floor, under a strong detection
VL_MIN_SIDE = 0.01           # a box thinner than this share of the picture is malformed, never a subject
VL_MAX_AREA = 0.70           # a box this share of the picture's area or more is a band or the whole: no subject
# A VL label whose head noun names a person, people or a face (rulebook 8): the rulebook's own people nouns, and more.
# The head is the last word of each part of the label (split at "and", commas and prepositions; "a group of medics"
# reads past the collective), so a thing named with a person word in front of it stays a thing: a police car, a pilot
# boat, a coast guard (the singular "guard" is left out for it), a firefighter's helmet.
VL_PERSON_WORDS = frozenset(PERSON_NOUNS | {
    "persons", "kid", "kids", "adult", "adults", "human", "humans", "face", "faces", "silhouette", "silhouettes",
    "crowds", "audience", "spectator", "spectators", "bystander", "bystanders", "passerby", "passersby",
    "fireman", "firemen", "responder", "responders", "lady", "ladies", "gentleman", "gentlemen", "guy", "guys",
    "victim", "victims", "photographer", "photographers", "reporter", "reporters", "journalist", "journalists",
    "sailor", "sailors", "someone", "somebody", "individual", "individuals", "couple", "group",
    "troops", "marine", "marines", "agent", "agents", "paramedic", "paramedics", "pilot", "pilots", "mourner",
    "mourners", "protester", "protesters", "guards", "worshipper", "worshippers", "nun", "nuns", "priest", "priests",
})
_VL_SPLIT = {"and", "&", "at", "on", "in", "with", "by", "near", "beside", "behind", "under", "over", "inside",
             "outside", "around", "next", "from", "to", "for", "holding", "wearing", "carrying", "standing",
             "sitting", "walking", "running", "in front"}
STOP = {"the", "a", "an", "of", "and", "from", "over", "in", "on", "at", "to", "with", "by", "for", "into", "its",
        "his", "her", "their", "seen", "view", "toward", "towards", "after", "before", "near", "one", "two"}


# A47 (WG-3, Real World C0: the cue "plume", the VL's label "smoke"): words a cue and a VL label share by meaning.
# Each group is one word for matching; short, versioned with the rulebook, never a person's word.
SYNONYMS = (
    ("plume", "smoke"),
    ("tower", "towers", "building", "buildings", "skyscraper", "skyscrapers"),
    ("ship", "ships", "vessel", "vessels", "boat", "boats"),
    ("statue", "monument"),
    # rulebook 7 (Real World 5.7: the title's police car, the VL's "van")
    ("car", "cars", "van", "vans", "vehicle", "vehicles", "automobile", "automobiles"),
)
_SYN = {w: g[0] for g in SYNONYMS for w in g}


def vl_person_like(label: str) -> bool:
    """Rulebook 8: the label names a person, people or a face. Each part of
    the label (split at "and", commas and the words in ``_VL_SPLIT``) is
    read by its head noun, its last word; "X of Y" reads Y when X is a
    collective or a number ("a group of medics", "two of the crew"). A part
    whose head is in ``VL_PERSON_WORDS`` makes the label a person's."""
    t = str(label or "").lower().replace("'s ", " 's ").replace("’s ", " 's ").replace(",", " , ")
    words = [w.strip(_EDGE) for w in t.replace("-", " ").split()]
    parts, cur = [], []
    for w in words:
        if w in _VL_SPLIT or w == ",":
            parts.append(cur)
            cur = []
        elif w == "'s":                       # a possessive: the owner is not the head ("a man's face" is a face)
            cur = []
        else:
            cur.append(w)
    parts.append(cur)
    for part in parts:
        part = [w for w in part if w]
        if "of" in part:
            k = part.index("of")
            if k == 0 or part[k - 1] in COLLECTIVE or part[k - 1] in NUMBERS or part[k - 1] in VL_PERSON_WORDS:
                part = part[k + 1:]
            else:
                part = part[:k]
        if part and part[-1] in VL_PERSON_WORDS:
            return True
    return False


def match_words(text: str) -> set[str]:
    """``content_words`` with each synonym group read as its first word."""
    return {_SYN.get(w, w) for w in content_words(text)}


def content_words(text: str) -> list[str]:
    ws = [w.strip(_EDGE).lower() for w in str(text or "").replace("-", " ").split()]
    return [w for w in ws if len(w) >= 3 and w.isalpha() and w not in STOP]


def vl_subject(cls: str, vl: dict | None, item: dict, cues) -> tuple[dict | None, str]:
    """A VL region as the subject of a place, object, map or document still:
    the first region (cue matches first, then the VL's canonical order) whose
    label shares a content word with a ``subject_at`` cue of a shot showing
    it, else with the item's own caption or title. A person or group region
    is never used (people come from MediaPipe alone), nor a label that
    names people (``vl_person_like``, read here whatever the cache holds, so
    an old sidecar never leaks one), a degenerate box never, and a box of
    ``VL_MAX_AREA`` of the picture or more never: it is a band of sky or the
    whole and singles nothing out. None when nothing matches (the still stays whole)."""
    if not vl or cls in ("person", "crowd"):
        return None, "no VL region for this class" if vl else "no VL measurement"
    cue_w = {w for c in cues or () for w in match_words(c)}
    cap_w = match_words(item.get("caption") or item.get("title") or "")
    best = None
    for k, g in enumerate(vl.get("regions") or []):
        if g.get("kind") not in VL_KINDS_USED or g["w"] < VL_MIN_SIDE or g["h"] < VL_MIN_SIDE or (
                g["w"] * g["h"] >= VL_MAX_AREA - 1e-9) or vl_person_like(g.get("label")):
            continue
        lw = match_words(g.get("label"))
        rank = 0 if lw & cue_w else (1 if lw & cap_w else None)
        if rank is not None and (best is None or (rank, k) < best[0]):
            best = ((rank, k), g, sorted(lw & (cue_w if rank == 0 else cap_w)))
    if best is None:
        return None, "no VL region's label is named by a cue or the caption"
    (rank, _), g, words = best
    return ({"x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"], "kind": g["kind"], "confidence": VL_CONFIDENCE,
             "label": g["label"]},
            f"VL region {g['label']!r} named by the {'subject_at cue' if rank == 0 else 'caption'} ({', '.join(words)})")


# --------------------------------------------------------------------------
# Seen from above (rulebook 7, A47 amendment; WG-3, Real World C0)
# --------------------------------------------------------------------------

# A still whose own words say it was made from above (an orbit, a satellite, an aircraft) has no sky at its top:
# up in the picture is not up in the world, so its whole sweep never rises (tour.whole_sweep). Versioned with
# RULEBOOK_VERSION. Phrases match whole words, any case; the acronyms only in capitals ("GOES" is not "goes").
# "aerial" and "overhead" also describe things on the ground ("an aerial ladder", "pipes overhead": Real World's PEOC
# door), so "aerial" counts unless a ladder, platform or truck follows it, and "overhead" only as the point of view.
AERIAL_WORDS = ("orbit", "orbital", "international space station", "satellite", "from the air", "from overhead",
                "overhead view", "overhead photograph", "overhead shot")
AERIAL_PATTERNS = (re.compile(r"(?<![\w-])aerial(?![\w-])(?!\s+(?:ladder|ladders|platform|platforms|truck|trucks)\b)"),)
AERIAL_ACRONYMS = (re.compile(r"\bISS(?=\d|\b)"), re.compile(r"\bGOES\b"))


def seen_from_above(item: dict) -> str | None:
    """The word in the item's own title, caption or ``seen`` that marks it as
    seen from above (``AERIAL_WORDS``, ``AERIAL_PATTERNS``,
    ``AERIAL_ACRONYMS``), or None."""
    raw = " ".join(str(item.get(k) or "") for k in ("title", "caption", "seen"))
    low = raw.lower()
    for w in AERIAL_WORDS:
        if _has(low, w):
            return w
    for rx in AERIAL_PATTERNS:
        m = rx.search(low)
        if m:
            return m.group(0)
    for rx in AERIAL_ACRONYMS:
        m = rx.search(raw)
        if m:
            return m.group(0)
    return None


def fields(item: dict, meas: dict | None, model: str, vl: dict | None = None, cues=(), vl_model: str = "") -> dict:
    """The rulebook: one ledger item and its measurement to the auto fields
    and the reasons ({fields, why}). ``meas`` None (nothing measured: the
    detector is missing here) gives no fields at all, so the still is planned
    exactly as without the pipeline (the A41 default and guards). ``vl`` is
    the cached, normalized VL answer when there is one, and ``cues`` the
    ``subject_at`` cues of the shots that show the item."""
    why: dict = {}
    out: dict = {}
    if meas is None:
        why["measure"] = "not measured here: no fields; the A41 default and guards apply"
        return {"fields": {}, "why": why}
    out["caption_names"] = caption_names(item.get("caption") or item.get("title") or "")
    above = seen_from_above(item)
    if above is not None:
        out["aerial"] = True
        why["aerial"] = f"the ledger's own words say it was seen from above ({above!r}): its whole sweep never rises"
    auto = located(meas, model)
    faces = meas.get("faces") or []
    for e in auto:                       # a face inside the figure gives the facing the pose could not
        if "facing" not in e:
            f = next((f for f in faces if _face_in(f, [e])), None)
            fc = face_facing(f) if f else None
            if fc:
                e["facing"] = fc
    why["faces"] = (f"{sum(1 for f in faces if _face_in(f, auto))} face(s) inside located figures; "
                    f"{sum(1 for f in faces if not _face_in(f, auto))} outside any figure set aside")
    people, unloc, why["people"] = merge_people(item.get("people"), auto)
    framed = auto if people is not item.get("people") else []
    cls, why["class"] = picture_class(item, framed, count_people(item.get("people")))
    out["class"] = cls
    if people is not item.get("people"):
        out["people"] = people
    sub, why["subject"] = subject(cls, framed, meas, unloc)
    sub_model = model
    if sub is None and vl is not None:
        vsub, why["vl"] = vl_subject(cls, vl, item, cues)
        if vsub is not None:
            sub, why["subject"], sub_model = vsub, why["vl"], vl_model or model
    if sub is not None and item.get("no_zoom") is True:
        sub = dict(sub, **_no_zoom(sub, meas["size"]))
        why["no_zoom"] = "no_zoom: the subject is the z 1 window about it (drift only)"
    if sub is None:
        out["whole"] = True
    else:
        e = {"name": "subject", **{k: sub[k] for k in ("x", "y", "w", "h")}, "kind": sub["kind"],
             "source": "auto", "confidence": sub["confidence"], "model": sub_model}
        if sub.get("facing"):
            e["facing"] = sub["facing"]
        out["roi"] = [e]
    out["compose"] = "golden" if cls in ("person", "crowd", "place") else f"centred:{cls}"
    return {"fields": out, "why": why}


def face_facing(face: dict) -> str | None:
    """Facing from a face's keypoints (picture fractions: right eye, left
    eye, nose tip, mouth, right ear, left ear): the nose against the middle
    of the eyes, in eye distances."""
    kp = face.get("kp") or []
    if len(kp) < 3:
        return None
    (rx, _), (lx, _), (nx, _) = kp[0], kp[1], kp[2]
    d = abs(lx - rx)
    if d < 1e-4:
        return None
    dx = (nx - (lx + rx) / 2.0) / d
    if abs(dx) <= FACING_CAMERA_DX:
        return "camera"
    return "right" if dx > 0 else "left"


def _face_in(face: dict, people: list[dict]) -> bool:
    """A face counts only inside a located figure (the short-range face
    model misfires on towers and seals when nobody is there)."""
    cx, cy = face["x"] + face["w"] / 2, face["y"] + face["h"] / 2
    return any(p["x"] <= cx <= p["x"] + p["w"] and p["y"] <= cy <= p["y"] + p["h"] and face["w"] <= p["w"]
               for p in people)


def overlay(item: dict, auto: dict) -> tuple[dict, list[str]]:
    """The item as the planner reads it: the human ledger's fields win, the
    rulebook's fill what the human left out. ``roi``: the human regions,
    then the rulebook's under names the human did not use. A human ``whole:
    true`` or ``roi`` keeps the rulebook's subject out. Returns (merged item,
    the fields the rulebook supplied)."""
    out = dict(item)
    used = []
    for k in ("class", "compose", "caption_names", "people", "aerial"):
        if k in auto and k not in item:
            out[k] = auto[k]
            used.append(k)
    if "people" in auto and "people" in item and auto["people"] is not item["people"]:
        out["people"] = auto["people"]           # merge_people already kept the human's word and count
        used.append("people")
    human_roi = [r for r in item.get("roi") or [] if isinstance(r, dict)] if isinstance(item.get("roi"), list) else None
    if item.get("whole") is True or human_roi:
        if human_roi is not None:
            names = {r.get("name") for r in human_roi}
            extra = [r for r in auto.get("roi") or [] if r["name"] not in names and r["name"] != "subject"]
            if extra:
                out["roi"] = human_roi + extra
                used.append("roi")
        return out, used
    if auto.get("roi"):
        out["roi"] = list(auto["roi"])
        used.append("roi")
    elif auto.get("whole") and "whole" not in item:
        out["whole"] = True
        used.append("whole")
    return out, used
