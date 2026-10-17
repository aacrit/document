"""R1 (GRAMMAR A29, the house score standard) and R4 (A30, no voice over empty
black, and the dip budget): small synthetic fixtures only, no film render."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from conftest import make_film, tone
from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC

RATE = 48000


def _edit_play(film, fn):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _plan(film, name="t"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def _lints(j, rule):
    return [e for e in J.read(j.path) if e.get("kind") == "lint" and e.get("rule") == rule]


def _sine(hz, seconds, amp=0.1):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _breathing(seconds, hz=600.0, amp=0.1, beat_s=1.2, rest_beats=2, of=8):
    """A drone that holds six beats of eight and rests two (the score v3 shape), with soft edges."""
    x = _sine(hz, seconds, amp)
    t = np.arange(len(x)) / RATE
    bar = (t / beat_s) % of
    env = np.where(bar < of - rest_beats, 1.0, 0.05)
    k = int(0.2 * RATE)
    env = np.convolve(env, np.ones(k) / k, mode="same")
    return (x * env).astype(np.float32)


def _write(path, x):
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, RATE)
    return path


def _cue(cid, role, start, x, *, fi=0.0, fo=0.0, gain=0.0):
    return {"id": cid, "role": role, "start_s": start, "fade_in_s": fi, "fade_out_s": fo, "gain_db": gain,
            "an": SC.analyse_cue(x, role, fi, fo)}


# --------------------------------------------------------------------------
# R1: the standard's numbers, settable per film only within bounds
# --------------------------------------------------------------------------

def test_a29_standard_defaults_and_bounds():
    std, stated, problems = SC.standard({})
    assert std == SC.STANDARD and stated == {} and problems == []
    assert SC.bed_lufs(std) == -32.0                       # 12 dB under the -20 LUFS dialogue (founder, 2026-10-11)
    assert std["bed_lowmid_hz"] == 400.0 and std["bed_breath_db"] == 6.0 and std["duck_hold_s"] == 1.2
    std, stated, problems = SC.standard({"score_standard": {"bed_under_dialogue_db": 15, "duck_hold_s": 2.5}})
    assert problems == [] and stated == {"bed_under_dialogue_db": 15.0, "duck_hold_s": 2.5} and SC.bed_lufs(std) == -35.0
    for bad in ({"bed_under_dialogue_db": 9}, {"bed_breath_db": 3}, {"music_hole_max_s": 4}, {"bed_lowmid_max_share": 0.5},
                {"transition_over_bed_max_db": 2}, {"loudness": 1}, {"bed_lowmid_hz": "400"}, {"duck_hold_s": True},
                {"music_treble_max_share": 0.05}, {"bed_highpass_hz": 300}):
        _, _, problems = SC.standard({"score_standard": bad})
        assert problems, bad                               # louder or laxer than the house allows is refused
    assert set(SC.STANDARD) == set(SC.BOUNDS)
    for k, (lo, hi) in SC.BOUNDS.items():
        assert lo <= SC.STANDARD[k] <= hi, k


def test_a29_a_film_outside_the_bounds_is_refused_at_plan_time(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: p.update(score_standard={"bed_under_dialogue_db": 6}))
    with pytest.raises(R.Refused, match=r"score-standard"):
        _plan(film, "std-bad")
    _edit_play(film, lambda p: p.update(score_standard={"bed_under_dialogue_db": 14}))
    plan, _ = _plan(film, "std-ok")
    assert plan["score_standard"]["bed_under_dialogue_db"] == 14.0 and plan["score_standard_stated"] == {"bed_under_dialogue_db": 14.0}


def test_a29_cue_roles_from_the_scores_own_names():
    u = {"kind": "music", "role": "underscore"}
    assert SC.cue_role(dict(u, wav="score/bed_dread-x2.wav", tradition="underscore: the heat")) == "bed"
    assert SC.cue_role(dict(u, wav="score/base/transition_grief.wav")) == "transition"
    assert SC.cue_role(dict(u, wav="score/base/rupture_entry.wav")) == "transition"
    assert SC.cue_role(dict(u, wav="score/base/sting_from_clip.wav")) == "sting"
    assert SC.cue_role(dict(u, wav="score/base/outro.wav")) == "outro"
    assert SC.cue_role(dict(u, tradition="underscore: transition:reckoning", wav="x.wav")) == "transition"
    assert SC.cue_role({"kind": "music", "role": "house_motif", "wav": "score/base/theme.wav"}) == "motif"
    assert SC.cue_role({"kind": "music", "role": "palette", "wav": "baul.wav"}) == "palette"
    assert SC.cue_role({"kind": "ambience"}) == "ambience"
    assert SC.cue_role(dict(u, wav="score/base/transition_grief.wav", score_role="bed")) == "bed"   # stated wins


def test_a29_an_unknown_score_role_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "M1.wav", _breathing(10))
    _edit_play(film, lambda p: p.update(music=[{"id": "M1", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0,
                                                "score_role": "drone"}]))
    with pytest.raises(R.Refused, match=r"score-role \(M1\)"):
        _plan(film, "role-bad")


# --------------------------------------------------------------------------
# R1: the measurements
# --------------------------------------------------------------------------

def test_a29_highpass_is_12_db_an_octave_at_300_hz():
    def gain(hz):
        x = _sine(hz, 2.0, 0.5)
        y = SC.highpass(x, 300.0)
        mid = slice(RATE // 2, 3 * RATE // 2)
        return 20 * math.log10(np.sqrt(np.mean(y[mid] ** 2)) / np.sqrt(np.mean(x[mid] ** 2)))
    assert gain(300.0) == pytest.approx(-3.01, abs=0.1)
    assert gain(150.0) == pytest.approx(-12.3, abs=0.3)             # one octave down: about 12 dB more
    assert gain(75.0) == pytest.approx(-24.1, abs=0.4)
    assert gain(2000.0) == pytest.approx(0.0, abs=0.05)             # the voice band passes untouched
    assert len(SC.highpass(_sine(440, 0.3), 300.0)) == int(0.3 * RATE)


def test_a29_k_weighted_loudness_agrees_with_ffmpeg():
    x = _sine(997.0, 6.0, 0.1)                                      # BS.1770: a 997 Hz sine at -20 dBFS peak is -23.0 LUFS
    kp = np.mean(SC._windows(SC.k_weight(x), int(SC.HOP_S * RATE)) ** 2, axis=1)
    lufs = SC.gated_loudness(np.convolve(kp, np.ones(4) / 4, mode="valid"))
    assert lufs == pytest.approx(-23.0, abs=0.15)
    y = _breathing(20.0, 400.0)
    an = SC.analyse_cue(y, "bed")
    assert an["integrated_lufs"] == pytest.approx(R._measure(y)["input_i"], abs=0.5)    # the engine's own meter


def test_a29_breathing_and_low_end_measures():
    flat = SC.analyse_cue(_sine(600, 20.0), "bed")
    assert flat["breath_db"] < 0.5                                   # a held drone does not breathe
    breath = SC.analyse_cue(_breathing(38.4), "bed")
    assert breath["breath_db"] >= 6.0
    low = SC.analyse_cue(SC.bed_shape(_sine(196.0, 10.0) + _sine(800.0, 10.0, 0.03), 400.0), "bed")
    high = SC.analyse_cue(SC.bed_shape(_sine(600.0, 10.0), 400.0), "bed")
    assert low["lowmid_share"] > 0.10 and high["lowmid_share"] < 0.01   # a harp's G3 under the shaping still sits low


def test_a29_bed_checks_level_low_end_breathing():
    std = dict(SC.STANDARD)
    target = SC.bed_lufs(std)

    def placed(x, gain=0.0, cid="B"):
        an = SC.analyse_cue(x, "bed")
        g = target - an["integrated_lufs"] + gain
        return _cue(cid, "bed", 0.0, x * np.float32(10 ** (g / 20)), gain=gain)

    ok = placed(SC.highpass(_breathing(20.0), 300.0), cid="ok")
    loud = placed(SC.highpass(_breathing(20.0), 300.0), gain=3.0, cid="loud")
    flat = placed(SC.highpass(_sine(600, 20.0), 300.0), cid="flat")
    low = placed(SC.highpass(_breathing(20.0, 196.0), 300.0), cid="low")
    res = {(c["rule"], c["unit"]): c for c in SC.score_checks([ok, loud, flat, low], std, duration_s=20.0)}
    assert res[("bed-under-voice", "ok")]["ok"] and not res[("bed-under-voice", "loud")]["ok"]
    assert res[("bed-under-voice", "loud")]["evidence"]["under_dialogue_db"] == pytest.approx(9.0, abs=0.6)
    assert res[("bed-breathing", "ok")]["ok"] and not res[("bed-breathing", "flat")]["ok"]
    assert res[("bed-low-end", "ok")]["ok"] and not res[("bed-low-end", "low")]["ok"]


def test_a29_a_bed_is_measured_in_the_voices_gaps():
    std = dict(SC.STANDARD)
    x = SC.highpass(_breathing(30.0), 300.0)
    an = SC.analyse_cue(x, "bed")
    x = x * np.float32(10 ** ((SC.bed_lufs(std) - an["integrated_lufs"]) / 20))
    c = _cue("B", "bed", 0.0, x)
    duck = np.full(300, 10 ** (-9 / 20))
    duck[100:160] = 1.0                                             # 6 s of gaps
    r = next(r for r in SC.score_checks([c], std, duration_s=30.0, duck100=duck) if r["rule"] == "bed-under-voice")
    assert r["evidence"]["measured_on"] == "the voice's gaps (no duck)" and r["evidence"]["windows"] == 60
    duck[100:160] = 10 ** (-9 / 20)
    duck[100:120] = 1.0                                             # 2 s of gaps: one phrase, so the whole bed is measured
    r = next(r for r in SC.score_checks([c], std, duration_s=30.0, duck100=duck) if r["rule"] == "bed-under-voice")
    assert r["evidence"]["measured_on"].startswith("the bed's full-level span") and r["ok"]


def test_a29_transition_ceiling_and_entry_from_silence():
    std = dict(SC.STANDARD)
    bed = _cue("bed", "bed", 4.0, _breathing(20.0, amp=0.05), fi=1.5)
    quiet = _cue("t-quiet", "transition", 0.0, _sine(600, 4.0, 0.02), fi=1.5)
    loud = _cue("t-loud", "transition", 0.0, _sine(600, 4.0, 0.2), fi=0.0)
    res = {(c["rule"], c["unit"]): c for c in SC.score_checks([quiet, bed], std, duration_s=24.0)}
    assert res[("transition-ceiling", "t-quiet")]["ok"] and res[("music-entry", "t-quiet")]["ok"]
    assert res[("transition-ceiling", "t-quiet")]["evidence"]["bed"] == "bed"
    assert ("music-entry", "bed") not in res                       # the bed enters under the transition, not from silence
    res = {(c["rule"], c["unit"]): c for c in SC.score_checks([loud, bed], std, duration_s=24.0)}
    assert not res[("transition-ceiling", "t-loud")]["ok"] and res[("transition-ceiling", "t-loud")]["evidence"]["over_db"] > 5
    assert not res[("music-entry", "t-loud")]["ok"]                 # from digital zero with no fade: a >100 dB step
    sting = _cue("s", "sting", 30.0, _sine(600, 1.0, 0.01))
    res = {(c["rule"], c["unit"]): c for c in SC.score_checks([bed, sting], std, duration_s=40.0)}
    assert res[("transition-ceiling", "s")]["evidence"]["compared_with"].startswith("the bed before it")


def test_a29_music_holes_between_cues_unless_declared():
    std = dict(SC.STANDARD)
    a = _cue("a", "bed", 0.0, _breathing(10.0))
    b = _cue("b", "bed", 12.0, _breathing(10.0))                    # 2 s of no music between them
    c = _cue("c", "bed", 23.0, _breathing(5.0))                     # 1 s: allowed
    holes = SC.music_holes([a, b, c], 30.0, [], [], std["music_hole_max_s"])
    assert [(h["from_s"], h["to_s"], h["after_cue"], h["before_cue"]) for h in holes] == [(10.0, 12.0, "a", "b")]
    assert SC.music_holes([a, b, c], 30.0, [(9.5, 12.5)], [], 1.5) == []          # a declared silence (a moment)
    assert SC.music_holes([a, b, c], 30.0, [], [(10.0, 12.0)], 1.5) == []         # a source's own sound fills it
    assert SC.music_holes([b], 40.0, [], [], 1.5) == []                            # before the first and after the last cue
    assert SC.music_holes([], 40.0, [], [], 1.5) == []


def test_a29_duck_holds_through_a_written_pause_inside_a_line():
    voice = np.zeros(20 * RATE, np.float32)
    voice[2 * RATE: 5 * RATE] = 0.1                                 # one line: 3 s of words, a 2.5 s written pause, 3 s more
    voice[int(7.5 * RATE): int(10.5 * RATE)] = 0.1
    voice[int(12.5 * RATE): int(14 * RATE)] = 0.1                   # the next line, after a 2 s gap between lines
    floor = 10 ** (-R.DUCK_DB / 20)
    old = R.duck_gain(voice)
    new = R.duck_gain(voice, spans=[(2.0, 10.5), (12.5, 14.0)], hold_s=1.2)
    assert old[int(6.25 * RATE)] == pytest.approx(1.0)              # before A29 the bed came back up in the pause
    assert new[int(6.25 * RATE)] == pytest.approx(floor, abs=1e-6)  # now it holds
    assert new[int(11.5 * RATE)] == pytest.approx(1.0)              # between lines (2 s, over the hold) it comes up
    g = int(SC.DUCK_GRID_S * RATE)
    act = np.abs(voice).reshape(-1, g).max(axis=1) > R.DUCK_VOICE_THRESHOLD
    spans = [(2.0, 10.5), (12.5, 14.0)]
    pumps = SC.duck_pumps(act, old.reshape(-1, g).mean(axis=1), spans, 1.2)
    assert [p["why_held"] for p in pumps] == ["a pause inside a line"] and pumps[0]["rises_db"] > 8
    assert SC.duck_pumps(act, new.reshape(-1, g).mean(axis=1), spans, 1.2) == []
    longer = R.duck_gain(voice, spans=spans, hold_s=2.5)            # a film may hold longer (up to 3 s, A29's bounds)
    assert longer[int(11.5 * RATE)] == pytest.approx(floor, abs=1e-6)


def _scored_film(tmp_path, bed, *, gain=0.0, fade_in=1.5):
    film = make_film(tmp_path / "film")
    _write(film / "score" / "bed_test.wav", bed)
    cue = {"id": "M1", "kind": "music", "role": "underscore", "tradition": "underscore: the test", "source": "test",
           "licence": "CC0", "start_s": 0.5, "end_s": 21.5, "fade_in_s": fade_in, "fade_out_s": 2.0, "gain_db": gain,
           "wav": "score/bed_test.wav"}
    _edit_play(film, lambda p: p.update(music=[cue]))
    return film


def test_a29_build_mix_band_shapes_and_levels_a_bed_to_the_standard(tmp_path):
    film = _scored_film(tmp_path, _breathing(22.0, 250.0) + _breathing(22.0, 900.0, 0.02))   # a viola line in the voice's range
    plan, j = _plan(film, "mix-bed")
    stems: dict = {}
    mix, placed = R.build_mix(plan, film, j, stems=stems)
    pc = next(c for c in placed["cues"] if c["id"] == "M1")
    assert pc["role"] == "bed" and pc["shaping"]["passes_over_hz"] == 400.0 and pc["shaping"]["sub_bass_kept_under_hz"] == 100.0
    evs = J.read(j.path)
    assert any(e["kind"] == "decision" and e.get("unit") == "M1" and "band-shaped" in e["what"] for e in evs)
    lv = [e for e in evs if e["kind"] == "decision" and e.get("unit") == "M1" and "levelled to" in e["what"]]
    assert lv and lv[0]["evidence"]["target"] == -32.0
    c = stems["cues"][0]
    assert c["role"] == "bed" and c["an"]["integrated_lufs"] == pytest.approx(-32.0, abs=1.0)
    assert len(stems["voice_grid"]) == len(stems["duck_grid"]) and stems["spans"]
    music = [x for x in R.score_lints(J.Journal(film="sl-draft"), plan, stems, draft=True)]
    assert music == []                                              # a draft journals warnings, never refuses
    out = R.score_lints(J.Journal(film="sl-final"), plan, stems)
    assert any(o.startswith("bed-low-end (M1") for o in out)       # its 250 Hz line survives the shaping (-15 dB)


def test_a29_a_final_render_refuses_and_audio_only_warns(tmp_path):
    film = _scored_film(tmp_path, _sine(700.0, 22.0), fade_in=0.0)  # a held drone, entering from silence
    with pytest.raises(R.Refused, match=r"score standard \(pre-flight\).*bed-breathing \(M1"):
        R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, encode_preset="veryfast")
    j = J.Journal(film="ao", out_dir=tmp_path / "out-ao")
    R.render(film, tmp_path / "out-ao", height=360, workers=1, min_free_gb=1, audio_only=True, journal=j)
    warned = {e["rule"]: e for e in J.read(j.path) if e.get("kind") == "lint" and e.get("rule") in SC.RULES and e["status"] == "fail"}
    assert set(warned) >= {"bed-breathing", "music-entry"} and all(e["severity"] == "warn" for e in warned.values())


def test_a29_the_offline_check_reads_a_films_cues(tmp_path):
    film = _scored_film(tmp_path, _sine(700.0, 22.0), fade_in=0.0)
    rep = SC.offline(film)
    bad = {c["rule"] for c in rep["checks"] if not c["ok"]}
    assert {"bed-breathing", "music-entry"} <= bad and rep["missing"] == ["C1"]          # the fixture's ambience, never made
    good = tmp_path / "rescored"
    _write(good / "bed_test.wav", SC.highpass(_breathing(22.0), 300.0))
    rep = SC.offline(film, wav_dir=good)
    assert rep["swapped"] == ["M1"] and "bed-breathing" not in {c["rule"] for c in rep["checks"] if not c["ok"]}


# --------------------------------------------------------------------------
# R4: no voice over empty black, and the dip budget
# --------------------------------------------------------------------------

def _black_film(tmp_path, **shot):
    film = make_film(tmp_path / "film")
    tone(film / "audio" / "L2.wav", 5.0, 330.0)                      # the reading now runs 5 s over S8 (black) and S9 (card)
    _edit_play(film, lambda p: _shot(p, "S8").update(**shot))
    return film


def test_a30_a_reading_over_black_longer_than_4_s_needs_an_intent(tmp_path):
    film = _black_film(tmp_path)
    plan, _ = _plan(film, "black")
    run = next(r for r in plan["dark_voice"] if "L2" in r["lines"])
    assert run["voice_s"] == pytest.approx(5.0, abs=0.05) and [s["id"] for s in run["shots"]] == ["S8", "S9"]
    j = J.Journal(film="black-final")
    out = R.black_dip_lints(j, plan)
    assert any(o.startswith("black-under-voice (S8") and "no intent on S8, S9" in o for o in out)
    jd = J.Journal(film="black-draft")
    assert not [o for o in R.black_dip_lints(jd, plan, draft=True) if o.startswith("black")]
    assert all(e["severity"] == "warn" for e in _lints(jd, "black-under-voice"))


def test_a30_an_intent_from_the_closed_list_passes_and_is_printed(tmp_path):
    film = _black_film(tmp_path, intent="count-of-the-dead")
    _edit_play(film, lambda p: _shot(p, "S9").update(intent="the-film-speaks"))
    plan, _ = _plan(film, "intent")
    j = J.Journal(film="intent-final")
    out = R.black_dip_lints(j, plan)
    assert any("no lower third for L2" in o for o in out)           # a reading over black carries its lower third
    _edit_play(film, lambda p: p["parts"][1]["text"].append(
        {"id": "T9", "kind": "lower_third", "start_s": 20.3, "end_s": 25.3,
         "lines": ["Fixture speaker", "Test stand-in, 1947", "Fixture source, studio test folder  ·  read by a computer voice"]}))
    plan, _ = _plan(film, "intent-lt")
    j = J.Journal(film="intent-ok")
    assert not [o for o in R.black_dip_lints(j, plan) if o.startswith("black")]
    dec = [e for e in J.read(j.path) if e["kind"] == "decision" and "intent count-of-the-dead" in e["what"]]
    assert dec and dec[0]["unit"] == "S8"
    doc = R.sources_doc(plan, j, {})
    assert {(b["shot"], b["intent"]) for b in doc["black_under_voice"]} == {("S8", "count-of-the-dead"), ("S9", "the-film-speaks")}
    assert doc["black_under_voice"][0]["why"] == R.BLACK_INTENTS["count-of-the-dead"]
    assert doc["score_standard"] == SC.STANDARD


def test_a30_an_intent_off_the_list_or_off_black_is_refused(tmp_path):
    film = _black_film(tmp_path, intent="mood")
    with pytest.raises(R.Refused, match=r"black-intent \(S8\)"):
        _plan(film, "intent-bad")
    film = make_film(tmp_path / "film2")
    _edit_play(film, lambda p: _shot(p, "S3").update(intent="poem"))
    with pytest.raises(R.Refused, match=r"black-intent \(S3\)"):
        _plan(film, "intent-still")


# A30 refined (founder, 2026-10-17): a free-text black_reason beside the closed intent list, on a black shot only.

def test_a30_a_black_reason_passes_and_is_a_reviewer_item(tmp_path):
    reason = "the record falls silent here, deliberately"
    film = _black_film(tmp_path, black_reason=reason)
    _edit_play(film, lambda p: _shot(p, "S9").update(intent="the-film-speaks"))
    plan, _ = _plan(film, "reason")
    j = J.Journal(film="reason-final")
    out = R.black_dip_lints(j, plan)
    assert any("no lower third for L2" in o for o in out)           # a reading over black still carries its lower third
    _edit_play(film, lambda p: p["parts"][1]["text"].append(
        {"id": "T9", "kind": "lower_third", "start_s": 20.3, "end_s": 25.3,
         "lines": ["Fixture speaker", "Test stand-in, 1947", "Fixture source, studio test folder  ·  read by a computer voice"]}))
    plan, _ = _plan(film, "reason-lt")
    j = J.Journal(film="reason-ok")
    assert not [o for o in R.black_dip_lints(j, plan) if o.startswith("black")]
    rv = [e for e in J.read(j.path) if e["kind"] == "lint" and e["rule"] == "black-reason" and e["severity"] == "review"]
    assert {e["unit"] for e in rv} == {"S8"} and rv[0]["evidence"]["black_reason"] == reason
    dec = [e for e in J.read(j.path) if e["kind"] == "decision"]
    assert not any(d.get("unit") == "S8" for d in dec)       # a reason is a reviewer item, never a closed-list decision
    doc = R.sources_doc(plan, j, {})
    assert {b["shot"] for b in doc["black_under_voice"]} == {"S9"}  # reason-based shots stay off the closed-intent list


def test_a30_a_black_reason_too_short_or_a_filler_token_is_refused(tmp_path):
    film = _black_film(tmp_path / "short", black_reason="mourning")
    with pytest.raises(R.Refused, match=r"black-reason \(S8\)"):
        _plan(film, "reason-short")
    film2 = _black_film(tmp_path / "filler", black_reason="silence silence silence silence")
    with pytest.raises(R.Refused, match=r"black-reason \(S8\)"):
        _plan(film2, "reason-filler")


def test_a30_a_black_reason_on_a_card_is_refused(tmp_path):
    film = _black_film(tmp_path)
    _edit_play(film, lambda p: _shot(p, "S9").update(black_reason="the record falls silent here, deliberately"))
    with pytest.raises(R.Refused, match=r"black-reason \(S9\).*for a black shot only"):
        _plan(film, "reason-card")


def test_a30_neither_intent_nor_reason_still_blocks(tmp_path):
    """Black under voice with no intent and no reason refuses exactly as A30 did before this change."""
    film = _black_film(tmp_path)
    plan, _ = _plan(film, "neither")
    j = J.Journal(film="neither-final")
    out = R.black_dip_lints(j, plan)
    assert any(o.startswith("black-under-voice (S8") and "no intent on S8, S9" in o for o in out)


def test_a30_under_4_s_of_voice_over_black_passes(plan):
    j = J.Journal(film="fixture-black")
    assert not [o for o in R.black_dip_lints(j, plan) if o.startswith("black")]
    assert [e["status"] for e in _lints(j, "black-under-voice")] == ["pass"]     # L2's 1.2 s over S8 and the credits card


def _dips(parts, dur=None, *, s=0.75, target=None):
    """``parts``: {part: (seconds, dips)}; each part one shot per dip plus one, tiling the film at 24 fps."""
    shots, f = [], 0
    for p, (secs, n) in parts.items():
        per = int(round(secs * 24)) // (n + 1)
        for i in range(n + 1):
            f1 = f + per if i < n else f + int(round(secs * 24)) - per * n
            shots.append({"id": f"{p}-{i}", "_part": p, "f0": f, "f1": f1,
                          "transition_in": {"type": "dip", "s": s} if i else {"type": "cut"}})
            f = f1
    dur = dur if dur is not None else f / 24
    return {"shots": shots, "duration_s": dur, "runtime_target_s": target, "lines": [], "film": ".", "dark_voice": [],
            "dips": R.dip_list({"shots": shots})}


def test_a30_dip_budget_per_part():
    """A39 (R12, founder: pacing is guidance): the dip budget is measured as before, but over it is a warning and a
    reviewer item (pacing-guide), never a refusal, on a final render of an event film too."""
    def run(plan, draft=False):
        j = J.Journal(film="dips")
        out = R.black_dip_lints(j, plan, draft=draft)
        return out, _lints(j, "dip-budget")[0], _lints(j, "pacing-guide")
    out, e, rv = run(_dips({"p1": (400.0, 10), "p2": (200.0, 5)}))      # one a 40 s in each part, 11.25 s of dip
    assert out == [] and e["status"] == "pass" and rv == []
    assert e["evidence"]["by_part"]["p1"] == {"dips": 10, "part_s": 400.0, "allowed": 10, "over": 0}
    out, e, rv = run(_dips({"p1": (400.0, 4), "p2": (200.0, 8)}))       # 12 dips in 600 s, but p2 has 8 in 200 s
    assert out == [] and e["status"] == "fail" and e["severity"] == "warn"
    assert [r["evidence"]["rule"] for r in rv] == ["dip-budget"] and rv[0]["severity"] == "review"
    assert e["evidence"]["parts_over"] == ["p2"] and "make cuts of 3 dip(s) in p2" in e["evidence"]["fix"]
    assert "A39" in e["evidence"]["advisory"]
    out, e, rv = run(_dips({"t": (15.0, 1), "p1": (585.0, 14)}))        # a 15 s title part keeps its one dip
    assert out == [] and e["evidence"]["by_part"]["t"]["allowed"] == 1
    out, e, rv = run(_dips({"p1": (600.0, 15)}, s=1.0))                 # 15 s of dip per 10 min: over the 12 s
    assert out == [] and e["status"] == "fail" and rv
    out, e, rv = run(_dips({"p1": (300.0, 16)}))                        # a short piece: a warning
    assert out == [] and e["status"] == "fail" and e["severity"] == "warn"
    out, e, rv = run(_dips({"p1": (1200.0, 60)}), draft=True)
    assert out == [] and e["severity"] == "warn"


def test_a30_partition_like_parts_record_their_counts(plan):
    j = J.Journal(film="fixture-dips")
    R.black_dip_lints(j, plan)
    ev = _lints(j, "dip-budget")[0]["evidence"]
    assert set(ev["by_part"]) == {s["_part"] for s in plan["shots"]} and ev["dips"] == len(plan["dips"])


def test_a30_a_final_render_refuses_before_any_frame(tmp_path):
    film = _black_film(tmp_path)
    with pytest.raises(R.Refused, match=r"on-screen time \(pre-flight\).*black-under-voice \(S8"):
        R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, encode_preset="veryfast")
    assert not list((tmp_path / "out").glob("segments/*.mp4"))


# --------------------------------------------------------------------------
# PR #23 review of 264b382
# --------------------------------------------------------------------------

def _p(cid, role, start, x, fi=0.0, fo=0.0, gain=0.0):
    c = {"id": cid, "kind": "music", "start_s": start, "end_s": start + len(x) / RATE, "fade_in_s": fi,
         "fade_out_s": fo, "gain_db": gain}
    if role:
        c["score_role"] = role
    return SC.place_cue(c, x, dict(SC.STANDARD))


def _fails(cues, dur=60.0, **kw):
    return {(c["rule"], c["unit"]) for c in SC.score_checks(cues, dict(SC.STANDARD), duration_s=dur, **kw) if not c["ok"]}


def test_review_a_lifted_underscore_cue_is_refused_and_measured(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "M1.wav", _breathing(10))
    for role in ("outro", "transition", None):
        cue = {"id": "M1", "kind": "music", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0, "gain_db": 12.0}
        if role:
            cue["score_role"] = role
        _edit_play(film, lambda p: p.update(music=[cue]))
        with pytest.raises(R.Refused, match=r"underscore-gain \(M1\)"):
            _plan(film, f"gain-{role}")
    bed = _p("BED", "bed", 0, _breathing(20, 600), fi=2, fo=2)
    out = _p("OUT", "outro", 19, _sine(600, 10), fi=2, fo=2, gain=12.0)
    assert {("underscore-level", "OUT"), ("transition-ceiling", "OUT")} <= _fails([bed, out])
    tr = _p("TR", "transition", 0, _sine(600, 5), fi=2, fo=2, gain=12.0)       # no bed anywhere in the film
    assert {("underscore-level", "TR"), ("transition-ceiling", "TR")} <= _fails([tr])
    ok = _p("TR0", "transition", 0, _sine(600, 5), fi=2, fo=2)
    assert not {r for r in _fails([ok]) if r[0] in ("underscore-level", "transition-ceiling")}


def test_review_roles_cannot_escape_the_standard(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "M1.wav", _breathing(10))
    base = {"id": "M1", "kind": "music", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0}
    for bad in ({"role": "texture"}, {"score_role": "palette"}, {"score_role": "motif"},
                {"role": "palette", "score_role": "motif"}, {"role": "house_motif", "score_role": "bed"},
                {"score_role": ["bed"]}, {"role": 3}):
        _edit_play(film, lambda p: p.update(music=[dict(base, **bad)]))
        with pytest.raises(R.Refused, match=r"score-role \(M1\)"):
            _plan(film, "role")
    for good in ({}, {"score_role": "sting"}, {"role": "palette"}, {"role": "house_motif", "score_role": "motif"}):
        _edit_play(film, lambda p: p.update(music=[dict(base, **good)]))
        _plan(film, "role-ok")
    assert SC.cue_role({"kind": "music", "role": "underscore", "score_role": "palette"}) == "bed"
    assert SC.cue_role({"kind": "music", "wav": "score/base/theme.wav"}) == "bed"      # only role makes the motif


def test_review_the_low_mid_cut_is_never_under_400_hz():
    assert SC.BOUNDS["bed_lowmid_hz"] == (400.0, 500.0)              # A29 refined: the high-pass bound it replaces was 300
    assert SC.standard({"score_standard": {"bed_lowmid_hz": 350}})[2]
    assert not SC.standard({"score_standard": {"bed_lowmid_hz": 450}})[2]


def test_review_a_hole_has_neither_voice_nor_music_and_ambience_is_not_music():
    m1 = _p("M1", "bed", 0, _breathing(10, 600), fi=2, fo=2)
    m2 = _p("M2", "bed", 20, _breathing(10, 600), fi=2, fo=2)
    amb = {"id": "A1", "role": "ambience", "start_s": 10.0, "fade_in_s": 0, "fade_out_s": 0, "gain_db": 0,
           "an": SC.analyse_cue(_sine(600, 10, 0.01), "ambience")}
    assert ("music-holes", "music") in _fails([m1, m2])
    assert ("music-holes", "music") in _fails([m1, amb, m2])                   # ambience does not fill it
    v = np.zeros(600, bool)
    v[100:200] = True                                                           # a voice through the gap: no hole
    assert ("music-holes", "music") not in _fails([m1, m2], voice100=v)
    v[180:200] = False                                                          # 2 s with neither: a hole
    holes = SC.music_holes([m1, m2], 60.0, [], [], 1.5, v)
    assert len(holes) == 1 and holes[0]["from_s"] == 18.0 and holes[0]["to_s"] == pytest.approx(20.0, abs=0.15)


def test_review_a_bed_and_a_last_cue_fade_out():
    bed = _p("B", "bed", 0, _breathing(20, 600), fi=2, fo=1.0)
    tr = _p("T", "transition", 25, _sine(600, 4, 0.02), fi=2, fo=0)
    bed2 = _p("B2", "bed", 28.5, _breathing(20, 600), fi=1.5, fo=2)
    f = _fails([bed, tr, bed2])
    assert ("music-exit", "B") in f and ("music-exit", "T") not in f and ("music-exit", "B2") not in f
    out = _p("O", "outro", 50, _sine(600, 5, 0.02), fi=2, fo=0)
    assert ("music-exit", "O") in _fails([bed2, out], dur=60)


def test_review_breathing_is_judged_before_the_fades():
    drone = _p("D", "bed", 0, _sine(600, 20), fi=10, fo=9.5)                    # the fades are not a breath
    assert drone["an"]["breath_db"] < 0.5 and ("bed-breathing", "D") in _fails([drone])
    short = _p("S", "bed", 0, _sine(600, 2.5), fi=1.5, fo=1.0)
    assert short["an"]["breath_judged"] is False
    r = next(c for c in SC.score_checks([short], dict(SC.STANDARD), duration_s=5) if c["rule"] == "bed-breathing")
    assert not r["ok"] and "not judged" in r["evidence"]["fix"]
    assert _p("OK", "bed", 0, _breathing(38.4), fi=10, fo=10)["an"]["breath_db"] >= 6


def test_review_intents_are_strings_and_the_count_is_on_black_only(tmp_path):
    film = _black_film(tmp_path, intent=["count-of-the-dead"])
    with pytest.raises(R.Refused, match=r"black-intent \(S8\)"):
        _plan(film, "intent-list")
    film = make_film(tmp_path / "film2")
    _edit_play(film, lambda p: _shot(p, "S9").update(intent="count-of-the-dead"))  # S9 is a card
    with pytest.raises(R.Refused, match=r"black-intent \(S9\).*for a black shot only"):
        _plan(film, "intent-card")


def test_review_offline_counts_archival_spans_as_voice(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: p["parts"][1]["lines"].append(
        {"id": "LA", "kind": "testimony", "speaker": "sp-fixture", "archival_audio": True, "clip": "FV-X", "in_s": 2.0,
         "out_s": 6.0, "start_s": 25.0}))
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    act, spans = SC.voice_activity(film, play, 40.0)
    assert (25.0, 29.0) in spans and act[2550] and act[2850] and not act[2950]


def test_review_a_scored_bed_never_touches_the_voices(tmp_path, monkeypatch):
    """Voice audio and the placed lines are bit-identical with and without a scored bed, in pass 1 and after a forced
    E14 pass 2 (A29 changes only the music and its duck)."""
    def run(film, force):
        seen = {}
        real_duck, real_mix_at = R.duck_gain, R._mix_at

        def duck(voice, *a, **k):
            seen.setdefault("voice", voice.copy())
            return real_duck(voice, *a, **k)

        def mix_at(*a, **k):
            mix, got = real_mix_at(*a, **k)
            seen["pass2"] = {i: (g["x"].copy(), g["db"]) for i, g in got.items()}
            return mix, got
        with monkeypatch.context() as mp:
            mp.setattr(R, "duck_gain", duck)
            mp.setattr(R, "_mix_at", mix_at)
            if force:
                mp.setattr(R, "_master_overreach", lambda mix, tp, work: (["forced by the test"], None))
                mp.setattr(R, "derived_voice_ceiling", lambda lift: (-7.0, -7.0, None))
            plan, j = _plan(film, f"bit-{force}")
            work = tmp_path / f"w-{force}-{film.parent.name}"
            work.mkdir(parents=True, exist_ok=True)
            _, placed = R.build_mix(plan, film, j, work=work)
        return seen, placed["lines"]

    plain = make_film(tmp_path / "p" / "film")
    scored = _scored_film(tmp_path / "s", _breathing(22.0))
    for force in (False, True):
        a, la = run(plain, force)
        b, lb = run(scored, force)
        assert a["voice"].dtype == b["voice"].dtype and np.array_equal(a["voice"], b["voice"])
        assert la == lb
        if force:
            assert a["pass2"] and a["pass2"].keys() == b["pass2"].keys()
            for i in a["pass2"]:
                assert np.array_equal(a["pass2"][i][0], b["pass2"][i][0]) and a["pass2"][i][1] == b["pass2"][i][1]


# --------------------------------------------------------------------------
# PR #23 re-review of 24f5de0
# --------------------------------------------------------------------------

def test_rereview_the_film_wide_dip_count_holds_over_many_short_parts():
    def run(plan):
        j = J.Journal(film="dips-film")
        return R.black_dip_lints(j, plan), _lints(j, "dip-budget")[0]
    out, e = run(_dips({f"p{i}": (20.0, 1) for i in range(36)}))     # 36 parts of 20 s, one dip each: 30 per 10 min
    assert e["evidence"]["parts_over"] == [] and e["evidence"]["film_allowed_dips"] == 18
    assert out == [] and e["status"] == "fail" and "make cuts of 18 dip(s) across the film" in e["evidence"]["fix"]
    out, e = run(_dips({f"p{i}": (40.0, 1) for i in range(15)}))     # 15 parts of 40 s: one per 40 s, exactly
    assert out == [] and e["status"] == "pass"


def test_rereview_a_cue_is_music_or_ambience(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "M1.wav", _breathing(10))
    for kind in ("Music", "sfx", None):
        def put(p, kind=kind):
            cue = {"id": "M1", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0, "kind": kind}
            p["parts"][1].setdefault("cues", []).append(cue)
        _edit_play(film, put)
        with pytest.raises(R.Refused, match=r"cue-kind \(M1\)"):
            _plan(film, f"kind-{kind}")
        _edit_play(film, lambda p: p["parts"][1].update(cues=[c for c in p["parts"][1]["cues"] if c["id"] != "M1"]))
    _edit_play(film, lambda p: p["parts"][1]["cues"].append(
        {"id": "M1", "kind": "ambience", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0, "gain_db": 6.0}))
    with pytest.raises(R.Refused, match=r"underscore-gain \(M1\)"):
        _plan(film, "amb-gain")


def test_rereview_ambience_cannot_carry_loud_music_past_a29():
    swell = _sine(600, 6.0, 0.05)
    swell[2 * RATE: 3 * RATE] *= 4.0
    loud = {"id": "A", "role": "ambience", "start_s": 0.0, "fade_in_s": 0, "fade_out_s": 0, "gain_db": 0,
            "an": SC.analyse_cue(swell, "ambience", unfaded=swell)}
    r = next(c for c in SC.score_checks([loud], dict(SC.STANDARD), duration_s=10) if c["rule"] == "ambience-level")
    assert not r["ok"] and r["evidence"]["integrated_lufs"] > -31
    room = _sine(600, 6.0, 0.05) * np.float32(10 ** ((SC.bed_lufs(SC.STANDARD) - 6 - SC.analyse_cue(
        _sine(600, 6.0, 0.05), "ambience")["integrated_lufs"]) / 20))
    quiet = dict(loud, id="Q", an=SC.analyse_cue(room, "ambience", unfaded=room))
    assert next(c for c in SC.score_checks([quiet], dict(SC.STANDARD), duration_s=10) if c["rule"] == "ambience-level")["ok"]


def test_rereview_underscore_level_reads_the_cue_before_its_fades():
    y = _sine(600, 6.0, 0.05)
    y[2 * RATE: 3 * RATE] *= 4.0                                                # a 6 s swell, 2 s fades
    t = _p("T", "transition", 0, y, fi=2.0, fo=2.0)
    assert t["an"]["integrated_unfaded_lufs"] == pytest.approx(-32.0, abs=0.1)
    r = next(c for c in SC.score_checks([t], dict(SC.STANDARD), duration_s=10) if c["rule"] == "underscore-level")
    assert r["ok"] and r["evidence"]["measured_on"] == "levelled, before the fades"


def test_rereview_the_no_bed_reference_is_a_stated_fallback():
    y = _sine(600, 6.0, 0.05)
    y[2 * RATE: 3 * RATE] *= 4.0
    quiet_bed = _p("B", "bed", 0, _breathing(20, 600, 0.05), fi=2, fo=2)
    t = _p("T", "transition", 60, y, fi=2.0, fo=2.0)                            # 40 s after the bed: none within 10 s
    r = next(c for c in SC.score_checks([quiet_bed, t], dict(SC.STANDARD), duration_s=80) if c["rule"] == "transition-ceiling")
    tgt = SC.bed_lufs(SC.STANDARD)
    assert r["evidence"]["compared_with"].startswith("fallback")
    assert r["evidence"]["bed_max_momentary_lufs"] == pytest.approx(min(tgt + SC.ORPHAN_HEADROOM_DB,
                                                                        quiet_bed["an"]["mom_max_lufs"]), abs=0.01)


def test_rereview_breathing_ignores_silence_built_into_a_wav_and_counts_whole_windows():
    y = np.concatenate([np.zeros(3 * RATE, np.float32), _sine(600, 20.0), np.zeros(3 * RATE, np.float32)])
    b = _p("B", "bed", 0, y)
    assert b["an"]["breath_judged"] and b["an"]["breath_db"] < 0.5           # a flat drone with silence at each end
    short = _p("S", "bed", 0, _breathing(4.05))                                # 40 whole windows and a part: judged on 40
    assert short["an"]["breath_judged"]
    shorter = _p("S2", "bed", 0, _breathing(3.99))
    assert not shorter["an"]["breath_judged"]


# --------------------------------------------------------------------------
# PR #23 confirmation of ea5dfca: ambience is held to real checks
# --------------------------------------------------------------------------

def _noise(alpha, seconds=20.0, seed=0):
    """Coloured noise: 1 is pink (a crowd's spread), 2 brown (wind, all of it under 230 Hz)."""
    n = int(seconds * RATE)
    X = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    f[0] = f[1]
    y = np.fft.irfft(X / f ** (alpha / 2), n)
    return (0.05 * y / np.std(y)).astype(np.float32)


def _amb(cid, x, start=0.0, fi=2.0, fo=2.0):
    return SC.place_cue({"id": cid, "kind": "ambience", "start_s": start, "end_s": start + len(x) / RATE,
                         "fade_in_s": fi, "fade_out_s": fo, "gain_db": 0.0}, x, dict(SC.STANDARD))


def _held(x):
    """x scaled to just under the ambience ceiling (the bed target plus TOL_DB), as the probe does."""
    lvl = _amb("x", x)["an"]["integrated_unfaded_lufs"]
    return (x * np.float32(10 ** ((SC.bed_lufs(SC.STANDARD) + 0.9 - lvl) / 20))).astype(np.float32)


def test_confirm_a_bass_drone_filed_as_ambience_is_refused():
    t = np.arange(20 * RATE) / RATE
    drone = (0.3 * np.sin(2 * np.pi * 55 * t) + 0.2 * np.sin(2 * np.pi * 110 * t)
             + 0.01 * np.random.default_rng(3).standard_normal(len(t))).astype(np.float32)
    a = _amb("A", _held(drone))
    f = _fails([a], dur=20.0)
    assert ("ambience-low-end", "A") in f and ("ambience-level", "A") not in f        # loud enough to pass, not room tone
    assert a["an"]["tonal_low_share"] > 0.9


@pytest.mark.parametrize("alpha,name", [(1, "pink: a crowd"), (2, "brown: wind")])
def test_confirm_room_tone_wind_and_crowd_pass(alpha, name):
    a = _amb("A", _held(_noise(alpha)))
    assert a["an"]["tonal_low_share"] <= SC.AMB_TONAL_LOW_MAX_SHARE
    assert not {r for r in _fails([a], dur=20.0) if r[0].startswith("ambience")}, name
    assert "bed-breathing" not in {r for r, _ in _fails([a], dur=20.0)}                # breathing is for beds only


def test_confirm_the_low_end_limit_applies_under_the_voice():
    t = np.arange(20 * RATE) / RATE
    drone = _held((0.3 * np.sin(2 * np.pi * 55 * t)).astype(np.float32))
    a = _amb("A", drone, start=30.0)
    v = np.zeros(800, bool)
    assert ("ambience-low-end", "A") not in _fails([a], dur=80.0, voice100=v)        # no voice over it: not judged
    v[350:360] = True
    assert ("ambience-low-end", "A") in _fails([a], dur=80.0, voice100=v)


def test_confirm_ambience_enters_and_leaves_with_a_fade_or_a_crossfade():
    room = _held(_noise(1))
    f = _fails([_amb("A", room, fi=0.0, fo=0.5)], dur=20.0)
    assert ("music-entry", "A") in f and ("music-exit", "A") in f                     # a step from and to digital zero
    a1, a2 = _amb("A1", room, 0.0, fi=2.0, fo=0.0), _amb("A2", room, 19.8, fi=0.0, fo=2.0)
    f = _fails([a1, a2], dur=40.0)
    assert ("music-exit", "A1") not in f and ("music-entry", "A2") not in f           # one room into the next


def test_confirm_a_missing_kind_is_refused_at_top_level_and_in_a_part(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "M1.wav", _breathing(10))
    _edit_play(film, lambda p: p.update(music=[{"id": "M1", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 9.0}]))
    with pytest.raises(R.Refused, match=r"cue-kind \(M1\)"):
        _plan(film, "kind-top")
    rep = SC.offline(film, voices=False)
    assert {"rule": "cue-kind", "ok": False, "unit": "M1"}.items() <= next(
        c for c in rep["checks"] if c["rule"] == "cue-kind").items()
