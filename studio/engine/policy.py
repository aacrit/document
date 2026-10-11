"""Per-film policy: the imagery rule (GRAMMAR A21, ticket E3), the policy
settings and stated shortfalls (A25, ticket E9). Pure functions, no I/O:
render.py lints with them and publish.py reads the same rule for the poster.

A film states its policy in its screenplay; a screenplay that states none
gets the Partition pilot's, which is exactly what the engine enforced before
these were settings:

- ``imagery_rule``: what the film may show and how a patient is shown. The
  default is GRAMMAR 1.6 and 11.1: no bodies, killing, wounds or corpses, and
  ``shows_bodies: false`` stated on every cited asset.
- ``settings``: ``readings_floor`` (0.20, GRAMMAR 6.1 as amended T1f; never
  under 0.10), ``voiceless_floor`` (0.10, A18; never under 0.10),
  ``women_floor`` (0.30, GRAMMAR 6.5; never under 0.30) and
  ``ai_generated_share_max`` (0.0, the pilots' decision; never over 0.15,
  GRAMMAR 2.6).
- ``shortfalls``: ``[{what, measured, floor, stated_on, stated_as?}]``. A share
  under its floor passes as a journaled review item only when it is declared
  here and the card named by ``stated_on`` states it in words a viewer reads,
  and every share that card prints is one the film measures.
"""

from __future__ import annotations

import math
import re

# --------------------------------------------------------------------------
# The imagery rule (E3, GRAMMAR A21)
# --------------------------------------------------------------------------

PARTITION_STATEMENT = "No footage or photograph of bodies, killing, wounds or corpses."
DEFAULT_IMAGERY_RULE = {
    "show_disease": False,                    # graphic_medical: true is refused
    "show_bodies": False,                     # shows_bodies must be stated false on every cited asset (GRAMMAR 1.6)
    "show_violence": False,                   # shows_violence: true is refused
    "name_only_where_source_names": True,     # a patient is named only where the source's own caption names them
    "min_hold_s": 8.0,                        # a patient still is held at least this long (A10's face hold)
    "no_detail_on_face": True,                # no DETAIL move on a patient's face
    "no_dissolve_into_patient": True,         # a patient shot is never the second half of a dissolve from another subject
    "statement": PARTITION_STATEMENT,
}
RULE_TYPES = {"show_disease": bool, "show_bodies": bool, "show_violence": bool, "name_only_where_source_names": bool,
              "no_detail_on_face": bool, "no_dissolve_into_patient": bool, "min_hold_s": (int, float, type(None)),
              "statement": str}
CONTENT_FIELDS = ("graphic_medical", "shows_bodies", "shows_violence", "named_patient", "minor", "consent_basis", "people")
# flags every cited asset states true or false once the film states a rule or the asset uses the content schema
REQUIRED_FLAGS = ("graphic_medical", "named_patient", "shows_violence")
# words a lower third never uses for an unnamed patient (the founder's imagery rule 4 for Nought): place and date only
PATIENT_WORDS = re.compile(r"\b(victims?|sufferers?|afflicted|stricken)\b", re.I)
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DATE1 = rf"(?:(?:\d{{1,2}} )?{_MONTH} )?\d{{4}}s?"
# line 2 of a place lower third over an unnamed patient: a date as a caption gives it, and nothing else
DATE_LINE = re.compile(rf"^(?:about |c\. ?)?{_DATE1}(?:(?: to |-){_DATE1})?$", re.I)


def statement_key(text) -> str:
    """A statement for comparison: lower case, words and digits only."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def imagery_rule(play: dict) -> tuple[dict, list[str]]:
    """The film's imagery rule with the default filled in, and what is wrong
    with the declared one (unknown keys, wrong types). The printed statement
    is tied to the flags: when no flag differs from the default it is absent
    or the default's own words; when any flag differs it must be the film's
    own words, never the default's (compared with case, spacing and
    punctuation set aside)."""
    declared = play.get("imagery_rule")
    rule = dict(DEFAULT_IMAGERY_RULE)
    problems: list[str] = []
    if declared is None:
        return dict(rule, declared=False), problems
    if not isinstance(declared, dict):
        return dict(rule, declared=True), [f"imagery_rule must be an object, not {type(declared).__name__}"]
    for k, v in declared.items():
        if k not in RULE_TYPES:
            problems.append(f"unknown key {k!r} (known: {', '.join(sorted(RULE_TYPES))})")
            continue
        if RULE_TYPES[k] is bool:
            ok, want = isinstance(v, bool), "true or false"
        elif k == "min_hold_s":
            ok, want = v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)), "a number of seconds or null"
        else:
            ok, want = isinstance(v, str), "a string"
        if not ok:
            problems.append(f"{k} must be {want}, not {v!r}")
            continue
        rule[k] = v
    if rule["min_hold_s"] is not None and (not math.isfinite(float(rule["min_hold_s"])) or float(rule["min_hold_s"]) < 0):
        problems.append(f"min_hold_s must be 0 or more, not {rule['min_hold_s']!r}")
    differs = [k for k in RULE_TYPES if k != "statement" and rule[k] != DEFAULT_IMAGERY_RULE[k]]
    said = statement_key(declared.get("statement"))
    default = statement_key(PARTITION_STATEMENT)
    if differs and (not said or said == default):
        problems.append(f"the rule differs from GRAMMAR 1.6 ({', '.join(differs)}) and needs its own statement, in plain "
                        "words, for the sources page")
    if not differs and said and said != default:
        problems.append("the statement says something the flags do not: no flag differs from GRAMMAR 1.6, so the "
                        "statement is absent or 1.6's own words")
    return dict(rule, declared=True), problems


def is_patient(item: dict | None) -> bool:
    """A frame of a person with the disease: graphic_medical or a named patient."""
    return bool(item) and (item.get("graphic_medical") is True or item.get("named_patient") is True)


def carries_content_fields(item: dict | None) -> bool:
    """The ledger item uses the E3 content schema beyond the legacy shows_bodies."""
    return bool(item) and any(k in item for k in CONTENT_FIELDS if k not in ("shows_bodies", "people"))


def names_of(item: dict | None) -> list[str]:
    people = (item or {}).get("people")
    if not isinstance(people, list):
        return []
    out = []
    for p in people:
        name = p.get("name") if isinstance(p, dict) else p
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def says_name(text: str, name: str) -> bool:
    """The name, as whole words, in the text (case and spacing set aside)."""
    n = _norm(name)
    return bool(n) and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", _norm(text)) is not None


def bodies_value(item: dict):
    """The ledger's shows_bodies, or the older shows_violence_or_bodies."""
    return item.get("shows_bodies", item.get("shows_violence_or_bodies"))


def asset_checks(item: dict, rule: dict) -> list[dict]:
    """Every check the film's imagery rule makes on one cited asset, as
    ``{rule, ok, severity, evidence}``. ``no-bodies`` is always present (the
    Partition lint, unchanged under the default rule); the others appear only
    when the asset uses the content schema or the film states its own rule,
    so a film on the default rule journals exactly what it did before. Then
    graphic_medical, named_patient and shows_violence are stated true or false
    on the asset: a missing or "unknown" flag is refused, never read as false."""
    out = []
    bodies = bodies_value(item)
    if rule["show_bodies"]:
        out.append({"rule": "no-bodies", "ok": bodies in (True, False), "severity": "block",
                    "evidence": {"shows_bodies": bodies, "imagery_rule": "show_bodies: true (the film's rule)",
                                 "why": None if bodies in (True, False) else "shows_bodies must be stated true or false"}})
    else:
        out.append({"rule": "no-bodies", "ok": bodies is False, "severity": "block", "evidence": {"shows_bodies": bodies}})
    if not (rule.get("declared") or carries_content_fields(item)):
        return out
    unstated = {k: item.get(k, "(absent)") for k in REQUIRED_FLAGS if item.get(k) not in (True, False)}
    out.append({"rule": "content-flags", "ok": not unstated, "severity": "block",
                "evidence": {"unstated": unstated, "why": None if not unstated else
                             "stated true or false on every cited asset once checked; missing or unknown is never read as false"}})
    gm = item.get("graphic_medical")
    ev = {"graphic_medical": gm, "show_disease": rule["show_disease"]}
    if gm is True and not rule["show_disease"]:
        out.append({"rule": "imagery-rule", "ok": False, "severity": "block",
                    "evidence": dict(ev, why="the film's imagery rule does not show disease")})
    else:
        out.append({"rule": "imagery-rule", "ok": True, "severity": "block", "evidence": ev})
    if item.get("shows_violence") is True and not rule["show_violence"]:
        out.append({"rule": "imagery-rule", "ok": False, "severity": "block",
                    "evidence": {"shows_violence": True, "why": "the film's imagery rule does not show violence"}})
    if item.get("named_patient") is True and rule["name_only_where_source_names"]:
        names = names_of(item)
        caption = " ".join(str(item.get(k) or "") for k in ("title", "caption"))
        unnamed = [n for n in names if not says_name(caption, n)]
        ok = bool(names) and not unnamed
        out.append({"rule": "patient-named-by-source", "ok": ok, "severity": "block",
                    "evidence": {"people": names, "not_in_caption": unnamed, "caption": item.get("caption") or item.get("title"),
                                 "fix": None if ok else "list the patient in people[] exactly as the source's own caption names them, "
                                                        "or set named_patient: false"}})
    if is_patient(item):
        consent = str(item.get("consent_basis") or "").strip()
        if item.get("named_patient") is True:
            out.append({"rule": "patient-consent", "ok": bool(consent), "severity": "block",
                        "evidence": {"named_patient": True, "consent_basis": consent or None}})
        elif item.get("minor") is not False:
            out.append({"rule": "patient-consent", "ok": bool(consent), "severity": "review",
                        "evidence": {"minor": item.get("minor"), "consent_basis": consent or None,
                                     "check": "a child, or a patient whose age the record does not give: the basis for showing them"}})
    return out


def poster_problem(item: dict, rule: dict) -> str | None:
    """Why a still cannot be the poster under the film's rule, or None. Under
    the default rule this is the Partition poster rule, word for word. A
    patient with no consent_basis is never the poster, whatever its age."""
    for c in asset_checks(item, rule):
        if c["ok"] or c["severity"] != "block":
            continue
        if c["rule"] == "no-bodies" and not rule["show_bodies"]:
            return (f"is not recorded as showing no bodies or violence (shows_bodies: {c['evidence']['shows_bodies']!r}): "
                    "never a poster")
        why = c["evidence"].get("why") or c["evidence"].get("fix") or c["rule"]
        return f"fails the film's imagery rule ({c['rule']}: {why}): never a poster"
    if is_patient(item) and not str(item.get("consent_basis") or "").strip():
        return "shows a patient and states no consent_basis: never a poster"
    return None


def patient_shot_checks(shots: list[dict], assets: dict, rule: dict, lower_thirds: list[dict],
                        cast_names: list[str] | tuple = ()) -> list[dict]:
    """The shot-level half of the rule, for patient shots only: the hold of a
    patient still (shots of one asset joined by a cut or a dissolve are one
    hold), no DETAIL on a patient still unless the shot says ``face: false``,
    no dissolve into a patient shot from another subject. Over a patient the
    source does not name, the only lower third accepted is the two-line place
    form, place then a date, naming nobody: no name from the shot's people[],
    the cast or any ledger item, and no characterising word."""
    out = []
    holds: list[list[dict]] = []
    ledger_names = [n for it in assets.values() for n in names_of(it)]
    prev = None
    for s in shots:
        item = assets.get(s.get("asset")) if s.get("asset") else None
        patient = s.get("kind") in ("archive_still", "archive_video") and is_patient(item)
        tr = (s.get("transition_in") or {}).get("type", "cut")
        if patient and rule["no_dissolve_into_patient"] and tr == "dissolve":
            same = prev is not None and prev.get("asset") == s.get("asset")
            out.append({"rule": "patient-dissolve", "ok": same, "unit": s["id"], "severity": "block",
                        "evidence": {"from": prev.get("id") if prev else None, "from_asset": prev.get("asset") if prev else None,
                                     "to_asset": s.get("asset"), "why": None if same else "a patient is never the second half of a "
                                                                                          "dissolve from another subject"}})
        if patient and s["kind"] == "archive_still":
            if str(s.get("preset") or "").upper() == "DETAIL" and rule["no_detail_on_face"]:
                ok = s.get("face") is False
                out.append({"rule": "patient-detail", "ok": ok, "unit": s["id"], "severity": "block",
                            "evidence": {"preset": "DETAIL", "face": s.get("face"),
                                         "fix": None if ok else "no DETAIL on a patient's face; a DETAIL on something else in "
                                                                "the photograph states face: false"}})
            if holds and prev is not None and prev.get("asset") == s.get("asset") and prev.get("kind") == "archive_still" \
                    and tr in ("cut", "dissolve"):
                holds[-1].append(s)
            else:
                holds.append([s])
        if patient and item.get("named_patient") is not True and rule["name_only_where_source_names"]:
            a, b = float(s["start_s"]), float(s["start_s"]) + float(s["_dur"])
            forbidden = sorted(set(names_of(item) + list(cast_names) + ledger_names))
            for lt in lower_thirds:
                if not (lt["start"] < b and lt["end"] > a):
                    continue
                lines = list(lt["lines"])
                why = []
                if len(lines) != 2 or lt.get("flag"):
                    why.append("only the two-line place form (place, then date) over a patient the source does not name")
                elif not DATE_LINE.match(lines[1].strip()):
                    why.append(f"line 2 is a date as the caption gives it, not {lines[1]!r}")
                named = [n for n in forbidden if any(says_name(ln, n) for ln in lines)]
                if named:
                    why.append(f"names {', '.join(named)}")
                words = sorted({m.group(0).lower() for ln in lines for m in PATIENT_WORDS.finditer(ln)})
                if words:
                    why.append(f"characterises the patient ({', '.join(words)})")
                out.append({"rule": "patient-lower-third", "ok": not why, "unit": lt["id"], "severity": "block",
                            "evidence": {"shot": s["id"], "lines": lines, "problems": why,
                                         "fix": None if not why else "an unnamed patient is given by place and date only"}})
        prev = s
    if rule["min_hold_s"] is not None:
        for h in holds:
            dur = round(sum(float(s["_dur"]) for s in h) - sum(float((s.get("transition_in") or {}).get("s", 0))
                                                                for s in h[1:] if (s.get("transition_in") or {}).get("type") == "dissolve"), 3)
            ok = dur + 0.5 / 24 >= float(rule["min_hold_s"])
            out.append({"rule": "patient-hold", "ok": ok, "unit": h[0]["id"], "severity": "block",
                        "evidence": {"shots": [s["id"] for s in h], "asset": h[0].get("asset"), "hold_s": dur,
                                     "min_hold_s": rule["min_hold_s"]}})
    return out


# --------------------------------------------------------------------------
# Policy settings and stated shortfalls (E9, GRAMMAR A25)
# --------------------------------------------------------------------------

DEFAULT_SETTINGS = {"readings_floor": 0.20, "voiceless_floor": 0.10, "women_floor": 0.30, "ai_generated_share_max": 0.0}
SETTING_BOUNDS = {                        # what GRAMMAR allows a film to set
    "readings_floor": (0.10, 1.0),        # 6.1 as amended (T1f): 20% by default; never under 10%
    "voiceless_floor": (0.10, 1.0),       # A18: the 10% voiceless floor stays
    "women_floor": (0.30, 1.0),           # 6.5: at least 30% (a shortfall is stated, never set lower)
    "ai_generated_share_max": (0.0, 0.15),   # 2.6 and A2: at most 15% of runtime
}
SHORTFALL_WHAT = {"readings": "readings_floor", "voiceless": "voiceless_floor", "women": "women_floor"}
SHORTFALL_TOL = 0.03                      # a printed share within 3 points of the measured one
FLOOR_EXACT = 0.005                       # a printed share that is the floor itself ("under the fifth the grammar asks")
SHORTFALL_WORDS = {
    "readings": ("reading", "recording", "testimony", "first-person", "first person", "own words"),
    "voiceless": ("silence", "silent", "voiceless", "no voice", "without a voice"),
    "women": ("woman", "women"),
}
SHORT_WORDS = ("under", "short", "below", "less than", "fewer", "only")
FRACTIONS = {"half": 1 / 2, "third": 1 / 3, "quarter": 1 / 4, "fifth": 1 / 5, "sixth": 1 / 6, "seventh": 1 / 7,
             "eighth": 1 / 8, "ninth": 1 / 9, "tenth": 1 / 10}


def film_settings(play: dict) -> tuple[dict, dict, list[str]]:
    """The film's policy settings with Partition's values as defaults, which
    of them the screenplay declared, and what is wrong (unknown key, not a
    number, outside GRAMMAR's bounds)."""
    declared = play.get("settings")
    settings = dict(DEFAULT_SETTINGS)
    problems: list[str] = []
    stated: dict = {}
    if declared is None:
        return settings, stated, problems
    if not isinstance(declared, dict):
        return settings, stated, [f"settings must be an object, not {type(declared).__name__}"]
    for k, v in declared.items():
        if k not in SETTING_BOUNDS:
            problems.append(f"unknown setting {k!r} (known: {', '.join(sorted(SETTING_BOUNDS))})")
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            problems.append(f"{k} must be a share from 0 to 1, not {v!r}")
            continue
        lo, hi = SETTING_BOUNDS[k]
        if not lo - 1e-9 <= float(v) <= hi + 1e-9:
            problems.append(f"{k} {v:g} is outside GRAMMAR's bounds ({lo:g} to {hi:g})")
            continue
        settings[k] = float(v)
        stated[k] = float(v)
    return settings, stated, problems


FLOOR_WORDS = ("asks", "floor", "rule", "grammar", "requires", "at least", "the standard")
BEFORE_FLOOR = ("under", "below", "short of", "less than")
CLAUSE = re.compile(r"[^,;:.!?]+")


def printed_share_spans(text: str) -> list[tuple[float, int, int]]:
    """Each share a text prints, with where it stands: '16 percent', '16%',
    '16 per cent', and fractions ('one sixth', 'a fifth'), in text order."""
    t = str(text or "").lower()
    out = [(float(m.group(1)) / 100, m.start(), m.end())
           for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", t)]
    for word, v in FRACTIONS.items():
        out += [(v, m.start(), m.end()) for m in re.finditer(rf"\b{word}s?\b", t)]
    return sorted(out, key=lambda x: x[1])


def printed_shares(text: str) -> list[float]:
    """Shares a text prints (printed_share_spans without positions)."""
    return [v for v, _, _ in printed_share_spans(text)]


def phrased_as_floor(text: str, start: int, end: int) -> bool:
    """A printed share stands as the rule's floor, not as a measured fact,
    only when its clause (between , ; : . ! ?) holds a floor word (asks,
    floor, rule, grammar, requires, at least, the standard) and a shortfall
    word (under, below, short of, less than) comes before it in that clause:
    "under the fifth the grammar asks", "under the 30 percent floor"."""
    t = str(text or "").lower()
    for m in CLAUSE.finditer(t):
        if m.start() <= start and end <= m.end():
            clause, before = m.group(0), t[m.start(): start]
            return (any(re.search(rf"\b{re.escape(w)}\b", clause) for w in FLOOR_WORDS)
                    and any(re.search(rf"\b{re.escape(w)}\b", before) for w in BEFORE_FLOOR))
    return False


def _share(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _states(sf: dict, text: str, siblings: list[dict]) -> tuple[bool, dict]:
    """The word-and-number test on one text: it names what is short, says it
    is short (a share within 3 points of the measured one, or a word of
    shortfall), and every share it prints is within 3 points of a measured
    share stated on this card, or is exactly one of their floors phrased as
    the rule's floor (phrased_as_floor). A floor printed as a fact ("Women
    carry 30 percent of the testimony.") is a false number."""
    t = _norm(text)
    measured = [m for m in (_share(s.get("measured")) for s in siblings) if m is not None]
    floors = [f for f in (_share(s.get("floor")) for s in siblings) if f is not None]
    spans = printed_share_spans(t)
    nums = [n for n, _, _ in spans]
    stray = [n for n, a, b in spans if not any(abs(n - m) <= SHORTFALL_TOL for m in measured)
             and not (any(abs(n - f) <= FLOOR_EXACT for f in floors) and phrased_as_floor(t, a, b))]
    m0 = _share(sf.get("measured"))
    mine = [n for n, a, b in spans if m0 is not None and abs(n - m0) <= SHORTFALL_TOL
            and not (any(abs(n - f) <= FLOOR_EXACT for f in floors) and phrased_as_floor(t, a, b))]
    names = [w for w in SHORTFALL_WORDS.get(sf.get("what"), ()) if w in t]
    short = [w for w in SHORT_WORDS if re.search(rf"\b{w}\b", t)]
    ok = bool(names) and bool(mine or short) and not stray
    return ok, {"names_it": names, "numbers_on_card": [round(n, 4) for n in nums], "numbers_of_it": [round(n, 4) for n in mine],
                "stray_numbers": [round(n, 4) for n in stray], "shortfall_words": short}


def shortfall_stated(sf: dict, card_text: str, siblings: list[dict] | None = None) -> tuple[bool, dict]:
    """Does the card's text state this shortfall truthfully? The card names
    what is short and says it is short, and every share it prints is the
    measured share of a shortfall it states (within 3 points) or that
    shortfall's floor. With ``stated_as``, that phrase is on the card and
    passes the same test on its own. ``how["numbers_of_it"]`` are the card's
    shares for this shortfall, which the mix checks against the film."""
    siblings = siblings or [sf]
    ok, how = _states(sf, card_text, siblings)
    if sf.get("stated_as"):
        phrase = _norm(sf["stated_as"])
        own_ok, own = _states(sf, phrase, siblings)
        on_card = phrase in _norm(card_text)
        how = dict(how, stated_as=sf["stated_as"], stated_as_on_card=on_card, stated_as_test=own)
        ok = ok and on_card and own_ok
    return ok, how


def shortfall_problems(sf: dict, settings: dict) -> list[str]:
    """What is wrong with one declared shortfall, before its card is read."""
    out = []
    if not isinstance(sf, dict):
        return [f"a shortfall must be an object, not {sf!r}"]
    what = sf.get("what")
    if what not in SHORTFALL_WHAT:
        out.append(f"what must be one of {', '.join(sorted(SHORTFALL_WHAT))}, not {what!r}")
        return out
    for k in ("measured", "floor"):
        v = sf.get(k)
        if _share(v) is None or not 0 <= float(v) <= 1:
            out.append(f"{k} must be a share from 0 to 1, not {v!r}")
    floor = settings[SHORTFALL_WHAT[what]]
    if _share(sf.get("floor")) is not None and abs(float(sf["floor"]) - floor) > 1e-6:
        out.append(f"floor {sf['floor']:g} is not the film's {SHORTFALL_WHAT[what]} ({floor:g})")
    if _share(sf.get("measured")) is not None and _share(sf.get("floor")) is not None and sf["measured"] >= sf["floor"]:
        out.append(f"measured {sf['measured']:g} is not under the floor {sf['floor']:g}: nothing is short")
    if not sf.get("stated_on"):
        out.append("stated_on must name the card shot that states it")
    return out
