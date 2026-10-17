"""A29 take (ticket S3, S4, S5, S7; founder 2026-10-17: "Whole, with room
tone."): a film's score as one continuous take, placed whole at 0 and judged
by its spans and its rest map. Small synthetic stems only (a dark room tone
under soft tones that rise and fall in dB, as a composed niente entry does),
no film render."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import make_film
from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC

RATE = 48000
STD = dict(SC.STANDARD)
ROOM_RMS = 1e-3                     # the room tone, about -60 dBFS (whole.py levels it to -58 LUFS)


def _room(seconds, seed=11):
    """A dark room tone: seeded noise low-passed at 1 kHz (nothing over 5 kHz to speak of, as a quiet room)."""
    x = np.random.default_rng(seed).standard_normal(int(seconds * RATE))
    x = SC._filtered(x, lambda f: SC.butter_mag(f, 1000.0, 4, "low"))
    return (x / np.sqrt(np.mean(x.astype(np.float64) ** 2)) * ROOM_RMS).astype(np.float32)


def _swell(seconds, *, amp, rise=3.5, fall=3.5, hz=(440.0, 660.0), breathe=False, from_db=-25.0):
    """Tones that rise from ``from_db`` to full over ``rise`` (linear in dB: composed, niente), hold, and fall back
    over ``fall``; ``breathe`` adds a slow 6 dB swell (a bed's breath). Zero before the rise and after the fall."""
    t = np.arange(int(seconds * RATE)) / RATE
    db = np.where(t < rise, from_db * (1 - t / rise), np.where(t > seconds - fall, from_db * (t - (seconds - fall)) / fall, 0.0))
    env = 10 ** (db / 20)
    if breathe:
        env = env * 10 ** ((-3 + 3 * np.cos(2 * np.pi * 0.4 * t)) / 20)
    x = sum(np.sin(2 * np.pi * f * t) for f in hz) / len(hz)
    return (amp * env * x).astype(np.float32)


# the 40 s fixture take: three rests of 8 s or more, a transition and the bed it leads into
SPANS = [{"id": "tr-1", "role": "transition", "start_s": 8.5, "end_s": 16.0, "marks_moment": "turn"},
         {"id": "bed-1", "role": "bed", "start_s": 24.5, "end_s": 32.0, "marks_moment": "establish"}]
RESTS = [{"id": "r1", "start_s": 0.0, "end_s": 8.5, "why": "the cold open: the room alone"},
         {"id": "r2", "start_s": 16.0, "end_s": 24.5, "why": "the record speaks for itself"},
         {"id": "r3", "start_s": 32.0, "end_s": 40.0, "why": "the close: the room alone"}]


def _stem(seconds=40.0, *, zero=None):
    """The fixture take: the room tone under everything, the transition (quieter) and the bed placed on their spans.
    ``zero`` (a, b) cuts digital zero into it."""
    y = _room(seconds)
    # the bed louder than the transition that leads into it, and in other notes (a theme developed, not repeated)
    for sp, amp, breathe, hz in ((SPANS[0], 0.03, False, (440.0, 660.0)), (SPANS[1], 0.07, True, (523.25, 784.0))):
        s = _swell(sp["end_s"] - sp["start_s"], amp=amp, breathe=breathe, hz=hz)
        i = int(sp["start_s"] * RATE)
        y[i: i + len(s)] += s
    if zero:
        y[int(zero[0] * RATE): int(zero[1] * RATE)] = 0.0
    return y


MANIFEST = {"room_tone": {"kind": "recording", "recording": "Freesound 329569, 'Roomtone Bedroom Yew' by leonelmail",
                          "licence": "CC0 (the sound page's licence line, read 2026-10-17)",
                          "licence_source": "https://freesound.org/people/leonelmail/sounds/329569/",
                          "credit_line": "room tone: leonelmail on Freesound (CC0)", "sha256": "0" * 64},
            "room_ir": {"source": "Aachen Impulse Response Database 1.4, lecture room", "licence": "MIT",
                        "url": "https://www.iks.rwth-aachen.de/air", "credit_line": "room: Aachen AIR 1.4 (MIT)"}}


def _take(spans=SPANS, rests=RESTS, manifest=MANIFEST, tid="score"):
    return {"id": tid, "wav": "score/score.whole.wav", "spans": [dict(s) for s in spans], "rests": [dict(r) for r in rests],
            "manifest": manifest, "paths": {}}


def _write(path, x):
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, RATE, subtype="FLOAT")
    return path


def _files(film, *, rests=RESTS, manifest=MANIFEST, stem=None):
    _write(film / "score" / "score.whole.wav", _stem() if stem is None else stem)
    (film / "score" / "score.spans.json").write_text(json.dumps(SPANS), encoding="utf-8")
    (film / "score" / "score.rests.json").write_text(json.dumps(rests), encoding="utf-8")
    (film / "score" / "score.take.json").write_text(json.dumps(manifest), encoding="utf-8")


def _take_cue(end_s=40.0, **kw):
    return {"id": "score", "kind": "music", "role": "underscore", "score_role": "take", "take": True,
            "source": "score/real-world.yaml", "licence": "CC0", "performer": "the house chamber group",
            "start_s": 0.0, "end_s": end_s, "wav": "score/score.whole.wav", "spans": "score/score.spans.json",
            "rests": "score/score.rests.json", "manifest": "score/score.take.json", **kw}


def _get(checks, rule, unit):
    return next(c for c in checks if c["rule"] == rule and c["unit"] == unit)


# --------------------------------------------------------------------------
# The cue and its files
# --------------------------------------------------------------------------

def test_a_take_states_all_three_and_is_its_own_role():
    c = _take_cue()
    assert SC.cue_role(c) == "take" and SC.role_problem(c) is None
    assert SC.role_problem(dict(c, score_role="bed")) is not None              # take: true needs score_role take
    assert SC.role_problem({k: v for k, v in c.items() if k != "take"}) is not None   # score_role take needs take: true
    assert SC.role_problem(dict(c, role="house_motif")) is not None
    assert SC.role_problem(dict(c, take="yes")) is not None
    assert SC.role_problem(dict(c, marks_moment="x")) is not None
    assert "take" in SC.FILM_LAYER                                              # bed-reuse: the film's own score


def test_the_take_is_anchored_at_zero_with_no_gain_and_no_fades():
    assert SC.take_cue_problems(_take_cue(), 40.0) == []
    assert any("gain_db" in p for p in SC.take_cue_problems(_take_cue(gain_db=-1.0), 40.0))
    assert any("anchored at 0" in p for p in SC.take_cue_problems(_take_cue(start_s=0.5), 40.0))
    assert any("fade_in_s" in p and "niente" in p for p in SC.take_cue_problems(_take_cue(fade_in_s=2.0), 40.0))
    assert any("to its end" in p for p in SC.take_cue_problems(_take_cue(end_s=30.0), 40.0))


def test_load_take_reads_the_maps_and_names_what_is_wrong(tmp_path):
    film = tmp_path / "film"
    _files(film)
    tk, probs = SC.load_take(film, _take_cue())
    assert probs == [] and [s["id"] for s in tk["spans"]] == ["tr-1", "bed-1"] and len(tk["rests"]) == 3
    (film / "score" / "score.spans.json").write_text(json.dumps([{"id": "x", "role": "title", "start_s": 1, "end_s": 2}]),
                                                     encoding="utf-8")
    (film / "score" / "score.rests.json").write_text(json.dumps([{"id": "r", "start_s": 0, "end_s": 9}]), encoding="utf-8")
    tk, probs = SC.load_take(film, _take_cue())
    assert any("role 'title'" in p for p in probs) and any("says why" in p for p in probs)
    tk, probs = SC.load_take(film, _take_cue(manifest="score/nowhere.json"))
    assert tk is None and any("is not there" in p for p in probs)


def test_the_handover_rest_covers_the_slot_and_eight_seconds_after():
    rest = {"id": "h", "start_s": 10.0, "end_s": 28.0, "why": "A40 handover: the title carries the room"}
    assert SC.take_handover(_take(rests=RESTS + [rest]), 10.0, 20.0)["id"] == "h"
    assert SC.take_handover(_take(rests=RESTS + [dict(rest, end_s=25.0)]), 10.0, 20.0) is None   # 5 s after, not 8
    assert SC.take_handover(_take(rests=RESTS + [dict(rest, why="a breath")]), 10.0, 20.0) is None


# --------------------------------------------------------------------------
# The span slicing and the composed edges
# --------------------------------------------------------------------------

def test_spans_become_virtual_cues_with_their_release_tail():
    an = SC.take_analysis(_stem(), _take())
    assert [(c["id"], c["role"], c["take_span"]) for c in an["cues"]] == [("tr-1", "transition", True), ("bed-1", "bed", True)]
    assert -64.0 < an["floor_db"] < -55.0 and "rests" in an["floor_from"]
    for c in an["cues"]:
        assert c["tail_s"] <= 0.1                                   # each has decayed into the room by its span's end
        assert c["an"]["n"] == int(round((c["end_s"] + c["tail_s"]) * RATE)) - int(round(c["start_s"] * RATE))
    # a release that rings on past the span is judged with it, until the room, at most TAKE_TAIL_MAX_S
    y = _room(40.0)
    s = _swell(20.0, amp=0.02, rise=3.5, fall=12.0)
    y[int(8.5 * RATE): int(8.5 * RATE) + len(s)] += s
    long = SC.take_analysis(y, _take(spans=[dict(SPANS[0], end_s=17.0)], rests=[RESTS[0], dict(RESTS[2], start_s=31.0)]))
    assert long["cues"][0]["tail_s"] == pytest.approx(SC.TAKE_TAIL_MAX_S)
    # and never into the next span
    near = SC.take_analysis(y, _take(spans=[dict(SPANS[0], end_s=17.0), dict(SPANS[1], start_s=19.0)],
                                     rests=[RESTS[0]]))
    assert near["cues"][0]["tail_s"] == pytest.approx(2.0)


def test_a_composed_entry_passes_and_a_hard_attack_fails():
    an = SC.take_analysis(_stem(), _take())
    e = SC.composed_edges(an["band_db"], an["floor_db"], 8.5, 16.0)
    assert e["entry"]["rise_s"] >= STD["entry_fade_min_s"] and e["exit"]["decay_s"] >= STD["entry_fade_min_s"]
    y = _room(40.0)
    s = _swell(7.5, amp=0.02, rise=0.05, fall=0.05)                # struck on and cut off: no niente
    y[int(8.5 * RATE): int(8.5 * RATE) + len(s)] += s
    hard = SC.take_analysis(y, _take(spans=[SPANS[0]]))
    e = SC.composed_edges(hard["band_db"], hard["floor_db"], 8.5, 16.0)
    assert e["entry"]["rise_s"] < 0.5 and e["exit"]["decay_s"] < 0.5
    checks = SC.take_checks(hard, STD)
    entry = _get(checks, "music-entry", "tr-1")
    assert not entry["ok"] and "niente" in entry["evidence"]["fix"] and "fade" not in entry["evidence"]["fix"].split("never")[0]
    assert not _get(checks, "music-exit", "tr-1")["ok"]


def test_an_edge_that_enters_from_music_is_not_judged():
    y = _room(40.0)
    s = _swell(30.0, amp=0.02, rise=0.05, fall=3.5, from_db=-30)    # music from 2 s, so the span at 20 s enters from music
    y[int(2.0 * RATE): int(2.0 * RATE) + len(s)] += s
    an = SC.take_analysis(y, _take(spans=[{"id": "b", "role": "bed", "start_s": 20.0, "end_s": 32.0}], rests=[RESTS[2]]))
    e = SC.composed_edges(an["band_db"], an["floor_db"], 20.0, 32.0)
    assert e["entry"] is None and e["exit"] is not None
    assert [c["rule"] for c in SC.take_checks(an, STD) if c["unit"] == "b"] == ["music-exit"]


# --------------------------------------------------------------------------
# Holes, rests, the handover and the provenance
# --------------------------------------------------------------------------

def test_digital_zero_is_a_hole_even_in_a_rest_but_not_under_the_titles():
    an = SC.take_analysis(_stem(zero=(3.0, 4.0)), _take())
    holes = SC.take_holes(an, STD["music_hole_max_s"])
    assert [(h["from_s"], h["to_s"], h["why"].split(":")[0]) for h in holes] == [(3.0, 4.0, "digital zero")]
    titled = SC.take_analysis(_stem(zero=(3.0, 4.0)), _take(), titles=[(2.5, 4.5)])
    assert SC.take_holes(titled, STD["music_hole_max_s"]) == []


def test_eight_four_counts_the_rests_with_no_voice():
    an = SC.take_analysis(_stem(), _take())
    ok = _get(SC.take_checks(an, STD), "silence-rests", "score")
    assert ok["ok"] and ok["evidence"]["count"] == 3
    voice = np.zeros(400, bool)
    voice[200:210] = True                                           # a line at 20 s splits r2 into 4 s and 3.5 s
    one = _get(SC.take_checks(an, STD, voice100=voice), "silence-rests", "score")
    assert not one["ok"] and one["evidence"]["count"] == 2 and "rests of 8 s" in one["evidence"]["fix"]


def test_the_handover_lint_hears_music_under_the_titles():
    rest = {"id": "h", "start_s": 0.0, "end_s": 16.0, "why": "A40 handover"}
    quiet = SC.take_analysis(_stem(), _take(rests=RESTS + [rest]), titles=[(0.0, 8.0)])
    assert _get(SC.take_checks(quiet, STD), "take-handover", "score")["ok"]
    loud = SC.take_analysis(_stem(), _take(rests=RESTS + [dict(rest, start_s=9.0, end_s=26.0)]), titles=[(9.0, 18.0)])
    h = _get(SC.take_checks(loud, STD), "take-handover", "score")
    assert not h["ok"] and h["evidence"]["max_over_room_db"] > 10
    undeclared = SC.take_analysis(_stem(), _take(), titles=[(0.0, 8.0)])
    assert "A40 handover" in _get(SC.take_checks(undeclared, STD), "take-handover", "score")["evidence"]["fix"]


def test_the_room_tone_is_a_real_credited_recording(tmp_path):
    ok = {c["rule"]: c for c in SC.take_provenance(_take())}
    assert ok["room-tone-provenance"]["ok"] and ok["room-ir-licence"]["ok"]
    bad = dict(MANIFEST, room_tone=dict(MANIFEST["room_tone"], kind="synthesised", licence="CC BY-SA 4.0", sha256="abc"))
    rt = SC.take_provenance(_take(manifest=bad))[0]
    assert not rt["ok"] and len(rt["evidence"]["problems"]) == 3
    assert not SC.take_provenance(_take(manifest={"room_ir": MANIFEST["room_ir"]}))[0]["ok"]
    assert not SC.take_provenance(_take(manifest=dict(MANIFEST, room_ir={"source": "x", "licence": "all rights reserved"})))[1]["ok"]
    # the sha256 is of the decoded samples, checked against the file when it is here
    f = _write(tmp_path / "room.wav", _room(2.0))
    good = dict(MANIFEST, room_tone=dict(MANIFEST["room_tone"], file=str(f), sha256=SC.audio_hashes(f)[0]))
    rt = SC.take_provenance(_take(manifest=good))[0]
    assert rt["ok"] and rt["evidence"]["sha256_checked_against_file"] is True
    wrong = dict(MANIFEST, room_tone=dict(MANIFEST["room_tone"], file=str(f)))
    assert not SC.take_provenance(_take(manifest=wrong))[0]["ok"]


def test_a_featured_span_is_held_to_the_featured_ceiling():
    y = _room(40.0)
    s = _swell(7.5, amp=0.25)                                       # about -15 LUFS: over -26
    y[int(8.5 * RATE): int(8.5 * RATE) + len(s)] += s
    an = SC.take_analysis(y, _take(spans=[dict(SPANS[0], role="featured")]))
    f = _get(SC.score_checks([], STD, duration_s=40.0, take=an), "featured-level", "tr-1")
    assert not f["ok"] and f["evidence"]["max_lufs"] == SC.FEATURE_LUFS + SC.TOL_DB and "never gained down" in f["evidence"]["fix"]


def test_the_canary_is_log_only_until_the_24th():
    assert SC.take_canary("2026-10-17") and SC.take_canary("2026-10-23")
    assert not SC.take_canary("2026-10-24") and not SC.take_canary("2026-11-01")


# --------------------------------------------------------------------------
# Integration: build_mix places a synthetic take, the checks read it by span
# --------------------------------------------------------------------------

def _mix_plan(film, cue, frames=40 * 24):
    return {"film": str(film), "slug": "take-test", "frames": frames, "duration_s": frames / 24, "lines": [], "shots": [],
            "speakers": {}, "assets": {}, "cues": [cue], "silences": [], "score_standard": dict(STD)}


def test_build_mix_places_the_take_whole_and_every_check_passes(tmp_path):
    film = tmp_path / "film"
    _files(film)
    cue = _take_cue()
    cue["_take"], probs = SC.load_take(film, cue)
    assert probs == []
    plan = _mix_plan(film, cue)
    stems: dict = {}
    j = J.Journal(film="take-mix")
    mix, placed = R.build_mix(plan, film, j, stems=stems)
    assert placed["cues"][0]["role"] == "take" and placed["cues"][0]["level_db"] is None
    assert np.allclose(mix[: 40 * RATE], _stem()[: 40 * RATE], atol=1e-6)          # untouched: no level, no shape, no fade
    assert "take" in stems and not [c for c in stems.get("cues", []) if c["role"] == "take"]
    checks = SC.score_checks(stems.get("cues", []), STD, duration_s=40.0, take=stems["take"], phone=stems["phone"],
                             voice100=stems["voice100"], duck100=stems["duck100"], voice_grid=stems["voice_grid"],
                             duck_grid=stems["duck_grid"], spans=stems["spans"])
    fails = [(c["rule"], c["unit"], c["evidence"].get("fix")) for c in checks if not c["ok"]]
    assert fails == []
    seen = {(c["rule"], c["unit"]) for c in checks}
    assert {("bed-under-voice", "bed-1"), ("bed-breathing", "bed-1"), ("bed-low-end", "bed-1"), ("music-treble", "tr-1"),
            ("underscore-level", "tr-1"), ("transition-ceiling", "tr-1"), ("music-entry", "tr-1"), ("music-exit", "bed-1"),
            ("music-holes", "music"), ("silence-rests", "score"), ("room-tone-provenance", "room_tone"),
            ("room-ir-licence", "room_ir")} <= seen
    assert all(c.get("canary") for c in checks if c["unit"] in ("tr-1", "bed-1", "score", "room_tone", "room_ir"))
    # the journal: every take check is a canary, log-only before 2026-10-24
    jj = J.Journal(film="take-lints")
    assert R.score_lints(jj, plan, stems, registry=[]) == []
    rows = [e for e in J.read(jj.path) if e.get("kind") == "lint" and e.get("rule") == "silence-rests"]
    assert rows and "A29 take" in rows[0]["evidence"]["canary"]


def test_a_digital_zero_gap_and_an_unrested_hole_fail_both_lints(tmp_path, monkeypatch):
    film = tmp_path / "film"
    _files(film, rests=[RESTS[0], RESTS[2]], stem=_stem(zero=(3.0, 4.0)))     # r2 not declared; digital zero in r1
    cue = _take_cue()
    cue["_take"], _ = SC.load_take(film, cue)
    plan = _mix_plan(film, cue)
    stems: dict = {}
    R.build_mix(plan, film, J.Journal(film="take-mix-bad"), stems=stems)
    checks = SC.score_checks(stems.get("cues", []), STD, duration_s=40.0, take=stems["take"], voice100=stems["voice100"])
    holes = _get(checks, "music-holes", "music")
    assert not holes["ok"]
    whys = {h["why"].split(":")[0] for h in holes["evidence"]["holes"]}
    assert whys == {"digital zero", "the room alone, not in the rest map"}
    unrested = next(h for h in holes["evidence"]["holes"] if h["why"].startswith("the room"))
    assert unrested["from_s"] <= 16.5 and unrested["to_s"] >= 24.0
    rests = _get(checks, "silence-rests", "score")
    assert not rests["ok"] and rests["evidence"]["digital_zero_s"] == pytest.approx(1.0) and rests["evidence"]["count"] == 2
    # log-only during the canary; blocking after it
    jj = J.Journal(film="take-lints-bad")
    assert R.score_lints(jj, plan, stems, registry=[]) == []
    lint = next(e for e in J.read(jj.path) if e.get("kind") == "lint" and e.get("rule") == "music-holes")
    assert lint["severity"] == "warn"
    monkeypatch.setattr(SC, "take_canary", lambda today=None: False)
    out = R.score_lints(J.Journal(film="take-lints-after"), plan, stems, registry=[])
    assert any(o.startswith("music-holes") for o in out) and any(o.startswith("silence-rests") for o in out)


# --------------------------------------------------------------------------
# The plan: the take cue's definition blocks; one take, beside it only the theme
# --------------------------------------------------------------------------

def _plan_film(tmp_path, cues):
    film = make_film(tmp_path / "film")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    end = max(s["start_s"] + (s.get("dur_s") or 3.0) for part in play["parts"] for s in part["shots"])
    _files(film, stem=_room(end + 1.0))
    play["music"] = [dict(c, end_s=end) if c.get("take") else c for c in cues]
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def test_build_plan_reads_the_take_and_refuses_a_second_music_cue(tmp_path):
    film = _plan_film(tmp_path, [_take_cue()])
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="take-plan"))
    take = next(c for c in plan["cues"] if c.get("take"))
    assert [s["id"] for s in take["_take"]["spans"]] == ["tr-1", "bed-1"]
    assert any("Freesound" in ln or "leonelmail" in ln for h, lns in plan["credits"] for ln in lns)   # the room tone credited
    bed = {"id": "M1", "kind": "music", "score_role": "bed", "source": "t", "licence": "CC0", "start_s": 4.5,
           "end_s": 12.0, "fade_in_s": 1.5, "fade_out_s": 1.5, "wav": "score/score.whole.wav"}
    film2 = _plan_film(tmp_path / "two", [_take_cue(), bed])
    with pytest.raises(R.Refused, match="take-only"):
        R.build_plan(film2, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="take-plan-2"))
    film3 = _plan_film(tmp_path / "gain", [_take_cue(gain_db=-2.0)])
    with pytest.raises(R.Refused, match="take-cue"):
        R.build_plan(film3, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="take-plan-3"))


# --------------------------------------------------------------------------
# S7: the take crosses the series titles only with its A40 handover declared
# --------------------------------------------------------------------------

from test_a40_title_sequence import COLD_S, SHIFT, TITLE_S, failed, masters, passed, plan_of, titled_film  # noqa: E402,F401


def test_the_take_may_span_the_titles_only_with_the_handover_rest(tmp_path, masters):  # noqa: F811
    def score(play):
        end = max(s["start_s"] + (s.get("dur_s") or 3.0) for part in play["parts"] for s in part["shots"])
        play["music"] = [_take_cue(end_s=end),
                         {"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S, "end_s": SHIFT, "wav": "mt.wav"}]
    handover = {"id": "rest-a40", "start_s": COLD_S, "end_s": SHIFT + 8.0, "why": "A40 handover: the titles carry the room"}
    film = titled_film(tmp_path / "a", masters, edit=score)
    _files(film, rests=RESTS + [handover], stem=_room(50.0))
    plan, j = plan_of(film)
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-audio-slot") and passed(j, "take-cue") and passed(j, "take-only")
    film = titled_film(tmp_path / "b", masters, edit=score)
    _files(film, rests=RESTS + [dict(handover, end_s=SHIFT + 4.0)], stem=_room(50.0))   # 4 s after the titles, not 8
    plan, j = plan_of(film)
    assert isinstance(plan, R.Refused) and failed(j, "title-audio-slot")


def test_overlapping_spans_are_not_a_copy_of_each_other():
    """Two spans that overlap (a transition into its bed) slice the same audio there: score-repetition compares
    distinct music, so such a pair is not judged a duplicate (found on Real World: tr-03 into bed-01)."""
    spans = [dict(SPANS[1], id="tr-x", role="transition", start_s=24.5, end_s=30.0), dict(SPANS[1], start_s=26.0)]
    an = SC.take_analysis(_stem(), _take(spans=spans))
    rep = [c for c in SC.score_checks([], STD, duration_s=40.0, take=an) if c["rule"] == "score-repetition"]
    assert rep and all(c["ok"] for c in rep)
