"""A film's own rules, so the engine serves a second film (ENGINE-STRESS E3,
E9, E11): the imagery rule and the content flags (GRAMMAR A21), the policy
settings and stated shortfalls (A25), and archival lines that play a span of
a source's own soundtrack (A26). Each is tested both ways, on the Partition
pilot's rule (the default) and on a rule like the smallpox film's ("Show not
tell"). No render: plans, mixes and small ffmpeg cuts only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from conftest import make_film
from studio.engine import journal as J
from studio.engine import policy as POL
from studio.engine import publish as P
from studio.engine import render as R

import make_media

SHOW = {"show_disease": True, "min_hold_s": 3.0,
        "statement": "This film shows smallpox: faces with the rash, held long enough to be seen, never flashed."}
CARD_D = ["The record holds no open-licence words of anyone who had smallpox.",
          "The readings and recordings in this film are about {readings_share:pct} of its running time, under "
          "{readings_floor:fraction} the grammar asks, and a woman's voice carries only {women_share:pct} of them. "
          "The film says so rather than invent."]
TRANSCRIPT = ("00:00:01.000 --> 00:00:02,500 | [Narrator:] The reel speaksfor\n"
              "00:00:02.500 --> 00:00:04,000 | itself, in its own words.\n")
ARCH_TEXT = "The reel speaks for itself, in its own words."


def lints(j, rule):
    return [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == rule]


def _plan(film, name="t"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def _edit(film: Path, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _still(ledger, sid):
    return next(x for x in ledger["items"] if x["id"] == sid)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """The fixture film, plus a small reel with its own soundtrack (FX-REEL)
    and the reel's transcript, made once and copied per test."""
    film = make_film(tmp_path_factory.mktemp("films") / "fixture")
    make_media.reel(film / "footage" / "fx-reel.mp4")
    (film / "transcripts").mkdir()
    (film / "transcripts" / "fx-reel.txt").write_text(TRANSCRIPT, encoding="utf-8")
    _edit(film, lambda d: d["items"].append({
        "id": "FX-REEL", "file": "fx-reel.mp4", "title": "Synthetic reel with its own soundtrack, test fixture",
        "date": "2026", "archive": "studio test fixture", "archive_short": "test fixture", "licence": "CC0",
        "synthetic": True, "test_fixture": True, "data_source": "ffmpeg testsrc2 and sine, test fixture",
        "telecined": False, "people": False, "shows_bodies": False, "transcript_file": "transcripts/fx-reel.txt"}),
        "footage-ledger.json")
    # A21: once checked, every cited asset states its content flags true or false (missing is never read as false)
    for ledger in ("stills-ledger.json", "footage-ledger.json"):
        _edit(film, lambda d: [x.update(graphic_medical=False, named_patient=False, shows_violence=False) for x in d["items"]], ledger)
    # no speaker lower third over the stills a test makes a patient (A21: over an unnamed patient, place and date only)
    _edit(film, lambda p: (p["parts"][1]["text"].remove(next(t for t in p["parts"][1]["text"] if t["id"] == "T1")),
                           p["subtitle_source"].remove(next(c for c in p["subtitle_source"] if c["ref"] == "T1"))))
    return film


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


def _patient(film, sid="FX-STILL-C", **flags):
    _edit(film, lambda d: _still(d, sid).update(**({"graphic_medical": True} | flags)), "stills-ledger.json")


# --------------------------------------------------------------------------
# E3: the imagery rule and the content flags (A21)
# --------------------------------------------------------------------------


def test_e3_the_default_rule_is_the_partition_lint_exactly():
    rule = dict(POL.DEFAULT_IMAGERY_RULE, declared=False)
    assert R.POL.imagery_rule({}) == (rule, [])
    assert [c["rule"] for c in POL.asset_checks({"shows_bodies": False}, rule)] == ["no-bodies"]
    assert POL.asset_checks({"shows_bodies": False}, rule)[0]["ok"]
    for item, ok in (({"shows_bodies": True}, False), ({}, False), ({"shows_violence_or_bodies": False}, True),
                     ({"shows_bodies": True, "shows_violence_or_bodies": False}, False)):
        assert POL.asset_checks(item, rule)[0]["ok"] is ok, item
    # the poster's refusal is word for word the Partition one
    assert POL.poster_problem({"shows_bodies": None}, rule) == \
        "is not recorded as showing no bodies or violence (shows_bodies: None): never a poster"


def test_e3_partition_refuses_disease_and_the_shown_rule_allows_it(film):
    _patient(film)
    with pytest.raises(R.Refused, match=r"imagery-rule \(S5\)"):
        _plan(film, "partition-disease")
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    plan, j = _plan(film, "show-disease")
    assert plan["imagery_rule"]["show_disease"] and plan["imagery_rule"]["declared"]
    assert {e["status"] for e in lints(j, "imagery-rule") if e["unit"] == "S5"} == {"pass"}
    assert [e["status"] for e in lints(j, "patient-hold")] == ["pass"]           # S5 holds 3.0 s, the rule's minimum
    assert {e["status"] for e in lints(j, "no-bodies")} == {"pass"}              # bodies stay out: show_bodies is false


def test_e3_bodies_and_violence_stay_out_unless_the_rule_says_so(film):
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _edit(film, lambda d: _still(d, "FX-STILL-C").update(shows_violence=True), "stills-ledger.json")
    with pytest.raises(R.Refused, match=r"imagery-rule \(S5\)"):
        _plan(film, "violence")
    _edit(film, lambda d: _still(d, "FX-STILL-C").update(shows_violence=False, shows_bodies=True), "stills-ledger.json")
    with pytest.raises(R.Refused, match=r"no-bodies \(S5\)"):
        _plan(film, "bodies")
    _edit(film, lambda p: p.update(imagery_rule=dict(SHOW, show_bodies=True)))
    _plan(film, "bodies-shown")                                                  # the film's rule says so, and states it


def test_e3_a_patient_still_is_held_never_detailed_and_never_dissolved_into(film):
    _patient(film)
    _edit(film, lambda p: p.update(imagery_rule=dict(SHOW, min_hold_s=8.0)))
    with pytest.raises(R.Refused, match=r"patient-hold \(S5\)"):
        _plan(film, "hold")
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _edit(film, lambda p: _shot(p, "S5").update(preset="DETAIL", dur_s=3.0))
    with pytest.raises(R.Refused, match=r"patient-detail \(S5\)"):
        _plan(film, "detail")
    _edit(film, lambda p: _shot(p, "S5").update(face=False))
    _plan(film, "detail-not-a-face")                                             # a DETAIL on something else: allowed
    _patient(film, "FX-STILL-B")
    with pytest.raises(R.Refused, match=r"patient-dissolve \(S4\)"):            # S4 dissolves in from S3, another subject
        _plan(film, "dissolve")
    _edit(film, lambda p: p.update(imagery_rule=dict(SHOW, no_dissolve_into_patient=False)))
    _plan(film, "dissolve-allowed")


def test_e3_a_patient_is_named_only_as_the_source_names_them(film):
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _patient(film, named_patient=True, people=[{"name": "Test Patient"}], consent_basis="the caption names her")
    with pytest.raises(R.Refused, match=r"patient-named-by-source \(S5\)"):
        _plan(film, "named-not-in-caption")
    _edit(film, lambda d: _still(d, "FX-STILL-C").update(title="Test Patient with her mother, test fixture"), "stills-ledger.json")
    _plan(film, "named-in-caption")
    _edit(film, lambda d: _still(d, "FX-STILL-C").pop("consent_basis"), "stills-ledger.json")
    with pytest.raises(R.Refused, match=r"patient-consent \(S5\)"):
        _plan(film, "named-no-consent")


def test_e3_an_unnamed_patient_is_given_by_place_and_date_only(film):
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _patient(film, minor=True)
    _edit(film, lambda p: p["parts"][1]["text"].append(
        {"id": "T9", "kind": "lower_third", "start_s": 11.9, "end_s": 14.0, "lines": ["A victim of the fixture", "2026"]}))
    with pytest.raises(R.Refused, match=r"patient-lower-third \(T9\)"):
        _plan(film, "victim")
    _edit(film, lambda p: next(t for t in p["parts"][1]["text"] if t["id"] == "T9").update(lines=["Fixture folder", "2026"]))
    plan, j = _plan(film, "place")
    consent = lints(j, "patient-consent")                    # an unnamed child: a review item for G3, not a refusal
    assert consent and consent[0]["severity"] == "review" and consent[0]["evidence"]["consent_basis"] is None


def test_e3_a_missing_or_unknown_flag_is_refused_never_read_as_false(film):
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _edit(film, lambda d: _still(d, "FX-STILL-C").pop("graphic_medical"), "stills-ledger.json")
    with pytest.raises(R.Refused, match=r"content-flags \(S5\)"):
        _plan(film, "flag-missing")
    _edit(film, lambda d: _still(d, "FX-STILL-C").update(graphic_medical="unknown (check)"), "stills-ledger.json")
    with pytest.raises(R.Refused, match=r"content-flags \(S5\)"):
        _plan(film, "flag-unknown")
    _edit(film, lambda p: p.pop("imagery_rule"))
    with pytest.raises(R.Refused, match=r"content-flags \(S5\)"):              # the item uses the schema: same under Partition
        _plan(film, "flag-unknown-default")
    rule = dict(POL.DEFAULT_IMAGERY_RULE, declared=False)
    assert [c["rule"] for c in POL.asset_checks({"shows_bodies": False}, rule)] == ["no-bodies"]   # a Partition item: unchanged


def test_e3_the_statement_is_tied_to_the_flags():
    assert POL.imagery_rule({"imagery_rule": {"statement": "No footage or photograph of bodies, killing, wounds, or corpses"}})[1] == []
    assert POL.imagery_rule({"imagery_rule": {}})[1] == []
    probs = POL.imagery_rule({"imagery_rule": {"statement": "This film shows smallpox."}})[1]
    assert probs and "no flag differs" in probs[0]                                # words the flags do not back
    probs = POL.imagery_rule({"imagery_rule": {"show_disease": True,
                                               "statement": "no footage or photograph of BODIES killing wounds or corpses!"}})[1]
    assert probs and "needs its own statement" in probs[0]                        # the default's words over a changed rule
    assert POL.imagery_rule({"imagery_rule": SHOW})[1] == []


@pytest.mark.parametrize("lines, why", [
    (["Fixture folder", "Test stand-in, 2026", "Fixture source, studio test folder  ·  read by a computer voice"], "two-line place"),
    (["Fixture folder", "a hard year"], "line 2 is a date"),
    (["Fixture speaker", "2026"], "names Fixture speaker"),                       # a cast name
    (["Test Patient", "16 October 1975"], "names Test Patient"),                  # a name a ledger item lists
])
def test_e3_over_an_unnamed_patient_only_place_and_date(film, lines, why):
    _edit(film, lambda p: p.update(imagery_rule=SHOW))
    _patient(film, people=[{"name": "Test Patient"}])
    _edit(film, lambda p: p["parts"][1]["text"].append({"id": "T9", "kind": "lower_third", "start_s": 11.9, "end_s": 14.0,
                                                        "lines": lines}))
    with pytest.raises(R.Refused, match=r"patient-lower-third \(T9\)") as e:
        _plan(film, "lt-form")
    assert why in str(e.value)
    assert POL.DATE_LINE.match("16 October 1975") and POL.DATE_LINE.match("1973 to 1975") and POL.DATE_LINE.match("May 1974")


def test_e3_a_name_is_matched_as_whole_words():
    assert POL.says_name("Rahima Banu in her mother's arms", "Rahima Banu")
    assert not POL.says_name("Annabel, Kuralia, 1975", "Ann") and POL.says_name("Ann, Kuralia, 1975", "ann")
    rule = dict(POL.imagery_rule({"imagery_rule": SHOW})[0])
    item = {"shows_bodies": False, "graphic_medical": True, "named_patient": True, "shows_violence": False,
            "people": [{"name": "Ann"}], "title": "Annabel with her mother", "consent_basis": "test"}
    assert not next(c for c in POL.asset_checks(item, rule) if c["rule"] == "patient-named-by-source")["ok"]


def test_e3_a_patient_with_no_consent_basis_is_never_the_poster():
    rule = POL.imagery_rule({"imagery_rule": SHOW})[0]
    item = {"shows_bodies": False, "graphic_medical": True, "named_patient": False, "shows_violence": False, "minor": False}
    assert "no consent_basis: never a poster" in POL.poster_problem(item, rule)
    assert POL.poster_problem(dict(item, consent_basis="government film of a public campaign"), rule) is None


def test_e3_a_declared_rule_states_itself_and_knows_its_keys(film):
    _edit(film, lambda p: p.update(imagery_rule={"show_disease": True}))
    with pytest.raises(R.Refused, match=r"imagery-rule-declared"):
        _plan(film, "no-statement")
    _edit(film, lambda p: p.update(imagery_rule=dict(SHOW, show_gore=True)))
    with pytest.raises(R.Refused, match=r"unknown key 'show_gore'"):
        _plan(film, "unknown-key")
    _edit(film, lambda p: p.update(imagery_rule=dict(SHOW, min_hold_s="8")))
    with pytest.raises(R.Refused, match=r"min_hold_s must be a number"):
        _plan(film, "bad-type")


def test_e3_the_poster_reads_the_films_rule(tmp_path):
    ledger = tmp_path / "stills.json"
    ledger.write_text(json.dumps({"items": [
        {"id": "S-7762", "title": "A girl of two, test", "licence": "public domain", "shows_bodies": False, "graphic_medical": True,
         "named_patient": False, "shows_violence": False, "minor": True, "consent_basis": "test"},
        {"id": "S-1", "title": "a crowd", "licence": "public domain", "shows_bodies": False}]}), encoding="utf-8")
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"jpg")
    with pytest.raises(R.Refused, match=r"S-7762 fails the film's imagery rule \(imagery-rule"):
        P.poster_record(ledger, "S-7762", poster)                                # Partition's rule: never a poster
    rule, _ = POL.imagery_rule({"imagery_rule": SHOW})
    assert P.poster_record(ledger, "S-7762", poster, rule)["ledger_id"] == "S-7762"
    assert P.poster_record(ledger, "S-1", poster)["ledger_id"] == "S-1"
    # the packet takes the rule the render stated in sources.json, else the screenplay's
    assert P.poster_rule({"imagery_rule": rule}, None) is rule
    play = tmp_path / "screenplay.json"
    play.write_text(json.dumps({"imagery_rule": SHOW, "parts": []}), encoding="utf-8")
    assert P.poster_rule({}, play)["show_disease"] is True and P.poster_rule({}, None) is None


def test_e3_e2_sources_json_states_the_rule_the_settings_and_the_films_own_sides(film):
    plan, j = _plan(film, "doc-default")
    doc = R.sources_doc(plan, j, {})
    assert doc["imagery_rule"]["statement"] == POL.PARTITION_STATEMENT and doc["imagery_rule"]["declared"] is False
    assert doc["settings"] == POL.DEFAULT_SETTINGS and doc["sides"] == ["britain"] and doc["shortfalls"] == []
    assert doc["readings_share_counts"] == ["reading", "archival"]
    _edit(film, lambda p: p.update(imagery_rule=SHOW, balance={"sides": ["usa", "uk"]}))
    plan, j = _plan(film, "doc-show")
    doc = R.sources_doc(plan, j, {})
    assert doc["imagery_rule"]["statement"] == SHOW["statement"] and doc["sides"] == ["usa", "uk"]
    assert doc["balance"] == {"sides": ["usa", "uk"]}
    _edit(film, lambda p: (p.pop("balance"), p["cast"]["speakers"].append({"id": "sp-2", "name": "B", "side": "uk", "gender": "f"})))
    assert R.film_sides(json.loads((film / "screenplay.json").read_text(encoding="utf-8"))) == ["britain", "uk"]


# --------------------------------------------------------------------------
# E9: policy settings and stated shortfalls (A25)
# --------------------------------------------------------------------------


def test_e9_settings_default_to_partition_and_stay_inside_grammar():
    assert POL.film_settings({}) == (POL.DEFAULT_SETTINGS, {}, [])
    assert POL.DEFAULT_SETTINGS == {"readings_floor": R.READINGS_FLOOR, "voiceless_floor": R.VOICELESS_FLOOR,
                                    "women_floor": 0.30, "ai_generated_share_max": 0.0}
    s, stated, probs = POL.film_settings({"settings": {"readings_floor": 0.12}})
    assert s["readings_floor"] == 0.12 and stated == {"readings_floor": 0.12} and not probs
    for bad, why in (({"readings_floor": 0.05}, "outside GRAMMAR's bounds"), ({"voiceless_floor": 0.0}, "outside"),
                     ({"women_floor": 0.2}, "outside"), ({"ai_generated_share_max": 0.2}, "outside"),
                     ({"readings_floor": True}, "must be a share"), ({"narration_max": 0.5}, "unknown setting")):
        assert any(why in p for p in POL.film_settings({"settings": bad})[2]), bad


def test_e9_a_film_setting_is_linted_and_names_its_ai_share(film):
    _edit(film, lambda p: p.update(settings={"readings_floor": 0.05}))
    with pytest.raises(R.Refused, match=r"film-settings"):
        _plan(film, "settings-bad")
    _edit(film, lambda p: p.update(settings={"ai_generated_share_max": 0.1}))
    plan, j = _plan(film, "settings-ai")
    assert [e["status"] for e in lints(j, "ai-generated-share-max")] == ["pass"] and not lints(j, "ai-generated-share-zero")
    _edit(film, lambda p: p.pop("settings"))
    plan, j = _plan(film, "settings-default")
    ev = lints(j, "ai-generated-share-zero")[0]
    assert ev["evidence"] == {"generated_frames": 0, "frames": plan["frames"]} and ev["grammar"] == "decision 2026-10-10"


CARD_R = [CARD_D[0], "The readings and recordings in this film are about {readings_share:pct} of its running time, under "
                     "{readings_floor:fraction} the grammar asks."]


def _with_card_d(film, shortfalls, text=None):
    """Card D on S7, stating the given shortfalls; by default the full card when women's is among them, else its readings half."""
    if text is None:
        text = CARD_D if any(isinstance(x, dict) and x.get("what") == "women" for x in shortfalls) else CARD_R
    _edit(film, lambda p: (_shot(p, "S7").update(text=text), p.update(shortfalls=shortfalls)))


SF_READ = {"what": "readings", "measured": 0.16, "floor": 0.20, "stated_on": "S7"}
SF_WOMEN = {"what": "women", "measured": 0.12, "floor": 0.30, "stated_on": "S7"}


def test_e9_a_shortfall_card_prints_numbers_only_through_placeholders(film):
    _with_card_d(film, [SF_READ, SF_WOMEN])
    plan, j = _plan(film, "card-d")
    assert [e["status"] for e in lints(j, "shortfall-stated")] == ["pass", "pass"]
    assert all(sf["stated"] for sf in plan["shortfalls"])
    card = [e for e in lints(j, "shortfall-card") if e["unit"] == "card:S7"][0]
    assert card["status"] == "pass" and card["evidence"]["placeholders"] == [
        "{readings_floor:fraction}", "{readings_share:pct}", "{women_share:pct}"]
    _with_card_d(film, [dict(SF_READ, stated_on="S5")])
    with pytest.raises(R.Refused, match=r"not a card"):
        _plan(film, "not-a-card")
    _with_card_d(film, [dict(SF_READ, floor=0.30)])
    with pytest.raises(R.Refused, match=r"is not the film's readings_floor"):
        _plan(film, "wrong-floor")
    _with_card_d(film, [dict(SF_READ, measured="about a sixth")])
    with pytest.raises(R.Refused, match=r"measured \(advisory\) must be a share"):
        _plan(film, "measured-not-a-share")
    _with_card_d(film, [{k: v for k, v in SF_READ.items() if k != "measured"}])
    _plan(film, "measured-advisory")                                               # measured may be left out: the cut decides


@pytest.mark.parametrize("words", ["thirty", "two sixths", "30\uff05", "0.30", "one sixth", "twenty-one percent", "a fifth",
                                   "half of them", "per cent", "\u00bd", "a dozen voices", "\u0663\u0660 percent"])
def test_e9_a_number_outside_a_placeholder_is_refused(film, words):
    _with_card_d(film, [SF_READ], [CARD_D[0], "The readings are {readings_share:pct} of the film, " + words + "."])
    with pytest.raises(R.Refused, match=r"shortfall-card \(card:S7\).*numbers outside a placeholder"):
        _plan(film, "stray")


def test_e9_the_cards_own_share_is_required_and_placeholders_stay_on_their_card(film):
    _with_card_d(film, [SF_READ, SF_WOMEN], [CARD_D[0], "The readings are {readings_share:pct}, under {readings_floor:fraction}."])
    with pytest.raises(R.Refused, match=r"shortfall-stated \(shortfall:women\).*does not print \{women_share\}"):
        _plan(film, "no-women-share")
    _with_card_d(film, [SF_READ], [CARD_D[0], "The readings are {readings_share:pct}; women {women_share:pct}."])
    with pytest.raises(R.Refused, match=r"placeholders for women, which no shortfall stated on this card declares"):
        _plan(film, "undeclared-placeholder")
    _with_card_d(film, [SF_READ], [CARD_D[0], "The readings are {readings_count} of {readings_share:pct}."])
    with pytest.raises(R.Refused, match=r"unknown placeholders"):
        _plan(film, "unknown-placeholder")
    _with_card_d(film, [SF_READ])
    _edit(film, lambda p: p["parts"][1]["text"].append({"id": "T9", "kind": "overlay", "start_s": 15.5, "end_s": 16.0,
                                                        "lines": ["{readings_share:pct}"]}))
    with pytest.raises(R.Refused, match=r"shortfall-card \(text:T9\)"):            # it would be drawn as written
        _plan(film, "placeholder-elsewhere")


def test_e9_a_subtitle_shown_with_the_card_obeys_the_card(film):
    _with_card_d(film, [SF_READ])
    _edit(film, lambda p: p["subtitle_source"].append({"ref": "S7", "start_s": 17.75, "end_s": 20.2,
                                                       "en": "Readings are thirty percent of the film."}))
    with pytest.raises(R.Refused, match=r"shortfall-card \(subtitle:S7\).*numbers outside a placeholder"):
        _plan(film, "subtitle-stray")


def test_e9_the_formatter_table():
    assert POL.format_share(0.157, None) == POL.format_share(0.157, "pct") == "16 percent"
    assert POL.format_share(0.12, "words") == "twelve percent" and POL.format_share(0.215, "words") == "twenty-two percent"
    assert POL.format_share(1.0, "words") == "one hundred percent" and POL.format_share(0.0, "words") == "zero percent"
    for v, w in ((0.5, "a half"), (1 / 3, "a third"), (0.25, "a quarter"), (0.2, "a fifth"), (0.1, "a tenth"), (0.203, "a fifth")):
        assert POL.format_share(v, "fraction") == w
    assert POL.format_share(1 / 6, "fraction") == "17 percent"                     # not in the table: falls back to pct
    assert POL.format_share(0.21, "fraction") == "21 percent"
    values = {"readings": {"share": 0.157, "floor": 0.2}, "women": {"share": 0.119, "floor": 0.3}}
    assert POL.fill_placeholders(CARD_D[1], values) == (
        "The readings and recordings in this film are about 16 percent of its running time, under a fifth the grammar "
        "asks, and a woman's voice carries only 12 percent of them. The film says so rather than invent.")


def test_e9_the_card_is_filled_from_the_cut_and_sources_json_carries_it(film):
    _with_card_d(film, [SF_READ, SF_WOMEN])
    _edit(film, lambda p: p["subtitle_source"].append({"ref": "S7", "start_s": 17.75, "end_s": 20.2, "en": CARD_D[1]}))
    plan, j = _plan(film, "fill")
    plan = _event(plan, speakers=SPEAKERS)
    values = R.shortfall_values(plan, _placed(0.135, women_s=30.0))
    assert values["women"]["share"] == pytest.approx(30 / 135, abs=1e-3) and values["readings"]["floor"] == 0.2
    changed = R.fill_cards(plan, values, j)
    s7 = next(s for s in plan["shots"] if s["id"] == "S7")
    assert changed == ["S7"] and "about 14 percent of its running time" in s7["text"][1] and "22 percent" in s7["text"][1]
    assert any("S7 filled from the cut" in e.get("what", "") for e in J.read(j.path) if e["kind"] == "decision")
    doc = R.sources_doc(plan, j, {})
    assert next(s for s in doc["shots"] if s["id"] == "S7")["text"] == s7["text"]
    assert doc["card_fills"]["texts"]["S7"] == s7["text"] and doc["card_fills"]["values"] == values
    assert next(sf for sf in doc["shortfalls"] if sf["what"] == "readings")["measured_cut"] == values["readings"]["share"]
    # the captions take the same values; with none, a placeholder is refused, never published as written
    from studio.engine import captions as C
    vtt = C.captions(film / "screenplay.json", fills=values)
    assert "14 percent" in vtt and "{" not in vtt
    with pytest.raises(C.CaptionError, match="placeholder"):
        C.captions(film / "screenplay.json")


def _event(plan, **kw):
    return dict(plan, duration_s=1000.0, runtime_target_s=1200, **kw)


def _placed(readings_share, women_s=0.0, archival=False):
    lines = [{"id": "N", "kind": "narration", "line_kind": "narration", "at_s": 0.0, "dur_s": 500.0,
              "speech_from_s": 0.0, "speech_to_s": 500.0},
             {"id": "R", "kind": "archival" if archival else "reading", "line_kind": "testimony", "speaker": "sp-m",
              "at_s": 501.0, "dur_s": 1000 * readings_share - women_s, "speech_from_s": 501.0,
              "speech_to_s": 501.0 + 1000 * readings_share - women_s}]
    if women_s:
        lines.append({"id": "W", "kind": "reading", "line_kind": "testimony", "speaker": "sp-f", "at_s": 900.0, "dur_s": women_s,
                      "speech_from_s": 900.0, "speech_to_s": 900.0 + women_s})
    return {"lines": lines}


SPEAKERS = {"sp-m": {"name": "M", "side": "usa", "gender": "m"}, "sp-f": {"name": "F", "side": "uk", "gender": "f"}}
MIX = np.full(48000, 1e-3, np.float32)


def test_e9_a_stated_shortfall_becomes_a_review_item_and_an_unstated_one_refuses(film):
    _with_card_d(film, [SF_READ])
    plan, _ = _plan(film, "sf-plan")
    event = _event(plan)
    j = J.Journal(film="sf-stated")
    assert R.sound_lints(j, event, MIX, _placed(0.10)) == []                     # whatever the cut measures, the card prints it
    rf = lints(j, "readings-floor")[0]
    assert rf["status"] == "review" and rf["severity"] == "review" and "stated on S7" in rf["evidence"]["result"]
    out = R.sound_lints(J.Journal(film="sf-unstated"), _event(plan, shortfalls=[]), MIX, _placed(0.16))
    assert any(o.startswith("readings-floor") and "'min': 0.2" in o for o in out)
    out = R.sound_lints(J.Journal(film="sf-unstated-card"), _event(plan, shortfalls=[dict(SF_READ, stated=False)]), MIX,
                        _placed(0.16))
    assert any("not stated on a card" in o for o in out)


def test_e9_a_film_that_meets_its_floor_is_refused_a_shortfall(film):
    _with_card_d(film, [SF_READ])
    plan, _ = _plan(film, "sf-met-plan")
    j = J.Journal(film="sf-met")
    out = R.sound_lints(j, _event(plan), MIX, _placed(0.25))
    assert any(o.startswith("shortfall-measured (readings)") and "not short" in o for o in out)
    assert lints(j, "shortfall-measured")[0]["severity"] == "block"
    jd = J.Journal(film="sf-met-draft")
    assert R.sound_lints(jd, _event(plan), MIX, _placed(0.25), draft=True) == []
    assert lints(jd, "shortfall-measured")[0]["severity"] == "warn"              # judged under --draft too, as a warning


def test_e9_the_readings_floor_is_the_films_own(film):
    plan, _ = _plan(film, "floor-own")
    out = R.sound_lints(J.Journal(film="floor-12"), _event(plan, settings=dict(POL.DEFAULT_SETTINGS, readings_floor=0.12)),
                        MIX, _placed(0.16))
    assert out == []
    out = R.sound_lints(J.Journal(film="floor-default"), _event(plan), MIX, _placed(0.16))
    assert any(o.startswith("readings-floor") for o in out)


def test_e9_archival_recordings_count_toward_readings_and_womens_share():
    placed = _placed(0.25, archival=True)
    assert R.voice_shares({"duration_s": 1000.0}, placed)["readings"] == pytest.approx(0.25, abs=0.001)
    assert R.READINGS_SHARE_COUNTS == ("reading", "archival")
    w = R.women_share({"speakers": SPEAKERS}, _placed(0.20, women_s=24.0, archival=True))
    assert w["share"] == pytest.approx(0.12, abs=0.001) and w["by_gender_s"]["m"] == pytest.approx(176.0)


def test_e9_the_womens_floor_is_a_review_item_until_a_film_states_it(film):
    plan, _ = _plan(film, "women")
    plan = dict(plan, speakers=SPEAKERS)
    placed = _placed(0.25, women_s=30.0)                                          # women 12% of testimony
    j = J.Journal(film="women-partition")
    assert R.sound_lints(j, _event(plan), MIX, placed) == []                      # T1f: the engine did not lint 6.5
    assert not lints(j, "women-floor")                                            # nor journals it, for a film that states nothing
    stated = _event(plan, settings_stated={"women_floor": 0.30})
    out = R.sound_lints(J.Journal(film="women-stated"), stated, MIX, placed)
    assert any(o.startswith("women-floor") for o in out)
    ok = dict(stated, shortfalls=[dict(SF_WOMEN, stated=True)])
    jj = J.Journal(film="women-card")
    assert R.sound_lints(jj, ok, MIX, placed) == []
    assert lints(jj, "women-floor")[0]["severity"] == "review"


# --------------------------------------------------------------------------
# E11: archival lines from a source's own soundtrack (A26)
# --------------------------------------------------------------------------


ARCH_LINE = {"id": "A1", "kind": "testimony", "speaker": "sp-reel", "year": 2026, "archival_audio": True, "clip": "FX-REEL",
             "in_s": 1.0, "out_s": 2.5, "start_s": 17.9, "text": ARCH_TEXT, "source": "FX-REEL",
             "transcript_source": "fixture transcript (transcripts/fx-reel.txt)"}
ARCH_LT = {"id": "T3", "kind": "lower_third", "start_s": 17.9, "end_s": 19.4,
           "lines": ["Fixture reel, original narration", "Test reel, 2026", "Fixture reel, studio test folder  ·  original recording"]}


def _archival(film, line=None, lt=None, cue=None):
    def fn(p):
        p["cast"]["speakers"].append({"id": "sp-reel", "name": "Fixture reel, original narration", "side": "usa", "gender": "m"})
        p["parts"][1]["lines"].append(dict(ARCH_LINE, **(line or {})))
        p["parts"][1]["text"].append(dict(ARCH_LT, **(lt or {})))
        p["subtitle_source"].append(dict({"ref": "A1", "start_s": 17.9, "end_s": 19.4, "en": ARCH_TEXT}, **(cue or {})))
    _edit(film, fn)


def test_e11_an_archival_span_line_passes_its_lints(film):
    _archival(film)
    plan, j = _plan(film, "arch")
    for rule in ("archival-span", "archival-transcript", "archival-subtitles", "archival-double-sound", "archival-lower-third"):
        assert [e["status"] for e in lints(j, rule)] == ["pass"], rule
    assert lints(j, "archival-transcript")[0]["evidence"]["found"] == "verbatim without spaces"   # "speaksfor": a caption join
    v = {x["id"]: x for x in R.voice_lines(json.loads((film / "screenplay.json").read_text(encoding="utf-8")), film)}
    assert v["A1"]["dur"] == pytest.approx(1.5)                                   # out minus in: the voice-overlap lint sees it
    doc = R.sources_doc(plan, j, {})
    a1 = next(r for r in doc["readings"] if r["id"] == "A1")
    assert (a1["mark"], a1["credit"], a1["dur_s"], a1["clip"]) == ("ARCHIVE", "original recording", 1.5, "FX-REEL")
    rec = dict(plan["credits"])["Recordings"]
    assert rec and rec[0].startswith("Fixture reel, original narration: original recording")
    assert "Read by a computer voice. No recording of Fixture reel" not in " ".join(dict(plan["credits"]).get("Readings", []))


@pytest.mark.parametrize("change, rule", [
    ({"line": {"text": "Words the reel never said."}, "cue": {"en": "Words the reel never said."}}, "archival-transcript"),
    ({"cue": {"en": "The reel speaks, in its own words."}}, "archival-subtitles"),
    ({"lt": {"lines": ["Fixture reel", "Test reel, 2026", "Fixture reel  ·  read by a computer voice"]}}, "archival-lower-third"),
    ({"line": {"out_s": 99.0}}, "archival-span"),
    ({"lt": {"lines": ["Someone else", "Test reel, 2026", "Fixture reel, studio test folder  ·  original recording"]}},
     "archival-lower-third"),
    ({"lt": {"lines": ["Fixture reel, original narration", "Test reel, 2026", "National Library of Medicine  ·  original recording"]}},
     "archival-lower-third"),
    ({"line": {"in_s": 5.0, "out_s": 6.5}}, "archival-transcript"),         # the words are in the transcript, at 1 to 4 s
    ({"line": {"mark": "RECONSTRUCTED"}}, "archival-span"),
    ({"line": {"transcript_source": None}}, "archival-transcript"),
])
def test_e11_an_archival_line_is_refused_when_it_is_not_its_own_recording(film, change, rule):
    _archival(film, **change)
    with pytest.raises(R.Refused, match=rf"{rule} \(A1\)"):
        _plan(film, rule)


def test_e11_a_shot_never_plays_the_same_soundtrack_under_the_line(film):
    _archival(film, line={"start_s": 15.0, "in_s": 1.0, "out_s": 2.5}, lt={"start_s": 15.0, "end_s": 16.5},
              cue={"start_s": 15.0, "end_s": 16.5})
    _edit(film, lambda p: (_shot(p, "S6").update(asset="FX-REEL", in_s=0.5, out_s=3.5, native_fps=24),
                           p["parts"][1]["text"].remove(next(t for t in p["parts"][1]["text"] if t["id"] == "T2")),
                           p["subtitle_source"].remove(next(c for c in p["subtitle_source"] if c["ref"] == "T2"))))
    with pytest.raises(R.Refused, match=r"archival-double-sound \(A1\)"):
        _plan(film, "double")
    _edit(film, lambda p: _shot(p, "S6").update(sound={"mode": "mute", "reason": "the archival line A1 plays it"}))
    _plan(film, "muted")


def test_e11_the_mix_plays_the_span_at_its_own_dynamics_never_cleaned_or_judged(film):
    _archival(film)
    plan, j = _plan(film, "arch-mix")
    mix, placed = R.build_mix(plan, film, j)
    a1 = next(x for x in placed["lines"] if x["id"] == "A1")
    assert a1["kind"] == "archival" and a1["dur_s"] == pytest.approx(1.5, abs=0.001) and a1["cleaned"] is None
    assert a1["span"] == {"clip": "FX-REEL", "in_s": 1.0, "out_s": 2.5}
    evs = J.read(j.path)
    for rule in ("voice-clean", "voice-chop", "voice-beside", "narrator-consistency", "voice-peak-control"):
        assert not [e for e in evs if e.get("rule") == rule and e.get("unit") == "A1"], rule
    seg = mix[int(17.9 * 48000): int(19.4 * 48000)]
    assert abs(seg[0]) < 1e-3 and abs(seg[-1]) < 1e-3                             # 20 ms fades: the cut never clicks
    level = R._measure_line(seg)["input_i"]
    assert level == pytest.approx(R.ARCHIVAL_DIALOGUE_LUFS, abs=1.0)            # one static gain to the dialogue level
    mid = seg[int(0.3 * 48000): int(1.2 * 48000)]
    env = np.abs(mid).reshape(-1, 480).max(axis=1)
    assert env.max() / env.min() < 1.1                                            # a steady tone stays steady: no gate, no expander
    cached = list((film / "cache" / "spans").glob("fx-reel.*.wav"))
    assert len(cached) == 1 and R._read_wav(cached[0]).size == pytest.approx(1.5 * 48000, abs=480)


def test_e11_a_long_reel_is_trimmed_to_a_cached_span_before_conform(film, monkeypatch):
    _edit(film, lambda p: (_shot(p, "S6").update(asset="FX-REEL", in_s=3.0, out_s=6.0, native_fps=24),
                           p["parts"][1]["text"].remove(next(t for t in p["parts"][1]["text"] if t["id"] == "T2")),
                           p["subtitle_source"].remove(next(c for c in p["subtitle_source"] if c["ref"] == "T2"))))
    plain, _ = _plan(film, "reel-whole")
    assert "_span" not in next(s for s in plain["shots"] if s["id"] == "S6")
    monkeypatch.setattr(R, "LONG_REEL_BYTES", 1)                                 # every reel is "long" now
    plan, j = _plan(film, "reel-span")
    s6 = next(s for s in plan["shots"] if s["id"] == "S6")
    sp = s6["_span"]
    assert sp["offset_s"] == pytest.approx(2.0) and Path(sp["file"]).parent == film / "cache" / "spans"
    span_pr = R.probe_video(Path(sp["file"]))
    assert span_pr["duration_s"] == pytest.approx(5.0, abs=0.1)                  # the shot plus a second either side, not 8 s
    assert s6["_video"]["probe"]["duration_s"] == pytest.approx(7.0, abs=0.1)    # in reel time
    assert (s6["in_s"], s6["out_s"]) == (3.0, 6.0)                               # sources.json keeps the reel's own times
    a = R.VideoReader(next(s for s in plain["shots"] if s["id"] == "S6"), 0.5)
    b = R.VideoReader(s6, 0.5)
    try:
        for t in (0.5, 1.0, 2.75):
            assert np.array_equal(np.asarray(a.frame(t)), np.asarray(b.frame(t))), t   # lossless: the reel's own frames
    finally:
        a.close()
        b.close()
    again = R.cached_span(film, s6["_item"]["_path"], 3.0, 6.0, video=True, pad_s=R.SPAN_PAD_S)
    assert again["sha256"] == sp["sha256"] and len(list((film / "cache" / "spans").glob("*.mkv"))) == 1   # cut once


def test_e11_an_untimed_transcript_cannot_place_a_span(film):
    (film / "transcripts" / "fx-reel.txt").write_text("The reel speaks for itself, in its own words.\n", encoding="utf-8")
    _archival(film)
    with pytest.raises(R.Refused, match=r"archival-transcript \(A1\)"):
        _plan(film, "untimed")
    assert R.transcript_cues(film / "transcripts" / "fx-reel.txt") == []         # no cue times: no span can be placed in it


def test_e11_transcript_cues_read_nlm_vtt_and_srt(tmp_path):
    f = tmp_path / "t.vtt"
    f.write_text("WEBVTT\n\n00:01.000 --> 00:02.500 line:62%\nFirst words\nacross two lines\n\n"
                 "00:00:03,000 --> 00:00:04,000\n[Music] second\n", encoding="utf-8")
    assert R.transcript_cues(f) == [(1.0, 2.5, "First words across two lines"), (3.0, 4.0, "second")]
    assert R.transcript_window(R.transcript_cues(f), 0.5, 1.5) == "First words across two lines"


def test_e11_an_audio_only_clip_is_measured_too(film):
    from conftest import tone
    tone(film / "footage" / "fx-audio.wav", 3.0)
    _edit(film, lambda d: d["items"].append({"id": "FX-AUDIO", "file": "fx-audio.wav", "title": "Test tone, test fixture",
                                             "date": "2026", "archive": "studio test fixture", "licence": "CC0", "synthetic": True,
                                             "transcript_file": "transcripts/fx-reel.txt"}), "footage-ledger.json")
    _archival(film, line={"clip": "FX-AUDIO", "in_s": 1.0, "out_s": 4.0})
    with pytest.raises(R.Refused, match=r"archival-span \(A1\).*past the clip's end"):
        _plan(film, "audio-past-end")
    _edit(film, lambda p: next(l for l in p["parts"][1]["lines"] if l["id"] == "A1").update(out_s=2.5))
    _plan(film, "audio-in-range")


def test_e11_a_line_gain_never_lifts_an_archival_span_past_the_ceiling(film):
    _archival(film, line={"gain_db": 30.0})
    plan, j = _plan(film, "arch-gain")
    mix, placed = R.build_mix(plan, film, j)
    seg = mix[int(17.9 * 48000): int(19.4 * 48000)]
    assert R._measure_line(seg)["input_tp"] <= R.VOICE_TP + 0.2                   # never limited, so held back instead


def test_e11_a_cached_span_whose_bytes_changed_is_cut_again(film):
    src = film / "footage" / "fx-reel.mp4"
    first = R.cached_span(film, src, 1.0, 2.5, video=False)
    Path(first["file"]).write_bytes(b"RIFF" + b"\0" * 64)                       # exFAT ate it
    again = R.cached_span(film, src, 1.0, 2.5, video=False)
    assert again["file"] == first["file"] and R.sha256_file(Path(again["file"])) == first["sha256"]
    assert first["edges"] == R.edge_digest(src)



def test_e9_a_render_fills_the_card_after_the_mix_and_keys_it_filled(film, tmp_path):
    """--audio-only runs the pre-flight, the mix, the fill and the deferred segment key, and draws no frame."""
    _with_card_d(film, [SF_READ])
    summary = R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, audio_only=True)
    evs = J.read(summary["journal"])
    filled = [e for e in evs if e["kind"] == "decision" and e.get("unit") == "S7" and "filled from the cut" in e.get("what", "")]
    assert filled and "{" not in filled[0]["what"] and "percent of its running time" in filled[0]["what"]
    assert filled[0]["evidence"]["values"]["readings"]["floor"] == 0.2
    assert not [e for e in evs if e["kind"] == "error"]


def test_e3_a_flag_is_a_real_bool_never_1_or_0():
    rule = POL.imagery_rule({"imagery_rule": SHOW})[0]
    base_item = {"shows_bodies": False, "graphic_medical": False, "named_patient": False, "shows_violence": False}
    assert next(c for c in POL.asset_checks(base_item, rule) if c["rule"] == "content-flags")["ok"]
    for k, v in (("graphic_medical", 1), ("named_patient", 0), ("shows_violence", "false")):
        c = next(c for c in POL.asset_checks(dict(base_item, **{k: v}), rule) if c["rule"] == "content-flags")
        assert not c["ok"] and k in c["evidence"]["unstated"], (k, v)
    assert not POL.asset_checks(dict(base_item, shows_bodies=0), POL.imagery_rule({})[0] | {"declared": False})[0]["ok"]
    assert not POL.is_patient({"graphic_medical": 1}) and POL.is_patient({"graphic_medical": True})
    shown = POL.imagery_rule({"imagery_rule": dict(SHOW, show_bodies=True, statement="Bodies and disease are shown.")})[0]
    assert not POL.asset_checks(dict(base_item, shows_bodies=1), shown)[0]["ok"]        # stated true or false, as a bool
    assert POL.poster_problem(dict(base_item, graphic_medical=1, consent_basis="x"), rule)    # 1 is not a stated flag


def test_e3_a_hyphen_is_part_of_a_name():
    assert not POL.says_name("Jean-Paul Martin, 1975", "Paul") and not POL.says_name("Paul-Henri, 1975", "Paul")
    assert POL.says_name("Paul Martin, 1975", "Paul") and POL.says_name("Jean-Paul Martin", "Jean-Paul")
