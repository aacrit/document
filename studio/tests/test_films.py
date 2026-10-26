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
                                    "women_floor": 0.30, "ai_generated_share_max": 0.0, "fill_max_upscale": R.FILL_MAX_UPSCALE}
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


def _with_sf(film, shortfalls):
    """A56: the film declares these shortfalls; they are stated in the sources data, never on a card."""
    _edit(film, lambda p: p.update(shortfalls=shortfalls))


SF_READ = {"what": "readings", "measured": 0.16, "floor": 0.20}
SF_WOMEN = {"what": "women", "measured": 0.12, "floor": 0.30}
STATE_R = "The readings and recordings are about {readings_share:pct} of the film, under {readings_floor:fraction}."


def test_e9_a56_a_shortfall_is_stated_in_the_sources_data_never_on_a_card(film):
    _with_sf(film, [SF_READ, SF_WOMEN])
    plan, j = _plan(film, "sf-data")
    assert [e["status"] for e in lints(j, "shortfall-stated")] == ["pass", "pass"]
    assert all(sf["stated"] for sf in plan["shortfalls"])
    assert [sf["statement"] for sf in plan["shortfalls"]] == [POL.SHORTFALL_STATEMENT["readings"],
                                                             POL.SHORTFALL_STATEMENT["women"]]
    _edit(film, lambda p: (_shot(p, "S7").update(text=CARD_D), p.update(shortfalls=[dict(SF_READ, stated_on="S7")])))
    with pytest.raises(R.Refused, match=r"shortfall-stated \(shortfall:readings\).*stated in the sources data, never in the frame"):
        _plan(film, "sf-card")
    _edit(film, lambda p: (_shot(p, "S7").update(text=["A plain statement."]),
                           p.update(shortfalls=[dict(SF_READ, stated_on="S5")])))
    plan, j = _plan(film, "sf-stale")                                              # a stale stated_on: a warning
    assert lints(j, "shortfall-stated-on")[0]["severity"] == "warn"
    _with_sf(film, [dict(SF_READ, floor=0.30)])
    with pytest.raises(R.Refused, match=r"is not the film's readings_floor"):
        _plan(film, "wrong-floor")
    _with_sf(film, [dict(SF_READ, measured="about a sixth")])
    with pytest.raises(R.Refused, match=r"measured \(advisory\) must be a share"):
        _plan(film, "measured-not-a-share")
    _with_sf(film, [{k: v for k, v in SF_READ.items() if k != "measured"}])
    _plan(film, "measured-advisory")                                               # measured may be left out: the cut decides


@pytest.mark.parametrize("words", ["thirty", "two sixths", "30\uff05", "0.30", "one sixth", "twenty-one percent", "a fifth",
                                   "half of them", "per cent", "\u00bd", "a dozen voices", "\u0663\u0660 percent"])
def test_e9_a_number_outside_a_placeholder_is_refused(film, words):
    _with_sf(film, [dict(SF_READ, statement="The readings are {readings_share:pct} of the film, " + words + ".")])
    with pytest.raises(R.Refused, match=r"shortfall-stated \(shortfall:readings\).*numbers outside a placeholder"):
        _plan(film, "stray")


def test_e9_the_statements_own_share_is_required_and_no_placeholder_is_drawn(film):
    _with_sf(film, [dict(SF_WOMEN, statement="Women are under {women_floor:fraction}.")])
    with pytest.raises(R.Refused, match=r"shortfall-stated \(shortfall:women\).*no \{<what>_share\} for women"):
        _plan(film, "no-women-share")
    _with_sf(film, [dict(SF_READ, statement="The readings are {readings_share:pct}; women {women_share:pct}.")])
    with pytest.raises(R.Refused, match=r"placeholders for women"):
        _plan(film, "undeclared-placeholder")
    _with_sf(film, [dict(SF_READ, statement="The readings are {readings_count} of {readings_share:pct}.")])
    with pytest.raises(R.Refused, match=r"unknown placeholders"):
        _plan(film, "unknown-placeholder")
    _with_sf(film, [SF_READ])
    _edit(film, lambda p: p["parts"][1]["text"].append({"id": "T9", "kind": "overlay", "start_s": 15.5, "end_s": 16.0,
                                                        "lines": ["{readings_share:pct}"]}))
    with pytest.raises(R.Refused, match=r"shortfall-card \(text:T9\)"):            # it would be drawn as written
        _plan(film, "placeholder-elsewhere")


def test_e9_a_subtitle_never_carries_a_placeholder(film):
    _with_sf(film, [SF_READ])
    _edit(film, lambda p: p["subtitle_source"].append({"ref": "S7", "start_s": 17.75, "end_s": 20.2,
                                                       "en": "Readings are {readings_share:pct} of the film."}))
    with pytest.raises(R.Refused, match=r"shortfall-card \(subtitle:S7\)"):
        _plan(film, "subtitle-placeholder")


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
        "The readings and recordings in this film are about 15 percent of its running time, under a fifth the grammar "
        "asks, and a woman's voice carries only 11 percent of them. The film says so rather than invent.")


def test_e9_the_statement_is_filled_from_the_cut_and_sources_json_carries_it(film):
    _with_sf(film, [dict(SF_READ, statement=STATE_R), SF_WOMEN])
    plan, j = _plan(film, "fill")
    plan = _event(plan, speakers=SPEAKERS)
    values = R.shortfall_values(plan, _placed(0.135, women_s=30.0))
    assert values["women"]["share"] == pytest.approx(30 / 135, abs=1e-3) and values["readings"]["floor"] == 0.2
    changed = R.fill_cards(plan, values, j)
    assert changed == []                                                           # no card changes: nothing in the frame
    sf = {x["what"]: x for x in plan["shortfalls"]}
    assert sf["readings"]["filled"] == "The readings and recordings are about 13 percent of the film, under a fifth."
    assert "22 percent" in sf["women"]["filled"] and "{" not in sf["women"]["filled"]
    assert any("stated in the sources data" in e.get("what", "") for e in J.read(j.path) if e["kind"] == "decision")
    doc = R.sources_doc(plan, j, {})
    assert next(x for x in doc["shortfalls"] if x["what"] == "readings")["filled"] == sf["readings"]["filled"]
    assert doc["card_fills"]["values"] == values
    assert next(x for x in doc["shortfalls"] if x["what"] == "readings")["measured_cut"] == values["readings"]["share"]


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
    _with_sf(film, [SF_READ])
    plan, _ = _plan(film, "sf-plan")
    event = _event(plan)
    j = J.Journal(film="sf-stated")
    assert R.sound_lints(j, event, MIX, _placed(0.10)) == []                     # whatever the cut measures, the card prints it
    rf = lints(j, "readings-floor")[0]
    assert rf["status"] == "review" and rf["severity"] == "review" and "stated in the sources data" in rf["evidence"]["result"]
    out = R.sound_lints(J.Journal(film="sf-unstated"), _event(plan, shortfalls=[]), MIX, _placed(0.16))
    assert any(o.startswith("readings-floor") and "'min': 0.2" in o for o in out)
    out = R.sound_lints(J.Journal(film="sf-unstated-card"), _event(plan, shortfalls=[dict(SF_READ, stated=False)]), MIX,
                        _placed(0.16))
    assert any("not stated in the sources data" in o for o in out)


def test_e9_a_film_that_meets_its_floor_is_refused_a_shortfall(film):
    _with_sf(film, [SF_READ])
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
             "in_s": 1.0, "out_s": 2.5, "start_s": 17.5, "text": ARCH_TEXT, "source": "FX-REEL",
             "transcript_source": "fixture transcript (transcripts/fx-reel.txt)"}
ARCH_LT = {"id": "T3", "kind": "lower_third", "start_s": 17.5, "end_s": 19.0,
           "lines": ["Fixture reel, original narration", "Test reel, 2026"]}


def _archival(film, line=None, lt=None, cue=None):
    def fn(p):
        p["cast"]["speakers"].append({"id": "sp-reel", "name": "Fixture reel, original narration", "side": "usa", "gender": "m"})
        p["parts"][1]["lines"].append(dict(ARCH_LINE, **(line or {})))
        p["parts"][1]["text"].append(dict(ARCH_LT, **(lt or {})))
        p["subtitle_source"].append(dict({"ref": "A1", "start_s": 17.5, "end_s": 19.0, "en": ARCH_TEXT}, **(cue or {})))
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
    assert rec and rec[0].startswith("Fixture reel, original narration, ")
    assert "Read by a computer voice. No recording of Fixture reel" not in " ".join(dict(plan["credits"]).get("Readings", []))


@pytest.mark.parametrize("change, rule", [
    ({"line": {"text": "Words the reel never said."}, "cue": {"en": "Words the reel never said."}}, "archival-transcript"),
    ({"cue": {"en": "The reel speaks, in its own words."}}, "archival-subtitles"),
    ({"lt": {"lines": ["Fixture reel", "Test reel, 2026", "Fixture reel  ·  read by a computer voice"]}}, "archival-lower-third"),
    ({"line": {"out_s": 99.0}}, "archival-span"),
    ({"lt": {"lines": ["Someone else", "Test reel, 2026"]}},
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
    # A33: the line sits on its own picture (0.25 s into the shot, 0.25 s into the source) and the shot says whether the
    # speaker's mouth is on screen
    _edit(film, lambda p: (_shot(p, "S6").update(asset="FX-REEL", in_s=0.75, out_s=3.75, native_fps=24, talking_head=False),
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
    seg = mix[int(17.5 * 48000): int(19.0 * 48000)]
    assert abs(seg[0]) < 1e-3 and abs(seg[-1]) < 1e-3                             # 20 ms fades: the cut never clicks
    level = R._measure_line(seg)["input_i"]
    assert level == pytest.approx(R.ARCHIVAL_DIALOGUE_LUFS, abs=1.0)            # one static gain to the dialogue level
    mid = seg[int(0.3 * 48000): int(1.2 * 48000)]
    env = np.abs(mid).reshape(-1, 480).max(axis=1)
    assert env.max() / env.min() < 1.1                                            # a steady tone stays steady: no gate, no expander
    cached = list((film / "cache" / "spans").glob("fx-reel.*.wav"))
    # A36: the span is cut with EDGE_PAD_S of the reel either side (from 0 here), so its edges can carry the reel's sound
    want = (2.5 + R.EDGE_PAD_S - max(0.0, 1.0 - R.EDGE_PAD_S)) * 48000
    assert len(cached) == 1 and R._read_wav(cached[0]).size == pytest.approx(want, abs=480)


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
    import soundfile as sf
    t = np.arange(3 * 48000) / 48000                     # a phrase from 1.15 to 2.25 s, so 1.0 to 2.5 s is on its edges (A33)
    sf.write(str(film / "footage" / "fx-audio.wav"), (0.2 * np.sin(2 * np.pi * 440 * t) * ((t >= 1.15) & (t < 2.25))).astype("float32"),
             48000)
    _edit(film, lambda d: d["items"].append({"id": "FX-AUDIO", "file": "fx-audio.wav", "title": "Test tone, test fixture",
                                             "date": "2026", "archive": "studio test fixture", "licence": "CC0", "synthetic": True,
                                             "test_fixture": True, "transcript_file": "transcripts/fx-reel.txt"}), "footage-ledger.json")
    _archival(film, line={"clip": "FX-AUDIO", "in_s": 1.0, "out_s": 4.0})
    with pytest.raises(R.Refused, match=r"archival-span \(A1\).*past the clip's end"):
        _plan(film, "audio-past-end")
    _edit(film, lambda p: next(l for l in p["parts"][1]["lines"] if l["id"] == "A1").update(out_s=2.5))
    _plan(film, "audio-in-range")


def test_e11_a_line_gain_never_lifts_an_archival_span_past_the_ceiling(film):
    _archival(film, line={"gain_db": 30.0})
    plan, j = _plan(film, "arch-gain")
    mix, placed = R.build_mix(plan, film, j)
    seg = mix[int(17.5 * 48000): int(19.0 * 48000)]
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
    _with_sf(film, [SF_READ])
    summary = R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, audio_only=True)
    evs = J.read(summary["journal"])
    filled = [e for e in evs if e["kind"] == "decision" and e.get("unit") == "shortfall:readings"
              and "stated in the sources data" in e.get("what", "")]
    assert filled and "{" not in filled[0]["what"] and "percent of the film's running time" in filled[0]["what"]
    assert filled[0]["evidence"]["values"]["floor"] == 0.2
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



# --------------------------------------------------------------------------
# Re-review of f42cecd: the reviewer's probes (scratchpad probe_tpl.py), each a test
# --------------------------------------------------------------------------


PROBE_STRAYS = [
    "Readings are about one sixth of the film, under the fifth the grammar asks.",
    "Women carry 30 percent of the testimony, only that.",
    "Readings fall under the fifth the grammar asks Women 30 percent of testimony",
    "Readings fall under the rule and still make up a fifth of the film.",
    "Women fall short of the rule and carry 30 percent of the testimony",
    "Readings are never under the fifth the grammar asks.",
    "Readings sit above rather than under the fifth the grammar asks.",
    "Women carry only thirty percent of the testimony.",
    "Readings fall short at forty per cent.",
    "Women carry only 30％ of the testimony.",
    "Women carry only a 30-percent share of testimony.",
    "Women carry only 0.30 of the testimony.",
    "Readings fall short: one in five words? no, three in ten.",
    "Readings are only two sixths of the film.",
    "Women are short of the rule, under three fifths the grammar asks.",
    "Readings fall short at 12 percent.",
    "Silence falls under the 30 percent floor.",
    "Under the rule, women carry 30 percent.",
    "Readings fall under the 20.0 percent floor.",
    "Women fall under the rule, 30 percent of the testimony",
    "Women carry 30% under the rule.",
    "Women: under 30 percent of testimony.",
    "{readings_share} of readings, under a fourth the grammar asks",
    "{readings_share} of readings, under a twentieth",
    "{women_share} women, a hundredth of what it should be",
    "{women_share} women, twice fewer than men",
    "{women_share} women, under three-tenths",
    "{women_share} women, under ³⁄₁₀",
    "{women_share} women, under Ⅲ tenths",
    "{women_share} women, under thirty​percent",
    "{women_share} women, under thi​rty percent",
    "{women_share} women, under ٣٠ percent",
    "{women_share} women, under XXX percent",
    "{women_share} women, a majority of men",
    "{women_share} women, the most of any year",
    "{women_share} women, once in the film",
    "{women_share} women, the ninetieth part",
    "{women_share} women, under 3⁄4",
    # final review (probe3): a prefix joined by a hyphen no longer hides the word
    "{women_share} women, a less-than-half share",
    "{women_share} women, a near-half of the testimony",
    "{readings_share} readings, a sub-fifth of the film",
    "{readings_share} readings, an under-tenth share",
    "{women_share} women, a non-majority",
    "{women_share} women, in the single digits",
    "{women_share} women, the bottom decile",
    "{women_share} women, the lowest quintile",
    "{women_share} women, a lower quartile",
    "{women_share} women, the tenth percentile",
    "{women_share} women, a handful of voices",
    "{women_share} women, a lone woman among men",
]


@pytest.mark.parametrize("text", PROBE_STRAYS)
def test_review_every_probe_is_refused(text):
    probs, info = POL.template_problems(text, {"readings", "women"}, needs_share=False)
    assert probs and info["stray"], text


def test_review_a_share_under_its_floor_never_prints_as_the_floor():
    for v in (0.195, 0.1951, 0.196, 0.1996, 0.1999):
        assert POL.format_share(v, "pct", 0.2) == "19 percent" and POL.format_share(v, "words", 0.2) == "nineteen percent"
        assert POL.format_share(v, "fraction", 0.2) == "19 percent"                 # never "a fifth", the floor's fraction
    for v in (0.2951, 0.2999):
        assert POL.format_share(v, "pct", 0.3) == "29 percent"
    assert POL.format_share(0.2049, "pct") == "20 percent"                          # no floor given: rounded to nearest
    assert POL.format_share(0.0995, "fraction", 0.2) == "a tenth"                   # a fraction under the floor's may print
    assert POL.format_share(0.004, "pct", 0.2) == "under 1 percent" and POL.format_share(0.004, "words", 0.2) == "under one percent"
    assert POL.format_share(0.0, "pct", 0.2) == "0 percent"
    assert POL.fill_placeholders("about {readings_share:pct}, under {readings_floor:fraction} the grammar asks",
                                 {"readings": {"share": 0.1996, "floor": 0.2}}) == "about 19 percent, under a fifth the grammar asks"
    assert POL.fill_placeholders("about {readings_share:fraction}, under {readings_floor:fraction}",
                                 {"readings": {"share": 0.197, "floor": 0.2}}) == "about 19 percent, under a fifth"


def test_review_the_fill_refuses_a_share_printed_as_its_floor(monkeypatch):
    monkeypatch.setattr(POL, "format_share", lambda v, fmt, floor=None: "20 percent")      # a formatter that rounds up
    with pytest.raises(POL.FillError, match="the floor itself"):
        POL.fill_placeholders("{readings_share:pct}", {"readings": {"share": 0.199, "floor": 0.2}})


def test_review_womens_share_is_refused_when_any_gender_is_unstated(film):
    _with_sf(film, [SF_READ, dict(SF_WOMEN, statement="Women carry {women_share:pct} of the readings.")])
    plan, j = _plan(film, "unknown-gender")
    plan = _event(plan, speakers={"sp-m": {"name": "M", "side": "usa"}})          # no gender stated for sp-m
    values = R.shortfall_values(plan, _placed(0.135, women_s=30.0))
    assert values["women"]["unknown_s"] > 0
    with pytest.raises(R.Refused, match=r"shortfall-fill.*no stated gender"):
        R.fill_cards(plan, values, j)
    assert [e["status"] for e in lints(j, "shortfall-fill")][-1] == "fail"


def test_review_a56_filling_the_statements_never_changes_a_shot_key(film):
    _with_sf(film, [SF_READ])
    plan_a, j = _plan(film, "key-a")
    plan_b, _ = _plan(film, "key-b")
    assert R.plan_has_placeholders(plan_a)                                         # the statement's
    va = {"readings": {"share": 0.11, "floor": 0.2}, "voiceless": {"share": 0.5, "floor": 0.1},
          "women": {"share": 0.0, "floor": 0.3, "unknown_s": 0}}
    vb = dict(va, readings={"share": 0.12, "floor": 0.2})
    R.fill_cards(plan_a, va, j)
    R.fill_cards(plan_b, vb, j)
    n = len(plan_a["shots"])
    assert [R.shot_key(plan_a, i, {}, None) for i in range(n)] == [R.shot_key(plan_b, i, {}, None) for i in range(n)]


def test_review_card_fills_only_when_something_was_filled(film):
    plan, j = _plan(film, "no-fill")
    assert R.fill_cards(plan, R.shortfall_values(plan, {"lines": []}), j) == [] and "card_fills" not in plan
    assert "card_fills" not in R.sources_doc(plan, j, {})


@pytest.mark.parametrize("element", [
    {"id": "T9", "kind": "lower_third", "start_s": 18.0, "end_s": 19.0, "lines": ["Fixture", "{readings_share:pct}"]},
    {"id": "T9", "kind": "overlay", "start_s": 18.0, "end_s": 19.0, "lines": ["{readings_share:pct}"]},
])
def test_review_a56_no_placeholder_anywhere_in_the_frame(film, element):
    _with_sf(film, [SF_READ])
    _edit(film, lambda p: p["parts"][1]["text"].append(element))
    with pytest.raises(R.Refused, match=r"shortfall-card \(text:T9\).*printed as written"):
        _plan(film, "placeholder-near-card")


def test_review_a_null_time_is_a_lint_failure_not_a_crash(film):
    _with_sf(film, [SF_READ])
    _edit(film, lambda p: p["subtitle_source"].append({"ref": "S7", "start_s": None, "end_s": 20.0,
                                                       "en": "Readings {readings_share:pct}."}))
    with pytest.raises(R.Refused, match=r"shortfall-card \(subtitle:S7\).*must be numbers"):
        _plan(film, "null-time")


def _master(out: Path, frames: int) -> Path:
    import subprocess
    out.mkdir(parents=True, exist_ok=True)
    m = out / "master.mp4"
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x36:r=24:d={frames / 24}",
                    "-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(m)], check=True)
    return m


def test_review_sources_only_refills_only_from_this_masters_full_render(film, tmp_path):
    _with_sf(film, [SF_READ])
    plan, _ = _plan(film, "so-plan")
    out = tmp_path / "out"
    master = _master(out, plan["frames"])
    values = {"readings": {"share": 0.11, "floor": 0.2}, "voiceless": {"share": 0.5, "floor": 0.1},
              "women": {"share": 0.0, "floor": 0.3, "unknown_s": 0}}
    good = {"master_sha256": R.sha256_file(master), "card_fills": {"values": values, "texts": {}}}

    def prev(doc):
        (out / "sources.json").write_text(json.dumps(doc), encoding="utf-8")

    prev(good)
    R.sources_only(film, out)
    doc = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert "are 11 percent" in next(x for x in doc["shortfalls"] if x["what"] == "readings")["filled"]
    stale = {"master_sha256": R.sha256_file(master)}
    for bad, why in ((dict(good, master_sha256="0" * 64), "another master"), (dict(good, partial=True), "partial render"),
                     (dict(good, card_fills={"values": {"readings": {"share": "x"}}}), "malformed"),
                     (dict(good, card_fills="x"), "malformed"), (stale, "no card_fills")):
        prev(bad)
        with pytest.raises(R.Refused, match=why):
            R.sources_only(film, out)


def test_review_telecined_is_a_real_bool(film):
    _edit(film, lambda d: next(x for x in d["items"] if x["id"] == "FX-TESTSRC").update(telecined=0), "footage-ledger.json")
    with pytest.raises(R.Refused, match=r"telecine-declared \(S6\)"):
        _plan(film, "telecined-0")


def test_final_a_share_just_under_its_floor_is_not_lost_to_float_error():
    assert POL.format_share(0.29, "pct", 0.30) == "29 percent" and POL.format_share(0.29, "words", 0.30) == "twenty-nine percent"
    assert POL.fill_placeholders("{women_share:pct}", {"women": {"share": 0.29, "floor": 0.30, "unknown_s": 0}}) == "29 percent"
    import math
    for k in range(1, 3000):                                                    # every share to a hundredth of a point
        v = k / 10000
        for fl in (0.1, 0.2, 0.3):
            if v < fl:
                assert POL.format_share(v, "pct", fl) in (f"{math.floor(round(v * 100, 9))} percent", "under 1 percent"), (v, fl)


def test_final_card_values_carry_womens_unknown_seconds():
    good = {"readings": {"share": 0.1, "floor": 0.2}, "voiceless": {"share": 0.5, "floor": 0.1},
            "women": {"share": 0.1, "floor": 0.3, "unknown_s": 0}}
    assert R.card_values_problems(good) == []
    no_unknown = dict(good, women={"share": 0.1, "floor": 0.3})
    assert any("unknown_s" in p for p in R.card_values_problems(no_unknown))


def test_final_the_captions_check_the_fills_provenance(film, tmp_path):
    from studio.engine import captions as C
    _with_sf(film, [SF_READ])
    plan, _ = _plan(film, "cap-prov")
    out = tmp_path / "out"
    master = _master(out, plan["frames"])
    # the plan refuses a placeholder in a subtitle (A56); the captions' own check still guards one written in later
    _edit(film, lambda p: p["subtitle_source"].append({"ref": "S7", "start_s": 17.75, "end_s": 20.2, "en": STATE_R}))
    shutil.copy(film / "screenplay.json", out / "screenplay.json")
    values = {"readings": {"share": 0.11, "floor": 0.2}, "voiceless": {"share": 0.5, "floor": 0.1},
              "women": {"share": 0.0, "floor": 0.3, "unknown_s": 0}}
    good = {"master": "master.mp4", "master_sha256": R.sha256_file(master), "card_fills": {"values": values, "texts": {}}}
    (out / "sources.json").write_text(json.dumps(good), encoding="utf-8")
    assert "11 percent" in " ".join(C.captions(out).split())                      # the cue wraps between 11 and percent
    for bad, why in ((dict(good, master_sha256="0" * 64), "another master"), (dict(good, partial=True), "partial render"),
                     (dict(good, card_fills={"values": {"women": {}}}), "malformed")):
        (out / "sources.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(C.CaptionError, match=why):
            C.captions(out)


def test_e14_an_archival_span_is_placed_again_under_the_derived_ceiling(film, monkeypatch):
    """A15 refined (E14): pass 2 holds an archival span's one static gain to
    the derived ceiling (never a limiter), and the line's record says so."""
    _archival(film, line={"gain_db": 30.0})
    plan, j1 = _plan(film, "e14-span-1")
    _, placed1 = R.build_mix(plan, film, j1)
    first = next(ln for ln in placed1["lines"] if ln["id"] == "A1")
    monkeypatch.setattr(R, "_master_overreach", lambda mix, tp, work: (["forced by the test"], None))
    monkeypatch.setattr(R, "derived_voice_ceiling", lambda lift: (-6.5, -6.5, None))
    plan, j = _plan(film, "e14-span")
    mix, placed = R.build_mix(plan, film, j)
    line = next(ln for ln in placed["lines"] if ln["id"] == "A1")
    assert line["kind"] == "archival" and line["voice_ceiling_dbtp"] == -6.5
    assert line["static_gain_db"] == pytest.approx(first["static_gain_db"] - (R.VOICE_TP + 6.5), abs=0.02)
    dec = [e for e in J.read(j.path) if e["kind"] == "decision" and e.get("unit") == "voice-ceiling"][0]
    ch = next(c for c in dec["evidence"]["changes"] if c["id"] == "A1")
    assert ch["kind"] == "archival" and ch["final_static_gain_db"] < ch["pass1_static_gain_db"]
    seg = mix[int(17.5 * 48000): int(19.0 * 48000)]
    assert R._measure_line(seg)["input_tp"] <= -6.5 + 0.2                    # never limited, so held back instead
    assert all(e["unit"] != "A1" for e in lints(j, "voice-peak-control"))      # an archival span is never peak-controlled


# --------------------------------------------------------------------------
# E15: a source that names its speakers on screen (A26 refined); a filled card is drawn whole
# --------------------------------------------------------------------------

REEL_NAME = "Fixture reel, original narration"


def _on(name, in_s=0.5, out_s=3.0):
    """A speakers_on_screen entry: the name and the clip-time span the picture shows it."""
    return {"name": name, "in_s": in_s, "out_s": out_s}


def _no_lower_third(film):
    _edit(film, lambda p: p["parts"][1]["text"].remove(next(t for t in p["parts"][1]["text"] if t["id"] == "T3")))


def _reel_names(film, **item):
    _edit(film, lambda d: next(x for x in d["items"] if x["id"] == "FX-REEL").update(**item), "footage-ledger.json")


def test_e15_an_archival_line_without_a_lower_third_is_refused_unless_its_source_names_the_speaker(film):
    _archival(film)
    _no_lower_third(film)
    with pytest.raises(R.Refused, match=r"archival-lower-third \(A1\)"):
        _plan(film, "named-none")
    _reel_names(film, speakers_on_screen=[_on(REEL_NAME)])                  # listed, but nothing declares the allowance
    with pytest.raises(R.Refused, match=r"archival-lower-third \(A1\)"):
        _plan(film, "named-undeclared")


@pytest.mark.parametrize("declare", ["screenplay", "ledger"])
def test_e15_a_source_that_names_its_speaker_on_screen_needs_no_lower_third(film, declare):
    _archival(film)
    _no_lower_third(film)
    _reel_names(film, speakers_on_screen=[_on("  fixture reel,  ORIGINAL narration ")], **({"names_its_speakers": True}
                                                                                       if declare == "ledger" else {}))
    if declare == "screenplay":
        _edit(film, lambda p: p.update(names_its_speakers=["FX-REEL"]))
    plan, j = _plan(film, f"named-{declare}")
    for rule in ("archival-lower-third", "archival-named-on-screen", "archival-named-elsewhere"):
        assert [e["status"] for e in lints(j, rule)] == ["pass"], rule
    assert lints(j, "archival-lower-third")[0]["evidence"]["named_on_screen_by_the_source"] is True
    # (b): still named where the record names every voice
    assert any(r["id"] == "A1" and r["name"] == REEL_NAME for r in R.sources_doc(plan, j, {})["readings"])
    assert dict(plan["credits"])["Recordings"][0].startswith(f"{REEL_NAME}, ")


def test_e15_the_ledger_must_list_the_speaker_the_source_names(film):
    _archival(film)
    _no_lower_third(film)
    _edit(film, lambda p: p.update(names_its_speakers=["FX-REEL"]))
    _reel_names(film, speakers_on_screen=[_on("Someone else")])
    with pytest.raises(R.Refused, match=r"archival-named-on-screen \(A1\)"):
        _plan(film, "named-wrong")
    _reel_names(film, speakers_on_screen=[_on(REEL_NAME, 2.6, 4.0)])        # named on screen, but not while the line plays
    with pytest.raises(R.Refused, match=r"archival-named-on-screen \(A1\)"):
        _plan(film, "named-elsewhen")
    _reel_names(film, speakers_on_screen=[REEL_NAME])                       # a name with no span
    with pytest.raises(R.Refused, match=r"archival-named-on-screen \(A1\)"):
        _plan(film, "named-no-span")
    for bad in (_on(REEL_NAME, -1.0, 3.0), _on(REEL_NAME, 2.0, 2.0), _on(REEL_NAME, 0.5, 999.0),
                {"name": REEL_NAME, "in_s": True, "out_s": 3.0}):
        _reel_names(film, speakers_on_screen=[bad])                          # 0 <= in_s < out_s <= the clip's length
        with pytest.raises(R.Refused, match=r"archival-named-on-screen \(A1\)"):
            _plan(film, "named-bad-span")
    _reel_names(film, speakers_on_screen=None)
    with pytest.raises(R.Refused, match=r"archival-named-on-screen \(A1\)"):
        _plan(film, "named-missing")


def test_e15_a_speaker_named_only_on_screen_must_still_be_in_the_credits(film, monkeypatch):
    _archival(film)
    _no_lower_third(film)
    _edit(film, lambda p: p.update(names_its_speakers=["FX-REEL"]))
    _reel_names(film, speakers_on_screen=[_on(REEL_NAME)])
    real = R.credits_blocks
    monkeypatch.setattr(R, "credits_blocks", lambda plan: [(h, ln) for h, ln in real(plan) if h != "Recordings"])
    with pytest.raises(R.Refused, match=r"archival-named-elsewhere \(A1\)"):
        _plan(film, "named-uncredited")


def test_e15_names_its_speakers_lists_ledger_clips(film):
    _edit(film, lambda p: p.update(names_its_speakers=["FX-NOWHERE"]))
    with pytest.raises(R.Refused, match=r"names-its-speakers"):
        _plan(film, "named-unknown")


def test_e15_two_speakers_from_one_clip_are_both_credited(film):
    _archival(film)
    _edit(film, lambda p: (p["cast"]["speakers"].append({"id": "sp-reel-2", "name": "Second voice", "side": "usa", "gender": "f"}),
                           p["parts"][1]["lines"].append(dict(ARCH_LINE, id="A2", speaker="sp-reel-2", start_s=24.0)),
                           p["subtitle_source"].append({"ref": "A2", "start_s": 24.0, "end_s": 25.5, "en": ARCH_TEXT}),
                           p.update(names_its_speakers=["FX-REEL"])))
    _reel_names(film, speakers_on_screen=[_on("Second voice")])
    plan, _ = _plan(film, "two-voices")
    rec = dict(plan["credits"])["Recordings"]
    heads = [n for n in (REEL_NAME, "Second voice") if any(r.startswith(n + ",") for r in rec)]
    assert heads == [REEL_NAME, "Second voice"]                                 # one clip, two voices, two credits
    assert not any("original recording" in r for r in rec)                       # A56: the note is sources data


def test_e15_a_filled_card_is_drawn_whole_or_refused(film, monkeypatch):
    """A56: no card carries a placeholder past the plan, but the post-fill layout check still guards a filled card."""
    plan, j = _plan(film, "fill-drawn")
    s7 = next(s for s in plan["shots"] if s["id"] == "S7")
    s7["text"] = ["The fixture's statement card.", "About 13 percent of it."]
    plan["card_fills"] = {"values": {}, "texts": {"S7": s7["text"]}}
    assert R.card_fill_lints(j, plan) == []
    assert [e["status"] for e in lints(j, "card-fills-drawn")] == ["pass"]
    real = R.M.card_layout
    monkeypatch.setattr(R.M, "card_layout", lambda *a, **k: dict(real(*a, **k), elements=real(*a, **k)["elements"][:1]))
    out = R.card_fill_lints(J.Journal(film="fill-cut"), plan)
    assert out and out[0].startswith("card-fills-drawn (S7)")


@pytest.mark.parametrize("drop", ["in_s", "out_s"])
def test_e15_an_archival_line_with_no_span_is_refused_even_when_its_source_names_the_speaker(film, drop):
    _archival(film)
    _no_lower_third(film)
    _edit(film, lambda p: (p.update(names_its_speakers=["FX-REEL"]),
                           next(x for x in p["parts"][1]["lines"] if x["id"] == "A1").pop(drop)))
    _reel_names(film, speakers_on_screen=[_on(REEL_NAME)])
    with pytest.raises(R.Refused, match=r"archival-span \(A1\).*archival-named-on-screen \(A1\)"):
        _plan(film, f"named-no-{drop}")


# ---- A3 refined: the unsigned apart (a women's-share card with testimony of unstated gender) ----------------------------

def test_a3_refined_the_unsigned_are_measured_apart_as_seconds_and_as_voices(film):
    plan, _ = _plan(film, "unsigned-values")
    plan = _event(plan, speakers={"sp-m": {"name": "M", "side": "usa"}, "sp-f": {"name": "F", "side": "uk", "gender": "f"}})
    values = R.shortfall_values(plan, _placed(0.135, women_s=30.0))
    w = values["women"]
    assert w["unknown_s"] > 0 and 0 < w["unsigned_share"] < 1
    assert w["speakers"] == {"all": 2, "f": 1, "m": 0, "unsigned": 1}
    assert R.card_values_problems(values) == []


def test_a3_refined_a_card_that_prints_the_unsigned_apart_fills(film):
    _with_sf(film, [dict(SF_WOMEN, statement="Of {women_speakers} voices in this film, {women_speakers_f} is a "
                                             "woman, {women_speakers_m} are men, {women_speakers_unsigned} are unsigned.")])
    plan, j = _plan(film, "unsigned-card")
    assert [e["status"] for e in lints(j, "shortfall-stated")] == ["pass"]
    plan = _event(plan, speakers={"sp-m": {"name": "M", "side": "usa"}, "sp-f": {"name": "F", "side": "uk", "gender": "f"}})
    values = R.shortfall_values(plan, _placed(0.135, women_s=30.0))
    R.fill_cards(plan, values, j)
    assert plan["shortfalls"][0]["filled"] == "Of 2 voices in this film, 1 is a woman, 0 are men, 1 are unsigned."
    assert lints(j, "shortfall-fill")[-1]["status"] == "pass"


def test_a3_refined_womens_share_beside_the_unsigned_share_fills_and_alone_refuses():
    vals = {"women": {"share": 0.04, "floor": 0.3, "unknown_s": 60.0, "unsigned_share": 0.12,
                      "speakers": {"all": 21, "f": 1, "m": 18, "unsigned": 2}}}
    assert POL.fill_placeholders("a woman {women_share:pct}, unsigned {women_unsigned_share:pct}", vals) == \
        "a woman 4 percent, unsigned 12 percent"
    assert POL.fill_placeholders("{women_speakers:words} voices, {women_speakers_unsigned:words} unsigned", vals) == \
        "twenty-one voices, two unsigned"
    with pytest.raises(POL.FillError, match="no stated gender"):
        POL.fill_placeholders("a woman's voice carries {women_share:pct}", vals)               # the known share alone
    with pytest.raises(POL.FillError, match="women_speakers_unsigned"):
        POL.fill_placeholders("{women_speakers_f} is a woman, {women_speakers_m} are men", vals)   # counts without the unsigned
    with pytest.raises(POL.FillError, match="women's shortfall only"):
        POL.fill_placeholders("{readings_unsigned_share}", {"readings": {"share": 0.1, "floor": 0.2, "unsigned_share": 0.1}})
    # no unsigned testimony: the known share prints alone, as before
    assert POL.fill_placeholders("{women_share:pct}", {"women": {"share": 0.29, "floor": 0.30, "unknown_s": 0}}) == "29 percent"


def test_a3_refined_the_card_template_accepts_the_counts_and_still_refuses_stray_numbers():
    ok = "Of {women_speakers} voices in this film, {women_speakers_f} is a woman, {women_speakers_m} are men, {women_speakers_unsigned} are unsigned."
    probs, _ = POL.template_problems(ok, {"women"}, needs_share=True)
    assert probs == []
    probs, _ = POL.template_problems("Of 21 voices, {women_speakers_f} is a woman.", {"women"}, needs_share=True)
    assert any("numbers outside a placeholder" in p for p in probs)
    probs, _ = POL.template_problems("The readings are {readings_speakers} voices.", {"readings"}, needs_share=False)
    assert any("women's shortfall only" in p for p in probs)
    probs, _ = POL.template_problems("Women are under-heard.", {"women"}, needs_share=True)
    assert any("no {<what>_share}" in p for p in probs)


def test_a3_refined_card_values_check_the_new_fields():
    good = {"readings": {"share": 0.1, "floor": 0.2}, "voiceless": {"share": 0.5, "floor": 0.1},
            "women": {"share": 0.1, "floor": 0.3, "unknown_s": 3.0, "unsigned_share": 0.05,
                      "speakers": {"all": 3, "f": 1, "m": 1, "unsigned": 1}}}
    assert R.card_values_problems(good) == []
    bad = dict(good, women=dict(good["women"], unsigned_share=1.5, speakers={"all": 3, "f": 1.5, "m": 1, "unsigned": 1}))
    probs = R.card_values_problems(bad)
    assert any("unsigned_share" in p for p in probs) and any("speakers" in p for p in probs)


# ---- the span cache can live off the film's disk (DOCUMENT_SPANS_CACHE) -----------------------------------------------

def test_spans_cache_defaults_to_the_film_and_follows_the_env(film, tmp_path, monkeypatch):
    monkeypatch.delenv("DOCUMENT_SPANS_CACHE", raising=False)
    assert R.spans_cache_dir(film) == film / "cache" / "spans"
    other = tmp_path / "elsewhere" / "spans"
    monkeypatch.setenv("DOCUMENT_SPANS_CACHE", str(other))
    assert R.spans_cache_dir(film) == other


def test_spans_cache_env_moves_the_cut_spans_off_the_film(film, tmp_path, monkeypatch):
    _edit(film, lambda p: (_shot(p, "S6").update(asset="FX-REEL", in_s=3.0, out_s=6.0, native_fps=24),
                           p["parts"][1]["text"].remove(next(t for t in p["parts"][1]["text"] if t["id"] == "T2")),
                           p["subtitle_source"].remove(next(c for c in p["subtitle_source"] if c["ref"] == "T2"))))
    monkeypatch.setattr(R, "LONG_REEL_BYTES", 1)
    other = tmp_path / "data-disk" / "spans"
    monkeypatch.setenv("DOCUMENT_SPANS_CACHE", str(other))
    plan, _ = _plan(film, "spans-elsewhere")
    sp = next(s for s in plan["shots"] if s["id"] == "S6")["_span"]
    assert Path(sp["file"]).parent == other and list(other.glob("*.mkv"))
    assert not list((film / "cache" / "spans").glob("*.mkv"))                      # nothing cut onto the film's disk


def test_a_moved_spans_cache_still_hits_and_names_where_the_span_is_now(film, tmp_path, monkeypatch):
    # WG-3, B side: the cache was copied off C: and DOCUMENT_SPANS_CACHE pointed at the copy; a hit returned the meta
    # as written, so "file" named the old folder and the mix's _read_wav failed on a missing file
    import shutil
    src = film / "footage" / "fx-reel.mp4"
    old = tmp_path / "c-drive" / "spans"
    monkeypatch.setenv("DOCUMENT_SPANS_CACHE", str(old))
    first = R.cached_span(film, src, 1.0, 2.5, video=False)
    assert Path(first["file"]).parent == old
    new = tmp_path / "d-drive" / "spans"
    shutil.copytree(old, new)
    shutil.rmtree(old)
    monkeypatch.setenv("DOCUMENT_SPANS_CACHE", str(new))

    def no_cut(*a, **k):
        raise AssertionError("a moved cache must hit, never cut again")
    monkeypatch.setattr(R.subprocess, "run", no_cut)
    hit = R.cached_span(film, src, 1.0, 2.5, video=False)
    assert Path(hit["file"]).parent == new and Path(hit["file"]).exists()
    assert hit["sha256"] == first["sha256"] and R.sha256_file(Path(hit["file"])) == first["sha256"]
    assert len(R._read_wav(Path(hit["file"]))) > 0


def test_a3_refined_a_caption_split_across_cues_counts_the_unsigned_in_its_neighbour():
    from studio.engine import captions as CAP
    vals = {"women": {"share": 0.04, "floor": 0.3, "unknown_s": 60.0, "unsigned_share": 0.12,
                      "speakers": {"all": 15, "f": 1, "m": 11, "unsigned": 3}}}
    play = {"subtitle_source": [
        {"ref": "c1", "en": "[Of {women_speakers} voices in this\nfilm, {women_speakers_f} is a woman,"},
        {"ref": "c2", "en": "{women_speakers_m} are men,\n{women_speakers_unsigned} are unsigned.]"}]}
    out = CAP.fill_play(play, vals)["subtitle_source"]
    assert out[0]["en"] == "[Of 15 voices in this\nfilm, 1 is a woman,"
    assert out[1]["en"] == "11 are men,\n3 are unsigned.]"
    # a lone cue with the counts and no unsigned anywhere near it is still refused
    alone = {"subtitle_source": [{"ref": "c1", "en": "{women_speakers_f} is a woman, {women_speakers_m} are men"},
                                 {"ref": "c2", "en": "Nothing here."}]}
    with pytest.raises(POL.FillError, match="women_speakers_unsigned"):
        CAP.fill_play(alone, vals)
