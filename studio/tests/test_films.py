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
          "The readings and recordings in this film are about one sixth of its running time, under the fifth the grammar asks, "
          "and only one of their voices is a woman's. The film says so rather than invent."]
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
         "named_patient": False, "minor": True, "consent_basis": "test"},
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


def _with_card_d(film, shortfalls, text=CARD_D):
    _edit(film, lambda p: (_shot(p, "S7").update(text=text), p.update(shortfalls=shortfalls)))


SF_READ = {"what": "readings", "measured": 0.16, "floor": 0.20, "stated_on": "S7"}
SF_WOMEN = {"what": "women", "measured": 0.12, "floor": 0.30, "stated_on": "S7"}


def test_e9_a_shortfall_names_a_card_that_states_it(film):
    _with_card_d(film, [SF_READ, SF_WOMEN])
    plan, j = _plan(film, "card-d")
    assert [e["status"] for e in lints(j, "shortfall-stated")] == ["pass", "pass"]
    assert all(sf["stated"] for sf in plan["shortfalls"])
    found = lints(j, "shortfall-stated")[0]["evidence"]["found"]
    assert found["numbers_matching"] and "recording" in found["names_it"]       # "one sixth" and "recordings"
    _with_card_d(film, [SF_READ], ["The record holds no open-licence words of anyone who had smallpox."])
    with pytest.raises(R.Refused, match=r"shortfall-stated \(shortfall:readings\).*does not state it"):
        _plan(film, "card-silent")
    _with_card_d(film, [dict(SF_READ, stated_on="S5")])
    with pytest.raises(R.Refused, match=r"not a card"):
        _plan(film, "not-a-card")
    _with_card_d(film, [dict(SF_READ, floor=0.30)])
    with pytest.raises(R.Refused, match=r"is not the film's readings_floor"):
        _plan(film, "wrong-floor")
    _with_card_d(film, [dict(SF_READ, stated_as="about one sixth of its running time")])
    _plan(film, "stated-as")
    _with_card_d(film, [dict(SF_READ, stated_as="a sixth of the film")])
    with pytest.raises(R.Refused, match=r"shortfall-stated"):
        _plan(film, "stated-as-missing")


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
    assert R.sound_lints(j, event, MIX, _placed(0.16)) == []                     # 16%, stated on card D: allowed
    rf = lints(j, "readings-floor")[0]
    assert rf["status"] == "review" and rf["severity"] == "review" and "stated on S7" in rf["evidence"]["result"]
    out = R.sound_lints(J.Journal(film="sf-unstated"), _event(plan, shortfalls=[]), MIX, _placed(0.16))
    assert any(o.startswith("readings-floor") and "'min': 0.2" in o for o in out)
    out = R.sound_lints(J.Journal(film="sf-false"), event, MIX, _placed(0.10))   # the card says a sixth; the film has a tenth
    assert any("says 0.16; the film measures 0.1" in o for o in out)
    j2 = J.Journal(film="sf-met")
    assert R.sound_lints(j2, event, MIX, _placed(0.25)) == []
    assert lints(j2, "shortfall-measured")[0]["severity"] == "warn"              # the card would claim a shortfall: said


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
    assert lints(j, "women-floor")[0]["severity"] == "review"
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
           "lines": ["Fixture reel", "Test reel, 2026", "Fixture reel, studio test folder  ·  original recording"]}


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
