"""--layers (loom Phase 2b, reports/briefs/modular-engine/architecture.md section 8 Phase 2):
flag off, the master is unchanged; flag on, every shot's clean plate (ProRes 422 HQ, with
handles), one full-length overlay pass (ProRes 4444 with alpha) and layers.json are written
under <out>/layers. The plates at their record frames, with the timeline's dissolves and dips,
under the overlay rebuild the master's frames; the dot's probes pass on the overlay alone."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import journal as J
from studio.engine import layers as LY
from studio.engine import motion as M
from studio.engine import render as R
from conftest import HEIGHT, WORKERS

# PSNR floors, in dB over 8-bit RGB (stated in the PR), measured on the fixture at 360p (2026-11-06).
# 1. Rebuild from the decoded layers against compose's own frame (no encode on that side): the layers' own loss.
#    Measured min 39.5 dB, on the fixture's saturated synthetic stills; the whole of it is the plates' 4:2:2
#    chroma (the same frames through lossless 4:2:2 score the same to 0.1 dB, through ProRes 4444 67 to 70 dB).
#    Card, clip and black frames score 46 to 91. Floor 38.
# 2. Rebuild against the decoded master. The master is itself lossy (x264 crf 12 4:4:4 segments, then crf 18
#    4:2:0): compose's own frames score only 34.3 dB against it on the testsrc clip. So the rebuild must score,
#    frame by frame, within 1 dB of what compose's frame scores against the master (measured: within 0.96 dB
#    on every frame where compose scores under 45 dB), and never under 33 dB (measured min 34.4).
PSNR_VS_COMPOSE_DB = 38.0
PSNR_VS_MASTER_DB = 33.0
MASTER_MARGIN_DB = 1.0
MASTER_NOISE_DB = 45.0              # above this both sides sit in the master's own noise: the margin is not judged
XSS = '"><img src=x onerror=alert(1)>'


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return 99.0 if mse == 0 else 10 * math.log10(255.0 ** 2 / mse)


# --------------------------------------------------------------------------
# Pure: what each plate holds, the estimate, the overlay's own clock
# --------------------------------------------------------------------------


def _shot(sid, kind, f0, f1, tr=None, mark="DRAWN", **kw):
    return dict({"id": sid, "kind": kind, "f0": f0, "f1": f1, "transition_in": tr or {"type": "cut"}, "mark": mark,
                 "_dur": (f1 - f0) / 24.0}, **kw)


def _plan(shots, frames=None, **kw):
    frames = frames if frames is not None else shots[-1]["f1"]
    return dict({"W": 640, "H": 360, "fps": 24.0, "fps_rate": "24", "frames": frames, "duration_s": frames / 24.0,
                 "shots": shots, "marks": [{"start": s["f0"] / 24.0, "cls": s["mark"], "label": "", "year": None}
                                           for s in shots],
                 "lower_thirds": [], "overlays": [], "subtitles": [], "wm_start": None, "card_spans": []}, **kw)


def test_a_still_extends_its_first_and_last_frame_by_a_second():
    plan = _plan([_shot("A", "archive_still", 0, 96), _shot("B", "archive_still", 96, 192)])
    sp = LY.plate_spec(plan, 0)
    assert (sp["head_frames"], sp["tail_frames"], sp["dissolve_out_frames"]) == (24, 24, 0)
    assert (sp["head_from"], sp["tail_from"]) == ("frozen", "frozen")
    assert (sp["plate_in"], sp["plate_out"], sp["frames"]) == (24, 120, 144)
    assert (sp["record_in"], sp["record_out"]) == (0, 96)


def test_a_master_at_2997_has_30_frame_handles():
    shots = [_shot("A", "card", 0, 90)]
    plan = _plan(shots, fps=30000 / 1001, fps_rate="30000/1001")
    assert LY.handle_frames(plan) == 30
    assert LY.plate_spec(plan, 0)["head_frames"] == 30


def test_the_tail_starts_with_the_frames_the_next_shots_dissolve_shows():
    a = _shot("A", "archive_still", 0, 96)
    b = _shot("B", "archive_still", 96, 192, tr={"type": "dissolve", "s": 0.75})
    plan = _plan([a, b])
    sp = LY.plate_spec(plan, 0)
    assert sp["dissolve_out_frames"] == 18                      # 0.75 s at 24
    assert sp["tail_frames"] == 24                              # the dissolve, then the rest of the second frozen
    long = _plan([a, dict(b, transition_in={"type": "dissolve", "s": 1.5})])
    assert LY.plate_spec(long, 0)["tail_frames"] == 36          # never shorter than the dissolve it carries


def test_a_clips_handles_are_as_long_as_its_source_allows():
    v = {"probe": {"duration_s": 4.0}}
    clip = _shot("C", "archive_video", 0, 72, in_s=0.5, out_s=3.5, _video=v)
    sp = LY.plate_spec(_plan([clip]), 0)
    assert (sp["head_frames"], sp["tail_frames"]) == (12, 12)    # half a second of reel either side
    assert (sp["head_from"], sp["tail_from"]) == ("source", "source")
    roomy = dict(clip, in_s=10.0, out_s=13.0, _video={"probe": {"duration_s": 60.0}})
    assert LY.plate_spec(_plan([roomy]), 0)["head_frames"] == 24
    at_zero = dict(clip, in_s=0.0, out_s=3.0)
    sp = LY.plate_spec(_plan([at_zero]), 0)
    assert sp["head_frames"] == 0 and sp["head_from"] == "none"
    unknown = dict(clip, _video={})
    sp = LY.plate_spec(_plan([unknown]), 0)
    assert (sp["head_frames"], sp["tail_frames"]) == (0, 0)


def test_a_clip_read_from_its_cached_span_has_only_the_spans_pad():
    span = {"offset_s": 99.0, "requested": [100.0, 103.0], "pad_s": 1.0, "file": "x.mkv"}
    clip = _shot("C", "archive_video", 0, 72, in_s=100.0, out_s=103.0, _video={"probe": {"duration_s": 3600.0}},
                 _span=span)
    assert LY.clip_room(clip) == (1.0, 1.0)
    edge = dict(clip, _span=dict(span, offset_s=99.6))
    assert LY.clip_room(edge)[0] == pytest.approx(0.4)


def test_the_estimate_counts_every_plate_frame_and_the_overlay():
    plan = _plan([_shot("A", "archive_still", 0, 96), _shot("B", "card", 96, 192)])
    specs = [LY.plate_spec(plan, i) for i in range(2)]
    px = 640 * 360
    plates = (144 + 144) * px * LY.PLATE_BPP / 8
    assert LY.layers_bytes(plan, specs) >= plates + 192 * px * LY.OVERLAY_BPP_QUIET / 8
    busy = dict(plan, lower_thirds=[{"start": 0.0, "end": 4.0, "lines": ["A"], "kind": "speaker", "flag": None}])
    assert LY.layers_bytes(busy, specs) > LY.layers_bytes(plan, specs)


def test_the_disk_floor_refuses_one_byte_short_and_passes_at_the_floor(tmp_path):
    class Usage:
        def __init__(self, free):
            self.free = free

    need = 5 * 1024 ** 3
    floor = 10 * 1024 ** 3
    with pytest.raises(R.Refused, match="under the 10 GB floor"):
        LY.check_disk(tmp_path, need, min_free_gb=10, disk_usage=lambda p: Usage(floor + need - 1))
    assert LY.check_disk(tmp_path, need, min_free_gb=10, disk_usage=lambda p: Usage(floor + need))["need_bytes"] == need


def test_a_folder_named_layers_that_is_not_ours_is_refused_and_left_alone(tmp_path):
    d = tmp_path / "layers"
    d.mkdir()
    (d / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(R.Refused, match="not an earlier render's layers"):
        LY._prepare_dir(d)
    assert (d / "notes.txt").read_text(encoding="utf-8") == "mine"
    ours = tmp_path / "ours" / "layers"
    (ours / "plates").mkdir(parents=True)
    LY._prepare_dir(ours)                                       # a run that stopped part way is resumed


@pytest.mark.parametrize("sid", [XSS, "../../escape", "CON", "a" * 200, "S1"])
def test_untrusted_shot_ids_become_safe_plate_names(sid):
    name = R.stem_file_name(sid, set())
    assert set(name) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    assert "/" not in name and "\\" not in name and name.strip(".")
    assert len(name) <= R.STEM_NAME_MAX and name.split(".")[0].upper() != "CON"


def _long_plan(seconds=90):
    f1 = int(seconds * 24)
    s = _shot("A", "archive_still", 0, f1, mark="ARCHIVE")
    plan = _plan([s])
    plan["marks"] = [{"start": 0.0, "end": float(seconds), "cls": "ARCHIVE", "label": "Archive, 1947", "year": "1947"}]
    return plan


def test_the_overlay_carries_the_dots_own_40_s_clock():
    """A42 on the overlay alone: the label grows at the cut, folds away, and grows again 40 s on and 80 s on,
    exactly as mark_state says, with the glyph passing its shape probe on every frame sampled."""
    plan = _long_plan()
    assert M.label_times(plan["marks"])[0] == [0.0, 40.0, 80.0]
    pics = R.Pictures(plan)
    seen = {}
    for t in (1.5, 20.0, 41.5, 60.0, 81.5):
        f = int(t * 24)
        probe: dict = {}
        canvas = np.asarray(LY.overlay_canvas(plan, pics, f, 0, probe))
        res = LY.probe_overlay_frame(plan, canvas, f, 0, probe["bare_rgba"])
        assert res["glyph"] == "ok", (t, res)
        seen[t] = res["label"]
    assert seen == {1.5: "on", 20.0: "off", 41.5: "on", 60.0: "off", 81.5: "on"}


def test_a_dips_black_hold_is_transparent_on_the_overlay():
    a = _shot("A", "archive_still", 0, 96)
    b = _shot("B", "archive_still", 96, 192, tr={"type": "dip", "s": 0.5})
    plan = _plan([a, b])
    hold = next(f for f in range(84, 108) if R.picture_level(plan, f, 0 if f < 96 else 1) <= 0.0)
    i = 0 if hold < 96 else 1
    pics = R.Pictures(plan)
    probe: dict = {}
    canvas = np.asarray(LY.overlay_canvas(plan, pics, hold, i, probe))
    assert not canvas[..., 3].any()
    assert LY.probe_overlay_frame(plan, canvas, hold, i, probe["bare_rgba"]) == {"glyph": "dip", "label": "dip", "ink": 0}


def test_the_overlay_is_what_compose_draws_over_the_picture():
    """Over any picture, the overlay composited by straight alpha is compose's own drawing to within
    one 8-bit step (PIL rounds each composite): a lower third, a text overlay and the label are up."""
    plan = _long_plan(20)
    plan.update(lower_thirds=[{"start": 0.5, "end": 4.5, "lines": ["Fixture speaker", "test stand-in, 1947"],
                               "kind": "speaker", "flag": None}],
                overlays=[{"start": 1.0, "end": 4.0, "text": "29.97 fps, 1947"}], wm_start=0.0)
    pics = R.Pictures(plan)
    rng = np.random.default_rng(7)
    picture = Image.fromarray(rng.integers(0, 256, (360, 640, 3), dtype=np.uint8), "RGB")
    for f in (36, 60, 90):
        want = np.asarray(R.draw_overlays(picture.convert("RGBA"), plan, pics, f, 0).convert("RGB")).astype(int)
        got = LY.compose_layers(np.asarray(picture), np.asarray(LY.overlay_canvas(plan, pics, f, 0))).astype(int)
        assert int(np.abs(want - got).max()) <= 1, f


# --------------------------------------------------------------------------
# The fixture film, in memory: plates and overlay as drawn, before any encode
# --------------------------------------------------------------------------


def test_the_layers_as_drawn_rebuild_compose_frame_for_frame(plan):
    """Every frame of the fixture, from the plates' frames as plate_frames yields them and the overlay as
    drawn, through the timeline's dissolves and dips: compose's frame to within one 8-bit step."""
    specs = [LY.plate_spec(plan, i) for i in range(len(plan["shots"]))]
    plates = {}
    for i, sp in enumerate(specs):
        items = list(LY.plate_frames(plan, i, sp))
        got, frames = items[-1], [np.asarray(x) for x in items[:-1]]
        assert len(frames) == got["head_frames"] + sp["record_frames"] + got["tail_frames"]
        assert got["tail_frames"] >= sp["dissolve_out_frames"]
        plates[sp["shot"]] = frames
    tl = LY.timeline(plan, specs)
    dis = {fr["record"]: (d["from"], fr) for d in tl["dissolves"] for fr in d["frames"]}
    lv = {x["record"]: x["level"] for x in tl["levels"]}
    pics, opics = R.Pictures(plan), R.Pictures(plan)
    worst = 0
    try:
        for run in tl["runs"]:
            i = next(k for k, s in enumerate(plan["shots"]) if s["id"] == run["plate"])
            for f in range(run["record_in"], run["record_out"]):
                plate = plates[run["plate"]][run["plate_in"] + f - run["record_in"]]
                prev = weight = None
                if f in dis:
                    src, fr = dis[f]
                    prev, weight = plates[src][fr["from_plate_frame"]], fr["weight"]
                got = LY.compose_layers(plate, np.asarray(LY.overlay_canvas(plan, opics, f, i)), prev=prev,
                                        weight=weight, level=lv.get(f, 1.0))
                want = np.asarray(R.compose(plan, pics, f, i))
                worst = max(worst, int(np.abs(got.astype(int) - want.astype(int)).max()))
    finally:
        pics.close()
        opics.close()
    assert worst <= 1


# --------------------------------------------------------------------------
# The fixture film, rendered with --layers
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def layered(film_safe, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("layers-out")
    summary = R.render(film_safe, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast",
                       write_layers=True)
    summary["out"] = out
    summary["manifest"] = json.loads((out / "layers" / "layers.json").read_text(encoding="utf-8"))
    return summary


def test_layers_off_is_unchanged(rendered, layered):
    """Flag off (the shared ``rendered`` fixture, the same film_safe and settings), the master is
    byte-identical to the render with the flag on: --layers adds a folder after the master."""
    assert Path(rendered["master"]).read_bytes() == Path(layered["master"]).read_bytes()
    assert not (Path(rendered["out"]) / "layers").exists()
    assert layered["manifest"]["master"]["sha256"] == J.sha256_file(Path(layered["master"]))


def test_layers_manifest_hashes_every_file(layered):
    d = Path(layered["out"]) / "layers"
    files = layered["manifest"]["files"]
    on_disk = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()} - {"layers.json"}
    assert set(files) == on_disk
    for rel, h in files.items():
        assert J.sha256_file(d / rel) == h, rel


def test_every_plate_holds_its_frames_with_handles_and_a_sidecar(layered):
    m, d = layered["manifest"], Path(layered["out"]) / "layers"
    shots = [p["shot"] for p in m["plates"]]
    assert shots == ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
    for p in m["plates"]:
        side = json.loads((d / (p["file"] + ".json")).read_text(encoding="utf-8"))
        assert side["shot"] == p["shot"] and side["file"] == Path(p["file"]).name
        assert R.count_frames(d / p["file"]) == side["frames"] == side["head_frames"] + side["record_frames"] + side["tail_frames"]
        assert side["plate_in"] == side["head_frames"] and side["plate_out"] - side["plate_in"] == side["record_frames"]
        assert side["record_out"] - side["record_in"] == side["record_frames"]
    by = {p["shot"]: p for p in m["plates"]}
    assert (by["S6"]["head_frames"], by["S6"]["tail_frames"], by["S6"]["head_from"]) == (12, 12, "source")
    assert by["S6"]["source"]["plate_frame_0_s"] == pytest.approx(0.0)
    assert by["S3"]["dissolve_out_frames"] == 18 and by["S3"]["tail_frames"] == 24
    assert all(by[s]["head_frames"] == 24 for s in ("S1", "S3", "S5", "S9"))


def test_the_layers_are_prores_at_the_master_rate(layered):
    d = Path(layered["out"]) / "layers"
    m = layered["manifest"]

    def stream(p):
        import subprocess
        r = subprocess.run([R.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_name,profile,pix_fmt,r_frame_rate,width,height", "-of", "json", str(p)],
                           capture_output=True, text=True)
        return json.loads(r.stdout)["streams"][0]

    plate = stream(d / m["plates"][0]["file"])
    assert (plate["codec_name"], plate["pix_fmt"], plate["r_frame_rate"]) == ("prores", "yuv422p10le", "24/1")
    assert "HQ" in plate["profile"]
    ov = stream(d / "overlay.mov")
    assert (ov["codec_name"], ov["r_frame_rate"]) == ("prores", "24/1")
    assert ov["pix_fmt"] in ("yuva444p10le", "yuva444p12le")             # 4444 decodes at its native 12 bits
    assert "4444" in ov["profile"]
    assert R.count_frames(d / "overlay.mov") == m["frames"] == layered["frames"]


def _decoded(layered):
    m, d = layered["manifest"], Path(layered["out"]) / "layers"
    W, H = m["width"], m["height"]
    plates = {p["shot"]: list(LY.read_frames(d / p["file"], W, H)) for p in m["plates"]}
    overlay = list(LY.read_frames(d / "overlay.mov", W, H, alpha=True))
    return m, plates, overlay


@pytest.fixture(scope="module")
def safe_plan(film_safe, layered):
    """The plan the layered render drew from: film_safe re-planned at the same size (it has no placeholders,
    so no card is filled after the mix)."""
    m = layered["manifest"]
    plan = R.build_plan(film_safe, W=m["width"], H=m["height"], burn_subtitles=False,
                        journal=J.Journal(film="layers-plan"))
    assert not R.plan_has_placeholders(plan)
    assert [s["f0"] for s in plan["shots"]] == [r["record_in"] for r in m["timeline"]["runs"]]
    return plan


@pytest.fixture(scope="module")
def rebuilt(layered):
    """Every record frame rebuilt from the decoded layers through layers.json's timeline."""
    m, plates, overlay = _decoded(layered)
    tl = m["timeline"]
    dis = {fr["record"]: (d["from"], fr) for d in tl["dissolves"] for fr in d["frames"]}
    lv = {x["record"]: x["level"] for x in tl["levels"]}
    out = {}
    for run in tl["runs"]:
        for f in range(run["record_in"], run["record_out"]):
            prev = weight = None
            if f in dis:
                src, fr = dis[f]
                prev, weight = plates[src][fr["from_plate_frame"]], fr["weight"]
            out[f] = LY.compose_layers(plates[run["plate"]][run["plate_in"] + f - run["record_in"]], overlay[f],
                                       prev=prev, weight=weight, level=lv.get(f, 1.0))
    return {"frames": out, "overlay": overlay, "manifest": m}


def _sample(m):
    """Every 6th frame, and every frame of each dissolve and dip, and each shot's first and last."""
    keep = set(range(0, m["frames"], 6))
    for d in m["timeline"]["dissolves"]:
        keep.update(fr["record"] for fr in d["frames"])
    keep.update(x["record"] for x in m["timeline"]["levels"])
    for r in m["timeline"]["runs"]:
        keep.update((r["record_in"], r["record_out"] - 1))
    return sorted(keep)


def test_plates_under_the_overlay_reproduce_the_master(layered, rebuilt, safe_plan):
    """The acceptance test's second half, measured: PSNR of the rebuild against compose's own frames
    (re-planned from the same film) and against the decoded master, on sampled frames, each over its floor
    (see the constants). An exact frame scores 99."""
    m = rebuilt["manifest"]
    frames = _sample(m)
    master = {}
    for k, arr in enumerate(LY.read_frames(layered["master"], m["width"], m["height"])):
        if k in frames:
            master[k] = arr
    assert len(master) == len(frames)
    plan = safe_plan
    pics = R.Pictures(plan)
    vs_master, vs_compose, compose_vs_master, short = [], [], [], []
    try:
        for f in frames:
            i = max(k for k, s in enumerate(plan["shots"]) if s["f0"] <= f)
            want = np.asarray(R.compose(plan, pics, f, i))
            got = rebuilt["frames"][f]
            vs_compose.append(psnr(got, want))
            vs_master.append(psnr(got, master[f]))
            compose_vs_master.append(psnr(want, master[f]))
            if compose_vs_master[-1] < MASTER_NOISE_DB and vs_master[-1] < compose_vs_master[-1] - MASTER_MARGIN_DB:
                short.append((f, round(vs_master[-1], 2), round(compose_vs_master[-1], 2)))
    finally:
        pics.close()
    report = {"frames": len(frames), "vs_compose_min": round(min(vs_compose), 2),
              "vs_compose_median": round(float(np.median(vs_compose)), 2),
              "vs_master_min": round(min(vs_master), 2), "vs_master_median": round(float(np.median(vs_master)), 2),
              "compose_vs_master_min": round(min(compose_vs_master), 2),
              "compose_vs_master_median": round(float(np.median(compose_vs_master)), 2)}
    print("layers PSNR", json.dumps(report))
    (Path(layered["out"]) / "layers-psnr.json").write_text(json.dumps(report), encoding="utf-8")
    assert report["vs_compose_min"] >= PSNR_VS_COMPOSE_DB, report
    assert report["vs_master_min"] >= PSNR_VS_MASTER_DB, report
    assert not short, short


def test_the_dots_probes_pass_on_the_decoded_overlay_alone(rebuilt, safe_plan):
    """Every frame of overlay.mov, decoded and laid over black: the glyph's shape and hue pass the
    mark-coverage check with nothing under them, and the label is up exactly when mark_state says."""
    m, overlay = rebuilt["manifest"], rebuilt["overlay"]
    assert len(overlay) == m["frames"]
    plan = safe_plan
    glyph, label, bad = {}, {}, []
    clear = [(0, 0, 0, 0)] * len(M.glyph_shape_probes(M.Layout(m["width"], m["height"])))
    for i, s in enumerate(plan["shots"]):
        for f in range(s["f0"], s["f1"]):
            res = LY.probe_overlay_frame(plan, overlay[f], f, i, clear)
            glyph[res["glyph"]] = glyph.get(res["glyph"], 0) + 1
            label[res["label"]] = label.get(res["label"], 0) + 1
            if res["glyph"] in ("fail", "shape") or res["label"] == "fail":
                bad.append((f, res))
    assert not bad, bad[:5]
    assert glyph.get("ok", 0) > 0 and label.get("on", 0) > 0 and label.get("off", 0) > 0
    assert m["overlay"]["probes"]["glyph"].get("fail", 0) == 0 and m["overlay"]["probes"]["label"].get("fail", 0) == 0


def test_layers_are_journaled(layered):
    evs = J.read(layered["journal"])
    lint = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "layers-overlay-mark"]
    assert lint and lint[0]["status"] == "pass"
    roles = {e.get("role") for e in evs if e["kind"] == "artifact"}
    assert {"layers/overlay.mov", "layers/layers.json"} <= roles
    assert any(e["kind"] == "human" and e.get("override") == "--layers" for e in evs)


def test_layers_refuse_a_span_or_a_check_render(film_safe, tmp_path):
    for kw in ({"shots": "S3..S4"}, {"until_s": 10.0}, {"audio_only": True}):
        with pytest.raises(R.Refused, match="--layers with --shots, --until or --audio-only"):
            R.render(film_safe, tmp_path / "o", height=HEIGHT, workers=1, min_free_gb=1, write_layers=True, **kw)
