"""GRAMMAR A40 standalone audio (founder ruling 2026-10-26: the series titles carry their own sound, and a film's score
starts after them; no main-title cue in films).

A title_sequence shot plays its master's own track in the film mix, at the house title level (TS.TITLE_LUFS, held
down only so its true peak stays under the limiter after the programme gain) unless the item declares ``audio_gain_db``, frame-aligned with the picture: across a drop or repeat conform the sound plays at its own speed
and pitch (no resample), so both keep the master's clock and the offset stays within a film frame. Under the lockup
card that ends the series-title part the title's sound continues: its declared ``audio_tail`` (the full-length mix),
or with none, the master's own room continued. title-audio refuses a master with no audio stream at plan time, and
after the render a title span that measures as digital black."""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from conftest import make_film
from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC
from studio.engine import titles as TS
from test_a40_title_sequence import (CARD, COLD_S, DIP, FOLEY_DBFS, HOLD, NO_LOCKUP, ROOM_DBFS, SHIFT, TITLE_S, TL,
                                     failed, lints, make_master, passed, plan_of, titled_film, with_shots)

RATE = 48000


@pytest.fixture(scope="module")
def tmasters(tmp_path_factory, film):
    """The A40 test master with its own track, the same master with no audio stream, with a silent one, and with
    Foley ringing to its last sample (no room to continue); and the title rendered at 30000/1001 (its click on its own
    frame for the record cut)."""
    from test_cine6_fps import NTSC_N, _at, make_master_at
    d = tmp_path_factory.mktemp("tmasters")
    rec = film / "stills" / "FX-STILL-B.png"
    tl = [dict(m, frame=_at(m["frame"])) for m in TL]
    dip = dict(DIP, centre_frame=_at(DIP["centre_frame"]))
    out = {"dir": d, "burned": make_master(d / "burned.mkv", rec), "mute": make_master(d / "mute.mkv", rec, sound=None),
           "silent": make_master(d / "silent.mkv", rec, sound="silent"),
           "ntsc": make_master_at(d / "ntsc.mkv", rec, "30000/1001", NTSC_N, tl, dip),
           "ntsc_item": {"file": "ntsc.mkv", "fps": "30000/1001", "frames": NTSC_N, "marks": tl, "dip": dip,
                         "record_frames": [_at(40), _at(50)], "lockup_frame": _at(84)},
           "ntsc_click": tl[1]["frame"]}
    make_master(d / "spike-src.mkv", rec)
    import subprocess
    z, _ = sf.read(str(d / "spike-src.sound.wav"), dtype="float32", always_2d=True)
    z[:] = 3e-4 * np.random.default_rng(3).standard_normal(z.shape)       # a room at about -70 dBFS, not silent
    z[48000: 48000 + 48] = 0.99
    sf.write(str(d / "spike.sound.wav"), z, RATE, subtype="FLOAT")
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-i", str(d / "spike-src.mkv"), "-i", str(d / "spike.sound.wav"),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", str(d / "spike.mkv")], check=True)
    out["spike"] = d / "spike.mkv"
    for name, shape in (("zero_end", "zero_end"), ("quiet", "quiet"), ("fade_zero", "fade_zero")):
        make_master(d / f"{name}-src.mkv", rec)
        z, _ = sf.read(str(d / f"{name}-src.sound.wav"), dtype="float32", always_2d=True)
        if shape == "zero_end":
            z[-int((1.0 + TS.ROOM_S) * RATE):] = 0.0             # it ends on digital zero, not a room
        elif shape == "fade_zero":                               # its room fades into digital zero over its last 1.5 s
            n = int(1.5 * RATE)
            z[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None] ** 4
            z[-int(0.6 * RATE):] = 0.0
        else:
            z *= np.float32(10 ** (-30 / 20))                    # 30 dB under the stand-in Foley: about -54 LUFS
        sf.write(str(d / f"{name}.sound.wav"), z, RATE, subtype="FLOAT")
        subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-i", str(d / f"{name}-src.mkv"), "-i", str(d / f"{name}.sound.wav"),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", str(d / f"{name}.mkv")],
                       check=True)
        out[name] = d / f"{name}.mkv"
    ring = make_master(d / "ring.mkv", rec)
    x, _ = sf.read(str(d / "ring.sound.wav"), dtype="float32", always_2d=True)
    x[-int(TS.ROOM_S * RATE):] = 0.05                      # loud to the last sample: no room in it
    sf.write(str(d / "ring.sound.wav"), x, RATE, subtype="FLOAT")
    import subprocess
    tmp = d / "ring2.mkv"
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-i", str(ring), "-i", str(d / "ring.sound.wav"), "-map", "0:v:0",
                    "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le", str(tmp)], check=True)
    out["ring"] = tmp
    return out


def tfilm(tmp_path, tmasters, master="burned", item=None, edit=None):
    return titled_film(tmp_path, dict(tmasters, burned=tmasters[master]), item=dict({"file": tmasters[master].name},
                                                                                    **(item or {})), edit=edit)


def mixed(film):
    plan, j = plan_of(film)
    assert not isinstance(plan, Exception), (plan, [(e["rule"], e.get("evidence")) for e in J.read(j.path)
                                                    if e.get("kind") == "lint" and e.get("status") == "fail"][:3])
    stems: dict = {}
    mix, placed = R.build_mix(plan, film, j, stems=stems)
    return plan, j, mix, placed, stems


def mixed_or_refused(film):
    plan, j = plan_of(film)
    if isinstance(plan, Exception):
        return plan, j
    try:
        R.build_mix(plan, film, j)
    except R.Refused as e:
        return e, j
    return plan, j


def seg(x, a, b):
    return x[int(round(a * RATE)): int(round(b * RATE))]


def master_track(path):
    return TS.master_audio(R.ffmpeg(), R.ffprobe(), str(path))[0]


# --------------------------------------------------------------------------
# Mixing: the master's own track, at the house title level, frame-aligned
# --------------------------------------------------------------------------


def g_of(rec):
    return np.float32(10 ** (rec["gain_db"] / 20))


def test_title_audio_the_master_track_is_mixed_at_the_house_title_level(tmp_path, tmasters):
    plan, j, mix, placed, stems = mixed(tfilm(tmp_path, tmasters))
    rec = placed["titles"][0]
    x = master_track(tmasters["burned"])
    got = seg(mix, COLD_S, COLD_S + TITLE_S - TS.END_FADE_S)
    assert np.allclose(got, x[: len(got)] * g_of(rec), rtol=2e-3, atol=1e-5)       # sample for sample: one gain, no shaping
    assert rec["shot"] == "TS1" and rec["gain_declared"] is False
    ev = lints(j, "title-audio-level")[0]["evidence"]
    assert passed(j, "title-audio-level")
    ceiling = R.TARGET_TP - R.LIMIT_MARGIN_DB - TS.TITLE_PEAK_MARGIN_DB
    assert ev["predicted_tp_dbtp"] <= ceiling + 0.05                     # the limiter never acts on the title
    # at the house level, unless its peaks hold it down (then by exactly as much as they need)
    assert rec["level_lufs"] == pytest.approx(TS.TITLE_LUFS, abs=0.05) or ev["predicted_tp_dbtp"] == pytest.approx(ceiling, abs=0.1)
    assert any(e["what"].startswith("TS1: the series titles play their own sound") for e in J.read(j.path)
               if e.get("kind") == "decision")
    # the title is a source's own sound for the score's lints (music-holes): present, not a hole
    assert (COLD_S, pytest.approx(SHIFT)) in [(a, pytest.approx(b)) for a, b in stems["own_sound"]] or any(
        abs(a - COLD_S) < 1e-6 and abs(b - SHIFT) < 1e-6 for a, b in stems["own_sound"])


def test_title_audio_a_declared_gain_moves_its_level(tmp_path, tmasters):
    _, _, mix, placed, _ = mixed(tfilm(tmp_path, tmasters, item={"audio_gain_db": -6.0}))
    x = master_track(tmasters["burned"])
    got = seg(mix, COLD_S, COLD_S + 2.0)
    assert TS.rms_dbfs(got) - TS.rms_dbfs(x[: len(got)]) == pytest.approx(-6.0, abs=0.01)
    assert placed["titles"][0]["gain_db"] == -6.0
    plan, j = plan_of(tfilm(tmp_path / "bad", tmasters, item={"audio_gain_db": "loud"}))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")


def test_title_audio_a_declared_gain_that_would_push_the_limiter_is_refused(tmp_path, tmasters):
    plan, j, *_ = mixed_or_refused(tfilm(tmp_path, tmasters, item={"audio_gain_db": 12.0}))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio-level")
    assert next(e for e in lints(j, "title-audio-level") if e["status"] == "fail")["evidence"]["declared"] is True


def test_title_audio_a_title_whose_peaks_would_hold_it_far_under_the_house_level_is_refused(tmp_path, tmasters):
    """A master that is near silence with one full-scale click: to keep the click under the limiter its level would
    sit more than TITLE_HOLD_MAX_DB under the house title loudness, so it is refused, not mixed inaudibly."""
    plan, j, *_ = mixed_or_refused(tfilm(tmp_path, tmasters, master="spike"))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio-level")
    ev = next(e for e in lints(j, "title-audio-level") if e["status"] == "fail")["evidence"]
    assert ev["held_under_house_db"] > TS.TITLE_HOLD_MAX_DB and "remaster" in ev["fix"]


def test_title_audio_conform_keeps_sync_and_pitch_at_24(tmp_path, tmasters):
    """A 30000/1001 master in a 24 fps film: the picture is drop-conformed (one frame in five), the sound plays at its
    own speed and pitch from the shot's first frame. The click on the master's frame for the record cut lands at that
    frame's own time, within one film frame of the film frame that shows it."""
    film = tfilm(tmp_path, tmasters, master="ntsc", item=tmasters["ntsc_item"])
    plan, j, mix, placed, _ = mixed(film)
    assert plan["fps"] == 24
    s = next(x for x in plan["shots"] if x["id"] == "TS1")
    src = 30000 / 1001
    ev = lints(j, "title-audio-sync")[0]["evidence"]
    assert passed(j, "title-audio-sync") and ev["max_offset_ms"] <= 1000 / 24 and "drop-conformed" in ev["method"]
    t0 = s["f0"] / 24
    w = seg(mix, t0, t0 + TITLE_S)
    at = int(np.argmax(np.abs(w))) / RATE                                # the click, as the mix placed it
    k = tmasters["ntsc_click"]
    assert at == pytest.approx(k / src, abs=2 / RATE)                    # its own time: no resample, no time-stretch
    shows = TS.film_frame(k, 24, src) / 24                               # the film frame that first shows that frame
    assert abs(at - shows) <= 1 / 24
    # its speed and pitch: the room starts where the master's own track puts it (a resample would move it)
    x = master_track(tmasters["ntsc"])
    env = np.array([TS.rms_dbfs(w[i: i + 480]) for i in range(0, len(w) - 480, 480)])
    room_at = np.argmax(env < (FOLEY_DBFS + ROOM_DBFS) / 2) * 480 / RATE
    want = (len(x) - int(round((1.0 + TS.ROOM_S) * RATE))) / RATE
    assert room_at == pytest.approx(want, abs=0.011)


def test_title_audio_sync_offset_is_bounded_by_the_conform():
    src = 30000 / 1001
    assert TS.sync_offset_ms(120, src, src) == 0.0                       # 1:1
    assert 0 < TS.sync_offset_ms(96, src, 24.0, 120) <= 1000 / 24        # drop: within a 24 frame
    assert 0 < TS.sync_offset_ms(120, 24.0, src, 96) <= 1000 / src       # repeat: within a 29.97 frame


# --------------------------------------------------------------------------
# The lockup card: the tail, or the room continued; never digital black
# --------------------------------------------------------------------------


def _tail(tmp_path, master, extra_s, *, hz=1000.0, dbfs=-27.0, differ=False, short=False):
    """A full-length mix: the master's own track, then ``extra_s`` of a tone (the theme, standing in, at about the
    Foley's own level)."""
    x, rate = sf.read(str(master.with_suffix(".sound.wav")), dtype="float32", always_2d=True)
    n = int(round(extra_s * rate))
    t = np.arange(n) / rate
    tone = (10 ** (dbfs / 20) * np.sqrt(2) * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    head = x.copy()
    if differ:
        head = head[::-1].copy()
    y = np.concatenate([head, np.stack([tone, tone], axis=1)])
    if short:
        y = y[: len(x) + n // 3]
    p = tmp_path / "title.tail.wav"
    sf.write(str(p), y, rate, subtype="FLOAT")
    return p


def test_title_audio_a_declared_tail_plays_across_the_lockup_card(tmp_path, tmasters):
    tail = _tail(tmp_path, tmasters["burned"], CARD["dur_s"])
    film = tfilm(tmp_path / "f", tmasters, item=dict(NO_LOCKUP, audio_tail=str(tail)), edit=with_shots((CARD,)))
    plan, j, mix, placed, stems = mixed(film)
    assert passed(j, "title-audio") and passed(j, "title-lockup")
    rec = placed["titles"][0]
    assert rec["lockup_card"] == "TS1b" and rec["from"] == "tail"
    assert rec["end_s"] == pytest.approx(SHIFT + CARD["dur_s"]) and rec["tail_s"] == pytest.approx(CARD["dur_s"], abs=0.01)
    card = seg(mix, SHIFT + 0.1, SHIFT + CARD["dur_s"] - 0.2)
    want = seg(TS.read_audio(R.ffmpeg(), str(tail)), TITLE_S + 0.1, TITLE_S + CARD["dur_s"] - 0.2)
    assert np.allclose(card, want * g_of(rec), rtol=2e-3, atol=1e-5)              # the tail's own samples, at the title's gain
    spec = np.abs(np.fft.rfft(card))
    assert abs(np.argmax(spec) * RATE / len(card) - 1000.0) < 2.0     # its own pitch
    # under the title the master's own track, spliced to the tail at the cut (no gap, no doubling)
    x = master_track(tmasters["burned"])
    head = seg(mix, COLD_S, SHIFT - 0.01)
    assert np.allclose(head, x[: len(head)] * g_of(rec), rtol=2e-3, atol=1e-5)
    assert any(abs(a - COLD_S) < 1e-6 and abs(b - (SHIFT + CARD["dur_s"])) < 1e-6 for a, b in stems["own_sound"])
    # it ends at the cut into the film: nothing of it after the card
    assert rec["dur_s"] == pytest.approx(TITLE_S + CARD["dur_s"], abs=1e-3)


def test_title_audio_with_no_tail_the_masters_room_continues_under_the_card(tmp_path, tmasters):
    film = tfilm(tmp_path, tmasters, item=NO_LOCKUP, edit=with_shots((HOLD, CARD)))
    plan, j, mix, placed, _ = mixed(film)
    rec = placed["titles"][0]
    assert rec["from"] == "room" and rec["room_s"] == pytest.approx(HOLD["dur_s"] + CARD["dur_s"], abs=0.01)
    span = seg(mix, SHIFT, SHIFT + HOLD["dur_s"] + CARD["dur_s"] - TS.END_FADE_S)
    room = master_track(tmasters["burned"])[-int(TS.ROOM_S * RATE):]
    assert TS.rms_dbfs(span) == pytest.approx(TS.rms_dbfs(room) + rec["gain_db"], abs=1.0)   # the master's own room, continued
    win = [TS.rms_dbfs(span[i: i + 4800]) for i in range(0, len(span) - 4800, 4800)]
    assert min(win) > -90.0                                                  # never digital black under the card


def test_title_audio_a_bad_tail_is_refused(tmp_path, tmasters):
    for name, kw in (("differ", {"differ": True}), ("short", {"short": True})):
        (tmp_path / name).mkdir()
        tail = _tail(tmp_path / name, tmasters["burned"], CARD["dur_s"], **kw)
        plan, j = plan_of(tfilm(tmp_path / f"f-{name}", tmasters, item=dict(NO_LOCKUP, audio_tail=str(tail)),
                                edit=with_shots((CARD,))))
        assert isinstance(plan, R.Refused) and failed(j, "title-audio"), name
    plan, j = plan_of(tfilm(tmp_path / "missing", tmasters, item=dict(NO_LOCKUP, audio_tail="nowhere.wav"),
                            edit=with_shots((CARD,))))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")


def test_title_audio_a_room_of_digital_zero_is_refused(tmp_path, tmasters):
    """No tail, and the master ends on digital zero: nothing to continue under the lockup card but digital black."""
    plan, j = plan_of(tfilm(tmp_path, tmasters, master="zero_end", item=NO_LOCKUP, edit=with_shots((CARD,))))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")
    assert "digital zero" in " ".join(next(e for e in lints(j, "title-audio") if e["status"] == "fail")["evidence"]["problems"])


def test_title_audio_a_room_fading_into_digital_zero_never_loops_digital_black(tmp_path, tmasters):
    """The master's room fades into digital zero: the zero blocks are trimmed before the room is measured, so what is
    left (under ROOM_S of room) is refused at plan time; a fade that still leaves ROOM_S of room is continued from
    where the room ends, never from the zero."""
    plan, j = plan_of(tfilm(tmp_path, tmasters, master="fade_zero", item=NO_LOCKUP, edit=with_shots((CARD,))))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")
    probs = " ".join(next(e for e in lints(j, "title-audio") if e["status"] == "fail")["evidence"]["problems"])
    assert "digital zero" in probs
    room = 3e-4 * np.random.default_rng(9).standard_normal(RATE * 4).astype(np.float32)
    x = np.concatenate([np.full(RATE, 0.1, np.float32), room, np.zeros(RATE // 2, np.float32)])
    a, b = TS.room_span(x)
    assert b == len(x) - RATE // 2 and TS.room_problem(x[a:b]) is None              # the zero trimmed, the room kept
    y, how = TS.title_track(x, len(x), len(x) + RATE * 6)
    assert how["zero_tail_replaced_s"] == pytest.approx(0.5) and how["from"] == "room"
    blocks = TS._block_db(y[RATE + RATE // 2: -int(TS.END_FADE_S * RATE)], int(TS.ROOM_BLOCK_S * RATE))
    assert blocks.min() > TS.TAIL_FLOOR_DBFS                                         # no digital black under the card
    gap = np.concatenate([room[: RATE * 2], np.zeros(RATE // 10, np.float32), room[: RATE]])   # one zero block inside
    assert "digital zero" in TS.room_problem(gap)


def test_title_audio_a_silence_ruling_must_cite_a_dated_founder_ruling(tmp_path, tmasters):
    for k, ruling in enumerate(("intended", "the founder said so", "founder 2026-10-28")):
        plan, j = plan_of(tfilm(tmp_path / f"r{k}", tmasters, master="silent", item={"audio_silence_ruling": ruling}))
        assert isinstance(plan, R.Refused) and failed(j, "title-audio"), ruling


def test_title_audio_the_engine_journals_its_commit_at_run_start():
    g = R.engine_git()
    assert set(g) == {"sha", "dirty", "root"}
    assert g["sha"] is None or (len(g["sha"]) == 40 and isinstance(g["dirty"], bool))


def test_title_audio_the_room_loop_takes_the_longest_room_the_master_ends_on():
    x = np.concatenate([np.full(RATE * 3, 0.1, np.float32),
                        3e-4 * np.random.default_rng(5).standard_normal(RATE * 9).astype(np.float32)])
    assert len(TS.room_of(x)) / RATE == pytest.approx(TS.ROOM_MAX_S)               # capped
    y = np.concatenate([np.full(RATE * 3, 0.1, np.float32), x[-int(RATE * 3.5):]])
    assert len(TS.room_of(y)) / RATE == pytest.approx(3.5, abs=TS.ROOM_BLOCK_S)     # all of the room, no Foley
    assert TS.room_problem(np.zeros(RATE * 2, np.float32)) is not None
    assert TS.room_problem(x[-RATE * 2:]) is None


def test_title_audio_a_house_gain_over_12_db_is_refused(tmp_path, tmasters):
    """A master so quiet the house level would ask more than +12 dB of it: refused, remaster its sound."""
    plan, j, *_ = mixed_or_refused(tfilm(tmp_path, tmasters, master="quiet"))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio-level")
    ev = next(e for e in lints(j, "title-audio-level") if e["status"] == "fail")["evidence"]
    assert ev["house_gain_wanted_db"] > 12 and ev["gain_db"] <= 12 and "remaster" in ev["fix"]


def test_title_audio_the_limiter_acting_inside_the_title_is_refused_after_mastering():
    placed = {"titles": [{"shot": "TS1", "at_s": 10.0, "end_s": 52.0, "predicted_tp_dbtp": -3.2, "programme_lift_db": 2.5}]}
    j = J.Journal(film="a40-mastered")
    clean = {"gain_db": 2.5, "limiter": {"acted": [{"at_s": 60.0, "dur_s": 0.01, "max_db": 0.4}], "acted_total": 1}}
    assert R.title_mastered_lints(j, placed, clean) == [] and passed(j, "title-audio-level")
    j = J.Journal(film="a40-mastered-2")
    hit = {"gain_db": 2.5, "limiter": {"acted": [{"at_s": 30.0, "dur_s": 0.02, "max_db": 0.6}], "acted_total": 1}}
    assert R.title_mastered_lints(j, placed, hit) and failed(j, "title-audio-level")
    j = J.Journal(film="a40-mastered-3")                      # the mastering lifted more than the level loop measured
    assert R.title_mastered_lints(j, placed, {"gain_db": 4.0, "limiter": None}) and failed(j, "title-audio-level")
    j = J.Journal(film="a40-mastered-4")
    assert R.title_mastered_lints(j, placed, hit, draft=True) == [] and failed(j, "title-audio-level")
    j = J.Journal(film="a40-mastered-5")                      # more places than logged: it fails closed
    many = {"gain_db": 2.5, "limiter": dict(clean["limiter"], acted_total=500)}
    assert R.title_mastered_lints(j, placed, many) and failed(j, "title-audio-level")


def test_title_audio_no_tail_and_no_room_to_continue_is_refused(tmp_path, tmasters):
    plan, j = plan_of(tfilm(tmp_path, tmasters, master="ring", item=NO_LOCKUP, edit=with_shots((CARD,))))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")
    probs = " ".join(next(e for e in lints(j, "title-audio") if e["status"] == "fail")["evidence"]["problems"])
    assert "of room (at least 2 s" in probs and "audio_tail" in probs        # Foley to its last block: no room


def test_title_track_splices_and_loops_without_a_gap():
    x = np.full(RATE * 3, 0.1, np.float32)
    x[-RATE * 2:] = 0.0003                                                  # its last 2 s: room
    y, how = TS.title_track(x, RATE * 3, RATE * 6)
    assert how["from"] == "room" and how["room_s"] == pytest.approx(3.0)
    assert np.all(np.abs(y[RATE * 3: RATE * 6 - int(TS.END_FADE_S * RATE)]) > 0)
    assert y[-1] == 0.0                                                     # it fades into the cut
    tail = np.concatenate([x, np.full(RATE * 3, 0.2, np.float32)])
    y, how = TS.title_track(x, RATE * 3, RATE * 6, tail=tail)
    assert how["from"] == "tail" and how["room_s"] == 0.0
    assert np.allclose(y[: RATE * 3 - 480], x[: RATE * 3 - 480]) and np.allclose(y[RATE * 3 + 480: RATE * 5], 0.2)
    assert TS.room_loop(np.ones(100, np.float32), 1000, 20).min() > 0.7     # equal-power: no dip at a seam


# --------------------------------------------------------------------------
# The lint, at plan time and after the render
# --------------------------------------------------------------------------


def test_title_audio_a_master_with_no_audio_stream_is_refused(tmp_path, tmasters):
    plan, j = plan_of(tfilm(tmp_path, tmasters, master="mute"))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")
    assert "no audio stream" in " ".join(next(e for e in lints(j, "title-audio") if e["status"] == "fail")["evidence"]["problems"])


def test_title_audio_a_silent_master_is_refused_unless_its_silence_cites_a_ruling(tmp_path, tmasters):
    """A silent track is a master muxed without its sound (the bug this rule exists for): refused, unless the item
    declares the silence and cites the founder ruling for it; then its silence is its own, declared intended."""
    plan, j = plan_of(tfilm(tmp_path / "bare", tmasters, master="silent"))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio")
    assert "audio_silence_ruling" in " ".join(next(e for e in lints(j, "title-audio") if e["status"] == "fail")["evidence"]["problems"])
    plan, j = plan_of(tfilm(tmp_path / "ruled", tmasters, master="silent",
                            item={"audio_silence_ruling": "founder, 2026-10-28: this title plays in silence (a test)"}))
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-audio") and plan["title_audio"][0]["silent"] is True
    assert (COLD_S, pytest.approx(SHIFT)) in [(a, pytest.approx(b)) for a, b in plan["silences"]] or any(
        abs(a - COLD_S) < 1e-6 and abs(b - SHIFT) < 1e-6 for a, b in plan["silences"])


def _rendered(tmp_path, x):
    p = tmp_path / "master.wav"
    sf.write(str(p), x.astype(np.float32), RATE, subtype="FLOAT")
    return p


def _ta(silent=False, end_s=None):
    return {"shot": "TS1", "file": "m.mkv", "at_s": 1.0, "title_end_s": 4.0, "end_s": end_s or 4.0, "tail": None,
            "gain_db": 0.0, "silent": silent, "master_rms_dbfs": -30.0, "lockup_card": None}


def test_title_audio_after_the_render_refuses_digital_black_under_the_title(tmp_path):
    plan = {"duration_s": 10.0, "title_audio": [_ta(end_s=7.0)]}
    x = np.zeros(RATE * 10, np.float32)
    x[RATE * 4: RATE * 7] = 1e-4 * np.random.default_rng(1).standard_normal(RATE * 3)     # the room under the card
    j = J.Journal(film="a40-post")
    bad = R.title_audio_rendered(j, plan, _rendered(tmp_path, x))
    assert bad and "title" in bad[0]                                        # the title span is digital black
    got = {e["evidence"]["part"]: e["status"] for e in lints(j, "title-audio")}
    assert got == {"title": "fail", "lockup": "pass"}
    x[RATE * 1: RATE * 4] = 0.03 * np.random.default_rng(2).standard_normal(RATE * 3)
    j = J.Journal(film="a40-post-2")
    assert R.title_audio_rendered(j, plan, _rendered(tmp_path, x)) == [] and passed(j, "title-audio")
    x[RATE * 4: RATE * 7] = 0.0                                             # digital black under the lockup card
    j = J.Journal(film="a40-post-3")
    assert R.title_audio_rendered(j, plan, _rendered(tmp_path, x)) and failed(j, "title-audio")
    j = J.Journal(film="a40-post-4")                                        # a draft journals it, never refuses
    assert R.title_audio_rendered(j, plan, _rendered(tmp_path, x), draft=True) == [] and failed(j, "title-audio")
    j = J.Journal(film="a40-post-5")                                        # a silent master's silence is its own
    plan = {"duration_s": 10.0, "title_audio": [_ta(silent=True)]}
    assert R.title_audio_rendered(j, plan, _rendered(tmp_path, np.zeros(RATE * 10, np.float32))) == []


def test_title_audio_after_the_render_measures_a_span_in_its_own_time(tmp_path):
    plan = {"duration_s": 30.0, "title_audio": [_ta()]}
    x = np.zeros(RATE * 5, np.float32)                                      # a --shots master starting at 0.5 s
    x[int(RATE * 0.5): int(RATE * 3.5)] = 0.03
    j = J.Journal(film="a40-span")
    span = {"t0_s": 0.5, "duration_s": 5.0}
    assert R.title_audio_rendered(j, plan, _rendered(tmp_path, x), span=span) == []
    assert lints(j, "title-audio")[0]["evidence"]["from_s"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# The score standard: the title's own sound is present sound; no film is scored under it
# --------------------------------------------------------------------------


def test_title_audio_music_holes_counts_the_titles_own_sound_as_present():
    play = {"parts": [{"id": "series", "shots": [{"id": "TS1", "kind": "title_sequence", "start_s": 10.0, "dur_s": 36.4},
                                                {"id": "TS1b", "kind": "card", "start_s": 46.4, "dur_s": 6.0}]},
                      {"id": "p1", "shots": [{"id": "S1", "kind": "card", "start_s": 52.4, "dur_s": 5.0}]}]}
    own = SC.title_own_sound(play)
    assert own == [(10.0, pytest.approx(52.4))]
    an = {"ms": np.full(600, 1e-3), "n": 60 * SC.RATE}
    cues = [{"id": "B1", "role": "bed", "start_s": 0.0, "an": dict(an, ms=np.r_[np.full(100, 1e-3), np.zeros(424),
                                                                              np.full(76, 1e-3)])}]
    assert SC.music_holes(cues, 60.0, [], [], 4.0)                         # no music under the title: a hole...
    assert not SC.music_holes(cues, 60.0, [], own, 4.0)                    # ... unless the title's sound is there


def test_title_audio_a_film_with_no_titles_is_unchanged(tmp_path):
    film = make_film(tmp_path / "film")
    plan, j = plan_of(film)
    assert not isinstance(plan, Exception), plan
    assert plan["title_audio"] == [] and not lints(j, "title-audio") and not lints(j, "title-audio-sync")
    buf = np.zeros(RATE, np.float32)
    assert R.title_tracks(plan) == ([], []) and R.level_title_audio([], [], buf, buf, j) == [] and not buf.any()
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assert SC.title_own_sound(play) == []
    _, placed = R.build_mix(plan, film, j)
    assert placed["titles"] == []
    assert R.title_audio_rendered(j, plan, tmp_path / "never-read.mp4") == []
