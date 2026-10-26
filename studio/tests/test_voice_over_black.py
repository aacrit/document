"""A55 (amending A30, P0 founder ruling 2026-10-18): voice-over-black. Small synthetic plan fixtures only, no film
render, no media files (every voice span here is a tape/archival span, so the lint never touches a WAV on disk)."""

from __future__ import annotations

from studio.engine import journal as J
from studio.engine import render as R

FPS = 24.0


def _lints(j, rule):
    if not j.path.exists():      # nothing was journaled at all (no shot reached the lint)
        return []
    return [e for e in J.read(j.path) if e.get("kind") == "lint" and e.get("rule") == rule]


def _line(lid, kind, start_s, dur_s):
    """A tape/archival span standing in for any voice line (narrator, reader or tape): no WAV file is needed."""
    return {"id": lid, "kind": kind, "start_s": start_s, "archival_audio": True, "clip": "x",
            "in_s": 0.0, "out_s": dur_s}


def _shot(sid, kind, f0, f1, *, transition_in=None, **extra):
    return dict({"id": sid, "kind": kind, "f0": f0, "f1": f1,
                 "transition_in": transition_in or {"type": "cut"}}, **extra)


def _plan(shots, lines):
    return {"shots": shots, "lines": lines, "film": ".", "fps": FPS}


def test_narrator_line_over_a_black_card_refuses():
    shots = [_shot("S1", "card", 0, int(5 * FPS))]
    lines = [_line("L1", "narration", 1.0, 1.0)]       # 1.0 to 2.0 s, inside the card's whole run
    j = J.Journal(film="vob-card")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert any(o.startswith("voice-over-black (S1") and "L1" in o and "founder P0" in o for o in out)
    e = _lints(j, "voice-over-black")[0]
    assert e["status"] == "fail" and e["evidence"]["lines"] == ["L1"] and e["evidence"]["overlap_s"]["L1"] == 1.0


def test_a_dip_hold_longer_than_allowed_refuses():
    # a dip of 4.0 s (abnormally long against GRAMMAR's own 0.5-1.0 s dip range, A28(b)) holds black for 0.4 s,
    # 9.6 frames at 24 fps, past DIP_HOLD_EXCEPTION_MAX_FRAMES: judged like sustained black.
    shots = [_shot("S1", "still", 0, int(2 * FPS)),
             _shot("S2", "still", int(2 * FPS), int(4 * FPS), transition_in={"type": "dip", "s": 4.0})]
    lines = [_line("L1", "testimony", 1.9, 0.3)]       # straddles the cut at 2.0 s, inside the 0.4 s hold window
    j = J.Journal(film="vob-dip-long")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert any(o.startswith("voice-over-black (S2") and "L1" in o and "founder P0" in o for o in out)
    e = next(e for e in _lints(j, "voice-over-black") if e["unit"] == "S2")
    assert e["status"] == "fail" and e["evidence"]["kind"] == "dip"


def test_an_ordinary_dip_holds_a_few_frames_and_passes():
    # the same line against a doctrine-ordinary 0.75 s dip (hold 0.075 s, 1.8 frames): well inside the exception.
    shots = [_shot("S1", "still", 0, int(2 * FPS)),
             _shot("S2", "still", int(2 * FPS), int(4 * FPS), transition_in={"type": "dip", "s": 0.75})]
    lines = [_line("L1", "testimony", 1.95, 0.1)]      # straddles the cut, inside the 0.075 s hold
    j = J.Journal(film="vob-dip-ok")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert not out
    e = next(e for e in _lints(j, "voice-over-black") if e["unit"] == "S2")
    assert e["status"] == "pass"


def test_voiceless_black_passes():
    shots = [_shot("S1", "black", 0, int(6 * FPS))]    # no line at all overlaps it
    j = J.Journal(film="vob-voiceless")
    out = R.voice_over_black_lints(j, _plan(shots, []))
    assert not out
    e = _lints(j, "voice-over-black")[0]
    assert e["status"] == "pass" and e["evidence"]["lines"] == []


def test_black_reason_no_longer_excuses_voiced_black():
    shots = [_shot("S1", "black", 0, int(5 * FPS), black_reason="the record falls silent here, deliberately")]
    lines = [_line("L1", "narration", 1.0, 1.0)]
    j = J.Journal(film="vob-reason")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert any(o.startswith("voice-over-black (S1") for o in out)


def test_a_document_reading_page_with_a_reader_passes():
    # a DRAWN document-reading still: kind is an ordinary still, never "black" or "card", so it is not black at all.
    shots = [_shot("S1", "archive_still", 0, int(8 * FPS), mark="DRAWN")]
    lines = [_line("L1", "testimony", 0.5, 6.0)]
    j = J.Journal(film="vob-document")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert not out
    assert _lints(j, "voice-over-black") == []         # the still never enters the black loop at all


def test_a_tape_span_over_black_refuses():
    shots = [_shot("S1", "card", 0, int(10 * FPS))]
    lines = [_line("L1", "testimony", 2.0, 3.0)]       # an archival/tape span, read via archival_audio + clip
    j = J.Journal(film="vob-tape")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert any(o.startswith("voice-over-black (S1") and "L1" in o for o in out)


def test_draft_warns_instead_of_refusing():
    shots = [_shot("S1", "card", 0, int(3 * FPS))]
    lines = [_line("L1", "narration", 0.5, 1.0)]
    j = J.Journal(film="vob-draft")
    out = R.voice_over_black_lints(j, _plan(shots, lines), draft=True)
    assert out == []
    e = _lints(j, "voice-over-black")[0]
    assert e["status"] == "fail" and e["severity"] == "warn"


def test_a_closed_intent_no_longer_excuses_voiced_black():
    # A30's closed list (count-of-the-dead read over bare black) is no excuse under A55 either.
    shots = [_shot("S1", "black", 0, int(5 * FPS), intent="count-of-the-dead")]
    lines = [_line("L1", "narration", 1.0, 2.0)]
    j = J.Journal(film="vob-intent")
    out = R.voice_over_black_lints(j, _plan(shots, lines))
    assert any(o.startswith("voice-over-black (S1") and "L1" in o for o in out)


def test_a_wav_backed_narration_line_over_black_refuses(tmp_path):
    # the narration path: no archival span, the line's own WAV gives its length (1.5 s at 1.0 s: 1.0 to 2.5 s)
    import numpy as np
    import soundfile as sf
    (tmp_path / "audio").mkdir()
    sf.write(str(tmp_path / "audio" / "N1.wav"), np.zeros(int(1.5 * R.AUDIO_RATE), dtype="float32"), R.AUDIO_RATE)
    shots = [_shot("S1", "still", 0, int(2 * FPS)), _shot("S2", "black", int(2 * FPS), int(6 * FPS))]
    plan = dict(_plan(shots, [{"id": "N1", "kind": "narration", "start_s": 1.0}]), film=str(tmp_path))
    j = J.Journal(film="vob-wav")
    out = R.voice_over_black_lints(j, plan)
    assert any(o.startswith("voice-over-black (S2") and "N1" in o for o in out)
    e = next(e for e in _lints(j, "voice-over-black") if e["unit"] == "S2")
    assert e["evidence"]["overlap_s"]["N1"] == 0.5


def test_a_tape_span_is_judged_where_the_mix_places_it():
    # A33(1b): a clip measured 600 ms late is placed earlier by its correction; a span that starts just after a
    # black card ends on paper lands over the card's tail in the mix, and refuses there.
    corr = R.CL.av_correction_s({"av_offset_ms": 600})
    assert corr > 0.2
    shots = [_shot("S1", "card", 0, int(2 * FPS)), _shot("S2", "still", int(2 * FPS), int(6 * FPS))]
    plan = dict(_plan(shots, [_line("L1", "testimony", 2.05, 2.0)]), assets={"x": {"av_offset_ms": 600}})
    j = J.Journal(film="vob-av")
    out = R.voice_over_black_lints(j, plan)
    assert any(o.startswith("voice-over-black (S1") and "L1" in o for o in out)
    assert not R.voice_over_black_lints(J.Journal(film="vob-av-0"), dict(plan, assets={"x": {}}))


def test_render_refuses_the_fixture_whose_reading_sits_over_black(film, tmp_path):
    # the wiring: render() runs voice_over_black_lints at pre-flight; the unmodified fixture has L2 inside S8
    from conftest import HEIGHT, WORKERS
    import pytest
    with pytest.raises(R.Refused, match=r"voice-over-black \(S8"):
        R.render(film, tmp_path / "out", height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast")
