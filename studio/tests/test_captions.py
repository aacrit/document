"""studio/engine/captions.py: English captions from the screenplay's
subtitle_source, against the Partition trailer's fitted screenplay (trimmed,
text only) and small hand-made screenplays."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from studio.engine import captions as C

FIXTURE = Path(__file__).resolve().parent / "fixture" / "captions-screenplay.json"
CUE_RE = re.compile(r"^(?P<id>\S+)\n(?P<a>\d\d:\d\d:\d\d\.\d{3}) --> (?P<b>\d\d:\d\d:\d\d\.\d{3})\n(?P<text>.+)$", re.S)


def secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt(text: str) -> list[dict]:
    assert text.startswith("WEBVTT\n\n")
    out = []
    for block in text.strip().split("\n\n")[1:]:
        m = CUE_RE.match(block)
        assert m, block
        out.append({"id": m["id"], "start": secs(m["a"]), "end": secs(m["b"]), "text": m["text"]})
    return out


def play_with(subs: list[dict], text: list[dict] | None = None) -> dict:
    return {"parts": [{"id": "ch-1", "kind": "chapter", "lines": [], "text": text or []}], "subtitle_source": subs}


@pytest.fixture(scope="module")
def trailer() -> list[dict]:
    return parse_vtt(C.captions(FIXTURE))


def test_trailer_cues_are_well_formed(trailer):
    assert len(trailer) > 20
    ids = [c["id"] for c in trailer]
    assert len(ids) == len(set(ids))
    for c in trailer:
        lines = c["text"].split("\n")
        assert 1 <= len(lines) <= 2, c
        assert all(len(line) <= 42 for line in lines), c
        assert c["end"] - c["start"] <= 7.0 + 1e-6, c
        assert "\u2014" not in c["text"]


def test_no_two_cues_overlap(trailer):
    for a, b in zip(trailer, trailer[1:]):
        assert a["end"] <= b["start"] + 1e-6, (a, b)


def test_a_split_reading_stays_on_screen_without_a_gap(trailer):
    by_ref: dict[str, list[dict]] = {}
    for c in trailer:
        by_ref.setdefault(c["id"].rsplit("-", 1)[0] if re.search(r"-\d+$", c["id"]) else c["id"], []).append(c)
    for ref, parts in by_ref.items():
        for a, b in zip(parts, parts[1:]):
            assert b["start"] == pytest.approx(a["end"], abs=1e-3), ref


def test_lower_thirds_fold_into_the_first_reading_cue(trailer):
    ids = [c["id"] for c in trailer]
    # Speaker lower thirds T1 to T4 and T6 to T8 sit over their readings: none stays a cue of its own.
    for t in ("T1", "T2", "T3", "T4", "T6", "T7", "T8"):
        assert not any(i == t or i.startswith(f"{t}-") for i in ids), t
    r1 = next(c for c in trailer if c["id"] in ("R1", "R1-1"))
    assert r1["text"].startswith("[Arthur Henderson]")
    assert r1["start"] == 62.0
    # A place lower third over silence stays its own bracketed cue.
    t5 = next(c for c in trailer if c["id"] in ("T5", "T5-1"))
    assert t5["text"].startswith("[New Delhi")


def test_cue_times_follow_the_resolved_screenplay(trailer):
    play = json.loads(FIXTURE.read_text(encoding="utf-8"))
    src = {c["ref"]: c for c in play["subtitle_source"]}
    r9 = [c for c in trailer if c["id"] == "R9" or c["id"].startswith("R9-")]
    assert r9[0]["start"] == pytest.approx(src["R9"]["start_s"], abs=1e-3)
    assert r9[-1]["end"] == pytest.approx(src["R9"]["end_s"], abs=1e-3)
    # The long Aizaz Rasul reading (25.7 s) is cut into parts that keep its words, in order.
    r8 = [c for c in trailer if c["id"].startswith("R8-")]
    assert len(r8) >= 4
    joined = " ".join(c["text"].replace("\n", " ") for c in r8)
    assert joined == "[Begum Aizaz Rasul] " + re.sub(r"\s+", " ", src["R8"]["en"]).strip()
    assert all(c["end"] - c["start"] >= 1.0 - 1e-6 for c in r8)


def test_split_shares_time_by_characters_and_keeps_two_lines():
    cue = C.Cue("R1", 10.0, 20.0, "word " * 40)
    parts = C.split_cue(cue)
    assert [p.ref for p in parts] == [f"R1-{i}" for i in range(1, len(parts) + 1)]
    assert parts[0].start == 10.0 and parts[-1].end == 20.0
    assert all(len(p.text.split("\n")) <= 2 for p in parts)
    assert all(b.start == pytest.approx(a.end) for a, b in zip(parts, parts[1:]))


def test_no_part_is_under_a_second_when_the_cue_can_afford_it():
    # A last word alone ("injured.") must not flash past.
    parts = C.split_cue(C.Cue("R1", 0.0, 10.4, "Verified casualties up to the evening of sixteenth March were one thousand and forty-six killed and one thousand one hundred and sixty-seven injured."))
    assert all(p.end - p.start >= 1.0 - 1e-6 for p in parts), [(p.text, p.end - p.start) for p in parts]
    assert parts[-1].end == 10.4


def test_a_short_cue_stays_whole():
    assert [(p.ref, p.text) for p in C.split_cue(C.Cue("N5", 6.5, 9.0, "Punjab, 1947."))] == [("N5", "Punjab, 1947.")]


def test_a_lower_third_over_nothing_is_kept_and_one_over_a_reading_is_folded():
    play = play_with(
        [
            {"ref": "T1", "start_s": 1, "end_s": 6, "en": "[Sir Evan Jenkins, Governor of the Punjab, 1947. Read by a computer voice.]"},
            {"ref": "R1", "start_s": 2, "end_s": 8, "en": "Neither the railways nor the main roads are safe."},
            {"ref": "T2", "start_s": 20, "end_s": 25, "en": "[Lahore, 1947]"},
        ],
        [
            {"id": "T1", "kind": "lower_third", "lines": ["Sir Evan Jenkins", "Governor of the Punjab, 1947", "Telegram  ·  read by a computer voice"]},
            {"id": "T2", "kind": "lower_third", "lines": ["Lahore", "1947"]},
        ],
    )
    cues = C.build_cues(play)
    assert [c.ref for c in cues] == ["R1", "T2"]
    assert cues[0].text.replace("\n", " ") == "[Sir Evan Jenkins] Neither the railways nor the main roads are safe."
    assert cues[1].text == "[Lahore, 1947]"


def test_a_lower_third_cue_timed_just_before_its_reading_still_folds_into_it():
    # The episode's LT-5: its cue ends 0.1 s before R1 starts, but the lower third is on screen over R1.
    play = play_with(
        [
            {"ref": "LT-5", "start_s": 147.365, "end_s": 148.565, "en": "[Arthur Henderson, Under-Secretary of State for India, 1947. Read by a computer voice.]"},
            {"ref": "T:R1", "start_s": 148.665, "end_s": 159.033, "en": "Verified casualties up to the evening of sixteenth March."},
        ],
        [{"id": "LT-5", "kind": "lower_third", "start_s": 148.665, "end_s": 153.665,
          "lines": ["Arthur Henderson", "Under-Secretary of State for India, 1947", "Hansard  ·  read by a computer voice"]}],
    )
    cues = C.build_cues(play)
    assert all(c.ref.startswith("T:R1") for c in cues)
    assert cues[0].text.startswith("[Arthur Henderson] Verified")
    assert all(c.end - c.start >= 1.0 for c in cues)


def test_an_em_dash_or_a_backwards_cue_is_refused():
    with pytest.raises(C.CaptionError, match="em dash"):
        C.build_cues(play_with([{"ref": "N1", "start_s": 0, "end_s": 2, "en": "Delhi \u2014 1947"}]))
    with pytest.raises(C.CaptionError, match="before it starts"):
        C.build_cues(play_with([{"ref": "N1", "start_s": 3, "end_s": 2, "en": "Delhi"}]))


def test_timestamps():
    assert C.timestamp(0) == "00:00:00.000"
    assert C.timestamp(186.6387) == "00:03:06.639"
    assert C.timestamp(3723.5) == "01:02:03.500"


def test_a_directory_prefers_the_fitted_screenplay_and_the_cli_writes_the_file(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "screenplay.fitted.json")
    (tmp_path / "screenplay.json").write_text(json.dumps(play_with([])), encoding="utf-8")
    assert C.find_screenplay(tmp_path).name == "screenplay.fitted.json"
    assert C.main([str(tmp_path)]) == 0
    vtt = (tmp_path / "captions-en.vtt").read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "[Arthur Henderson]" in vtt
    (tmp_path / "screenplay.fitted.json").unlink()
    assert C.find_screenplay(tmp_path).name == "screenplay.json"
    assert C.main([str(tmp_path / "missing")]) == 1
