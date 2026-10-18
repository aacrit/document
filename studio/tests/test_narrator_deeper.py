"""Founder rulings 2026-10-16: a deeper Tara (option C: every take lowered 2 semitones by PSOLA, declared per film
as the narrator's ``pitch_shift_st``, held to a stored variant of her profile), the readers' EQ target pinned to the
old Tara reference, and document-over-black, an advisory warning for long black under a reading from a document."""

import json
import math

import numpy as np
import pytest

from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import score as SC
from studio.engine import voicing as VO

TARA = {"engine": "orpheus", "voice": "tara"}
DEEP = dict(TARA, pitch_shift_st=-2)
WARM = {"low": {"type": "bell", "hz": 170.0, "gain_db": 3.0, "q": 0.9},
        "high": {"type": "high_shelf", "hz": 5000.0, "gain_db": -3.0, "slope": 0.8}}


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


def _st(a, b):
    return 12 * math.log2(a / b)


# --------------------------------------------------------------------------
# The stored profile and its declared variant
# --------------------------------------------------------------------------


def test_the_committed_profile_holds_tara_and_her_two_semitone_variant():
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    assert prof["voice"] == TARA and len(prof["takes"]) == 5          # the stock profile is unchanged
    (var,) = [v for v in prof["variants"] if v["voice"] == DEEP]
    assert sorted(var["takes"]) == [f"tara-2st-{k}.wav" for k in range(5)]   # the same five approved takes, shifted
    d = _st(var["baseline"]["f0_hz"], prof["baseline"]["f0_hz"])
    assert -2.3 < d < -1.5, d                                         # PSOLA lowers the measured median by about 2 st
    assert abs(var["baseline"]["centroid_hz"] / prof["baseline"]["centroid_hz"] - 1) < 0.10   # formants kept


def test_the_profile_is_chosen_by_the_films_declared_shift():
    stock, why = R.load_narrator_profile(TARA)
    assert stock["voice"] == TARA and "orpheus:tara)" in why
    deep, why = R.load_narrator_profile(DEEP)
    assert deep["voice"] == DEEP and "shifted -2 st" in why
    assert deep["baseline"]["f0_hz"] < stock["baseline"]["f0_hz"]
    assert R.load_narrator_profile(dict(TARA, pitch_shift_st=0))[0]["voice"] == TARA   # 0 is the stock voice
    none, why = R.load_narrator_profile(dict(TARA, pitch_shift_st=-3))   # no variant: no reference, never the stock one
    assert none is None and "none has that shift" in why                # (-1 st is now a stored variant: test_real_world)
    bad, why = R.load_narrator_profile(dict(TARA, pitch_shift_st="low"))
    assert bad is None and "not a number" in why
    other, why = R.load_narrator_profile({"engine": "orpheus", "voice": "leah", "pitch_shift_st": -2})
    assert other is None and "the film's narrator is orpheus:leah" in why   # zoe has her own entry (test_real_world)


def _profile_file(tmp_path, monkeypatch, stock_f0, variant_f0, cen=1100.0):
    f = tmp_path / "narrator-profile.json"
    f.write_text(json.dumps({"voice": {"engine": "test-tone", "voice": "none"},
                             "baseline": {"f0_hz": stock_f0, "centroid_hz": cen},
                             "variants": [{"voice": {"engine": "test-tone", "voice": "none", "pitch_shift_st": -2},
                                           "baseline": {"f0_hz": variant_f0, "centroid_hz": cen}}]}), encoding="utf-8")
    monkeypatch.setattr(R, "NARRATOR_PROFILE", f)


def _drift(lines_f0, declared, cen=1100.0):
    voice = {"engine": "test-tone", "voice": "none", **({"pitch_shift_st": declared} if declared is not None else {})}
    j = J.Journal(film=f"deep-{lines_f0}-{declared}")
    profiles = {f"N{k}": {"f0_hz": lines_f0 * (1 + 0.002 * k), "centroid_hz": cen, "f0_range_hz": 60.0, "wps": 2.5,
                          "mood": "plain" if k % 2 else "measured"} for k in range(6)}
    off = R.narrator_consistency_lints(j, profiles, False, voice)
    return off, {e["unit"]: e for e in lints(J.read(j.path), "narrator-drift")}


STOCK_F0 = 180.0
DEEP_F0 = STOCK_F0 * 2 ** (-2.3 / 12)       # a variant measured 2.3 st under the stock, past the 2 st block bound


def test_deeper_takes_declared_as_shifted_pass_drift(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, STOCK_F0, DEEP_F0)
    off, d = _drift(DEEP_F0, -2)
    assert off == [] and d["narrator-f0"]["status"] == "pass" and d["narrator-centroid"]["status"] == "pass"
    assert d["narrator-f0"]["evidence"]["reference"]["f0_hz"] == pytest.approx(DEEP_F0)
    assert "shifted -2 st" in d["narrator-f0"]["evidence"]["why"]


def test_deeper_takes_not_declared_are_held_to_the_stock_voice_and_refused(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, STOCK_F0, DEEP_F0)
    off, d = _drift(DEEP_F0, None)
    assert d["narrator-f0"]["status"] == "fail" and d["narrator-f0"]["evidence"]["grade"] == "block"
    assert any(o.startswith("narrator-drift f0 -2.") for o in off)


def test_unshifted_takes_declared_as_shifted_are_refused(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, STOCK_F0, DEEP_F0)
    off, d = _drift(STOCK_F0, -2)                                    # the declaration is checked against the takes
    assert d["narrator-f0"]["evidence"]["grade"] == "block" and any(o.startswith("narrator-drift f0 +2.") for o in off)


def test_a_declared_shift_with_no_stored_variant_has_no_reference(tmp_path, monkeypatch):
    _profile_file(tmp_path, monkeypatch, STOCK_F0, DEEP_F0)
    off, d = _drift(DEEP_F0, -1)
    assert off == [] and list(d) == ["narrator"] and d["narrator"]["severity"] == "review"
    assert d["narrator"]["evidence"]["check"] == "no reference profile"


def test_the_films_warm_narrator_eq_is_inside_the_bounds():
    eq, how, problems = SC.narrator_eq_setting({"narrator_eq": WARM})
    assert problems == [] and how == "film" and eq == WARM


# --------------------------------------------------------------------------
# The readers' target, pinned to the old Tara reference
# --------------------------------------------------------------------------


def test_the_reader_target_is_pinned_and_re_derives_from_the_old_reference():
    assert VO.derived_targets() == VO.targets() == VO.READER_TARGET
    assert VO.READER_TARGET_NARRATOR_EQ == SC.NARRATOR_EQ_HOUSE      # the pin is the house EQ R13 derived it from
    table = json.loads(VO.TABLE.read_text(encoding="utf-8"))
    assert table["target"]["warmth_db"] == VO.READER_TARGET["warmth_db"]
    assert {int(k): v for k, v in table["target"]["treble_db"].items()} == VO.READER_TARGET["treble_db"]


def test_a_new_narrator_eq_does_not_move_the_readers(monkeypatch):
    ex = {c: v for c, v in VO.NARRATOR_EXCESS.items()}
    ex.update({5000: 7.0, 6300: 11.0, 8000: 14.0, 160: 2.0, 200: 2.5})    # a bright, thin reader
    before = VO.derive(ex, 120.0)
    # the other direction: had the target followed the warm narrator EQ, it would have moved
    moved = VO.after_eq(VO.NARRATOR_EXCESS, WARM)
    assert abs(VO.warmth(moved) - VO.READER_TARGET["warmth_db"]) > 0.3
    monkeypatch.setattr(SC, "NARRATOR_EQ_HOUSE", WARM)                   # a later house change, or a film's own EQ
    assert VO.targets() == VO.READER_TARGET
    assert VO.derive(ex, 120.0) == before
    built = VO.build_table([])
    assert built["target"]["warmth_db"] == VO.READER_TARGET["warmth_db"]


# --------------------------------------------------------------------------
# document-over-black (advisory)
# --------------------------------------------------------------------------


def _doc_plan(tmp_path, black_s, *, intent="no-open-image-of-the-author", source="frus-1950-v05-d790", read_s=30.0):
    import soundfile as sf
    (tmp_path / "audio").mkdir(exist_ok=True)
    sf.write(str(tmp_path / "audio" / "R1.wav"), np.zeros(int(48000 * read_s), np.float32), 48000)
    f = R.FPS
    shots = [{"id": "A", "kind": "archive_still", "f0": 0, "f1": int((read_s + 2 - black_s) * f), "_part": "p"},
             {"id": "B", "kind": "black", "intent": intent, "f0": int((read_s + 2 - black_s) * f),
              "f1": int((read_s + 2) * f), "_part": "p"}]
    line = {"id": "R1", "kind": "testimony", "start_s": 1.0, "wav": "audio/R1.wav", "read_by": "v-01", "source": source}
    return {"film": str(tmp_path), "shots": shots, "lines": [line]}


@pytest.mark.parametrize("black_s,status", [(9.0, "pass"), (11.0, "pass"), (12.0, "fail"), (31.0, "fail")])
def test_document_over_black_warns_past_ten_seconds_and_never_refuses(tmp_path, black_s, status):
    plan = _doc_plan(tmp_path, black_s)
    j = J.Journal(film=f"doc-black-{black_s}")
    R.document_over_black_lints(j, plan)
    (e,) = lints(J.read(j.path), "document-over-black")
    assert e["status"] == status and e["severity"] == "warn" and e["evidence"]["advisory"] is True
    assert e["evidence"]["black_s"] == pytest.approx(black_s - 1.0, abs=0.1)     # the reading starts 1 s in
    if status == "fail":
        assert "quote cards" in e["evidence"]["fix"]


def test_document_over_black_leaves_out_a_count_of_the_dead_and_unsourced_lines(tmp_path):
    j = J.Journal(film="doc-black-exempt")
    R.document_over_black_lints(j, _doc_plan(tmp_path, 20.0, intent="count-of-the-dead"))
    R.document_over_black_lints(j, _doc_plan(tmp_path, 20.0, source=None))
    j.lint("probe", True, stage="scout", phase="preflight", unit="x", severity="warn")   # so the journal exists
    assert lints(J.read(j.path), "document-over-black") == []
