"""R10 (GRAMMAR A29 refined, founder 2026-10-11): the score in three layers.
The brand (the motif, a bass-led pulse at the cards), the film's own score
(beds band-shaped around the voice, never another film's), and regional
punctuation (sparse, each on a named moment); a small-speaker check of the
mix; and no repetition (no tiled loop, no two cues alike). Small synthetic
fixtures only, no film render."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from conftest import make_film
from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC

RATE = 48000
STD = dict(SC.STANDARD)


def _t(seconds):
    return np.arange(int(seconds * RATE)) / RATE


def _sine(hz, seconds, amp=0.1):
    return (amp * np.sin(2 * np.pi * hz * _t(seconds))).astype(np.float32)


def _tone(hz, seconds, harm=(1.0,), amp=0.1):
    t = _t(seconds)
    return (amp * sum(h * np.sin(2 * np.pi * hz * (k + 1) * t) for k, h in enumerate(harm) if hz * (k + 1) < 20000)
            ).astype(np.float32)


def _breathing(x, beat_s=1.2, rest_beats=2, of=8):
    """x holding six beats of eight and resting two, soft-edged (the shape A29's breathing asks of a bed)."""
    t = np.arange(len(x)) / RATE
    env = np.where((t / beat_s) % of < of - rest_beats, 1.0, 0.05)
    k = int(0.2 * RATE)
    return (x * np.convolve(env, np.ones(k) / k, mode="same")).astype(np.float32)


def _note(midi, dur, harm=(1, .5, .33, .25, .2, .16), decay=1.5):
    t = _t(dur)
    f = 440 * 2 ** ((midi - 69) / 12)
    y = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(harm) if f * (k + 1) < 20000)
    return (0.2 * y * np.exp(-t / decay) * np.minimum(1, t / 0.01)).astype(np.float32)


MELODY = [int(x) for x in np.random.default_rng(7).choice([57, 59, 60, 62, 64, 65, 67, 69, 71, 72], 16)]
RHYTHM = [1.5, 0.5, 1, 1, 0.5, 0.5, 1, 2, 1, 0.5, 0.5, 1, 1.5, 0.5, 1, 1]


def _phrase(notes=MELODY, beat=0.6, harm=(1, .5, .33, .25, .2, .16), shift=0, rhythm=None):
    """A 4-bar phrase on a decaying harmonic tone (16 beats at 0.6 s: 9.6 s)."""
    rhythm = rhythm or [1] * len(notes)
    out = np.zeros(int((sum(rhythm) * beat + 1) * RATE), np.float32)
    t = 0.0
    for n, r in zip(notes, rhythm):
        y = _note(n + shift, r * beat + 1.0, harm=harm)
        i = int(t * RATE)
        out[i:i + len(y)] += y[: len(out) - i]
        t += r * beat
    return out[: int(t * RATE)]


def _write(path, x, subtype=None):
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, RATE, subtype=subtype)
    return path


def _edit_play(film, fn):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")


def _plan(film, name="t"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def _cue(cid, x, start=0.0, *, role=None, score_role=None, fi=0.0, fo=0.0, **kw):
    c = {"id": cid, "kind": "music", "start_s": start, "end_s": start + len(x) / RATE, "fade_in_s": fi, "fade_out_s": fo, **kw}
    if role:
        c["role"] = role
    if score_role:
        c["score_role"] = score_role
    return SC.place_cue(c, x, STD)


def _checks(cues, dur=60.0, **kw):
    return SC.score_checks(cues, STD, duration_s=dur, **kw)


def _get(checks, rule, unit):
    return next(c for c in checks if c["rule"] == rule and c["unit"] == unit)


def _db_at(mag, hz):
    return 20 * math.log10(float(mag(np.array([float(hz)]))[0]))


# --------------------------------------------------------------------------
# The bands and the bed's shaping
# --------------------------------------------------------------------------

def test_the_bands_are_named_and_the_standard_is_bounded():
    assert SC.SUB_BASS_HZ == 100.0 and SC.VOICE_BAND_HZ == (150.0, 4000.0) and SC.LOW_MID_HZ == (150.0, 400.0)
    assert SC.TREBLE_HZ == 5000.0
    assert "bed_highpass_hz" not in SC.STANDARD                          # the 300 Hz high-pass is gone
    assert SC.standard({"score_standard": {"bed_highpass_hz": 300}})[2]
    for bad in ({"bed_lowmid_max_share": 0.2}, {"music_treble_max_share": 0.05}, {"bed_lowmid_hz": 300}):
        assert SC.standard({"score_standard": bad})[2], bad             # laxer than the house is refused
    assert not SC.standard({"score_standard": {"bed_lowmid_max_share": 0.05, "music_treble_max_share": 0.01}})[2]


def test_the_shaping_keeps_the_sub_bass_cuts_the_voices_low_mids_and_shelves_the_treble():
    mag = lambda f: SC.bed_shape_mag(f, 400.0)                           # noqa: E731
    assert _db_at(mag, 50) > -0.5 and _db_at(mag, 60) > -0.5             # the sub-bass passes
    assert _db_at(mag, 150) < -12 and _db_at(mag, 200) < -17 and _db_at(mag, 300) < -9
    assert _db_at(mag, 1000) > -0.5                                      # the voice's upper band and the music in it pass
    assert -3.5 < _db_at(mag, 5000) < -2.5 and -6.1 < _db_at(mag, 16000) < -4.5      # a gentle shelf, 6 dB at most
    y = SC.bed_shape(_sine(55, 2.0) + _sine(200, 2.0), 400.0)
    shares = SC.band_shares(y[RATE // 2: 3 * RATE // 2])
    assert shares["sub_share"] > 0.97                                    # the 55 Hz survives, the 200 Hz does not


def test_bed_low_end_reads_the_low_mids_and_a_sub_bass_neither_dilutes_nor_fails_it():
    sub_and_high = _breathing(_sine(55, 20, 0.2) + _tone(660, 20, (1, .3, .1), 0.05))
    cello = _breathing(_tone(98, 20, [1 / k for k in range(1, 40)]))    # a cello G2: its partials fill 150 to 400 Hz
    ok, bad = _cue("OK", sub_and_high, fi=2, fo=2), _cue("CELLO", cello, fi=2, fo=2)
    assert ok["an"]["sub_share"] > 0.5 and ok["an"]["lowmid_share"] < 0.01
    ch = _checks([ok, bad])
    assert _get(ch, "bed-low-end", "OK")["ok"] and not _get(ch, "bed-low-end", "CELLO")["ok"]
    assert _get(ch, "bed-low-end", "CELLO")["evidence"]["share"] > 0.15
    # measured against the energy over 100 Hz: a loud sub-bass under the same cello does not hide it
    dil = _cue("DIL", _breathing(cello + _sine(45, 20, 0.6)), fi=2, fo=2)
    assert dil["an"]["lowmid_share"] == pytest.approx(bad["an"]["lowmid_share"], abs=0.02)


def test_music_treble_refuses_a_bright_cue_and_passes_a_dark_one():
    dark = _cue("DARK", _breathing(_tone(440, 20, (1, .3, .1))), fi=2, fo=2)
    bright = _cue("SAW", _tone(440, 20, [1 / k for k in range(1, 50)]), score_role="transition", fi=2)
    hiss = _cue("AIR", _tone(660, 20, (1, .3)) + np.random.default_rng(0).normal(0, 0.03, 20 * RATE).astype(np.float32),
                score_role="outro", fi=2, fo=2)
    ch = _checks([dark, bright, hiss])
    assert _get(ch, "music-treble", "DARK")["ok"]
    assert not _get(ch, "music-treble", "SAW")["ok"] and not _get(ch, "music-treble", "AIR")["ok"]
    assert _get(ch, "music-treble", "SAW")["evidence"]["share"] > SC.STANDARD["music_treble_max_share"]


# --------------------------------------------------------------------------
# The brand pulse
# --------------------------------------------------------------------------

def _pulse(harm, seconds=6.0, bpm=60):
    x = _tone(55.0, seconds, harm, 0.3)
    ph = (_t(seconds) * bpm / 60) % 1
    return (x * np.exp(-ph / 0.35) * np.minimum(1, ph / 0.02)).astype(np.float32)


def test_a_brand_pulse_is_a_role_levelled_as_a_featured_cue():
    assert SC.cue_role({"kind": "music", "role": "brand_pulse"}) == "brand_pulse"
    assert SC.role_problem({"kind": "music", "role": "brand_pulse"}) is None
    assert SC.role_problem({"kind": "music", "role": "brand_pulse", "score_role": "brand_pulse"}) is None
    assert SC.role_problem({"kind": "music", "score_role": "brand_pulse"})            # an underscore cue may not claim it
    p = _cue("P", _pulse((1, 0, .25)), role="brand_pulse")
    assert p["role"] == "brand_pulse" and p["shaping"] is None                         # never band-shaped: its sub-bass is the point
    assert p["an"]["integrated_unfaded_lufs"] == pytest.approx(SC.FEATURE_LUFS, abs=0.5)


def test_the_pulse_must_carry_a_harmonic_a_phone_can_play():
    floor = SC.pulse_floor_lufs()
    assert floor == SC.DIALOGUE_LUFS - SC.PULSE_PHONE_UNDER_DIALOGUE_DB
    pure = _cue("PURE", _pulse((1,)), role="brand_pulse")
    soft = _cue("SOFT", _pulse((1, 0, .25)), role="brand_pulse")                     # a twelfth up, 12 dB down
    ch = _checks([pure, soft], cards=[(0.0, 6.0)])
    assert not _get(ch, "phone-check", "PURE")["ok"] and _get(ch, "phone-check", "PURE")["evidence"]["phone_lufs"] < floor - 10
    assert _get(ch, "phone-check", "SOFT")["ok"]
    assert pure["an"]["sub_share"] > 0.99 and soft["an"]["sub_share"] > 0.9            # still bass-led


def test_the_pulse_plays_at_a_card_or_where_no_voice_speaks():
    p = _cue("P", _pulse((1, 0, .25), 4.0), start=10.0, role="brand_pulse")
    v = np.zeros(300, bool)
    v[100:160] = True                                                                  # a voice from 10 s to 16 s
    assert not _get(_checks([p], voice100=v), "brand-pulse-place", "P")["ok"]          # under the narration
    assert _get(_checks([p], voice100=v, cards=[(11.0, 13.0)]), "brand-pulse-place", "P")["ok"]   # around a card
    assert not _get(_checks([p], voice100=v, cards=[(20.0, 24.0)]), "brand-pulse-place", "P")["ok"]
    v[:] = False
    assert _get(_checks([p], voice100=v), "brand-pulse-place", "P")["ok"]              # a voiceless stretch
    assert not _get(_checks([p]), "brand-pulse-place", "P")["ok"]                      # no voice measured, no card


def test_a_lifted_brand_pulse_is_refused_at_plan_time(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "BP.wav", _pulse((1, 0, .25), 2.0))
    cue = {"id": "BP", "kind": "music", "role": "brand_pulse", "source": "t", "licence": "CC0", "start_s": 0.5, "end_s": 2.5}
    _edit_play(film, lambda p: p.update(music=[dict(cue, gain_db=3.0)]))
    with pytest.raises(R.Refused, match=r"underscore-gain \(BP\)"):
        _plan(film, "pulse-gain")
    _edit_play(film, lambda p: p.update(music=[cue]))
    _plan(film, "pulse-ok")


# --------------------------------------------------------------------------
# Regional punctuation
# --------------------------------------------------------------------------

def _regional(cid, start, seconds=6.0, moment="the line is announced"):
    x = _breathing(_tone(523.25, seconds, (1, .4, .2)))
    return _cue(cid, x, start, score_role="regional", fi=1.5, fo=1.5, marks_moment=moment)


def test_a_regional_cue_names_its_moment_and_only_a_regional_cue_does(tmp_path):
    assert SC.cue_role({"kind": "music", "score_role": "regional"}) == "regional"
    assert SC.cue_role({"kind": "music", "wav": "score/regional_tanpura.wav"}) == "bed"     # only ever stated
    assert "marks_moment" in SC.role_problem({"kind": "music", "score_role": "regional"})
    assert SC.role_problem({"kind": "music", "score_role": "regional", "marks_moment": "  "})
    assert SC.role_problem({"kind": "music", "score_role": "regional", "marks_moment": "the award"}) is None
    assert SC.role_problem({"kind": "music", "score_role": "bed", "marks_moment": "the award"})
    film = make_film(tmp_path / "film")
    _write(film / "audio" / "RG.wav", _tone(523.25, 6.0))
    cue = {"id": "RG", "kind": "music", "score_role": "regional", "source": "t", "licence": "CC0", "start_s": 8.0,
           "end_s": 14.0, "fade_in_s": 1.5, "fade_out_s": 1.5}
    _edit_play(film, lambda p: p.update(music=[cue]))
    with pytest.raises(R.Refused, match=r"score-role \(RG\)"):
        _plan(film, "regional-bare")
    _edit_play(film, lambda p: p.update(music=[dict(cue, marks_moment="the award is read out")]))
    plan, j = _plan(film, "regional-ok")
    doc = R.sources_doc(plan, j, {})
    rg = next(c for c in doc["cues"] if c["id"] == "RG")
    assert rg["score_role"] == "regional" and rg["marks_moment"] == "the award is read out"
    assert "marks_moment" not in next(c for c in doc["cues"] if c["id"] == "C1")       # printed for regional cues only


def test_regional_density_short_sparse_and_a_small_share():
    a, b = _regional("R1", 30.0), _regional("R2", 100.0)                               # 6 s each, 64 s apart
    ch = _checks([a, b], dur=300.0)
    assert all(c["ok"] for c in ch if c["rule"] == "regional-density")
    assert _get(ch, "regional-density", "R1")["evidence"]["marks_moment"] == "the line is announced"
    assert not _get(_checks([_regional("LONG", 30.0, 12.0)], dur=300.0), "regional-density", "LONG")["ok"]
    near = _checks([a, _regional("R3", 50.0)], dur=300.0)                             # 14 s after R1 ends
    assert not _get(near, "regional-density", "R3")["ok"] and _get(near, "regional-density", "R3")["evidence"]["gap_s"] == 14.0
    crowd = _checks([a, b], dur=200.0)                                                 # 12 s in a 200 s film: 6%
    assert not _get(crowd, "regional-density", "regional")["ok"]
    assert _get(crowd, "regional-density", "regional")["evidence"]["share"] == pytest.approx(0.06, abs=0.001)


def test_a_regional_cue_sits_under_the_voice_like_a_bed():
    r = _regional("R1", 0.0)
    assert r["shaping"] is not None                                                    # band-shaped like a bed
    assert r["an"]["integrated_unfaded_lufs"] == pytest.approx(SC.bed_lufs(STD), abs=0.5)
    lifted = SC.place_cue({"id": "RL", "kind": "music", "score_role": "regional", "marks_moment": "x", "start_s": 0.0,
                           "end_s": 6.0, "fade_in_s": 1.5, "fade_out_s": 1.5, "gain_db": 6.0},
                          _tone(523.25, 6.0, (1, .4, .2)), STD)
    ch = _checks([r, lifted])
    assert _get(ch, "underscore-level", "R1")["ok"] and not _get(ch, "underscore-level", "RL")["ok"]
    assert {"bed-low-end", "music-treble", "music-entry"} <= {c["rule"] for c in ch if c["unit"] == "R1"}


# --------------------------------------------------------------------------
# Repetition (founder: "patterns are repeating and it's jarring")
# --------------------------------------------------------------------------

def test_a_tiled_loop_is_refused_and_a_restatement_passes():
    p = _phrase()
    loop = _cue("LOOP", np.concatenate([p, p, p]), fi=2, fo=2)
    twice = _cue("TWICE", np.concatenate([p, p, _phrase(MELODY[::-1])]), fi=2, fo=2)
    moved = _cue("MOVED", np.concatenate([p, _phrase(shift=5), _phrase(shift=12)]), fi=2, fo=2)
    revoiced = _cue("VOICED", np.concatenate([p, _phrase(harm=(1, 0, .6, 0, .4, 0, .3)), _phrase(rhythm=RHYTHM)]), fi=2, fo=2)
    ch = _checks([loop, twice, moved, revoiced], dur=120)
    lp = _get(ch, "score-repetition", "LOOP")
    assert not lp["ok"] and lp["evidence"]["loop"]["period_s"] == pytest.approx(9.6, abs=0.15)
    assert lp["evidence"]["max_self_similarity"]["score"] >= 1.0
    for u in ("TWICE", "MOVED", "VOICED"):
        r = _get(ch, "score-repetition", u)
        assert r["ok"] and r["evidence"]["max_self_similarity"]["score"] < 0.95, u   # journaled, under the line


def test_a_loop_survives_a_breath_and_a_low_cut_but_a_held_chord_is_not_a_pattern():
    p = _phrase()
    t = _t(3 * len(p) / RATE)
    swell = (10 ** ((-4 + 4 * np.sin(2 * np.pi * t / 12.8)) / 20)).astype(np.float32)   # Nought's breathing curve
    disguised = _cue("D", SC.highpass(np.concatenate([p, p, p]) * swell, 340.0), fi=2, fo=2)
    assert not _get(_checks([disguised]), "score-repetition", "D")["ok"]
    chord = _cue("HELD", _tone(110, 30, (1, .5, .3)) + _tone(164.81, 30, (1, .5)), fi=2, fo=2)
    r = _get(_checks([chord]), "score-repetition", "HELD")
    assert r["ok"] and r["evidence"]["max_self_similarity"]["onset"] is None              # no rhythm: bed-breathing's to judge


def test_two_cues_alike_are_refused_the_brand_recurs_and_a_transformed_theme_passes():
    p = _phrase()
    a, b = _cue("A", p, 0.0, fi=2, fo=2), _cue("B", p, 30.0, fi=2, fo=2)
    r = _get(_checks([a, b]), "score-repetition", "music")
    assert not r["ok"] and r["evidence"]["duplicates"][0]["a"] == "A" and r["evidence"]["duplicates"][0]["b"] == "B"
    sting = _cue("S", p[: int(2.4 * RATE)], 50.0, score_role="sting", fo=1.0)              # a sting cut from the same phrase
    assert not _get(_checks([a, sting]), "score-repetition", "music")["ok"]
    for name, x in (("key", _phrase(shift=5)), ("register", _phrase(shift=12)),
                    ("orchestration", _phrase(harm=(1, 0, .6, 0, .4, 0, .3))), ("rhythm", _phrase(rhythm=RHYTHM))):
        r = _get(_checks([a, _cue("T", x, 30.0, fi=2, fo=2)]), "score-repetition", "music")
        assert r["ok"], name
        assert r["evidence"]["max_cross_similarity"]["score"] < 1.0
    m1, m2 = _cue("M1", p, 0.0, role="house_motif"), _cue("M2", p, 30.0, role="house_motif")
    assert not [c for c in _checks([m1, m2]) if c["rule"] == "score-repetition"]          # the brand recurs by design


# --------------------------------------------------------------------------
# bed-reuse: a film's own score is its own
# --------------------------------------------------------------------------

def _film_with_bed(tmp_path, name, slug, x, wav="score/bed_a.wav", **extra):
    film = make_film(tmp_path / name)
    _write(film / wav, x)
    cue = {"id": "M1", "kind": "music", "score_role": "bed", "source": "t", "licence": "CC0", "start_s": 0.5,
           "end_s": 0.5 + len(x) / RATE, "fade_in_s": 1.5, "fade_out_s": 2.0, "wav": wav, **extra}
    _edit_play(film, lambda p: p.update(slug=slug, music=[cue]))
    return film


def _reuse(film, registry):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    return {c["unit"]: c for c in SC.reuse_check(film, play, registry)["checks"]}


def test_bed_reuse_refuses_another_films_bed_by_content(tmp_path):
    import soundfile as sf
    other = _film_with_bed(tmp_path, "other", "other-film", _breathing(_tone(660, 12, (1, .3))))      # a 16-bit WAV
    reg = [{"slug": "other-film", "screenplay": other / "screenplay.json", "from": "test"}]
    bed = sf.read(str(other / "score" / "bed_a.wav"), dtype="float32")[0]
    # the same samples re-encoded as 32-bit float under another name: the content, not the bytes or the name
    same = _film_with_bed(tmp_path, "same", "this-film", bed, wav="score/my_bed.wav")
    _write(same / "score" / "my_bed.wav", bed, subtype="FLOAT")
    assert (same / "score" / "my_bed.wav").read_bytes() != (other / "score" / "bed_a.wav").read_bytes()
    r = _reuse(same, reg)
    assert not r["M1"]["ok"] and r["M1"]["evidence"]["used_by"][0] == {"film": "other-film", "cue": "M1", "wav": "bed_a.wav",
                                                                        "match": "whole"}
    folded = _film_with_bed(tmp_path, "fold", "fold-film", np.concatenate([bed, bed]))            # a fold of it
    r = _reuse(folded, reg)
    assert not r["M1"]["ok"] and r["M1"]["evidence"]["used_by"][0]["match"] == "first 5 s"
    own = _film_with_bed(tmp_path, "own", "own-film", _breathing(_tone(587.33, 12, (1, .3))))
    r = _reuse(own, reg)
    assert r["M1"]["ok"] and r["registry"]["ok"] and r["registry"]["evidence"]["films_checked"] == ["other-film"]
    assert _reuse(other, reg)["M1"]["ok"]                                                         # a film is not its own other


def test_bed_reuse_lets_the_brand_recur_and_reads_films_json_and_the_env(tmp_path, monkeypatch):
    motif = _tone(392, 8, (1, .3))
    a = _film_with_bed(tmp_path, "a", "film-a", motif, role="house_motif")
    b = _film_with_bed(tmp_path, "b", "film-b", motif, role="house_motif")
    reg = [{"slug": "film-a", "screenplay": a / "screenplay.json", "from": "test"}]
    assert list(_reuse(b, reg)) == ["registry"]                                                   # the motif is not checked
    root = tmp_path / "repo"
    root.mkdir()
    (root / "films.json").write_text(json.dumps({"v": 1, "films": [
        {"slug": "film-a", "screenplay_path": str(a / "screenplay.json")},
        {"slug": "film-c", "screenplay_path": "films/c/screenplay.json"},
        {"slug": "film-d"}]}), encoding="utf-8")
    monkeypatch.delenv("DOCUMENT_FILMS", raising=False)
    got = SC.film_registry(root)
    assert [g["slug"] for g in got] == ["film-a", "film-c", "film-d"]
    assert got[1]["screenplay"] == root / "films" / "c" / "screenplay.json" and got[2]["screenplay"] is None
    r = _reuse(b, got)
    assert not r["registry"]["ok"] and r["registry"]["evidence"]["not_found"][0]["film"] == "film-c"
    assert r["registry"]["evidence"]["not_located"] == ["film-d"]
    monkeypatch.setenv("DOCUMENT_FILMS", f"{a}{__import__('os').pathsep}{b / 'screenplay.json'}")
    assert [g["screenplay"] for g in SC.film_registry(root)] == [a / "screenplay.json", b / "screenplay.json"]
    monkeypatch.setenv("DOCUMENT_FILMS", "")
    assert SC.film_registry(root) == []


# --------------------------------------------------------------------------
# phone-check: the words clear on a small speaker
# --------------------------------------------------------------------------

def _speech(seconds):
    """A stand-in for speech: a 140 Hz voice with formant-band partials, syllables 4 a second."""
    t = _t(seconds)
    x = sum(a * np.sin(2 * np.pi * 140 * k * t) for k, a in ((1, .5), (2, .4), (4, .6), (7, .5), (12, .3), (20, .15)))
    return (0.2 * x * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2)).astype(np.float32)


def test_phone_check_hears_a_bed_that_covers_the_words_and_not_a_sub_bass():
    n = 12 * RATE
    voice = np.zeros(n, np.float32)
    voice[2 * RATE: 10 * RATE] = _speech(8.0)
    spans = [(2.0, 10.0)]
    vl = 20 * math.log10(float(np.sqrt(np.mean(voice[2 * RATE: 10 * RATE] ** 2))))

    def bg(x, db_under):
        lvl = 20 * math.log10(float(np.sqrt(np.mean(x ** 2))))
        return (x * np.float32(10 ** ((vl - db_under - lvl) / 20)))[:n]

    quiet = SC.phone_check(voice, bg(_tone(330, 12, (1, .5, .3)), 25), spans)["checks"][0]
    loud = SC.phone_check(voice, bg(_tone(330, 12, (1, .5, .3)), 8), spans)["checks"][0]
    sub = SC.phone_check(voice, bg(_sine(50, 12), 0), spans)["checks"][0]          # as loud as the voice, all of it sub-bass
    assert quiet["ok"] and quiet["evidence"]["min_margin_db"] >= SC.PHONE_VOICE_MARGIN_DB
    assert not loud["ok"] and loud["evidence"]["under"] > 0 and loud["evidence"]["min_margin_db"] < 10
    assert sub["ok"]                                                                # a phone plays none of it
    assert quiet["evidence"]["lines"] == 1 and quiet["evidence"]["windows"] >= 14


def test_the_mix_is_phone_checked_and_every_new_rule_is_journaled(tmp_path):
    film = make_film(tmp_path / "film")
    _write(film / "score" / "bed_x.wav", _breathing(_tone(660, 22, (1, .3))))
    _write(film / "score" / "pulse.wav", _pulse((1, 0, .25), 2.0))
    cues = [{"id": "M1", "kind": "music", "score_role": "bed", "source": "t", "licence": "CC0", "start_s": 4.5, "end_s": 21.5,
             "fade_in_s": 1.5, "fade_out_s": 2.0, "wav": "score/bed_x.wav"},
            {"id": "BP", "kind": "music", "role": "brand_pulse", "source": "t", "licence": "CC0", "start_s": 2.5,
             "end_s": 4.5, "wav": "score/pulse.wav"}]
    _edit_play(film, lambda p: p.update(music=cues))
    plan, j = _plan(film, "r10-mix")
    stems: dict = {}
    R.build_mix(plan, film, j, stems=stems)
    assert stems["phone"]["checks"][0]["rule"] == "phone-check" and stems["phone"]["checks"][0]["evidence"]["lines"] >= 1
    jj = J.Journal(film="r10-lints")
    R.score_lints(jj, plan, stems, draft=True, registry=[])
    seen = {(e["rule"], e.get("unit")) for e in J.read(jj.path) if e.get("kind") == "lint"}
    assert {("phone-check", "voice"), ("phone-check", "BP"), ("brand-pulse-place", "BP"), ("bed-low-end", "M1"),
            ("music-treble", "M1"), ("music-treble", "BP"), ("score-repetition", "M1"), ("bed-reuse", "M1"),
            ("bed-reuse", "registry")} <= seen
    place = next(e for e in J.read(jj.path) if e.get("rule") == "brand-pulse-place")
    assert place["status"] == "pass" and place["evidence"]["card"] in ([0.0, 2.5], [2.5, 4.5])   # the title or chapter card


def test_the_offline_checker_runs_the_new_checks(tmp_path):
    p = _phrase()
    film = _film_with_bed(tmp_path, "film", "fixture", np.concatenate([p, p, p]))
    rep = SC.offline(film, registry=[])
    fails = {(c["rule"], c["unit"]) for c in rep["checks"] if not c["ok"]}
    assert ("score-repetition", "M1") in fails
    assert {c["rule"] for c in rep["checks"]} >= {"phone-check", "bed-reuse", "score-repetition", "bed-low-end", "music-treble"}
    assert {"lowmid_share", "treble_share", "sub_share"} <= set(rep["cues"][0])
    _edit_play(film, lambda pl: pl["music"][0].update(score_role="regional"))
    rep = SC.offline(film, voices=False, registry=[])
    assert ("score-role", "M1") in {(c["rule"], c["unit"]) for c in rep["checks"] if not c["ok"]}  # no marks_moment
