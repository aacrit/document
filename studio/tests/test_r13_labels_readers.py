"""R13 (founder rulings, 2026-10-12): the readers' voicing EQ (A38 refined),
measured per voice and held by a lint, archival audio never EQ'd. The
label-rate guide (A39 refined) is tested with the marks in test_r2_marks.py."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import make_film
from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC
from studio.engine import voicing as VO

RATE = SC.RATE


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


def _edit(film, fn):
    data = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(data)
    (film / "screenplay.json").write_text(json.dumps(data), encoding="utf-8")


def _plan(film, name):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


@pytest.fixture()
def film(tmp_path):
    return make_film(tmp_path / "fixture")


def _shift(ex, lo=0.0, hi=0.0):
    """A spectrum moved from the narrator's: the chest (<= 315 Hz) by lo, everything from 4 kHz by hi."""
    return {c: v + (lo if c <= 315 else 0.0) + (hi if c >= 4000 else 0.0) for c, v in VO.NARRATOR_EXCESS.items()}


# --------------------------------------------------------------------------
# The derivation, both directions
# --------------------------------------------------------------------------

def test_the_derivation_gives_the_narrator_back_her_own_house_eq():
    """The readers are held to where Tara sits after hers: measured as a
    reader, she gets exactly the house narrator EQ (A38) back."""
    eq, ev = VO.derive(VO.NARRATOR_EXCESS, VO.NARRATOR_F0_HZ)
    assert eq == SC.NARRATOR_EQ_HOUSE
    assert ev["warmth_after_db"] == pytest.approx(VO.targets()["warmth_db"], abs=0.05)


def test_a_brighter_voice_is_cut_and_a_darker_one_is_never_lifted():
    bright, _ = VO.derive(_shift(VO.NARRATOR_EXCESS, hi=4.0), 120.0)
    brighter, _ = VO.derive(_shift(VO.NARRATOR_EXCESS, hi=8.0), 120.0)
    dark, ev = VO.derive(_shift(VO.NARRATOR_EXCESS, hi=-6.0), 120.0)
    assert bright["high"]["gain_db"] < SC.NARRATOR_EQ_HOUSE["high"]["gain_db"] < 0
    assert brighter["high"]["gain_db"] <= bright["high"]["gain_db"]
    assert dark["high"] == {"type": "high_shelf", "hz": 6000.0, "gain_db": 0.0, "slope": 1.0}   # never a boost
    # its treble is left where it was (only the bell's lift of the 500 Hz match moves it, by a tenth of a dB)
    assert ev["treble_after_db"] == {str(c): pytest.approx(v, abs=0.15) for c, v in ev["excess_db"].items()
                                     if int(c) in VO.TREBLE_BANDS}


def test_a_thin_voice_gets_warmth_and_a_full_one_none_and_the_bell_sits_just_above_its_f0():
    thin, _ = VO.derive(_shift(VO.NARRATOR_EXCESS, lo=-3.0), 120.0)
    full, _ = VO.derive(_shift(VO.NARRATOR_EXCESS, lo=4.0), 120.0)
    assert thin["low"]["gain_db"] > SC.NARRATOR_EQ_HOUSE["low"]["gain_db"] and full["low"]["gain_db"] == 0.0
    assert thin["low"]["hz"] == 135.0 == round(120.0 * VO.WARMTH_ABOVE_F0 / 5) * 5    # just above a man's 120 Hz
    assert VO.derive(VO.NARRATOR_EXCESS, 60.0)[0]["low"]["hz"] == 100.0              # clamped into the bounds
    assert VO.derive(VO.NARRATOR_EXCESS, 400.0)[0]["low"]["hz"] == 300.0
    assert "low" not in VO.derive(VO.NARRATOR_EXCESS, None)[0]                       # no f0, no bell


@pytest.mark.parametrize("lo, hi", [(-30.0, 30.0), (30.0, -30.0), (0.0, 0.0), (-30.0, -30.0)])
def test_the_derivation_stays_inside_the_bounds_however_far_off_a_voice_is(lo, hi):
    eq, _ = VO.derive(_shift(VO.NARRATOR_EXCESS, lo=lo, hi=hi), 150.0)
    assert VO.eq_problems("derived", eq) == []


def test_the_long_term_spectrum_reads_a_tilt_and_ignores_level():
    rng = np.random.default_rng(5)
    n = 6 * RATE
    white = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    bright = np.fft.irfft(np.fft.rfft(white) * np.sqrt(np.maximum(f, 50.0) / 1000.0), n)  # +3 dB an octave
    x = (bright / np.abs(bright).max() * 0.5).astype(np.float32)
    a = VO.excess(VO.band_power([VO.levelled(x)])[0])
    b = VO.excess(VO.band_power([VO.levelled(x * 0.1)])[0])
    assert a == b                                                                     # levelled first
    assert abs(sum(a[c] for c in VO.NORM_BANDS)) < 0.25                                # matched over 500 Hz to 1 kHz
    # +3 dB an octave over the three octaves from 1 to 8 kHz, plus S3.5's own fall there (25.01 - 1.13 dB)
    assert a[8000] - a[1000] == pytest.approx(9.0 + VO.S35_NORMAL[1000] - VO.S35_NORMAL[8000], abs=1.0)
    assert VO.band_power([np.zeros(RATE, np.float32)]) == ({}, 0)                      # silence: nothing to measure


def test_voice_names_follow_the_cast_files():
    assert VO.voice_key({"engine": "kokoro", "voice": "bm_george"}) == "kokoro:bm_george"
    assert VO.voice_key({"engine": "kokoro-blend", "voice": "blend:br-m-2"}) == "blend:br-m-2"
    assert VO.voice_key({"engine": "kokoro", "voice": "blend:sa-m-4"}) == "blend:sa-m-4"
    assert VO.voice_key(None) is None and VO.voice_key({"engine": "kokoro"}) is None


# --------------------------------------------------------------------------
# The house table and the declaration
# --------------------------------------------------------------------------

def test_the_house_table_is_derived_never_hand_set_and_inside_the_bounds():
    data = json.loads(VO.TABLE.read_text(encoding="utf-8"))
    voices = data["voices"]
    assert len(voices) == 38 and data["bounds"] == json.loads(json.dumps(VO.READER_EQ_BOUNDS))
    assert data["target"]["warmth_db"] == VO.targets()["warmth_db"]
    for k, rec in voices.items():
        assert VO.eq_problems(k, rec["eq"]) == [], k
        ex = {int(c): v for c, v in rec["excess_db"].items()}
        assert VO.derive(ex, rec["f0_hz"])[0] == rec["eq"], k                         # re-derives exactly
        assert set(rec["films"]) <= {"smallpox", "episode-v2"} and rec["takes"] >= 1
    # the brightest readers measured (+14 dB at 6.3 to 8 kHz) take the deepest cut; the darkest keep their treble
    assert voices["kokoro:bm_george"]["eq"]["high"]["gain_db"] == -6.0
    assert voices["kokoro:hm_psi"]["eq"]["high"]["gain_db"] == 0.0


def test_adding_a_films_new_voices_never_moves_an_entry_the_table_holds():
    table = {"_note": "n", "target": {"warmth_db": 1.0}, "voices": {"kokoro:a": {"eq": {"high": {"hz": 6000, "gain_db": -1.0}}, "films": ["f1"]}}}
    built = {"voices": {"kokoro:a": {"eq": {"high": {"hz": 5000, "gain_db": -6.0}}, "films": ["f2"]},
                        "blend:b": {"eq": {"high": {"hz": 6000, "gain_db": 0.0}}, "films": ["f2"]}}}
    out, added = VO.add_voices(table, built)
    assert added == ["blend:b"]
    assert out["voices"]["kokoro:a"] == table["voices"]["kokoro:a"]          # the held entry is kept exactly
    assert out["voices"]["blend:b"] == built["voices"]["blend:b"] and out["_note"] == "n"
    assert table["voices"].keys() == {"kokoro:a"}                             # the input is not changed
    assert VO.add_voices(out, built)[1] == []                                  # nothing to add twice


def test_the_declaration_house_off_and_per_voice():
    play = {"cast": {"voices": [{"id": "v-1", "engine": "kokoro", "voice": "bm_george"},
                                {"id": "v-2", "engine": "kokoro", "voice": "new_voice"}]},
            "parts": [{"lines": [{"id": "R1", "kind": "testimony", "read_by": "v-1"},
                                 {"id": "R2", "kind": "testimony", "read_by": "v-2"},
                                 {"id": "A1", "kind": "testimony", "archival_audio": True, "clip": "X", "read_by": "v-1"},
                                 {"id": "N1", "kind": "narration", "read_by": "v-1"}]}]}
    table, _ = VO.load_table()
    assert VO.reader_voices(play) == {"R1": "kokoro:bm_george", "R2": "kokoro:new_voice"}   # never archival, never narration
    per, how, probs = VO.setting(play, table)
    assert how == "house (default)" and not probs
    assert per["kokoro:bm_george"] == {"eq": table["kokoro:bm_george"]["eq"], "how": "house table"}
    assert per["kokoro:new_voice"] == {"eq": None, "how": "house, measured on this film's takes"}
    per, how, _ = VO.setting(dict(play, reader_eq="off"), table)
    assert how == "off" and all(v["eq"] is None for v in per.values())
    own = {"low": {"type": "bell", "hz": 140.0, "gain_db": 1.0, "q": 1.0},
           "high": {"type": "high_shelf", "hz": 6000.0, "gain_db": -4.0, "slope": 1.0}}
    per, how, probs = VO.setting(dict(play, reader_eq={"kokoro:bm_george": own, "kokoro:new_voice": "off"}), table)
    assert how == "film" and not probs and per["kokoro:bm_george"]["eq"] == own and per["kokoro:new_voice"]["eq"] is None
    for bad in ({"kokoro:bm_george": dict(own, high=dict(own["high"], gain_db=-7.0))},          # past -6 dB
                {"kokoro:bm_george": dict(own, high=dict(own["high"], gain_db=1.0))},           # a treble boost
                {"kokoro:bm_george": dict(own, low=dict(own["low"], gain_db=4.0))},
                {"kokoro:nobody": "off"}, "loud", {"kokoro:bm_george": {"mid": own["low"]}}):
        assert VO.setting(dict(play, reader_eq=bad), table)[2], bad


# --------------------------------------------------------------------------
# The engine: applied, re-levelled, held by the lint, never on archival audio
# --------------------------------------------------------------------------

def test_a_reading_is_eqd_with_its_voices_eq_and_kept_at_its_loudness(film):
    plan, j = _plan(film, "r13-house")
    assert plan["reader_voices"] == {"L2": "test-tone:none"}
    eq = plan["reader_eq"]["test-tone:none"]
    evs = J.read(j.path)
    m = lints(evs, "reader-eq-measured")[0]                       # the fixture's voice is not in the house table
    assert m["severity"] == "review" and m["evidence"]["eq"] == eq and m["evidence"]["takes"] == 1
    assert lints(evs, "reader-eq-declared")[0]["status"] == "pass"
    stems = {}
    _, placed = R.build_mix(plan, film, j, stems=stems)
    evs = J.read(j.path)
    ev = lints(evs, "reader-eq")[0]
    assert ev["status"] == "pass" and ev["severity"] == "block"
    assert ev["evidence"]["voices"]["test-tone:none"]["eq"] == eq and ev["evidence"]["voices"]["test-tone:none"]["lines"] == 1
    assert "phone" in stems                                       # the phone check still hears the EQ'd voices
    assert {e["rule"] for e in evs if e["kind"] == "lint" and e.get("unit") == "L2"} >= {"voice-clean"}   # its own checks
    x = R._read_wav(film / "audio" / "L2.wav")
    g = 10 ** ((R.DIALOGUE_LUFS - SC.integrated_lufs(x)) / 20)
    y, rec = SC.apply_voice_eq((x * g).astype(np.float32), eq)
    assert SC.integrated_lufs(y) == pytest.approx(R.DIALOGUE_LUFS, abs=0.1)   # re-levelled to the dialogue target


def test_the_house_table_voice_is_used_and_off_leaves_the_reading_alone(film, monkeypatch):
    own = {"low": {"type": "bell", "hz": 250.0, "gain_db": 3.0, "q": 1.2},
           "high": {"type": "high_shelf", "hz": 5000.0, "gain_db": -6.0, "slope": 1.0}}
    monkeypatch.setattr(VO, "load_table", lambda path=VO.TABLE: ({"test-tone:none": {"eq": own}}, "test"))
    plan, j = _plan(film, "r13-table")
    assert plan["reader_eq"] == {"test-tone:none": own} and not lints(J.read(j.path), "reader-eq-measured")
    _, on = R.build_mix(plan, film, j)
    _edit(film, lambda p: p.update(reader_eq="off"))
    plan_off, j_off = _plan(film, "r13-off")
    assert plan_off["reader_eq"] == {"test-tone:none": None}
    _, off = R.build_mix(plan_off, film, j_off)
    ev = lints(J.read(j_off.path), "reader-eq")[0]
    assert ev["status"] == "pass" and ev["evidence"]["declared"] == "off"
    # the narrator is untouched by the readers' setting, and the reading's re-levelled loudness is the same
    a, b = ({x["id"]: x for x in p["lines"]} for p in (on, off))
    assert a["L1"] == b["L1"] and a["L2"]["level_db"] == b["L2"]["level_db"]


def test_an_eq_other_than_the_declared_one_is_refused_and_journaled_on_a_draft(film, monkeypatch):
    plan, j = _plan(film, "r13-swapped")
    real = SC.apply_voice_eq
    monkeypatch.setattr(SC, "apply_voice_eq",
                        lambda x, eq: real(x, eq if eq == plan["narrator_eq"] else dict(eq, high=dict(eq["high"], gain_db=-3.0))))
    with pytest.raises(R.Refused, match=r"reader-eq \(A38\): .*L2 \(test-tone:none\) was EQ'd"):
        R.build_mix(plan, film, j)
    j2 = J.Journal(film="r13-swapped-draft")
    R.build_mix(plan, film, j2, draft=True)
    ev = lints(J.read(j2.path), "reader-eq")[0]
    assert ev["status"] == "fail" and ev["severity"] == "warn"
    monkeypatch.setattr(SC, "apply_voice_eq", real)
    j3 = J.Journal(film="r13-other-declared")
    R.build_mix(dict(plan, reader_eq={"test-tone:none": SC.NARRATOR_EQ_HOUSE}), film, j3)
    assert lints(J.read(j3.path), "reader-eq")[0]["status"] == "pass"     # what is declared is what is applied


def test_a_reading_eqd_when_its_voice_is_declared_off_is_refused(film):
    plan, j = _plan(film, "r13-declared-off")
    voices = {"L2": "test-tone:none"}
    rec = {"eq": SC.NARRATOR_EQ_HOUSE, "relevel_db": -1.0, "response": [], "voice": "test-tone:none"}
    placed = {"lines": [{"id": "L2", "kind": "reading"}]}
    j = J.Journal(film="r13-declared-off-lint")
    bad = R.reader_eq_lints(j, dict(plan, reader_eq={"test-tone:none": None}, reader_voices=voices), {"L2": rec}, placed, False)
    assert bad and "not the declared None" in bad[0]
    bad = R.reader_eq_lints(j, dict(plan, reader_voices=voices), {}, placed, False)          # declared, never applied
    assert bad and "was EQ'd with None" in bad[0]
    arch = {"lines": [{"id": "L2", "kind": "archival"}]}
    bad = R.reader_eq_lints(j, dict(plan, reader_voices=voices), {"L2": rec}, arch, False)
    assert bad == ["L2 is archival audio and was EQ'd"]


def test_a_response_off_the_declaration_is_refused(film, monkeypatch):
    plan, j = _plan(film, "r13-response")
    real = SC.apply_voice_eq

    def off(x, eq):
        y, rec = real(x, eq)
        if eq != plan["narrator_eq"]:
            rec = dict(rec, response=[dict(c, error_db=0.9, measured_db=0.9, declared_db=0.0) for c in rec["response"]])
        return y, rec
    monkeypatch.setattr(SC, "apply_voice_eq", off)
    with pytest.raises(R.Refused, match="reader-eq"):
        R.build_mix(plan, film, j)


def test_archival_audio_is_never_eqd(film):
    plan, j = _plan(film, "r13-archival")
    x = R._read_wav(film / "audio" / "L2.wav")
    plan["lines"] = [dict(ln, archival_audio=True) if ln["id"] == "L2" else ln for ln in plan["lines"]]
    stems = {}
    mix, placed = R.build_mix(plan, film, j, stems=stems)
    L2 = {x["id"]: x for x in placed["lines"]}["L2"]
    assert L2["kind"] == "archival" and L2["level_db"] is None
    assert not lints(J.read(j.path), "reader-eq")                 # no reading left to hold
    # the archival line plays its own samples, unfiltered and unlevelled: nothing else sounds at 20.3 s
    at = int(round(20.3 * RATE))
    seg = mix[at: at + len(x)]
    assert len(seg) == len(x) and np.abs(seg - x).max() < 1e-6


def test_a_reading_with_no_cast_voice_cannot_declare_its_eq(film):
    _edit(film, lambda p: p["parts"][1]["lines"][1].update(read_by="v-99"))
    with pytest.raises(R.Refused, match="reader-eq-declared"):
        _plan(film, "r13-no-voice")
    _edit(film, lambda p: p.update(reader_eq="off"))
    plan, _ = _plan(film, "r13-no-voice-off")                     # off, nothing is declared, so nothing is missing
    assert plan["reader_eq"] == {}


def test_a_film_may_declare_its_own_reader_eq_inside_the_bounds(film):
    own = {"low": {"type": "bell", "hz": 140.0, "gain_db": 1.0, "q": 1.0},
           "high": {"type": "high_shelf", "hz": 6500.0, "gain_db": -4.0, "slope": 1.0}}
    _edit(film, lambda p: p.update(reader_eq={"test-tone:none": own}))
    plan, j = _plan(film, "r13-own")
    assert plan["reader_eq"] == {"test-tone:none": own} and plan["reader_eq_declared"] == "film"
    _edit(film, lambda p: p.update(reader_eq={"test-tone:none": dict(own, high=dict(own["high"], gain_db=-9.0))}))
    with pytest.raises(R.Refused, match="reader-eq-declared"):
        _plan(film, "r13-own-bad")
