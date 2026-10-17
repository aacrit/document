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
  GRAMMAR 2.6) and ``fill_max_upscale`` (1.6, A34: how far a FILL may
  magnify its source, output pixels per source pixel; 1.0 to 3.0).
- ``shortfalls``: ``[{what, floor, stated_on, measured?}]``. A share under its
  floor passes as a journaled review item only when it is declared here and
  the card named by ``stated_on`` prints it through ``{<what>_share}``, which
  the engine fills from the film's own measurement; the card holds no other
  number. ``measured`` is advisory.
"""

from __future__ import annotations

import math
import re
import unicodedata

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


def flag(v) -> bool:
    """A content flag stated true or false: a real bool, never 1, 0 or "true"."""
    return type(v) is bool


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
    """The name, as whole words, in the text (case and spacing set aside); a
    hyphen is part of a name, so "Paul" is not found in "Jean-Paul"."""
    n = _norm(name)
    return bool(n) and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", _norm(text)) is not None


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
        out.append({"rule": "no-bodies", "ok": flag(bodies), "severity": "block",
                    "evidence": {"shows_bodies": bodies, "imagery_rule": "show_bodies: true (the film's rule)",
                                 "why": None if flag(bodies) else "shows_bodies must be stated true or false"}})
    else:
        out.append({"rule": "no-bodies", "ok": bodies is False, "severity": "block", "evidence": {"shows_bodies": bodies}})
    if not (rule.get("declared") or carries_content_fields(item)):
        return out
    unstated = {k: item.get(k, "(absent)") for k in REQUIRED_FLAGS if not flag(item.get(k))}
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

DEFAULT_SETTINGS = {"readings_floor": 0.20, "voiceless_floor": 0.10, "women_floor": 0.30, "ai_generated_share_max": 0.0,
                    "fill_max_upscale": 1.6}
SETTING_BOUNDS = {                        # what GRAMMAR allows a film to set
    "readings_floor": (0.10, 1.0),        # 6.1 as amended (T1f): 20% by default; never under 10%
    "voiceless_floor": (0.10, 1.0),       # A18: the 10% voiceless floor stays
    "women_floor": (0.30, 1.0),           # 6.5: at least 30% (a shortfall is stated, never set lower)
    "ai_generated_share_max": (0.0, 0.15),   # 2.6 and A2: at most 15% of runtime
    "fill_max_upscale": (1.0, 3.0),       # A34: output pixels per source pixel a FILL may reach (1.6 by default)
}
SHARE_SETTINGS = ("readings_floor", "voiceless_floor", "women_floor", "ai_generated_share_max")
SHORTFALL_WHAT = {"readings": "readings_floor", "voiceless": "voiceless_floor", "women": "women_floor"}
# A25 refined (CoS design reset): a shortfall card prints its numbers only through placeholders, filled from
# the film's own measurement at the mix; the card may hold no other number of any kind.
# A3 refined (unsigned voices): women's shortfall may also print the speakers the cut hears by stated gender and the
# unsigned (no stated gender) apart, as counts or as the unsigned speakers' share of testimony seconds; these kinds
# exist for women only (template_problems refuses them elsewhere).
WOMEN_ONLY_KINDS = ("unsigned_share", "speakers_unsigned", "speakers_f", "speakers_m", "speakers")
PLACEHOLDER = re.compile(r"\{(readings|women|voiceless)_(unsigned_share|speakers_unsigned|speakers_f|speakers_m|speakers|share|floor)"
                         r"(?::(pct|words|fraction))?\}")
UNSIGNED_KINDS = ("unsigned_share", "speakers_unsigned")
ANY_BRACE = re.compile(r"\{[^{}]*\}")
FRACTION_FORMS = ((1 / 2, "a half"), (1 / 3, "a third"), (1 / 4, "a quarter"), (1 / 5, "a fifth"), (1 / 10, "a tenth"))
FRACTION_EXACT = 0.005                    # a share within half a point of a fraction is written as that fraction
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINALS = ("fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
             "seventeenth eighteenth nineteenth twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth "
             "ninetieth hundredth thousandth millionth").split()
_STRAY_WORDS = (_ONES + _TENS + _ORDINALS
                + ["hundred", "thousand", "million", "billion", "dozen", "half", "halves", "third", "quarter",
                   "once", "twice", "thrice", "double", "triple", "quadruple", "majority", "minority", "most",
                   "percent", "percentage", "per cent", "digit", "single", "decile", "quintile", "quartile",
                   "percentile", "handful", "lone"])
# number, ordinal, fraction and multiplicative words, with an optional plural; percent signs; the fraction slash
STRAY_NUMBER = re.compile(r"\d|[%\uff05\u2030\u2044]|(?<!\w)(?:"
                          + "|".join(re.escape(w).replace("\\ ", "\\s+") for w in sorted(_STRAY_WORDS, key=len, reverse=True))
                          + r")s?(?![\w])", re.I)


def stray_numbers(text: str) -> list[str]:
    """Every number a text prints outside a placeholder: any character with
    a numeric value (digits in any script, superscripts, subscripts, vulgar
    fractions, Roman numeral signs), then, on the text normalised (NFKC,
    zero-width and other format characters removed, so "thi\u200brty" is
    "thirty"), any digit, number, ordinal, fraction or multiplicative word,
    percent sign or fraction slash."""
    t = str(text or "")
    out = [c for c in t if unicodedata.numeric(c, None) is not None]
    nfkc = unicodedata.normalize("NFKC", t)
    for joiner in ("", " "):              # a format character inside a word ("thi​rty") or between two ("thirty​percent")
        norm = "".join(joiner if unicodedata.category(c) == "Cf" else c for c in nfkc)
        out += [m.group(0) for m in STRAY_NUMBER.finditer(norm)]
    seen, uniq = set(), []
    for x in out:
        if x.lower() not in seen:
            seen.add(x.lower())
            uniq.append(x)
    return uniq


def number_words(n: int) -> str:
    """0 to 100 in words ("twelve", "twenty-one", "one hundred")."""
    if n == 100:
        return "one hundred"
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens - 2] + (f"-{_ONES[ones]}" if ones else "")


def format_share(v: float, fmt: str | None, floor: float | None = None) -> str:
    """The fixed formatter table: ``pct`` "12 percent" (the default),
    ``words`` "twelve percent", ``fraction`` "a fifth" for a half, a third,
    a quarter, a fifth or a tenth within half a point, else pct. A share
    under its ``floor`` is rounded down, so it never prints as the floor
    (19.96% under 20 is "19 percent"), and never as a fraction at or above
    the floor; a share above 0 and under 1% prints "under 1 percent"."""
    v = float(v)
    short = floor is not None and v < float(floor)
    n = int(math.floor(v * 100 + 1e-9)) if short else int(math.floor(v * 100 + 0.5))   # 0.29 * 100 is 28.999...
    if fmt == "fraction":
        for f, words in FRACTION_FORMS:
            if abs(v - f) <= FRACTION_EXACT and not (short and f >= float(floor) - 1e-9):
                return words
    if 0 < v < 0.01:
        return "under one percent" if fmt == "words" else "under 1 percent"
    if fmt == "words":
        return f"{number_words(max(0, min(100, n)))} percent"
    return f"{n} percent"


def prints_unsigned(text: str) -> bool:
    """True when ``text`` prints the unsigned share or count apart (A3 refined)."""
    return any(m.group(1) == "women" and m.group(2) in UNSIGNED_KINDS for m in PLACEHOLDER.finditer(str(text or "")))


class FillError(ValueError):
    """A placeholder that cannot be filled truthfully."""


def fill_placeholders(text: str, values: dict, *, accounts: bool | None = None) -> str:
    """Every placeholder filled from ``values`` ({what: {"share", "floor"}}).
    A share is formatted against its floor (rounded down under it); as a
    backstop, a share under its floor whose text equals the floor's in any
    format is refused (it would print the floor as the measurement). A
    ``{women_share}`` (or a count of women's or men's voices) is refused when
    any testimony's speaker states no gender (``unknown_s`` > 0) unless the
    same text also prints the unsigned apart (``{women_unsigned_share}`` or
    ``{women_speakers_unsigned}``): gender is never inferred, and a share
    of the known never stands for the whole (A3 refined). Counts print as
    digits, or as words with ``:words``."""
    text = str(text or "")
    if accounts is None:  # a caller filling one piece of a longer statement (a split caption cue) says whether the whole accounts
        accounts = prints_unsigned(text)

    def one(m):
        what, kind, fmt = m.group(1), m.group(2), m.group(3)
        src = values.get(what) or {}
        if kind.startswith("speakers"):
            sp = src.get("speakers") or {}
            key = {"speakers": "all", "speakers_f": "f", "speakers_m": "m", "speakers_unsigned": "unsigned"}[kind]
            if key not in sp:
                raise FillError(f"no measured value for {m.group(0)}")
            v, floor = sp[key], None
        else:
            if what not in values or kind not in src:
                raise FillError(f"no measured value for {m.group(0)}")
            v, floor = float(src[kind]), src.get("floor")
        if (kind in ("speakers_f", "speakers_m") and what == "women" and float(src.get("unknown_s") or 0) > 0
                and not accounts):
            raise FillError(f"{m.group(0)}: some testimony has no stated gender, so a count of women's or men's voices "
                            "is printed only with {women_speakers_unsigned} beside it (A3 refined)")
        if kind == "floor":
            return format_share(v, fmt)
        if kind in WOMEN_ONLY_KINDS and what != "women":
            raise FillError(f"{m.group(0)}: speaker counts and the unsigned share exist for women's shortfall only")
        if kind == "unsigned_share":
            return format_share(v, fmt)
        if kind.startswith("speakers"):
            if float(v) != int(v) or v < 0:
                raise FillError(f"{m.group(0)}: a count of voices is a whole number, not {v!r}")
            return number_words(int(v)) if fmt == "words" and int(v) <= 100 else str(int(v))
        if what == "women" and float(values[what].get("unknown_s") or 0) > 0 and not accounts:
            raise FillError(f"{m.group(0)}: {values[what]['unknown_s']:g} s of testimony has no stated gender, so women's "
                            "share cannot be printed without the unsigned apart ({women_unsigned_share} or "
                            "{women_speakers_unsigned} on the same card; gender is never inferred, A3)")
        out = format_share(v, fmt, floor)
        if floor is not None and v < float(floor) and out in {format_share(float(floor), f) for f in ("pct", "words", "fraction")}:
            raise FillError(f"{m.group(0)} would print {out!r}, the floor itself, for a share of {v:.4f} under it")
        return out
    return PLACEHOLDER.sub(one, text)


def has_placeholder(text: str) -> bool:
    return bool(ANY_BRACE.search(str(text or "")))


def states_shortfall(what: str, text: str) -> bool:
    """A card states a shortfall by printing the film's measured share
    (``{<what>_share}``); women's shortfall may instead print the voices the
    cut hears by stated gender (``{women_speakers_f}``), A3 refined."""
    t = str(text or "")
    return bool(re.search(rf"\{{{what}_share(?::\w+)?\}}", t)
                or (what == "women" and re.search(r"\{women_speakers_f(?::\w+)?\}", t)))


def template_problems(text: str, whats: set | list, *, needs_share: bool) -> tuple[list[str], dict]:
    """What is wrong with a shortfall card's text (or a subtitle or text
    element shown with it): an unknown placeholder, a placeholder for a
    shortfall the card does not state, any digit, number word, fraction or
    percent sign outside a placeholder, and, on the card itself, a stated
    shortfall without its ``{<what>_share}``."""
    t = str(text or "")
    probs = []
    unknown = [m.group(0) for m in ANY_BRACE.finditer(t) if not PLACEHOLDER.fullmatch(m.group(0))]
    if unknown:
        probs.append(f"unknown placeholders {unknown} (known: {{<readings|women|voiceless>_<share|floor>[:pct|words|fraction]}}, "
                     "and for women {women_unsigned_share}, {women_speakers}, {women_speakers_f}, {women_speakers_m}, "
                     "{women_speakers_unsigned})")
    wrong_kind = [m.group(0) for m in PLACEHOLDER.finditer(t) if m.group(2) in WOMEN_ONLY_KINDS and m.group(1) != "women"]
    if wrong_kind:
        probs.append(f"{wrong_kind}: speaker counts and the unsigned share exist for women's shortfall only")
    used = {m.group(1) for m in PLACEHOLDER.finditer(t)}
    others = sorted(used - set(whats))
    if others:
        probs.append(f"placeholders for {', '.join(others)}, which no shortfall stated on this card declares")
    stray = stray_numbers(ANY_BRACE.sub(" ", t))
    if stray:
        probs.append(f"numbers outside a placeholder: {stray}; a shortfall card prints numbers only through placeholders")
    missing = sorted(w for w in whats if needs_share and not states_shortfall(w, t))
    if missing:
        probs.append(f"no {{<what>_share}} for {', '.join(missing)}: a card that states a shortfall prints the film's measured share")
    return probs, {"placeholders": sorted({m.group(0) for m in PLACEHOLDER.finditer(t)}), "stray": stray}


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
        if k == "master_fps":             # A44: a rate, not a number in bounds (studio/engine/cadence.py), kept exact
            from studio.engine import cadence as CAD
            try:
                stated[k] = CAD.rate_str(CAD.parse_rate(v))
            except CAD.RateError as e:
                problems.append(str(e))
            continue
        if k not in SETTING_BOUNDS:
            problems.append(f"unknown setting {k!r} (known: {', '.join(sorted([*SETTING_BOUNDS, 'master_fps']))})")
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            problems.append(f"{k} must be a share from 0 to 1, not {v!r}" if k in SHARE_SETTINGS else
                            f"{k} must be a number, not {v!r}")
            continue
        lo, hi = SETTING_BOUNDS[k]
        if not lo - 1e-9 <= float(v) <= hi + 1e-9:
            problems.append(f"{k} {v:g} is outside GRAMMAR's bounds ({lo:g} to {hi:g})")
            continue
        settings[k] = float(v)
        stated[k] = float(v)
    return settings, stated, problems


def _share(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def shortfall_problems(sf: dict, settings: dict) -> list[str]:
    """What is wrong with one declared shortfall, before its card is read.
    ``measured`` is advisory (the card prints the film's own measurement);
    if given it must be a share."""
    out = []
    if not isinstance(sf, dict):
        return [f"a shortfall must be an object, not {sf!r}"]
    what = sf.get("what")
    if what not in SHORTFALL_WHAT:
        out.append(f"what must be one of {', '.join(sorted(SHORTFALL_WHAT))}, not {what!r}")
        return out
    v = sf.get("floor")
    if _share(v) is None or not 0 <= float(v) <= 1:
        out.append(f"floor must be a share from 0 to 1, not {v!r}")
    if "measured" in sf and (_share(sf["measured"]) is None or not 0 <= float(sf["measured"]) <= 1):
        out.append(f"measured (advisory) must be a share from 0 to 1, not {sf['measured']!r}")
    floor = settings[SHORTFALL_WHAT[what]]
    if _share(sf.get("floor")) is not None and abs(float(sf["floor"]) - floor) > 1e-6:
        out.append(f"floor {sf['floor']:g} is not the film's {SHORTFALL_WHAT[what]} ({floor:g})")
    if not sf.get("stated_on"):
        out.append("stated_on must name the card shot that states it")
    return out
