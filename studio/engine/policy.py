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
  here and the card named by ``stated_on`` states it in words a viewer reads.
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
    "name_only_where_source_names": True,     # a named patient is named only as the source's own caption names them
    "min_hold_s": 8.0,                        # a patient still is held at least this long (A10's face hold)
    "no_detail_on_face": True,                # no DETAIL move on a patient's face
    "no_dissolve_into_patient": True,         # a patient shot is never the second half of a dissolve from another subject
    "statement": PARTITION_STATEMENT,
}
RULE_TYPES = {"show_disease": bool, "show_bodies": bool, "show_violence": bool, "name_only_where_source_names": bool,
              "no_detail_on_face": bool, "no_dissolve_into_patient": bool, "min_hold_s": (int, float, type(None)),
              "statement": str}
CONTENT_FIELDS = ("graphic_medical", "shows_bodies", "shows_violence", "named_patient", "minor", "consent_basis", "people")
# words a lower third never uses for an unnamed patient (the founder's imagery rule 4 for Nought): place and date only
PATIENT_WORDS = re.compile(r"\b(victims?|sufferers?|afflicted|stricken)\b", re.I)


def imagery_rule(play: dict) -> tuple[dict, list[str]]:
    """The film's imagery rule with the default filled in, and what is wrong
    with the declared one (unknown keys, wrong types, a declared rule that
    differs from the default without a statement for the sources page)."""
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
    differs = any(rule[k] != DEFAULT_IMAGERY_RULE[k] for k in RULE_TYPES if k != "statement")
    if differs and (not str(declared.get("statement") or "").strip() or rule["statement"] == PARTITION_STATEMENT):
        problems.append("a rule that differs from GRAMMAR 1.6 needs its own statement, in plain words, for the sources page")
    return dict(rule, declared=True), problems


def is_patient(item: dict | None) -> bool:
    """A frame of a person with the disease: graphic_medical or a named patient."""
    return bool(item) and (item.get("graphic_medical") is True or item.get("named_patient") is True)


def carries_content_fields(item: dict | None) -> bool:
    """The ledger item uses the E3 content schema beyond the legacy shows_bodies."""
    return bool(item) and any(k in item for k in CONTENT_FIELDS if k not in ("shows_bodies", "people"))


def _names(item: dict) -> list[str]:
    people = item.get("people")
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


def bodies_value(item: dict):
    """The ledger's shows_bodies, or the older shows_violence_or_bodies."""
    return item.get("shows_bodies", item.get("shows_violence_or_bodies"))


def asset_checks(item: dict, rule: dict) -> list[dict]:
    """Every check the film's imagery rule makes on one cited asset, as
    ``{rule, ok, severity, evidence}``. ``no-bodies`` is always present (the
    Partition lint, unchanged under the default rule); the others appear only
    when the asset uses the content schema or the film states its own rule,
    so a film on the default rule journals exactly what it did before."""
    out = []
    bodies = bodies_value(item)
    if rule["show_bodies"]:
        out.append({"rule": "no-bodies", "ok": True, "severity": "block",
                    "evidence": {"shows_bodies": bodies, "imagery_rule": "show_bodies: true (the film's rule)"}})
    else:
        out.append({"rule": "no-bodies", "ok": bodies is False, "severity": "block", "evidence": {"shows_bodies": bodies}})
    if not (rule.get("declared") or carries_content_fields(item)):
        return out
    gm = item.get("graphic_medical")
    ev = {"graphic_medical": gm, "show_disease": rule["show_disease"]}
    if gm not in (None, True, False):
        out.append({"rule": "imagery-rule", "ok": False, "severity": "block",
                    "evidence": dict(ev, why=f"graphic_medical must be true or false once checked, not {gm!r}")})
    elif gm is True and not rule["show_disease"]:
        out.append({"rule": "imagery-rule", "ok": False, "severity": "block",
                    "evidence": dict(ev, why="the film's imagery rule does not show disease")})
    else:
        out.append({"rule": "imagery-rule", "ok": True, "severity": "block", "evidence": ev})
    viol = item.get("shows_violence")
    if viol is True and not rule["show_violence"]:
        out.append({"rule": "imagery-rule", "ok": False, "severity": "block",
                    "evidence": {"shows_violence": True, "why": "the film's imagery rule does not show violence"}})
    if item.get("named_patient") is True and rule["name_only_where_source_names"]:
        names = _names(item)
        caption = _norm(" ".join(str(item.get(k) or "") for k in ("title", "caption")))
        unnamed = [n for n in names if _norm(n) not in caption]
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
    the default rule this is the Partition poster rule, word for word."""
    for c in asset_checks(item, rule):
        if c["ok"] or c["severity"] != "block":
            continue
        if c["rule"] == "no-bodies":
            return (f"is not recorded as showing no bodies or violence (shows_bodies: {c['evidence']['shows_bodies']!r}): "
                    "never a poster")
        why = c["evidence"].get("why") or c["evidence"].get("fix") or c["rule"]
        return f"fails the film's imagery rule ({c['rule']}: {why}): never a poster"
    return None


def patient_shot_checks(shots: list[dict], assets: dict, rule: dict, lower_thirds: list[dict]) -> list[dict]:
    """The shot-level half of the rule, for patient shots only: the hold of a
    patient still (shots of one asset joined by a cut or a dissolve are one
    hold), no DETAIL on a patient still unless the shot says ``face: false``,
    no dissolve into a patient shot from another subject, and no
    characterising word in a lower third over an unnamed patient."""
    out = []
    holds: list[list[dict]] = []
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
        if patient:
            a, b = float(s["start_s"]), float(s["start_s"]) + float(s["_dur"])
            for lt in lower_thirds:
                if lt["start"] < b and lt["end"] > a and item.get("named_patient") is not True:
                    words = sorted({m.group(0).lower() for ln in lt["lines"] for m in PATIENT_WORDS.finditer(ln)})
                    if words and rule["name_only_where_source_names"]:
                        out.append({"rule": "patient-lower-third", "ok": False, "unit": lt["id"], "severity": "block",
                                    "evidence": {"shot": s["id"], "words": words, "lines": lt["lines"],
                                                 "fix": "an unnamed patient is given by place and date only"}})
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
SHORTFALL_TOL = 0.03                      # a stated share within 3 points of the measured one
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


def _numbers(text: str) -> list[float]:
    """Shares a card states: '16 percent', '16%', '16 per cent', and fractions ('one sixth', 'a fifth')."""
    t = text.lower()
    out = [float(m.group(1)) / 100 for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", t)]
    for word, v in FRACTIONS.items():
        if re.search(rf"\b{word}s?\b", t):
            out.append(v)
    return out


def shortfall_stated(sf: dict, card_text: str) -> tuple[bool, dict]:
    """Does the card's text state this shortfall? With ``stated_as``, that
    phrase must be on the card. Otherwise the card names what is short (a word
    for readings, voiceless or women) and says it is short: a share within 3
    points of the measured or the floor, or a word of shortfall."""
    text = _norm(card_text)
    what = sf.get("what")
    if sf.get("stated_as"):
        phrase = _norm(sf["stated_as"])
        return phrase in text, {"stated_as": sf["stated_as"], "found": phrase in text}
    words = [w for w in SHORTFALL_WORDS.get(what, ()) if w in text]
    nums = _numbers(text)
    targets = [float(sf[k]) for k in ("measured", "floor") if isinstance(sf.get(k), (int, float)) and not isinstance(sf.get(k), bool)]
    matched = [n for n in nums if any(abs(n - t) <= SHORTFALL_TOL for t in targets)]
    short = [w for w in SHORT_WORDS if re.search(rf"\b{w}\b", text)]
    ok = bool(words) and bool(matched or short)
    return ok, {"names_it": words, "numbers_on_card": [round(n, 4) for n in nums], "numbers_matching": [round(n, 4) for n in matched],
                "shortfall_words": short}


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
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= float(v) <= 1:
            out.append(f"{k} must be a share from 0 to 1, not {v!r}")
    floor = settings[SHORTFALL_WHAT[what]]
    if isinstance(sf.get("floor"), (int, float)) and abs(float(sf["floor"]) - floor) > 1e-6:
        out.append(f"floor {sf['floor']:g} is not the film's {SHORTFALL_WHAT[what]} ({floor:g})")
    if isinstance(sf.get("measured"), (int, float)) and isinstance(sf.get("floor"), (int, float)) and sf["measured"] >= sf["floor"]:
        out.append(f"measured {sf['measured']:g} is not under the floor {sf['floor']:g}: nothing is short")
    if not sf.get("stated_on"):
        out.append("stated_on must name the card shot that states it")
    return out
