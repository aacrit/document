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
