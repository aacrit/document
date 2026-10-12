"""R11 (GRAMMAR A33, clip integrity): an archival line stays on its own
picture, a quote is cut on its speech edges, a shot ends on a natural
boundary (no flash, no replay, no mouth moving unheard), and a narrated shot
breathes to its source shot's end. Every rule is tested both ways: once on
bounds given as data (the rule's arithmetic), and through build_plan, the
mix and a render on a synthetic clip whose cuts and words are known to the
frame (make_media.talker)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import make_media
from conftest import HEIGHT, make_film, tone
from studio.engine import clips as C
from studio.engine import journal as J
from studio.engine import render as R


def results(res, rule, unit=None):
    return [r for r in res if r["rule"] == rule and (unit is None or r["unit"] == unit)]


def ok(res, rule, unit=None):
    got = results(res, rule, unit)
    assert got, (rule, unit)
    return all(r["ok"] for r in got)


def clip(sid, start, in_s, out_s, *, asset="CLIP", th=None, sound="mute", cut_reason=None, repeat_of=None):
    s = {"id": sid, "kind": "archive_video", "asset": asset, "start_s": start, "in_s": in_s, "out_s": out_s,
         "sound": {"mode": sound}}
    if th is not None:
        s["talking_head"] = th
    if cut_reason:
        s["cut_reason"] = cut_reason
    if repeat_of:
        s["repeat_of"] = repeat_of
    return s


def card(sid, start, dur):
    return {"id": sid, "kind": "card", "start_s": start, "dur_s": dur}


def line(lid, start, in_s, out_s, clip_id="CLIP"):
    return {"id": lid, "kind": "testimony", "archival_audio": True, "clip": clip_id, "start_s": start, "in_s": in_s, "out_s": out_s}


def check(shots, lines, bounds, items=None):
    items = items or {}
    return C.check_clips(C.norm_shots(shots, items), lines, bounds, items)


# a source: cuts at 10 and 20; a phrase 12.0 to 14.0, another 15.0 to 16.0, then 22.0 to 23.0
B = C.StaticBounds(cuts=[10.0, 20.0], speech=[(12.0, 14.0), (15.0, 16.0), (22.0, 23.0)], duration=60.0)


# --------------------------------------------------------------------------
# A33(1) archival-sync and talking-head-declared
# --------------------------------------------------------------------------


def test_a_line_on_its_own_picture_at_its_source_offset_passes():
    res = check([clip("V", 100.0, 10.0, 17.5, th=False), card("K", 107.5, 3)], [line("A", 101.85, 11.85, 14.25)], {"CLIP": B})
    assert ok(res, "archival-sync", "A") and ok(res, "talking-head-declared", "V")


def test_a_line_pushed_later_than_its_picture_is_refused_with_the_offset():
    res = check([clip("V", 100.0, 10.0, 17.5, th=False), card("K", 107.5, 3)], [line("A", 102.10, 11.85, 14.25)], {"CLIP": B})
    r = results(res, "archival-sync", "A")[0]
    assert not r["ok"] and r["severity"] == "block"
    assert r["evidence"]["shots"][0]["error_ms"] == 250                                # the debate's V:A07
    assert "in_s 9.750" in r["evidence"]["shots"][0]["fix"]


def test_one_frame_of_error_is_inside_the_tolerance_and_two_are_not():
    one = check([clip("V", 100.0, 10.0, 17.5, th=False)], [line("A", 101.85 + 0.04, 11.85, 14.25)], {"CLIP": B})
    two = check([clip("V", 100.0, 10.0, 17.5, th=False)], [line("A", 101.85 + 0.084, 11.85, 14.25)], {"CLIP": B})
    assert ok(one, "archival-sync") and not ok(two, "archival-sync")


def test_a_line_over_another_picture_has_no_sync_to_keep():
    res = check([card("K", 100.0, 10.0)], [line("A", 101.85, 11.85, 14.25)], {"CLIP": B})
    assert not results(res, "archival-sync") and not results(res, "talking-head-declared")


def test_a_quote_shot_must_say_whether_the_speaker_is_on_screen():
    res = check([clip("V", 100.0, 10.0, 17.5)], [line("A", 101.85, 11.85, 14.25)], {"CLIP": B})
    assert not ok(res, "talking-head-declared", "V")
    res = check([clip("V", 100.0, 10.0, 17.5)], [line("A", 101.85, 11.85, 14.25)], {"CLIP": B}, {"CLIP": {"talking_head": True}})
    assert ok(res, "talking-head-declared", "V")                                        # the ledger item may say it


# --------------------------------------------------------------------------
# A33(2c) quote-edges
# --------------------------------------------------------------------------


def test_a_quote_on_its_speech_edges_passes():
    res = check([clip("V", 100.0, 10.0, 20.0, th=False)], [line("A", 101.85, 11.85, 14.25)], {"CLIP": B})
    assert ok(res, "quote-edges", "A")


@pytest.mark.parametrize("in_s, out_s, says", [
    (12.3, 14.25, "cuts into speech that starts at 12.00"),                             # a caption edge: the first syllable lost
    (11.85, 15.3, "the next phrase"),                                                   # the next sentence's onset leaks in
    (11.85, 13.5, "of the word clipped"),                                               # the last word cut off
    (11.0, 14.25, "not on its edge"),                                                   # a second of the room before the words
    (11.85, 14.05, "its tail is clipped"),
    (11.98, 14.25, "attack is clipped"),
])
def test_a_quote_off_its_speech_edges_is_refused(in_s, out_s, says):
    res = check([card("K", 100.0, 10.0)], [line("A", 101.0, in_s, out_s)], {"CLIP": B})
    r = results(res, "quote-edges", "A")[0]
    assert not r["ok"] and any(says in p for p in r["evidence"]["problems"]), r["evidence"]["problems"]
    fix = r["evidence"]["fix"]
    assert (fix["in_s"], fix["out_s"]) == (11.85, 14.25)                                # the edges the source has


def test_speech_just_outside_the_span_is_refused_too():
    b = C.StaticBounds(speech=[(11.70, 11.80), (12.0, 14.0)], duration=60.0)            # a word ends 50 ms before the in point
    res = check([card("K", 100.0, 10.0)], [line("A", 101.0, 11.85, 14.25)], {"CLIP": b})
    assert not ok(res, "quote-edges")


# --------------------------------------------------------------------------
# A33(2d) reading-hold (A10(2))
# --------------------------------------------------------------------------


def test_the_picture_holds_one_and_a_half_seconds_after_the_last_word():
    # the last word ends at source 14.0, so film 102.15; the next cut must be at or after 103.65
    good = check([card("K", 100.0, 3.65), card("L", 103.65, 2)], [line("A", 100.0, 11.85, 14.25)], {"CLIP": B})
    bad = check([card("K", 100.0, 3.1), card("L", 103.1, 2)], [line("A", 100.0, 11.85, 14.25)], {"CLIP": B})
    assert ok(good, "reading-hold")
    r = results(bad, "reading-hold")[0]
    assert not r["ok"] and r["evidence"]["hold_s"] == pytest.approx(0.95) and r["evidence"]["need_s"] == 1.5


def test_where_the_source_cuts_sooner_the_hold_is_the_source_shots():
    b = C.StaticBounds(cuts=[14.4], speech=[(12.0, 14.0)], duration=60.0)
    # the source cuts 0.4 s after the last word (the debate's Neff to Katz); ending on that cut passes ...
    res = check([clip("V", 100.0, 11.0, 14.4, th=False), card("K", 103.4, 2)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": b})
    assert ok(res, "reading-hold") and results(res, "reading-hold")[0]["evidence"]["need_s"] == pytest.approx(0.4)
    # ... ending before it does not
    res = check([clip("V", 100.0, 11.0, 14.2, th=False), card("K", 103.2, 2)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": b})
    assert not ok(res, "reading-hold")


def test_a_talking_head_holds_only_the_speakers_own_pause():
    b = C.StaticBounds(speech=[(12.0, 14.0), (14.8, 16.0)], duration=60.0)             # he starts again 0.8 s later
    res = check([clip("V", 100.0, 11.0, 14.68, th=True), card("K", 103.68, 2)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": b})
    assert ok(res, "reading-hold") and ok(res, "talking-head-silent")
    res = check([clip("V", 100.0, 11.0, 14.3, th=True), card("K", 103.3, 2)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": b})
    assert not ok(res, "reading-hold")                                                  # cut before his pause is used


# --------------------------------------------------------------------------
# A33(2a) clip-flash and the open-on-a-tail warning
# --------------------------------------------------------------------------


@pytest.mark.parametrize("in_s, out_s, good", [
    (10.0, 15.0, True),             # on the cut
    (10.01, 15.0, True),            # within half a frame
    (10.08, 15.0, True),            # 0.08 s after a cut: trims, shows nothing of the other shot
    (9.5, 15.0, False),             # opens on half a second of the previous source shot
    (10.3, 15.0, False),            # starts 0.3 s after a cut: start on it
    (11.0, 20.0, True),             # ends on the cut
    (11.0, 20.5, False),            # half a second into the next source shot (Tonga 2.3)
    (11.0, 20.08, False),           # two frames into it (the debate's 2.19)
    (11.0, 19.5, False),            # ends 0.5 s before a cut: end on it
    (11.0, 18.0, True),             # two seconds short of the cut: a cut of its own
])
def test_no_shot_starts_or_ends_within_three_quarters_of_a_second_of_a_cut(in_s, out_s, good):
    res = check([clip("V", 100.0, in_s, out_s, th=False)], [], {"CLIP": B})
    assert ok(res, "clip-flash") is good


def test_the_nearest_cut_is_judged_when_two_sit_together():
    b = C.StaticBounds(cuts=[82.816, 82.983], duration=200.0)                            # Partition 1.2b: on the second
    assert ok(check([clip("V", 0.0, 83.0, 90.0, th=False)], [], {"CLIP": b}), "clip-flash")


def test_a_talking_head_may_end_in_the_speakers_pause_before_a_cut():
    b = C.StaticBounds(cuts=[20.0], speech=[(15.0, 19.3), (19.6, 19.95)], duration=60.0)   # he starts again before the cut
    res = check([clip("V", 100.0, 11.0, 19.45, th=True)], [], {"CLIP": b})
    assert ok(res, "clip-flash")                                                        # not "end on the cut": he'd talk unheard
    res = check([clip("V", 100.0, 11.0, 19.45, th=False)], [], {"CLIP": b})
    assert not ok(res, "clip-flash")


def test_opening_a_second_before_a_cut_is_a_warning():
    res = check([clip("V", 0.0, 9.0, 15.0, th=False)], [], {"CLIP": B})                  # Partition 1.1: 0.98 s of Parliament
    r = results(res, "clip-opens-on-a-tail", "V")[0]
    assert not r["ok"] and r["severity"] == "warn" and r["evidence"]["cut_s"] == 10.0
    assert ok(check([clip("V", 0.0, 9.0, 15.0, th=False, cut_reason="the arrival")], [], {"CLIP": B}), "clip-opens-on-a-tail")
    assert ok(check([clip("V", 0.0, 10.0, 15.0, th=False)], [], {"CLIP": B}), "clip-opens-on-a-tail")


# --------------------------------------------------------------------------
# A33(2b) clip-repeat
# --------------------------------------------------------------------------


def test_a_shot_never_replays_the_one_before_it():
    shots = [clip("V1", 0.0, 1.0, 5.0, th=False), clip("V2", 4.0, 4.0, 9.0, th=False)]   # Tonga 2.2 to 2.3: 1 s backwards
    res = check(shots, [], {"CLIP": C.StaticBounds(duration=60.0)})
    r = results(res, "clip-repeat", "V2")[0]
    assert not r["ok"] and r["evidence"]["replays"][0]["overlap_s"] == pytest.approx(1.0)
    shots = [clip("V1", 0.0, 1.0, 5.0, th=False), clip("V2", 4.0, 5.0, 9.0, th=False)]   # abutting: one take, continued
    assert ok(check(shots, [], {"CLIP": C.StaticBounds(duration=60.0)}), "clip-repeat")
    shots = [clip("V1", 0.0, 1.0, 5.0, th=False), clip("V2", 4.0, 4.0, 9.0, th=False, repeat_of="V1")]
    assert not ok(check(shots, [], {"CLIP": C.StaticBounds(duration=60.0)}), "clip-repeat")    # adjacent: never a refrain


def test_a_refrain_further_on_is_declared():
    shots = [clip("O1", 0.0, 0.0, 6.9, th=False), card("K", 6.9, 30), clip("C10", 36.9, 0.0, 6.9, th=False)]
    assert not ok(check(shots, [], {"CLIP": C.StaticBounds(duration=6.9)}), "clip-repeat")
    shots[-1]["repeat_of"] = "O1"
    assert ok(check(shots, [], {"CLIP": C.StaticBounds(duration=6.9)}), "clip-repeat")


# --------------------------------------------------------------------------
# A33(2e) talking-head-silent
# --------------------------------------------------------------------------


def test_a_muted_talking_head_under_narration_is_refused():
    res = check([clip("V", 0.0, 11.0, 17.0, th=True)], [], {"CLIP": B})                  # the debate's 2.18
    r = results(res, "talking-head-silent", "V")[0]
    assert not r["ok"] and r["evidence"]["unheard_s"] == pytest.approx(3.0)


def test_a_talking_head_heard_whole_passes_and_one_that_runs_on_does_not():
    good = check([clip("V", 100.0, 11.0, 14.5, th=True)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": B})
    assert ok(good, "talking-head-silent")
    on = check([clip("V", 100.0, 11.0, 15.6, th=True)], [line("A", 100.85, 11.85, 14.25)], {"CLIP": B})
    r = results(on, "talking-head-silent", "V")[0]
    assert not r["ok"] and r["evidence"]["unheard_speech_source_s"] == [[15.0, 15.6]]
    assert not results(check([clip("V", 0.0, 11.0, 17.0, th=False)], [], {"CLIP": B}), "talking-head-silent")
    # with its own sound playing, every word the mouth makes is heard
    assert not results(check([clip("V", 0.0, 11.0, 17.0, th=True, sound="own")], [], {"CLIP": B}), "talking-head-silent")


# --------------------------------------------------------------------------
# A33(3) clip-cut-mid-action (a warning)
# --------------------------------------------------------------------------


def test_a_shot_cut_well_before_its_source_shot_ends_is_warned():
    res = check([clip("V", 0.0, 11.0, 16.0, th=False)], [], {"CLIP": B})
    r = results(res, "clip-cut-mid-action", "V")[0]
    assert not r["ok"] and r["severity"] == "warn" and r["evidence"]["left_unplayed_s"] == pytest.approx(4.0)
    for s in (clip("V", 0.0, 11.0, 20.0, th=False), clip("V", 0.0, 11.0, 19.2, th=False, cut_reason="the next scene"),
              clip("V", 0.0, 11.0, 19.0, th=False)):
        assert ok(check([s], [], {"CLIP": B}), "clip-cut-mid-action"), s
    cont = [clip("V1", 0.0, 11.0, 16.0, th=False), clip("V2", 5.0, 16.0, 20.0, th=False)]    # Partition 1.1 into 1.2
    assert ok(check(cont, [], {"CLIP": B}), "clip-cut-mid-action", "V1")
    held = check([clip("V", 0.0, 0.0, 6.9, th=False)], [], {"CLIP": C.StaticBounds(duration=5.0)})   # Partition O1: played out,
    assert ok(held, "clip-cut-mid-action")                                                         # then a held last frame
    assert ok(check(cont, [], {"CLIP": B}), "clip-cut-mid-action", "V1")


# --------------------------------------------------------------------------
# A33(1b) av_offset_ms and its correction
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ms, corr", [(None, 0.0), (0, 0.0), (99, 0.0), (120, 0.0), (-45, 0.0), (130, 0.05), (380, 0.3),
                                      (-60, -0.14), ("80", 0.0)])
def test_a_correction_only_outside_the_detectability_window(ms, corr):
    assert C.av_correction_s({"av_offset_ms": ms} if ms is not None else {}) == pytest.approx(corr)


def test_av_offset_is_stated_on_a_talking_head_clip_and_must_be_a_number():
    shots, lines = [clip("V", 100.0, 10.0, 17.5, th=True)], [line("A", 101.85, 11.85, 14.25)]
    r = results(check(shots, lines, {"CLIP": B}), "av-offset", "CLIP")[0]
    assert not r["ok"] and r["severity"] == "warn"
    assert ok(check(shots, lines, {"CLIP": B}, {"CLIP": {"av_offset_ms": 99}}), "av-offset")
    r = results(check(shots, lines, {"CLIP": B}, {"CLIP": {"av_offset_ms": "late"}}), "av-offset", "CLIP")[0]
    assert not r["ok"] and r["severity"] == "block"


# --------------------------------------------------------------------------
# What a builder calls
# --------------------------------------------------------------------------


def test_natural_out_waits_for_the_first_cut_in_reach():
    assert C.natural_out(B, 16.0)["out_s"] == 20.0                                       # 4 s after the last word: in reach
    far = C.natural_out(C.StaticBounds(cuts=[30.0], duration=60.0), 16.0)
    assert far["out_s"] == 17.5 and far["cut_reason"]                                    # none within 6 s: 1.5 s and a reason
    near = C.natural_out(C.StaticBounds(cuts=[16.4, 30.0], duration=60.0), 16.0)
    assert near["out_s"] == 16.4 and near["on"] == "cut"                                 # the source's own shot ends first
    end = C.natural_out(C.StaticBounds(duration=19.0), 16.0)
    assert end["out_s"] == 19.0 and end["on"] == "clip end"
    th = C.natural_out(C.StaticBounds(cuts=[20.0], speech=[(12.0, 16.0), (16.9, 18.0)], duration=60.0), 16.0, talking_head=True)
    assert th["out_s"] == pytest.approx(16.78) and th["on"] == "speaker's pause"


def test_breathe_out_plays_to_the_source_shots_end_unless_it_is_far():
    assert C.breathe_out(B, 15.0) == {"out_s": 20.0, "on": "cut", "cut_reason": None, "breath_s": 5.0}
    far = C.breathe_out(C.StaticBounds(cuts=[30.0], duration=60.0), 15.0)
    assert far["out_s"] == 15.0 and far["cut_reason"]
    flash = C.breathe_out(C.StaticBounds(cuts=[14.7, 40.0], duration=60.0), 15.0)
    assert flash["out_s"] == 14.7                                                        # never 0.3 s into the next shot


def test_snap_in_and_quote_edges():
    assert C.snap_in(B, 9.4) == {"in_s": 10.0, "on": "cut"} and C.snap_in(B, 12.0) == {"in_s": 12.0, "on": None}
    assert C.quote_edges(B, 12.0, 14.0) == {"in_s": 11.85, "out_s": 14.25}
    tight = C.StaticBounds(speech=[(11.8, 11.9), (12.0, 14.0), (14.2, 15.0)])
    e = C.quote_edges(tight, 12.0, 14.0)
    assert e["in_s"] >= 11.9 and e["out_s"] <= 14.2


# --------------------------------------------------------------------------
# --fit-voices keeps an archival line on its picture
# --------------------------------------------------------------------------


def _fit_film(tmp_path, shots, lines):
    film = tmp_path / "fit"
    (film / "audio").mkdir(parents=True)
    for ln in lines:
        if not ln.get("archival_audio"):
            tone(film / "audio" / f"{ln['id']}.wav", ln.pop("_dur"))
    play = {"parts": [{"id": "p", "shots": shots, "lines": lines, "cues": [], "text": []}], "subtitle_source": []}
    return film, play


def _sync_errors(play):
    shots = [dict(s, _dur=(s["out_s"] - s["in_s"]) if s["kind"] == "archive_video" else s["dur_s"]) for s in play["parts"][0]["shots"]]
    lines = [x for x in play["parts"][0]["lines"] if x.get("archival_audio")]
    return [e["error_ms"] for r in results(check(shots, lines, {}), "archival-sync") for e in r["evidence"]["shots"]]


def test_fit_voices_lengthens_the_shot_before_a_clip_instead_of_sliding_the_line(tmp_path):
    shots = [{"id": "P0", "kind": "card", "start_s": 0.0, "dur_s": 4.0}, clip("V1", 4.0, 10.0, 16.0)]
    lines = [{"id": "N1", "kind": "narration", "start_s": 2.0, "text": "x", "_dur": 2.5}, line("A1", 4.5, 10.5, 13.0)]
    film, play = _fit_film(tmp_path, shots, lines)
    assert _sync_errors(play) == [0]
    j = J.Journal(film="fit-shift")
    fitted = R.fit_voices(play, film, j)
    sh = {s["id"]: s for s in fitted["parts"][0]["shots"]}
    ln = {x["id"]: x for x in fitted["parts"][0]["lines"]}
    assert sh["P0"]["dur_s"] == pytest.approx(4.8) and sh["V1"]["start_s"] == pytest.approx(4.8)
    assert (sh["V1"]["in_s"], sh["V1"]["out_s"]) == (10.0, 16.0) and ln["A1"]["start_s"] == pytest.approx(5.3)
    assert _sync_errors(fitted) == [0]
    d = [e for e in J.read(j.path) if e["kind"] == "decision"][0]
    assert d["mode"] == "lengthen-previous" and d["lengthened"] == "P0"


def test_fit_voices_opens_the_clip_earlier_when_the_collision_is_inside_it(tmp_path):
    shots = [clip("V1", 0.0, 10.0, 16.0)]
    lines = [{"id": "N1", "kind": "narration", "start_s": 0.5, "text": "x", "_dur": 2.0}, line("A1", 2.8, 12.8, 14.0)]
    film, play = _fit_film(tmp_path, shots, lines)
    j = J.Journal(film="fit-in")
    fitted = R.fit_voices(play, film, j)
    v1 = fitted["parts"][0]["shots"][0]
    assert v1["in_s"] == pytest.approx(9.5) and v1["out_s"] == 16.0
    assert {x["id"]: x["start_s"] for x in fitted["parts"][0]["lines"]}["A1"] == pytest.approx(3.3)
    assert _sync_errors(fitted) == [0]
    assert [e for e in J.read(j.path) if e["kind"] == "decision"][0]["mode"] == "shift-in-point"


def test_fit_voices_never_pulls_two_lines_of_one_take_apart(tmp_path):
    shots = [clip("V1", 0.0, 10.0, 16.0)]
    lines = [line("A1", 1.0, 11.0, 13.0), line("A2", 3.2, 13.2, 14.0)]
    film, play = _fit_film(tmp_path, shots, lines)
    j = J.Journal(film="fit-none")
    fitted = R.fit_voices(play, film, j)
    assert fitted == play and _sync_errors(fitted) == [0, 0]
    d = [e for e in J.read(j.path) if e["kind"] == "decision"]
    assert d and "did not move A2" in d[0]["what"]
    assert R.voice_collisions(R.voice_lines(fitted, film))                               # the voice-overlap lint still refuses


def test_fit_voices_still_grows_a_clip_with_no_archival_line_after_the_insertion(tmp_path):
    shots = [clip("V1", 0.0, 10.0, 16.0)]
    lines = [{"id": "N1", "kind": "narration", "start_s": 0.5, "text": "x", "_dur": 2.0},
             {"id": "N2", "kind": "narration", "start_s": 2.8, "text": "y", "_dur": 1.0}]
    film, play = _fit_film(tmp_path, shots, lines)
    v1 = R.fit_voices(play, film, J.Journal(film="fit-grow"))["parts"][0]["shots"][0]
    assert (v1["in_s"], v1["out_s"]) == (10.0, pytest.approx(16.5))


# --------------------------------------------------------------------------
# Measured on a real (synthetic) clip
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def talk(tmp_path_factory):
    d = tmp_path_factory.mktemp("talk")
    return make_media.talker(d / "talk.mkv", words=((1.0, 1.8), (4.6, 6.2), (7.5, 8.3)))


def test_bounds_finds_the_cuts_and_words_and_keeps_them_in_a_sidecar(talk, tmp_path):
    b = C.ClipBounds(talk, tmp_path / "bounds")
    assert b.cuts() == [4.0, 7.0]                                                        # to the frame
    sp = b.speech(0, 12)
    want = [(1.0, 1.8), (4.6, 6.2), (7.5, 8.3)]
    assert len(sp) == 3 and all(abs(a - x) <= 0.02 and abs(z - y) <= 0.02 for (a, z), (x, y) in zip(sp, want)), sp
    assert b.analysed_now == [0] and b.sidecar.name == f"talk.{R.edge_digest(talk)[:16]}.json" and b.sidecar.exists()
    again = C.ClipBounds(talk, tmp_path / "bounds")
    assert again.cuts() == [4.0, 7.0] and again.analysed_now == []                       # read from the sidecar, not measured
    other = tmp_path / "other.mkv"
    make_media.talker(other, seconds=6.0, cuts=(2.0,), words=())
    ob = C.ClipBounds(other, tmp_path / "bounds")
    assert ob.sidecar != b.sidecar and ob.cuts() == [2.0] and ob.speech(0, 6) == []      # keyed by the source's own bytes


def test_a_long_clip_is_analysed_only_where_a_shot_needs_it(tmp_path):
    reel = make_media.talker(tmp_path / "reel.mkv", seconds=65.0, cuts=(10.0, 33.0, 50.0), words=((34.0, 35.0),), size="160x120")
    b = C.ClipBounds(reel, tmp_path / "bounds")
    sp = b.speech(31.0, 36.0)
    assert len(sp) == 1 and sp[0] == pytest.approx((34.0, 35.0), abs=0.02) and b.analysed_now == [1]   # 30 to 60 s, never the reel
    assert b.cuts(30.0, 60.0) == [33.0, 50.0] and b.analysed_now == [1]
    res = check([clip("V", 0.0, 31.0, 38.0, th=False)], [], {"CLIP": b})
    assert results(res, "clip-cut-mid-action")[0]["evidence"]["source_shot_ends_s"] == 50.0
    assert b.analysed_now == [1, 2]                                                      # the natural end, 25 s on at most


def test_extra_cuts_from_the_ledger_join_the_measured_ones(talk, tmp_path):
    b = C.ClipBounds(talk, tmp_path / "bounds", extra_cuts=[9.5])
    assert b.cuts() == [4.0, 7.0, 9.5]
    assert C.extra_cuts_of({"extra_cuts": [9.5]}) == ([9.5], None) and C.extra_cuts_of({"extra_cuts": ["x"]})[1]


def _talk_film(tmp_path, talk, *, line_start=15.2, in_s=4.45, out_s=6.45, s6=None, item=None):
    """The fixture film with S6 cut from the talker (in 4.0, out 7.0: one source shot, cut to cut) and an archival line A1
    playing the talker's words 4.6 to 6.2 on that picture."""
    film = make_film(tmp_path / "talkfilm")
    shutil.copy(talk, film / "footage" / "fx-talk.mkv")
    (film / "transcripts").mkdir()
    (film / "transcripts" / "fx-talk.txt").write_text("00:00:04.400 --> 00:00:06.500 | Words of the fixture talker.\n", encoding="utf-8")

    def ledger(d):
        it = dict({"id": "FX-TALK", "file": "fx-talk.mkv", "title": "Synthetic talker, test fixture", "date": "2026",
                                "archive": "studio test fixture", "archive_short": "test fixture", "licence": "CC0", "synthetic": True,
                                "test_fixture": True, "telecined": False, "people": False, "shows_bodies": False,
                                "talking_head": True, "av_offset_ms": 80, "transcript_file": "transcripts/fx-talk.txt"},
                   **(item or {}))
        d["items"].append({k: v for k, v in it.items() if v is not None})              # None: the key left out
        for x in d["items"]:
            x.update(graphic_medical=False, named_patient=False, shows_violence=False)
    p = film / "footage-ledger.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    ledger(d)
    p.write_text(json.dumps(d), encoding="utf-8")
    p = film / "stills-ledger.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for x in d["items"]:
        x.update(graphic_medical=False, named_patient=False, shows_violence=False)
    p.write_text(json.dumps(d), encoding="utf-8")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    ch = play["parts"][1]
    s = next(x for x in ch["shots"] if x["id"] == "S6")
    s.update(dict({"asset": "FX-TALK", "in_s": 4.0, "out_s": 7.0, "native_fps": 24,
                   "sound": {"mode": "mute", "reason": "the archival line A1 plays this span (A26)"}}, **(s6 or {})))
    ch["text"] = [t for t in ch["text"] if t["id"] not in ("T1", "T2")]
    play["subtitle_source"] = [c for c in play["subtitle_source"] if c["ref"] not in ("T1", "T2")]
    play["cast"]["speakers"].append({"id": "sp-talk", "name": "Fixture talker", "side": "usa", "gender": "m"})
    ch["lines"].append({"id": "A1", "kind": "testimony", "speaker": "sp-talk", "year": 2026, "archival_audio": True,
                        "clip": "FX-TALK", "in_s": in_s, "out_s": out_s, "start_s": line_start, "text": "Words of the fixture talker.",
                        "source": "FX-TALK", "transcript_source": "fixture transcript (transcripts/fx-talk.txt)"})
    ch["text"].append({"id": "T3", "kind": "lower_third", "start_s": line_start, "end_s": line_start + 2.0,
                       "lines": ["Fixture talker", "Test talker, 2026", "Fixture talker, studio test folder  ·  original recording"]})
    play["subtitle_source"].append({"ref": "A1", "start_s": line_start, "end_s": line_start + out_s - in_s,
                                    "en": "Words of the fixture talker."})
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def _plan(film, name):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


A33_RULES = ("archival-sync", "talking-head-declared", "quote-edges", "reading-hold", "clip-flash", "talking-head-silent",
             "clip-repeat", "clip-cut-mid-action", "clip-opens-on-a-tail", "av-offset")


def test_a_clip_on_its_natural_boundaries_with_its_words_whole_passes_every_a33_lint(talk, tmp_path):
    plan, j = _plan(_talk_film(tmp_path, talk), "a33-good")
    evs = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("grammar") == "A33"]
    for rule in A33_RULES:
        got = [e for e in evs if e["rule"] == rule]
        assert got and {e["status"] for e in got} == {"pass"}, (rule, got)
    assert plan["clip_integrity"]["warnings"] == []
    assert any(e["kind"] == "decision" and "analysed fx-talk.mkv" in e["what"] for e in J.read(j.path))


@pytest.mark.parametrize("change, rule", [
    ({"line_start": 15.45}, "archival-sync"),                                            # the line 0.25 s late on its picture
    ({"in_s": 4.75, "line_start": 15.5}, "quote-edges"),                                 # 0.15 s of the first word cut
    ({"s6": {"in_s": 3.5, "out_s": 6.5}, "line_start": 15.7}, "clip-flash"),             # opens on 0.5 s of the previous shot
    ({"item": {"talking_head": None}}, "talking-head-declared"),                         # nobody says if the mouth is seen
])
def test_a_clip_off_its_boundaries_is_refused_at_plan_time(talk, tmp_path, change, rule):
    film = _talk_film(tmp_path, talk, **change)
    with pytest.raises(R.Refused, match=rf"{rule} \((A1|S6)\)"):
        _plan(film, rule)


def test_the_mix_places_a_resynced_span_earlier_by_its_correction(talk, tmp_path):
    film = _talk_film(tmp_path, talk, item={"av_offset_ms": 380})                        # 300 ms late beyond its natural lag
    plan, j = _plan(film, "a33-resync")
    mix, placed = R.build_mix(plan, film, j)
    a1 = next(x for x in placed["lines"] if x["id"] == "A1")
    assert a1["at_s"] == pytest.approx(15.2 - 0.3)
    onset = next(i for i in range(int(14.0 * 48000), len(mix)) if abs(mix[i]) > 1e-3) / 48000
    assert onset == pytest.approx(15.2 - 0.3 + (4.6 - 4.45), abs=0.02)                   # the first word 0.3 s earlier
    dec = [e for e in J.read(j.path) if e["kind"] == "decision" and e.get("unit") == "A1" and "placed" in e["what"]]
    assert dec and dec[0]["evidence"]["correction_s"] == pytest.approx(0.3)
    assert next(r for r in R.readings_doc(plan) if r["id"] == "A1")["av_correction_ms"] == 300


# --------------------------------------------------------------------------
# Measured in a master (A33(1c)) and on the lips (A33(1b))
# --------------------------------------------------------------------------


def _master(src: Path, dest: Path, at: float, dur: float, audio_shift: float = 0.0, still: bool = False) -> Path:
    """A 640x360 24 fps "master" of [at, at + dur] of src, pillarboxed as the engine fits 4:3, its sound taken
    ``audio_shift`` s later in the source (positive: the sound runs ahead of the picture)."""
    vf = "fps=24,scale=480:360,pad=640:360:80:0" + (",trim=end_frame=1,loop=loop=-1:size=1,trim=duration=" + str(dur) if still else "")
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-ss", f"{at}", "-t", f"{dur}", "-i", str(src),
                    "-ss", f"{at + audio_shift}", "-t", f"{dur}", "-i", str(src), "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", str(dest)], check=True, capture_output=True)
    return dest


@pytest.mark.parametrize("shift, late", [(0.0, 0), (0.25, -250), (-0.25, 250)])
def test_the_master_is_measured_picture_against_sound(talk, tmp_path, shift, late):
    m = _master(talk, tmp_path / "m.mp4", 4.0, 3.0, shift)
    got = C.measure_sync(m, 0.15, 2.6, talk, 0.0, 4.0, 0.0, "480:360:80:0")
    assert got["conclusive"] and got["audio_late_ms"] == pytest.approx(late, abs=C.RENDER_SYNC_TOL_MS), got


def test_a_still_picture_cannot_be_measured_and_says_so(talk, tmp_path):
    m = _master(talk, tmp_path / "m.mp4", 4.0, 3.0, 0.0, still=True)
    assert not C.measure_sync(m, 0.15, 2.6, talk, 0.0, 4.0, 0.0, "480:360:80:0")["conclusive"]


def _sync_plan(talk, corr_ms=None):
    item = {"_path": str(talk)} | ({"av_offset_ms": corr_ms} if corr_ms is not None else {})
    return {"W": 640, "H": 360, "assets": {"T": item},
            "shots": [{"id": "V", "kind": "archive_video", "asset": "T", "f0": 0, "f1": 72, "in_s": 4.0, "_item": item,
                       "_video": {"fit": [480, 360]}}],
            "lines": [{"id": "A", "archival_audio": True, "clip": "T", "in_s": 4.45, "out_s": 6.85, "start_s": 0.45}]}


def test_a_final_render_refuses_a_line_heard_off_its_picture_and_a_draft_journals_it(talk, tmp_path):
    good = _master(talk, tmp_path / "good.mp4", 4.0, 3.0, 0.0)
    bad = _master(talk, tmp_path / "bad.mp4", 4.0, 3.0, -0.25)                            # the sound 250 ms late
    j = J.Journal(film="sync-good")
    assert C.rendered_sync_lints(j, _sync_plan(talk), good) == []
    e = [x for x in J.read(j.path) if x.get("rule") == "archival-sync-rendered"][0]
    assert e["status"] == "pass" and e["severity"] == "block" and e["phase"] == "post-render"
    j = J.Journal(film="sync-bad")
    ref = C.rendered_sync_lints(j, _sync_plan(talk), bad)
    assert ref and "+2" in ref[0]
    j = J.Journal(film="sync-draft")
    assert C.rendered_sync_lints(j, _sync_plan(talk), bad, draft=True) == []
    e = [x for x in J.read(j.path) if x.get("rule") == "archival-sync-rendered"][0]
    assert e["status"] == "fail" and e["severity"] == "warn"
    # a span re-synced by 300 ms is expected 300 ms early, not in step with the uncorrected source
    j = J.Journal(film="sync-corr")
    assert C.rendered_sync_lints(j, _sync_plan(talk, corr_ms=380), good)


def _lips(dest: Path, delay_s: float, seconds: float = 8.0, fps: float = 30000 / 1001) -> Path:
    """A synthetic talking head: a textured face whose dark mouth opens with a syllable envelope, and a noise voice
    following the same envelope ``delay_s`` later (positive: the sound is late)."""
    import soundfile as sf
    rng = np.random.default_rng(7)
    on = np.sort(rng.uniform(0.2, seconds - 0.6, 26))

    def env(t):
        return np.clip(sum(np.exp(-0.5 * ((t - c) / 0.07) ** 2) for c in on), 0, 1)
    W, H = 200, 150
    tex = (rng.random((H, W)) * 60 + 60).astype(np.float32)
    n = int(seconds * fps)
    frames = np.empty((n, H, W), np.uint8)
    yy, xx = np.mgrid[0:H, 0:W]
    for k in range(n):
        f = tex.copy()
        f[30:130, 50:150] = 185 + (tex[30:130, 50:150] - 90) * 0.2                         # the face, lit
        f[45:60, 70:90] = 40
        f[45:60, 110:130] = 40                                                             # eyes, for the tracker
        h = 2 + 18 * env(k / fps)
        f[((xx - 100) / 22) ** 2 + ((yy - 100) / h) ** 2 <= 1] = 15                        # the mouth
        frames[k] = f.clip(0, 255)
    sr = 48000
    t = np.arange(int(seconds * sr)) / sr
    voice = (rng.standard_normal(len(t)) * 0.2 * env(t - delay_s)).astype(np.float32)
    wav = dest.with_suffix(".wav")
    sf.write(str(wav), voice, sr)
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", f"{fps}",
                    "-i", "-", "-i", str(wav), "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "pcm_s16le", str(dest)], input=frames.tobytes(), check=True, capture_output=True)
    return dest


@pytest.mark.parametrize("delay", [0.0, 0.2, -0.15])
def test_lipsync_measures_how_late_the_sound_runs_behind_the_lips(tmp_path, delay):
    clip_ = _lips(tmp_path / "lips.mkv", delay)
    m = C.lip_offset(clip_, 0.3, 7.2, face=(45, 25, 155, 135), mouth=(75, 80, 125, 122))
    assert m["av_offset_ms"] == pytest.approx(delay * 1000, abs=35), m
    assert m["r"] > 0.5


def test_lipsync_writes_the_ledger_only_when_asked(tmp_path):
    film = tmp_path / "f"
    film.mkdir()
    (film / "footage-ledger.json").write_text(json.dumps({"items": [{"id": "X", "file": "x.mkv"}]}), encoding="utf-8")
    play = {"ledgers": {"footage": "footage-ledger.json"}}
    C.write_av_offset(film, play, "X", {"av_offset_ms": 99, "r": 0.3, "window_s": [4.3, 15.9]})
    it = json.loads((film / "footage-ledger.json").read_text(encoding="utf-8"))["items"][0]
    assert it["av_offset_ms"] == 99 and it["av_offset_measure"]["window_s"] == [4.3, 15.9]
    with pytest.raises(KeyError):
        C.write_av_offset(film, play, "Y", {"av_offset_ms": 1})


# --------------------------------------------------------------------------
# The render: re-measured in the final master and journaled
# --------------------------------------------------------------------------


def test_a_render_measures_every_archival_line_on_its_own_picture(talk, tmp_path):
    film = _talk_film(tmp_path, talk)
    s = R.render(film, tmp_path / "out", height=HEIGHT, workers=2, min_free_gb=1, encode_preset="veryfast", draft=True)
    evs = J.read(Path(s["journal"]))
    got = [e for e in evs if e.get("rule") == "archival-sync-rendered"]
    assert len(got) == 1 and got[0]["unit"] == "A1" and got[0]["status"] == "pass", got
    assert abs(got[0]["evidence"]["audio_late_ms"]) <= C.RENDER_SYNC_TOL_MS
    assert s["clip_warnings"] == []


# --------------------------------------------------------------------------
# R12 (A34): a FILL clip is measured where its framing is still
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def late_talk(tmp_path_factory):
    d = tmp_path_factory.mktemp("late-talk")
    return make_media.talker(d / "late.mkv", words=((8.8, 9.6), (10.0, 10.9), (11.1, 11.8)))


def _held_fill_master(src: Path, dest: Path, window, audio_shift: float = 0.0) -> Path:
    """The first 12 s of src as a FILL holds it: the end window cropped out and scaled to 640x360."""
    x0, y0, x1, y1 = (int(round(v)) for v in window)
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-t", "12", "-i", str(src), "-ss", f"{audio_shift}", "-t", "12", "-i", str(src),
                    "-map", "0:v:0", "-map", "1:a:0", "-vf", f"fps=24,crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale=640:360",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", str(dest)], check=True, capture_output=True)
    return dest


def _fill_plan(src, cam, line_in, line_out):
    item = {"_path": str(src)}
    return {"W": 640, "H": 360, "assets": {"T": item},
            "shots": [{"id": "V", "kind": "archive_video", "asset": "T", "f0": 0, "f1": 288, "in_s": 0.0, "_item": item,
                       "_video": {"fit": [480, 360]}, "_cam": cam}],
            "lines": [{"id": "A", "archival_audio": True, "clip": "T", "in_s": line_in, "out_s": line_out, "start_s": line_in}]}


def test_a34_a_fill_clip_is_measured_on_its_held_fill_and_never_on_the_move(late_talk, tmp_path):
    cam = R.fill_camera({"id": "V", "_dur": 12.0}, (320, 240), 640, 360, max_upscale=3.0)
    assert cam["fill"]["full"]
    assert cam["open_s"] + cam["move_s"] == pytest.approx(8.5)
    good = _held_fill_master(late_talk, tmp_path / "good.mp4", cam["fill"]["end_window_px"])
    j = J.Journal(film="fill-sync")
    assert C.rendered_sync_lints(j, _fill_plan(late_talk, cam, 8.65, 11.95), good) == []
    e = [x for x in J.read(j.path) if x.get("rule") == "archival-sync-rendered"][0]
    assert e["status"] == "pass" and e["evidence"]["audio_late_ms"] == pytest.approx(0, abs=C.RENDER_SYNC_TOL_MS)
    bad = _held_fill_master(late_talk, tmp_path / "bad.mp4", cam["fill"]["end_window_px"], audio_shift=-0.25)
    assert C.rendered_sync_lints(J.Journal(film="fill-sync-bad"), _fill_plan(late_talk, cam, 8.65, 11.95), bad)
    j = J.Journal(film="fill-sync-move")                                                   # the line sits on the move
    assert C.rendered_sync_lints(j, _fill_plan(late_talk, cam, 3.0, 7.0), good) == []
    e = [x for x in J.read(j.path) if x.get("rule") == "archival-sync-rendered"][0]
    assert e["status"] == "inconclusive" and "move" in e["evidence"]["why"]
