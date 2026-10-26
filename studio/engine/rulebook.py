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

RULEBOOK_VERSION = "11"    # 2: a bare title is one name; 3: a run is a place by its first or last word only;
                           # 4: a VL place or object region named by a cue or the caption is the subject
                           # 5: people words that are only names count one person per name
                           # 6: a cue and a VL label match through SYNONYMS (plume and smoke, A47)
                           # 7: a still seen from above (AERIAL) is marked ``aerial`` and never sweeps rising;
                           #    a VL region that is the whole picture is never the subject; car, van and
                           #    vehicle are one word (SYNONYMS)
                           # 8: a VL label that names people (vl_person_like, read at use, whatever the cache holds) is
                           #    never a candidate; a VL box of 0.70 of the picture's area or more is never the subject
                           # 9: a located figure carries the face MediaPipe found inside it (``face``, A51: faces are
                           #    steered clear of live text)
                           # 10 (A52): text the item's own words quote is a must_show region (``quoted_must_show``); a
                           #    caption naming two things prefers the event after "and the"/"with the" (smoke, a
                           #    plume, fire); a monument the caption places the photographer at is the vantage,
                           #    never the subject
                           # 11 (A53): every emitted box (a located person, its face, and each ``roi`` entry) is
                           #    clamped to the picture [0, 1] before it reaches the sidecar, so a measurement or a
                           #    union of boxes landing a hair past the edge never fails the cine-schema check
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


# --------------------------------------------------------------------------
# Rulebook 10 (A52): quoted text, two things named, a monument as vantage
# --------------------------------------------------------------------------

# Quoted words in the item's own title, caption or ``why``: double quotes, curly quotes, or single quotes that are
# not an apostrophe (no letter on the outside of either mark)
QUOTES = re.compile(r"\"([^\"]+)\"|“([^”]+)”|‘([^’]+)’|(?<![\w])'([^']+)'(?![\w])")
QUOTE_MATCH = 0.6            # a text region whose label holds this share of the quote's content words is the quote
# A VL text label that says only "this is writing", not what it says: the quote falls back on where it is
GENERIC_TEXT = frozenset({"text", "texts", "sign", "signs", "signage", "lettering", "letters", "letter", "word",
                          "words", "writing", "inscription", "caption", "label", "labels", "banner", "motto",
                          "slogan", "logo", "print", "printing", "script", "plate", "placard", "notice"})
TEXT_PAD = 0.2               # a quoted text region grows by this share of its own size on each side: the VL boxes
                             # the ink on a 0.005 grid, and the words are whole only with their first and last letter
INSIDE_SHARE = 0.8           # a text region this share inside a region is on it ("on the police car")
# The event a caption's second clause names ("X and the smoke over Y", "X with Y behind"): the picture is about it
# (never a crowd: people are MediaPipe's alone, and a VL label naming them is never a candidate, rulebook 8)
EVENT_WORDS = frozenset({"smoke", "plume", "fire", "fires", "flame", "flames", "debris", "dust"})
_TWO_THINGS = (re.compile(r"^(?P<x>.+?)\s+(?:and|with)\s+the\s+(?P<y>[^,;:()]+)", re.I),
               re.compile(r"^(?P<x>.+?)\s+with\s+(?P<y>[^,;:()]+?)\s+behind\b", re.I))
# A monument the photographer stood at or beside is where the picture was made from, not what it shows
MONUMENT_WORDS = frozenset({"statue", "monument", "memorial", "landmark", "obelisk", "pedestal", "column", "arch"})
_VANTAGE = re.compile(r"(?<![\w-])(?:(?:seen|viewed|photographed|taken|shot) from|from|beside|next to|"
                      r"at the foot of|at the base of|at)\s+(?:the\s+)?(?P<p>[^,;:()]+)", re.I)
_VANTAGE_END = {"and", "with", "over", "toward", "towards", "as", "while", "after", "before", "in", "on", "into",
                "across", "to", "under", "behind", "during"}
BOXK = ("x", "y", "w", "h")


def clamp_box(b: dict) -> dict:
    """A {x, y, w, h} box (picture fractions) pulled back onto the picture:
    x and y land in [0, 1], then w and h are capped so x + w and y + h never
    pass 1. A box already inside the picture comes back unchanged (``b``
    itself), so this never perturbs an in-range box; one a measurement
    pushed a hair past the edge (A52/A53) is clamped, deterministically."""
    x, y = max(0.0, min(1.0, b["x"])), max(0.0, min(1.0, b["y"]))
    w, h = max(0.0, min(b["w"], 1.0 - x)), max(0.0, min(b["h"], 1.0 - y))
    if x == b["x"] and y == b["y"] and w == b["w"] and h == b["h"]:
        return b
    return {**b, "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def _clamp_boxes(entries) -> None:
    """Clamp every box on a rulebook-emitted list in place: each entry's own
    {x, y, w, h} and, on a person, the {x, y, w, h} face found inside it."""
    for e in entries:
        if not isinstance(e, dict):
            continue
        if all(k in e for k in BOXK):
            cb = clamp_box(e)
            if cb is not e:
                e["x"], e["y"], e["w"], e["h"] = cb["x"], cb["y"], cb["w"], cb["h"]
        face = e.get("face")
        if isinstance(face, dict) and all(k in face for k in BOXK):
            cb = clamp_box(face)
            if cb is not face:
                e["face"] = cb


# A quote is VISIBLE LETTERING (review, 2026-10-18) only when the item's own words say so: one of these right before it
# ("a sign reading", "the words"), "on the <thing>" right after it, or the item's ``seen`` (what the editor saw in the
# picture) naming lettering. Quoted speech is never written in the picture (A0): a speech word round the quote
# forbids every fallback, so only a VL label that holds the words themselves can bind it.
LETTERING_BEFORE = frozenset({"reading", "reads", "read", "lettered", "inscribed", "painted", "sign", "banner",
                              "headline", "placard", "lettering", "inscription", "motto", "slogan", "poster",
                              "plaque", "stencilled", "stenciled", "printed", "marked"})
LETTERING_SEEN = re.compile(r"(?<![\w-])(?:lettered|lettering|inscribed|inscription|painted|reading|reads|sign|"
                            r"signs|banner|headline|placard|motto|slogan|plaque|stencil(?:l)?ed|the words)(?![\w-])")
_ON_THING = re.compile(r"^[\s,.;:]*on\s+(?:the|a|an|its|his|her|their)\s+\w+", re.I)
SPEECH = frozenset({"said", "says", "say", "saying", "shouts", "shouted", "shout", "shouting", "told", "tells",
                    "tell", "called", "calls", "call", "calling", "asked", "asks", "ask", "declared", "declares",
                    "announced", "announces", "cried", "cries", "yelled", "yells", "replied", "replies", "spoke",
                    "speaks", "speech", "remarks", "promised", "vowed", "warned", "added", "words",
                    # naming is not lettering either ("named it", "knew it as", "dubbed")
                    "named", "names", "naming", "dubbed", "nicknamed", "christened", "knew", "know", "known",
                    "termed"})
SPEECH_WINDOW = (4, 3)       # words before and after a quote searched for a speech word


def quoted(item: dict) -> list[str]:
    """The quoted passages in the item's own ``title``, ``caption`` and
    ``why`` (each once, in that order)."""
    out: list[str] = []
    for k in ("title", "caption", "why"):
        v = item.get(k)
        for text in (v if isinstance(v, list) else [v]):
            for m in QUOTES.finditer(str(text or "")):
                q = next(g for g in m.groups() if g is not None).strip()
                if q and q not in out:
                    out.append(q)
    return out


def quote_marks(item: dict) -> list[tuple[str, str]]:
    """Each quote (``quoted``'s order) with how the item's own words mark it:
    ``"speech"`` (a ``SPEECH`` word within ``SPEECH_WINDOW`` of it; "the
    words" alone is lettering, "the Mayor's words" speech), ``"lettering"``
    (a ``LETTERING_BEFORE`` word right before it, or "on the <thing>" right
    after it), or ``"unmarked"``. A quote marked twice keeps the stronger
    mark: speech over lettering over unmarked."""
    rank = {"unmarked": 0, "lettering": 1, "speech": 2}
    marks: dict[str, str] = {}
    for k in ("title", "caption", "why"):
        v = item.get(k)
        for text in (v if isinstance(v, list) else [v]):
            text = str(text or "")
            for m in QUOTES.finditer(text):
                q = next(g for g in m.groups() if g is not None).strip()
                if not q:
                    continue
                before = [w.strip(_EDGE).lower() for w in text[:m.start()].split()]
                after = [w.strip(_EDGE).lower() for w in text[m.end():].split()]
                before = [w for w in before if w]
                near = before[-SPEECH_WINDOW[0]:] + [w for w in after if w][:SPEECH_WINDOW[1]]
                the_words = len(before) >= 2 and before[-1] == "words" and before[-2] == "the"
                # a marker in the clause right before a colon counts too ("The headline the next day: ...")
                head = text[:m.start()].rstrip()
                clause = []
                if head.endswith(":"):
                    clause = [w.strip(_EDGE).lower() for w in re.split(r"[,;:.!?]", head[:-1])[-1].split()]
                if any(w in SPEECH for w in near + clause) and not (the_words and not any(
                        w in SPEECH - {"words"} for w in near)):
                    mark = "speech"
                elif (before and before[-1] in LETTERING_BEFORE) or the_words or _ON_THING.match(text[m.end():]) or (
                        any(w in LETTERING_BEFORE for w in clause)):
                    mark = "lettering"
                else:
                    mark = "unmarked"
                if q not in marks or rank[mark] > rank[marks[q]]:
                    marks[q] = mark
    return [(q, marks[q]) for q in quoted(item) if q in marks]


def quote_visible(item: dict, q: str, mark: str) -> str | None:
    """Which fallbacks a quote may take (re-review, 2026-10-18): ``None``
    for speech or naming, or with no evidence it is lettering; ``"all"``
    (the lone generic text region, or the one on a named thing) when the
    item's words mark it as lettering beside it, or its ``seen`` holds the
    quote's own words (``QUOTE_MATCH`` of them); ``"bearer"`` (only the
    text region lying on a thing the caption or ``seen`` names, as 5.7's
    motto lies on the car) when the only evidence is ``seen`` naming
    lettering somewhere in the picture."""
    if mark == "speech":
        return None
    if mark == "lettering":
        return "all"
    seen = str(item.get("seen") or "")
    qw = set(content_words(q))
    if qw and len(qw & set(content_words(seen))) / len(qw) >= QUOTE_MATCH - 1e-9:
        return "all"
    return "bearer" if LETTERING_SEEN.search(seen.lower()) is not None else None


def _generic_text(label) -> bool:
    ws = content_words(label)
    return not ws or all(w in GENERIC_TEXT for w in ws)


def _inside(a: dict, b: dict) -> float:
    """The share of box ``a`` that lies inside box ``b``."""
    ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return ix * iy / _area(a) if _area(a) > 0 else 0.0


def iou(a: dict, b: dict) -> float:
    """Intersection over union of two {x, y, w, h} boxes."""
    ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    u = _area(a) + _area(b) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def _pad(g: dict, share: float) -> dict:
    x0, y0 = max(0.0, g["x"] - share * g["w"]), max(0.0, g["y"] - share * g["h"])
    x1, y1 = min(1.0, g["x"] + g["w"] * (1 + share)), min(1.0, g["y"] + g["h"] * (1 + share))
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}


def _usable(g: dict) -> bool:
    """A VL box that can be a region: neither a sliver nor a band or the whole."""
    return g["w"] >= VL_MIN_SIDE and g["h"] >= VL_MIN_SIDE and g["w"] * g["h"] < VL_MAX_AREA - 1e-9


def quoted_must_show(vl: dict | None, item: dict) -> tuple[list[dict], str]:
    """Rulebook 10 (A52): text the item's own words quote is in the picture
    and must be read, so the VL ``text`` region that holds it becomes a
    ``must_show`` region. For each quote (``quote_marks``): the text region
    whose label holds at least ``QUOTE_MATCH`` of the quote's content words
    (the most, then the VL's order) binds outright. The fallbacks apply only
    to a quote the item's words mark as visible lettering (``quote_visible``;
    never quoted speech): when the VL labels its text
    regions only as writing ("text", "sign", "lettering"), the one such
    region in the picture; else, of several, the one lying on the thing the
    caption names (``INSIDE_SHARE`` of it inside a VL region whose label the
    caption or title names: "a police car" and the lettering on its door).
    None of these, or two that tie, and the quote finds no region (said in
    the why; the A41 guards stand). Each region found grows by ``TEXT_PAD``
    on each side, so its words are whole. Returns (regions as {x, y, w, h,
    label}, why)."""
    qs = quote_marks(item)
    if not qs:
        return [], "nothing quoted"
    if not vl:
        return [], f"{len(qs)} quote(s), no VL measurement"
    regs = [g for g in vl.get("regions") or [] if _usable(g) and not vl_person_like(g.get("label"))]
    texts = [g for g in regs if g.get("kind") == "text"]
    generic = [g for g in texts if _generic_text(g.get("label"))]
    cap_w = match_words(item.get("caption") or item.get("title") or "") | match_words(item.get("seen") or "")
    bearers = [g for g in regs if g.get("kind") != "text" and match_words(g.get("label")) & cap_w]
    out: list[dict] = []
    whys: list[str] = []
    for q, mark in qs:
        qw = set(content_words(q))
        if not qw:
            continue
        best = None
        for k, g in enumerate(texts):
            share = len(qw & set(content_words(g.get("label")))) / len(qw)
            if share >= QUOTE_MATCH - 1e-9 and (best is None or (-share, k) < best[0]):
                best = ((-share, k), g)
        pick, how = (best[1], f"its label holds {-best[0][0]:.0%} of the quote's words") if best else (None, "")
        visible = quote_visible(item, q, mark)
        if pick is None and not visible:
            whys.append(f"{q!r}: no text label holds its words, and the item's words do not mark it as lettering"
                        + (" (quoted speech)" if mark == "speech" else ""))
            continue
        if pick is None and visible == "all" and len(generic) == 1:
            pick, how = generic[0], "the one text region, labelled only as writing"
        if pick is None and (len(generic) > 1 or visible == "bearer"):
            on = [g for g in generic if any(_inside(g, b) >= INSIDE_SHARE - 1e-9 for b in bearers)]
            if len(on) == 1:
                b = next(b for b in bearers if _inside(on[0], b) >= INSIDE_SHARE - 1e-9)
                pick, how = on[0], f"the one text region on the {b['label']!r} the item's words name"
        if pick is None:
            whys.append(f"{q!r}: no text region holds it")
            continue
        box = _pad(pick, TEXT_PAD)
        if not any(all(abs(box[k] - o[k]) < 1e-9 for k in BOXK) for o in out):
            out.append(dict(box, label=pick.get("label")))
        whys.append(f"{q!r}: VL text region {pick.get('label')!r}, {how}")
    return out, "; ".join(whys)


def event_clause(item: dict) -> set[str]:
    """Rulebook 10 (A52): when the caption (else the title) names two things,
    "X and the Y" or "X with (the) Y behind", and the second clause names
    an event (``EVENT_WORDS``: smoke, a plume, fire, debris, a crowd), the
    event's match words; else empty."""
    text = str(item.get("caption") or item.get("title") or "")
    ev = {_SYN.get(w, w) for w in EVENT_WORDS}
    for rx in _TWO_THINGS:
        m = rx.search(text)
        if m:
            got = match_words(m.group("y")) & ev
            if got:
                return got
    return set()


def vantage_words(item: dict) -> set[str]:
    """Rulebook 10 (A52): the match words of a monument the caption (or the
    title) places the photographer at or beside ("from the Statue of
    Liberty", "seen from", "beside", "at the foot of"): the phrase after one
    of those words, up to a comma or a joining word, when it holds a
    ``MONUMENT_WORDS`` word. A region it names is the vantage, never the
    subject."""
    out: set[str] = set()
    for k in ("caption", "title"):
        for m in _VANTAGE.finditer(str(item.get(k) or "")):
            ws = []
            for w in m.group("p").split():
                if w.strip(_EDGE).lower() in _VANTAGE_END:
                    break
                ws.append(w)
            if any(w.strip(_EDGE).lower() in MONUMENT_WORDS for w in ws):
                out |= match_words(" ".join(ws))
    return out


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
    # rulebook 10 (A52): two things named, the second an event: only the event's region is the caption's subject
    ev_w = event_clause(item)
    if ev_w:
        cap_w = ev_w
    van_w = vantage_words(item)
    best, vantage = None, []
    for k, g in enumerate(vl.get("regions") or []):
        if g.get("kind") not in VL_KINDS_USED or g["w"] < VL_MIN_SIDE or g["h"] < VL_MIN_SIDE or (
                g["w"] * g["h"] >= VL_MAX_AREA - 1e-9) or vl_person_like(g.get("label")):
            continue
        lw = match_words(g.get("label"))
        if lw & van_w:                       # rulebook 10: the monument the photographer stood at is the vantage
            vantage.append(g["label"])
            continue
        rank = 0 if lw & cue_w else (1 if lw & cap_w else None)
        if rank is not None and (best is None or (rank, k) < best[0]):
            best = ((rank, k), g, sorted(lw & (cue_w if rank == 0 else cap_w)))
    if best is None:
        return None, ("no VL region's label is named by a cue or the caption"
                      + (f" (the event: {', '.join(sorted(ev_w))})" if ev_w else "")
                      + (f"; the vantage set aside: {', '.join(vantage)}" if vantage else ""))
    (rank, _), g, words = best
    named = "subject_at cue" if rank == 0 else ("caption's second clause, the event" if ev_w else "caption")
    return ({"x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"], "kind": g["kind"], "confidence": VL_CONFIDENCE,
             "label": g["label"]},
            f"VL region {g['label']!r} named by the {named} ({', '.join(words)})"
            + (f"; the vantage set aside: {', '.join(vantage)}" if vantage else ""))


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
        f = next((f for f in faces if _face_in(f, [e])), None)
        if f is not None:                # A51: and where the face is, so the camera keeps it clear of live text
            e["face"] = {k: f[k] for k in ("x", "y", "w", "h")}
        if "facing" not in e:
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
    # rulebook 10 (A52): text the item's own words quote is must_show, whatever the subject
    quotes, qwhy = quoted_must_show(vl, item) if vl is not None else ([], "")
    if qwhy and qwhy != "nothing quoted":
        why["quoted"] = qwhy
    for k, q in enumerate(quotes, 1):
        out.setdefault("roi", []).append({"name": f"text-{k}", **{b: q[b] for b in BOXK}, "kind": "text",
                                          "source": "auto", "confidence": VL_CONFIDENCE,
                                          "model": vl_model or model, "must_show": True})
    out["compose"] = "golden" if cls in ("person", "crowd", "place") else f"centred:{cls}"
    # A53: clamp every emitted box to the picture before it ever reaches the sidecar or the cine-schema check
    # (a measurer, or a union of its boxes, can land a hair past the edge; never a hand-drawn box, founder ruling 2)
    _clamp_boxes(out.get("people") or [])
    _clamp_boxes(out.get("roi") or [])
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
            # rulebook 10: a region a human drew over the same place wins (one must_show, never two)
            extra = [r for r in auto.get("roi") or [] if r["name"] not in names and r["name"] != "subject"
                     and not _human_covers(r, human_roi)]
            if extra:
                out["roi"] = human_roi + extra
                used.append("roi")
        return out, used
    if auto.get("roi"):
        out["roi"] = list(auto["roi"])
        used.append("roi")
    if auto.get("whole") and "whole" not in item:
        out["whole"] = True
        used.append("whole")
    return out, used


def _human_covers(r: dict, human_roi: list[dict]) -> bool:
    """Rulebook 10: a human region over the same place as a rulebook region
    (``iou`` at least a half, or the rulebook's box ``INSIDE_SHARE`` inside
    it)."""
    if not all(isinstance(r.get(k), (int, float)) for k in BOXK):
        return False
    for h in human_roi:
        if all(isinstance(h.get(k), (int, float)) for k in BOXK) and (
                iou(r, h) >= 0.5 or _inside(r, h) >= INSIDE_SHARE - 1e-9):
            return True
    return False
