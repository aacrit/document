"""--shots A..B: a check render of a span of shots. The whole film is planned and linted; only the span's
frames are rendered, from the full plan, with the full film's mix cut to the span to the sample. The span
never writes or passes as the film's master or sources.json."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio.engine import journal as J
from studio.engine import render as R
from conftest import HEIGHT, ROOT, WORKERS


def events(summary):
    return J.read(summary["journal"])


def by_id(plan):
    return {s["id"]: s for s in plan["shots"]}


def decode_small(path: Path, f0: int, f1: int) -> np.ndarray:
    """Frames [f0, f1) of a video, decoded to 160x90 grey (enough to tell frames apart, small in memory)."""
    r = subprocess.run([R.ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                        "-vf", f"select='between(n\\,{f0}\\,{f1 - 1})',scale=160:90:flags=area", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, 90, 160).astype(np.int16)


# --------------------------------------------------------------------------
# The span on the plan (pure)
# --------------------------------------------------------------------------


def test_parse_shots_takes_a_range_or_one_id():
    assert R.parse_shots("5.9..5.9bb") == ("5.9", "5.9bb")
    assert R.parse_shots(" S4 .. S6 ") == ("S4", "S6")
    assert R.parse_shots("C0") == ("C0", "C0")
    assert R.parse_shots(("S4", "S5")) == ("S4", "S5")
    for bad in ("..S5", "S4..", ""):
        with pytest.raises(R.Refused, match="--shots"):
            R.parse_shots(bad)


def test_the_span_is_the_films_own_frames_from_a_to_b(plan):
    s = by_id(plan)
    sp = R.shot_span(plan, "S4", "S6")
    assert (sp["i0"], sp["i1"], sp["ids"]) == (3, 5, ["S4", "S5", "S6"])
    assert (sp["f0"], sp["f1"]) == (s["S4"]["f0"], s["S6"]["f1"])
    assert sp["frames"] == sp["f1"] - sp["f0"] == round(sp["duration_s"] * plan["fps"])
    one = R.shot_span(plan, "S5", "S5")
    assert one["frames"] == s["S5"]["f1"] - s["S5"]["f0"]


def test_edge_transitions_play_as_in_the_film(plan):
    """S4 enters by a dissolve from S3; S7 enters by a dip, S5 is followed by a cut, S3 by S4's dissolve."""
    sp = R.shot_span(plan, "S4", "S6")
    assert sp["edge_in"]["transition"] == "dissolve" and "S3" in sp["edge_in"]["plays"]
    assert sp["edge_out"]["transition"] == "dip" and "falls into the dip" in sp["edge_out"]["plays"]
    before = R.shot_span(plan, "S2", "S3")               # S3 enters by a dip: it rises from black
    assert before["edge_in"]["transition"] == "dip" and before["edge_out"]["transition"] == "dissolve"
    assert "ends where the dissolve into S4 begins" in before["edge_out"]["plays"]
    assert R.shot_span(plan, "S9", "S9")["edge_out"]["transition"] == "end"


def test_unknown_ids_and_a_reversed_range_refuse(plan):
    with pytest.raises(R.Refused, match="no shot 'S99'"):
        R.shot_span(plan, "S4", "S99")
    with pytest.raises(R.Refused, match="no shot 'X1'"):
        R.shot_span(plan, "X1", "S4")
    with pytest.raises(R.Refused, match="reversed range"):
        R.shot_span(plan, "S6", "S4")


def test_span_samples_are_exact_and_tile_at_both_master_rates():
    p24 = {"fps": 24, "fps_rate": "24"}
    assert R.span_samples(p24, 48, 96) == (96000, 192000)
    p2997 = {"fps": 30000 / 1001, "fps_rate": "30000/1001"}
    n0, n1 = R.span_samples(p2997, 30, 60)                # 30 frames at 30000/1001 = 1.001 s
    assert (n0, n1) == (48048, 96096)
    a = R.span_samples(p2997, 7, 1234)
    b = R.span_samples(p2997, 1234, 5000)
    assert a[1] == b[0]                                   # neighbouring spans share their boundary sample
    assert a == (round(7 * 1601.6), round(1234 * 1601.6))
    x = np.arange(200000, dtype=np.float32)
    y = R.slice_mix(x, p24, 48, 96)
    assert len(y) == 96000 and y[0] == 96000 and y[-1] == 191999
    tail = R.slice_mix(x, p24, 96, 120)                   # past the mix's end: zero-padded to the span's length
    assert len(tail) == 48000 and tail[-1] == 0


def test_span_view_puts_the_span_at_time_zero(plan):
    sp = R.shot_span(plan, "S4", "S6")
    v = R.span_view(plan, sp)
    assert [s["id"] for s in v["shots"]] == ["S4", "S5", "S6"] and v["shots"][0]["f0"] == 0
    assert v["shots"][-1]["f1"] == sp["frames"] and v["frames"] == sp["frames"]
    assert all(0 <= float(ln["start_s"]) < sp["duration_s"] for ln in v["lines"])


# --------------------------------------------------------------------------
# A span rendered from the fixture film
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def span(film, rendered):
    out = rendered["out"]
    keep = lambda: {str(p.relative_to(out)): J.sha256_file(p) for p in out.rglob("*") if p.is_file()
                    and not str(p.relative_to(out)).startswith(("check-", "shots-", "master.check-", "master.shots-"))}
    before = keep()
    s = R.render(film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", shots="S4..S6")
    return {"summary": s, "out": out, "before": before, "after": keep()}


def test_a_span_never_touches_the_films_master_or_sources(span):
    s, out = span["summary"], span["out"]
    assert span["after"] == span["before"]                # master.mp4, sources.json, segments/ and work/ untouched
    assert Path(s["master"]) == out / "master.shots-S4-S6.mp4" and s["sources"] is None
    assert not list(out.glob("sources.shots-*")) and (out / "shots-S4-S6" / "segments").is_dir()
    assert s["partial"] is True and s["rendered"] == ["S4", "S5", "S6"]
    evs = events(s)
    roles = {e.get("role") for e in evs if e["kind"] == "artifact"}
    assert {"check-master", "check-segment", "check-mix-span"} <= roles
    assert not roles & {"master", "segment", "sources", "check-sources"}
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--shots"]
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "ok" and evs[-1]["shots"]["a"] == "S4"


def test_a_span_has_span_duration_times_fps_frames_at_the_master_rate(span, plan):
    s = span["summary"]
    sp = R.shot_span(plan, "S4", "S6")
    pr = R.probe_video(Path(s["master"]))
    assert R.count_frames(Path(s["master"])) == s["frames"] == sp["frames"] == round(sp["duration_s"] * 24)
    assert pr["r_frame_rate"] == "24/1" and (pr["width"], pr["height"]) == R.frame_size(HEIGHT) and pr["has_audio"]
    fmt = [e for e in events(s) if e["kind"] == "lint" and e.get("rule") == "master-format"][0]
    assert fmt["status"] == "pass" and fmt["evidence"]["expected_frames"] == sp["frames"]


def test_a_spans_segments_are_the_full_renders_byte_for_byte(span, rendered):
    full = {p.name.split(".")[0]: J.sha256_file(p) for p in (rendered["out"] / "segments").glob("*.mp4")}
    mine = {p.name.split(".")[0]: J.sha256_file(p) for p in (span["out"] / "shots-S4-S6" / "segments").glob("*.mp4")}
    assert set(mine) == {"S4", "S5", "S6"}
    assert all(mine[k] == full[k] for k in mine)


def test_a_spans_frames_are_the_films_frames_edges_included(span, rendered, plan):
    """Decoded from the two masters: the span's frame k is the film's frame f0 + k (within the final encode's
    loss), the dissolve from S3 at the start and the dip into S7 at the end included."""
    sp = R.shot_span(plan, "S4", "S6")
    a = decode_small(Path(span["summary"]["master"]), 0, sp["frames"])
    b = decode_small(Path(rendered["master"]), sp["f0"], sp["f1"])
    assert a.shape == b.shape and len(a) == sp["frames"]
    diff = np.abs(a - b).mean(axis=(1, 2))
    assert diff.max() < 2.0, diff.argmax()
    shifted = np.abs(a[1:] - b[:-1]).mean(axis=(1, 2))   # one frame off is visibly worse on the moving clip
    assert shifted.max() > diff.max()
    lead = decode_small(Path(rendered["master"]), sp["f0"] - 1, sp["f0"])[0]
    assert np.abs(a[0] - lead).mean() < 25                # mid-dissolve: S3 still showing in S4's first frame
    assert a[-1].mean() < a[len(a) // 2].mean()           # S6's tail falls into S7's dip


def test_a_spans_sound_is_the_full_mix_cut_to_the_sample(span, rendered, plan):
    sp = R.shot_span(plan, "S4", "S6")
    work = span["out"] / "shots-S4-S6" / "work"
    cut, sr = sf.read(str(work / "mix-shots-S4-S6.wav"), dtype="float32", always_2d=False)
    full, sr2 = sf.read(str(rendered["out"] / "work" / "mix-norm.wav"), dtype="float32", always_2d=False)
    assert sr == sr2 == R.AUDIO_RATE
    n0, n1 = R.span_samples(plan, sp["f0"], sp["f1"])
    assert (n0, n1) == (sp["f0"] * 2000, sp["f1"] * 2000)
    assert len(cut) == n1 - n0 and np.array_equal(cut, full[n0:n1])
    ev = [e for e in events(span["summary"]) if e.get("lens") == "span-mix"][0]
    assert ev["samples"] == [n0, n1] and ev["frames"] == [sp["f0"], sp["f1"]]


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kw,match", [
    ({"shots": "S4..S99"}, "no shot 'S99'"),
    ({"shots": "S6..S4"}, "reversed range"),
    ({"shots": "S4..S5", "until_s": 5.0}, "--shots and --until are exclusive"),
    ({"shots": "S4..S5", "from_shot": "S4"}, "--shots with --from"),
    ({"shots": "S4..S5", "audio_only": True}, "--shots with --audio-only"),
])
def test_bad_spans_refuse_before_any_frame(film, tmp_path, kw, match):
    j = J.Journal(film="shots-refused")
    with pytest.raises(R.Refused, match=match):
        R.render(film, tmp_path / "o", height=HEIGHT, workers=1, min_free_gb=1, journal=j, **kw)
    evs = J.read(j.path)
    assert evs[0]["lens"] == "run.start" and evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused"
    assert "--from" not in evs[-1]["resume"]["command"] or "from_shot" in kw    # a span resumes by running it again
    assert not list((tmp_path / "o").rglob("*.mp4"))


def test_the_cli_refuses_a_bad_span_with_exit_code_2(film, tmp_path):
    r = subprocess.run([sys.executable, "-m", "studio.engine.render", str(film), "--out", str(tmp_path / "o"),
                        "--res", "720", "--shots", "S5..S4", "--workers", "1"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "reversed range" in r.stderr
