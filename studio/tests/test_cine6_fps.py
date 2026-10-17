"""Cinematography ticket #6, GRAMMAR A44: the master frame rate per film (founder ruling 1 (c), 2026-10-17: "Per
film, the native rate of the majority of clip runtime. Real World masters at 30000/1001.").

A film masters at 24 or 30000/1001: stated in ``settings.master_fps``, else the native rate of the majority of its clip
runtime (a tie, or no clip, gives 24). A clip at the master's rate plays 1:1; any other is conformed by drop or repeat
and declared. Everything timed in seconds (stills, cards, dips, the label) keeps its seconds; frame counts follow."""

from __future__ import annotations

import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from conftest import HEIGHT, WORKERS, make_film
from studio.engine import cadence as CAD
from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import policy as POL
from studio.engine import render as R
from studio.engine import titles as TS

REAL_WORLD = Path("C:/Users/aacri/document-work/sept11")
BITS, BAR, BAND = 16, 40, (150, 190)        # a frame's index, written as 16 bars 40 px wide across the frame's middle


def lints(j, rule):
    return [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == rule]


def decisions(j):
    return [e for e in J.read(j.path) if e["kind"] == "decision"]


def _plan(film, name="t"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def _edit(film: Path, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


# --------------------------------------------------------------------------
# A clip whose every frame carries its own index (lossless), and how to read it back
# --------------------------------------------------------------------------


def indexed_clip(dest: Path, rate: str, seconds: float, size=(640, 360)) -> Path:
    """A synthetic clip at ``rate`` whose frame i shows i in binary: 16 black or white bars in a band across the middle
    of a mid-grey frame (clear of the glyph, the label and the watermark), encoded losslessly."""
    W, H = size
    n = int(math.floor(seconds * float(Fraction(rate))))
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([R.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
                          "-framerate", rate, "-i", "-", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
                          "-pix_fmt", "yuv420p", "-r", rate, str(dest)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    base = np.full((H, W), 128, np.uint8)
    for i in range(n):
        f = base.copy()
        for b in range(BITS):
            f[BAND[0]:BAND[1], b * BAR:(b + 1) * BAR] = 255 if (i >> b) & 1 else 0
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0, p.stderr.read().decode(errors="replace")
    return dest


def read_index(gray: np.ndarray, x0: int = 0, y0: int = 0) -> int | None:
    """The index a frame shows (None when a bar is neither black nor white: a dip, a dissolve, no clip)."""
    y = y0 + (BAND[0] + BAND[1]) // 2
    v = 0
    for b in range(BITS):
        px = int(gray[y, x0 + b * BAR + BAR // 2])
        if 60 < px < 196:
            return None
        v |= (px >= 196) << b
    return v


def decode_gray(path: Path, W: int, H: int) -> list[np.ndarray]:
    r = subprocess.run([R.ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "gray",
                        "-"], capture_output=True, check=True)
    a = np.frombuffer(r.stdout, np.uint8)
    return list(a.reshape(-1, H, W))


def ledger_item(fid: str, file: str, rate: str, seconds: float) -> dict:
    return {"id": fid, "file": file, "title": f"Synthetic frame-index pattern at {rate} fps, test fixture, not archival",
            "date": "2026", "creator": "void document studio (generated)", "archive": "studio test fixture",
            "archive_short": "test fixture", "item_url": None, "licence": "CC0", "basis": "generated for engine tests",
            "credit": "void document studio test fixture", "synthetic": True, "test_fixture": True,
            "data_source": "studio/tests/test_cine6_fps.py indexed_clip()", "generator": "test_cine6_fps.indexed_clip",
            "width": 640, "height": 360, "fps": rate, "telecined": False, "duration_s": seconds, "people": False,
            "shows_bodies": False}


# --------------------------------------------------------------------------
# The rate as a rational, and the majority rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize("v, want", [(24, CAD.HOUSE), ("24", CAD.HOUSE), (24.0, CAD.HOUSE), ("30000/1001", CAD.NTSC),
                                     ("29.97", CAD.NTSC), (29.97, CAD.NTSC), (" 30000/1001 ", CAD.NTSC)])
def test_a44_the_stated_rate_is_kept_exactly_as_a_rational(v, want):
    r = CAD.parse_rate(v)
    assert r == want and isinstance(r, Fraction)
    assert CAD.rate_str(r) == ("24" if want == CAD.HOUSE else "30000/1001")
    assert CAD.timescale(r) == (24000 if want == CAD.HOUSE else 30000)


@pytest.mark.parametrize("v", [25, 30, "30", 23.976, "24000/1001", "29.970", True, None, "fast", 29.9, float("nan")])
def test_a44_any_other_rate_is_refused(v):
    with pytest.raises(CAD.RateError, match="24 or 30000/1001"):
        CAD.parse_rate(v)


def test_a44_the_setting_is_linted_with_the_others():
    s, stated, probs = POL.film_settings({"settings": {"master_fps": "29.97"}})
    assert stated == {"master_fps": "30000/1001"} and not probs and "master_fps" not in s   # policy numbers stay numbers
    _, _, probs = POL.film_settings({"settings": {"master_fps": 25}})
    assert probs and "30000/1001" in probs[0]


def test_a44_the_majority_of_clip_runtime_sets_the_rate():
    ntsc, film, ten = Fraction(30000, 1001), Fraction(24), Fraction(10)
    assert CAD.majority([])[0] == CAD.HOUSE                                       # no clips: the house rate
    assert CAD.resolve(None, [])["from"] == "house"
    assert CAD.majority([{"rate": ntsc, "runtime_s": 30}, {"rate": film, "runtime_s": 29.9}])[0] == CAD.NTSC
    assert CAD.majority([{"rate": ntsc, "runtime_s": 29.9}, {"rate": film, "runtime_s": 30}])[0] == CAD.HOUSE
    assert CAD.majority([{"rate": ntsc, "runtime_s": 30}, {"rate": film, "runtime_s": 30}])[0] == CAD.HOUSE   # a tie: 24
    # telecined 29.97 is film under pulldown (24 after inverse telecine); 23.976 counts for 24 and 30 for 29.97
    assert CAD.majority([{"rate": ntsc, "runtime_s": 60, "telecined": True}, {"rate": ntsc, "runtime_s": 10}])[0] == CAD.HOUSE
    assert CAD.majority([{"rate": Fraction(24000, 1001), "runtime_s": 5}, {"rate": Fraction(30), "runtime_s": 6}])[0] == CAD.NTSC
    # a rate no master plays 1:1 (10 fps, 25, 59.94) does not vote
    rate, tally = CAD.majority([{"rate": ten, "runtime_s": 100}, {"rate": Fraction(25), "runtime_s": 100},
                                {"rate": ntsc, "runtime_s": 3}])
    assert rate == CAD.NTSC and tally == {"24": 0.0, "30000/1001": 3.0}
    # a stated rate wins over the majority
    assert CAD.resolve("24", [{"rate": ntsc, "runtime_s": 209}])["rate"] == CAD.HOUSE
    assert CAD.resolve(None, [{"rate": ntsc, "runtime_s": 209}]) == {
        "rate": CAD.NTSC, "name": "30000/1001", "fps": 30000 / 1001, "from": "majority",
        "tally": {"24": 0.0, "30000/1001": 209.0}, "problem": None}


@pytest.mark.skipif(not (REAL_WORLD / "screenplay.json").exists(), reason="Real World's working folder is not on this machine")
def test_a44_real_world_resolves_to_30000_1001_by_its_clips():
    play = json.loads((REAL_WORLD / "screenplay.json").read_text(encoding="utf-8"))
    cad = R.master_rate(play, R.load_ledgers(REAL_WORLD, play))
    assert cad["rate"] == CAD.NTSC and cad["name"] == "30000/1001" and cad["from"] == "majority"
    assert cad["tally"]["30000/1001"] > 200 and cad["tally"]["24"] == 0
    assert all(c["native"] == "30000/1001" for c in cad["clips"])


def test_a44_the_fixture_film_states_24_and_keeps_it(film):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assert play["settings"]["master_fps"] == 24
    cad = R.master_rate(play, R.load_ledgers(film, play))
    assert cad["rate"] == CAD.HOUSE and cad["from"] == "settings" and cad["tally"]["30000/1001"] > 0


# --------------------------------------------------------------------------
# The conform: 1:1 at the master's rate, else drop or repeat, declared
# --------------------------------------------------------------------------


def test_a44_conform_plan_follows_the_master():
    ntsc = {"fps": 30000 / 1001}
    film = {"fps": 24.0}
    c = R.conform_plan({"telecined": False}, ntsc, CAD.NTSC)
    assert c["method"] == "none" and c["filter"] == "" and c["out_rate"] == "30000/1001"
    c = R.conform_plan({"telecined": False}, film, CAD.NTSC)
    assert c["method"] == "repeat" and c["filter"] == "fps=30000/1001"
    c = R.conform_plan({"telecined": False}, ntsc, CAD.HOUSE)
    assert c["method"] == "drop" and c["filter"] == "fps=24" and c["out_fps"] == 24
    c = R.conform_plan({"telecined": True, "field_order": "tff"}, ntsc, CAD.NTSC)
    assert c["method"] == "ivtc" and c["filter"].endswith("decimate,fps=30000/1001")
    assert R.conform_plan({"telecined": False}, film)["method"] == "none"      # the default master is the house rate


def test_a44_the_conform_pattern():
    assert CAD.pattern(CAD.NTSC, CAD.NTSC, 300) == {"out_frames": 300, "source_frames": 300, "dropped": 0, "repeated": 0}
    up = CAD.pattern(24, CAD.NTSC, 300)          # 24 in 29.97: one frame in five shown twice, none dropped
    assert up["dropped"] == 0 and up["repeated"] == 60 and up["source_frames"] == 240
    down = CAD.pattern(CAD.NTSC, 24, 240)        # 29.97 in 24: one frame in five dropped (what Real World did at 24)
    assert down["repeated"] == 0 and down["dropped"] == 60
    # the closed form is ffmpeg's fps filter: frame i lands on slot round(i x master / src), a slot shows the latest
    for src, dst in ((24, CAD.NTSC), (CAD.NTSC, 24), (10, 24), (25, 24), (60, CAD.NTSC)):
        idx = CAD.source_indices(src, dst, 400)
        for k, i in enumerate(idx):
            assert CAD.output_slot(i, src, dst) <= k < CAD.output_slot(i + 1, src, dst)


def _reader_indices(path: Path, conf: dict, seconds: float, fps: float) -> list[int | None]:
    shot = {"id": "X", "in_s": 0.0, "_dur": seconds, "_item": {"_path": str(path)},
            "_video": {"fit": [640, 360], "conform": conf, "probe": R.probe_video(path)}}
    rd = R.VideoReader(shot, 0.0)
    try:
        n = int(round(seconds * fps))
        return [read_index(np.asarray(rd.frame(k / fps).convert("L"))) for k in range(n)]
    finally:
        rd.close()


def test_a44_a_24_clip_in_a_29_97_master_is_repeated_as_declared(tmp_path):
    src = indexed_clip(tmp_path / "film24.mkv", "24", 6.0)
    pr = R.probe_video(src)
    conf = R.conform_plan({"telecined": False}, pr, CAD.NTSC)
    assert conf["method"] == "repeat"
    n = int(round(5.0 * float(CAD.NTSC)))
    got = _reader_indices(src, conf, 5.0, float(CAD.NTSC))
    assert None not in got
    assert got == CAD.source_indices(24, CAD.NTSC, n)        # exactly the declared pattern, frame for frame
    pat = CAD.pattern(pr["fps"], CAD.NTSC, n)
    assert len(got) - len(set(got)) == pat["repeated"] > 0 and pat["dropped"] == 0
    assert sorted(set(got)) == list(range(got[0], got[-1] + 1))   # every source frame shown: none dropped


def test_a44_a_29_97_clip_in_a_29_97_master_reads_1_to_1(tmp_path):
    src = indexed_clip(tmp_path / "ntsc.mkv", "30000/1001", 10.5)
    conf = R.conform_plan({"telecined": False}, R.probe_video(src), CAD.NTSC)
    got = _reader_indices(src, conf, 10.0, float(CAD.NTSC))
    assert got == list(range(len(got))) and len(got) == 300


# --------------------------------------------------------------------------
# A strip rendered through the engine: a 29.97 film whose clip plays 1:1
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def strip(tmp_path_factory):
    """The fixture film with its clip replaced by 10 s of a 29.97 frame-index clip and no stated rate (so the majority
    rule masters it at 30000/1001), check-rendered at 640x360 up to the clip's shot."""
    base = tmp_path_factory.mktemp("strip")
    film = make_film(base / "film")
    indexed_clip(film / "footage" / "fx-index-2997.mkv", "30000/1001", 10.6)
    _edit(film, lambda d: d["items"].append(ledger_item("FX-INDEX", "fx-index-2997.mkv", "30000/1001", 10.6)),
          "footage-ledger.json")
    shift = 7.0

    def edit(p):
        p.pop("settings", None)
        s6 = _shot(p, "S6")
        s6.update(asset="FX-INDEX", in_s=0.0, out_s=10.0, native_fps=29.97)
        s6["sound"] = {"mode": "silent"}
        for part in p["parts"]:
            for s in part["shots"]:
                if s["start_s"] > s6["start_s"]:
                    s["start_s"] = round(s["start_s"] + shift, 4)
            for ln in part.get("lines", []):
                if ln["start_s"] > s6["start_s"]:
                    ln["start_s"] = round(ln["start_s"] + shift, 4)
            part["text"] = [t for t in part.get("text", []) if t["id"] != "T2"]
            for c in part.get("cues", []):
                if c["start_s"] >= s6["start_s"]:
                    c["end_s"] = round(c["end_s"] + shift, 4)
        p["subtitle_source"] = [c for c in p.get("subtitle_source", []) if c.get("ref") != "T2"]
        for c in p["subtitle_source"]:
            if c["start_s"] > s6["start_s"]:
                c["start_s"], c["end_s"] = round(c["start_s"] + shift, 4), round(c["end_s"] + shift, 4)
    _edit(film, edit)
    s6_start = _shot(json.loads((film / "screenplay.json").read_text(encoding="utf-8")), "S6")["start_s"]
    out = base / "out"
    summary = R.render(film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast",
                       until_s=s6_start + 0.5)
    plan, j = _plan(film, "strip-plan")
    return {"film": film, "out": out, "summary": summary, "plan": plan, "j": j}


def test_a44_the_strip_masters_at_30000_1001_by_the_majority_rule(strip):
    plan, j = strip["plan"], strip["j"]
    assert plan["fps"] == 30000 / 1001 and plan["fps_rate"] == "30000/1001"
    d = [e for e in decisions(j) if e["what"] == "master frame rate 30000/1001"]
    assert len(d) == 1 and "majority" in d[0]["why"] and d[0]["evidence"]["from"] == "majority"
    cad = lints(j, "cadence")
    assert len(cad) == 1 and cad[0]["severity"] == "review" and cad[0]["evidence"]["master_fps"] == "30000/1001"
    assert cad[0]["evidence"]["conformed"] == []                   # its one clip is at the master's rate
    s6 = next(s for s in plan["shots"] if s["id"] == "S6")
    assert s6["_video"]["conform"]["method"] == "none" and s6["_video"]["conform"]["filter"] == ""
    pr = R.probe_video(Path(strip["summary"]["master"]))
    assert pr["r_frame_rate"] == "30000/1001" and pr["rate"] == "30000/1001"


def test_a44_a_29_97_clip_plays_1_to_1_with_no_frame_dropped_or_repeated(strip):
    """Frame-exact: every output frame of the clip's shot shows source frame (in point + its offset in the shot)."""
    plan = strip["plan"]
    doc = json.loads(Path(strip["summary"]["sources"]).read_text(encoding="utf-8"))
    s6 = next(s for s in doc["shots"] if s["id"] == "S6")
    i6 = next(i for i, s in enumerate(plan["shots"]) if s["id"] == "S6")
    frames = decode_gray(Path(strip["summary"]["master"]), 640, 360)
    assert len(frames) == doc["frames"]
    seen = []
    for f in range(s6["start_frame"], s6["end_frame"]):
        if R.picture_level(plan, f, i6) < 1.0:
            continue                                 # the dips into and out of the shot
        k = read_index(frames[f])
        assert k == f - s6["start_frame"], (f, k)    # in_s 0: output frame k is source frame k
        seen.append(k)
    assert len(seen) >= 300 - 2 * 8                  # 10 s at 29.97 less the two dips' halves (0.25 s, 8 frames each)
    assert seen == list(range(seen[0], seen[-1] + 1))          # zero dropped, zero repeated


def test_a44_dips_keep_their_two_frame_black_floor_at_the_master_rate(strip):
    for ds in (0.5, 0.75, 1.0):
        assert M.dip_black_frames(ds, 30000 / 1001) >= M.DIP_HOLD_MIN_FRAMES
        assert M.dip_hold_s(ds, fps=30000 / 1001) == max(0.10 * ds, 2 / (30000 / 1001))
    assert all(e["status"] == "pass" and e["evidence"]["black_frames"] >= 2 for e in lints(strip["j"], "dip-black-hold"))
    plan = strip["plan"]
    frames = decode_gray(Path(strip["summary"]["master"]), 640, 360)
    i6 = next(i for i, s in enumerate(plan["shots"]) if s["id"] == "S6")
    f0 = plan["shots"][i6]["f0"]
    black = [f for f in range(f0 - 20, f0 + 20) if int(frames[f].max()) <= 20]
    assert len(black) >= M.DIP_HOLD_MIN_FRAMES and max(black) - min(black) == len(black) - 1
    # the cross-class rule is in seconds: 0.5 s is 15 frames at 29.97 (12 at 24)
    assert CAD.frame_floor(0.5, CAD.NTSC) == 15 and CAD.frame_floor(0.5, CAD.HOUSE) == 12


def test_a44_sources_json_frame_fields_agree_with_the_rate(strip):
    doc = json.loads(Path(strip["summary"]["sources"]).read_text(encoding="utf-8"))
    fps = doc["fps"]
    assert fps == pytest.approx(30000 / 1001) and doc["fps_rate"] == "30000/1001"
    assert doc["cadence"]["name"] == "30000/1001" and doc["cadence"]["from"] == "majority"
    assert round(doc["duration_s"] * fps) == doc["frames"]
    for s in doc["shots"]:
        assert round(s["start_s"] * fps) == s["start_frame"] and round(s["end_s"] * fps) == s["end_frame"], s["id"]
    for m in doc["marks"]:
        assert abs(m["from_s"] * fps - round(m["from_s"] * fps)) < 0.01
    assert doc["shots"][-1]["end_frame"] == doc["frames"]


def test_a44_stills_cards_and_the_label_keep_their_seconds(film, strip):
    p24, _ = _plan(film, "t24")
    p30 = strip["plan"]
    assert p24["fps"] == 24 and p30["fps"] == 30000 / 1001
    for a in p24["shots"]:
        if a["id"] in ("S6",) or a["start_s"] >= next(s for s in p24["shots"] if s["id"] == "S6")["start_s"]:
            continue                                 # the strip lengthened S6 and moved what follows it
        b = next(s for s in p30["shots"] if s["id"] == a["id"])
        assert abs(a["f0"] / 24 - b["f0"] / p30["fps"]) <= 0.5 / 24 + 0.5 / p30["fps"], a["id"]   # the same second
        assert a["_dur"] == b["_dur"]                                                              # stills and cards
    # the dot's whisper, hold, fold and 40 s repeat are seconds, not frames
    assert round(M.WHISPER.settle_time(), 3) == 0.357 and M.LABEL["hold"] == 2.0 and M.LABEL["exit"] == 0.75
    assert M.LABEL["repeat_s"] == 40.0 and M.LABEL_MAX_S == M.WHISPER.settle_time() + 2.0 + 0.75
    t24 = M.label_times(p24["marks"])
    t30 = M.label_times(p30["marks"])
    for i, a in enumerate(p24["shots"]):
        if a["start_s"] >= next(s for s in p24["shots"] if s["id"] == "S6")["start_s"]:
            break
        assert len(t24[i]) == len(t30[i]) and all(abs(x - y) <= 1 / 24 for x, y in zip(t24[i], t30[i])), a["id"]
    assert M.label_reveal(1.0, 0.0) == M.label_reveal(1.0, 0.0)   # no rate goes in: the curve is in seconds


def test_a44_the_encoder_and_the_cache_key_carry_the_rate(film):
    plan, _ = _plan(film, "t-enc")
    cmd = R.encoder_cmd(plan, Path("x.mp4"))
    assert cmd[cmd.index("-r") + 1] == "24" and cmd[cmd.index("-video_track_timescale") + 1] == "24000"
    ntsc = dict(plan, fps=30000 / 1001, fps_rate="30000/1001")
    cmd = R.encoder_cmd(ntsc, Path("x.mp4"))
    assert cmd[cmd.index("-r") + 1] == "30000/1001" and cmd[cmd.index("-video_track_timescale") + 1] == "30000"
    assert R.shot_key(plan, 2, {}) != R.shot_key(ntsc, 2, {})


def test_a44_a_title_master_maps_onto_a_29_97_film():
    assert [TS.source_frame(k) for k in range(5)] == [0, 1, 2, 3, 4]               # at 24: the master's own frames
    got = [TS.source_frame(k, 30000 / 1001) for k in range(300)]
    assert got == CAD.source_indices(24, CAD.NTSC, 300) and len(got) - len(set(got)) == 60
    assert all(TS.source_frame(TS.film_frame(j, 30000 / 1001), 30000 / 1001) == j for j in range(240))
    item = {"marks": [{"frame": 0, "cls": "DRAWN", "label": "x"}, {"frame": 120, "cls": "CARD"}]}
    assert TS.spans(item, 1000, 1300, 30000 / 1001) == [(1000, 1150, "DRAWN", "x"), (1150, 1300, "CARD", "")]
    assert TS.spans(item, 1000, 1240) == [(1000, 1120, "DRAWN", "x"), (1120, 1240, "CARD", "")]


# --------------------------------------------------------------------------
# The series titles (A40) in a 29.97 film: a master at the film's rate plays 1:1, else the 24 one is conformed
# --------------------------------------------------------------------------

NTSC_N = 120                                    # the A40 test master's 4 s at 30000/1001 (4.004 s)


def _at(frame24: int) -> int:
    return round(frame24 * (30000 / 1001) / 24)


def make_master_at(path, record_png, rate: str, n: int, tl, dip):
    """A40's synthetic master (the machine, the record held whole, a dip, the lockup; its marks burned in) rendered at
    ``rate``: the A40 test's make_master with its frame clock at that rate."""
    import test_a40_title_sequence as A
    from PIL import Image
    r = float(Fraction(rate))
    W, H = TS.SIZE
    fonts = M.Fonts()
    machine, rec, lock = A._machine(W, H), TS.hold_fit(Image.open(record_png), W, H), A._lockup(W, H)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    item = {"marks": tl, "dip": dip, "frames": n, "fps": rate}
    holds = TS.dip_hold_frames(item)
    shots = [{"start": m["frame"] / r, "cls": m["cls"], "label": m.get("label", "")} for m in tl]
    t0 = dip["centre_frame"] / r - dip["s"] / 2
    p = subprocess.Popen([R.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", rate,
                          "-i", "-", "-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "bgr0", str(path)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / r
        pic = machine if k < tl[1]["frame"] else rec if k < tl[2]["frame"] else lock
        if t0 <= t < t0 + dip["s"]:
            pic = Image.blend(black, pic, M.dip_level(t - t0, dip["s"], fps=r))
        if k not in holds:
            pic = M.mark_frame(pic, t, shots, fonts).convert("RGB")
        p.stdin.write(np.asarray(pic.convert("RGB")).tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return path


@pytest.fixture(scope="module")
def ntsc_titles(tmp_path_factory, film):
    """The A40 test masters plus the same title rendered at 30000/1001 (its marks, dip and beats at that clock)."""
    import test_a40_title_sequence as A
    d = tmp_path_factory.mktemp("masters")
    rec = film / "stills" / "FX-STILL-B.png"
    tl = [dict(m, frame=_at(m["frame"])) for m in A.TL]
    dip = dict(A.DIP, centre_frame=_at(A.DIP["centre_frame"]))
    alt = {"file": "ntsc.mkv", "frames": NTSC_N, "marks": tl, "dip": dip, "record_frames": [_at(40), _at(50)],
           "lockup_frame": _at(84)}
    return {"dir": d, "burned": A.make_master(d / "burned.mkv", rec),
            "ntsc": make_master_at(d / "ntsc.mkv", rec, "30000/1001", NTSC_N, tl, dip), "alt": alt}


def _titled_ntsc(tmp_path, ntsc_titles, item):
    """A40's titled fixture film, with no stated rate: its only clip is 29.97, so it masters at 30000/1001."""
    import test_a40_title_sequence as A
    return A.titled_film(tmp_path, ntsc_titles, item=item, edit=lambda p: p.pop("settings", None))


def _title_plan(film):
    import test_a40_title_sequence as A
    plan, j = A.plan_of(film)
    assert not isinstance(plan, R.Refused), plan
    for rule in A.RULES:
        if rule not in ("title-audio-slot",):
            assert A.passed(j, rule) or not A.lints(j, rule), (rule, A.lints(j, rule)[:1])
    return plan, j, next(s for s in plan["shots"] if s["id"] == "TS1")


def test_a44_a_title_declared_at_the_films_rate_plays_1_to_1(tmp_path, ntsc_titles):
    """The item's own file is 24; it declares a 30000/1001 master beside it: that one is chosen and plays 1:1."""
    plan, j, s = _title_plan(_titled_ntsc(tmp_path, ntsc_titles, {"masters": {"30000/1001": ntsc_titles["alt"]}}))
    assert plan["fps_rate"] == "30000/1001"
    assert s["_item"]["file"] == "ntsc.mkv" and s["_item"]["fps"] == "30000/1001" and s["_title"]["fps"] == 30000 / 1001
    assert s["f1"] - s["f0"] == NTSC_N
    cad = lints(j, "cadence")[0]["evidence"]
    assert cad["titles"] == [{"shot": "TS1", "asset": "TS-test", "file": "ntsc.mkv", "fps": "30000/1001", "how": "alternate"}]
    assert not [c for c in cad["conformed"] if c.get("shot") == "TS1"]            # 0 repeats: nothing to declare
    assert [TS.source_frame(k, plan["fps"], s["_title"]["fps"]) for k in range(NTSC_N)] == list(range(NTSC_N))
    pics = R.Pictures(plan)
    try:
        for k in (0, 1, 2, 44, 45, 46, 74, 75, 76, 104, 118, 119):
            pics.title(s, k / plan["fps"])
            want = TS.read_frame(R.ffmpeg(), str(ntsc_titles["ntsc"]), k, fps=30000 / 1001)
            assert np.array_equal(pics.title_native, want), k                  # frame k of the film is master frame k
    finally:
        pics.close()


def test_a44_a_title_whose_own_rate_is_the_films_plays_1_to_1(tmp_path, ntsc_titles):
    item = dict(ntsc_titles["alt"], fps="30000/1001")
    plan, j, s = _title_plan(_titled_ntsc(tmp_path, ntsc_titles, item))
    cad = lints(j, "cadence")[0]["evidence"]
    assert cad["titles"][0]["how"] == "own" and not [c for c in cad["conformed"] if c.get("shot") == "TS1"]
    assert s["f1"] - s["f0"] == NTSC_N


def test_a44_a_24_only_title_in_a_29_97_film_is_conformed_and_declared(tmp_path, ntsc_titles):
    plan, j, s = _title_plan(_titled_ntsc(tmp_path, ntsc_titles, None))
    assert s["_item"]["file"] == "burned.mkv" and s["_title"]["fps"] == 24
    cad = lints(j, "cadence")[0]["evidence"]
    assert cad["titles"][0]["how"] == "conform"
    conf = [c for c in cad["conformed"] if c.get("shot") == "TS1"]
    assert len(conf) == 1 and conf[0]["method"] == "repeat" and conf[0]["repeated"] > 0 and conf[0]["dropped"] == 0
    assert conf[0]["out_frames"] == s["f1"] - s["f0"] and conf[0]["source_frames"] == 96
    got = [TS.source_frame(k, plan["fps"], 24) for k in range(s["f1"] - s["f0"])]
    assert len(got) - len(set(got)) == conf[0]["repeated"]
    assert any(e["what"].startswith("TS1: the series titles (24 fps) conformed") for e in decisions(j))


def test_a44_a_24_film_keeps_its_24_title_even_with_a_29_97_one_declared(tmp_path, ntsc_titles):
    import test_a40_title_sequence as A
    film = A.titled_film(tmp_path, ntsc_titles, item={"masters": {"30000/1001": ntsc_titles["alt"]}})   # states 24
    plan, j, s = _title_plan(film)
    assert plan["fps"] == 24 and s["_item"]["file"] == "burned.mkv" and lints(j, "cadence")[0]["evidence"]["titles"][0]["how"] == "own"
    assert TS.select_master({"fps": 25, "file": "x"}, 24.0)[1] == "conform" and TS.rate_of({"fps": 25}) is None
