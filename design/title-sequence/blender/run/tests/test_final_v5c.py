"""The Run v5c final: mastered at 29.97 (founder ruling 2026-10-25), the final_hq profile, no denoiser anywhere in the
scene or the job, and the shot's camera opens wide, never cuts, and ends on the record's pose."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import channel_v5c as C  # noqa: E402

TITLE = json.loads((RUN.parent / "title.json").read_text(encoding="utf-8"))
BAKE = Path("D:/document-media/title-sequence/run/sim/v5c/run-bake.json")


def test_titles_master_at_2997_and_final_hq_is_declared():
    assert TITLE["master_fps"] == "30000/1001"
    p = TITLE["render"]["final_hq"]
    assert p["res"] == [2560, 1440] and p["samples"] <= 1024 and p["noise_threshold"] >= 0.01
    assert p["use_denoising"] is False and p["fps"] == "30000/1001"
    src = (RUN / "render_whole.py").read_text(encoding="utf-8")
    assert '"--fps"' in src and '"--profile"' in src and 'default="final_hq"' in src


def test_the_v5c_scene_and_job_never_denoise():
    s = (RUN / "scene_v5c.py").read_text(encoding="utf-8")
    assert "cy.use_denoising = False" in s and "cy.use_preview_denoising = False" in s
    j = (RUN / "final_v5c.py").read_text(encoding="utf-8")
    assert 'prof.get("use_denoising", False) is False' in j and '"denoise": False' in j


def test_the_shot_is_one_continuous_move_ending_on_the_record():
    if not BAKE.exists():
        return
    import shot_v5c as SH
    bake = json.loads(BAKE.read_text(encoding="utf-8"))
    rest = json.loads((BAKE.parent / "run-timing.json").read_text(encoding="utf-8"))["rest_sim_s"]
    fr = SH.shot(bake, 30000 / 1001, rest)
    E = np.array([f["eye"] for f in fr])
    step = np.linalg.norm(np.diff(E, axis=0), axis=1)
    assert step.max() < 0.08                              # no cut: the eye never jumps between frames
    assert C.RUNTIME["min"] <= len(fr) / (30000 / 1001) <= C.RUNTIME["max"]
    eye, tgt = SH.record_pose()
    assert np.allclose(fr[-1]["eye"], eye) and fr[-1]["end"] == 1.0
    held = [f for f in fr if f["end"] >= 0.999]
    assert len(held) / (30000 / 1001) >= 0.5
    assert abs(fr[0]["eye"][2] - C.OPEN["height"]) < 1e-9


# ---- the ending fixed for A7 (2026-10-26): each film's record, its declared pose, the tail and the exposure ease

def test_each_record_lies_flat_inside_the_felt_clear_of_the_marble():
    rest = (2.4891, 1.581)                                  # run-timing.json's rest_xy
    assert np.allclose(C.record_rect("C20-METAR-0851"), C.ITEMS["record"]["rect"])
    for rec, r in C.RECORDS.items():
        x0, x1, y0, y1 = C.record_rect(rec)
        assert abs((x1 - x0) / (y1 - y0) - r["px"][0] / r["px"][1]) < 1e-9        # the scan's aspect, not stretched
        assert x0 >= C.WELL["x"][0] + 0.005 and x1 <= C.WELL["x"][1] - 0.005
        assert y0 >= C.WELL["y"][0] + 0.005 and y1 <= C.WELL["y"][1] - 0.005
        assert x0 - rest[0] >= C.R + 0.10                                       # the marble rests well short of it


def test_each_records_pose_window_passes_the_engines_pose_check():
    sys.path.insert(0, str(RUN.parents[3]))
    from studio.engine import titles as TT
    for rec, r in C.RECORDS.items():
        win = C.record_window(rec)
        assert TT.pose_problem(list(win), r["px"], 1920, 1080) is None
    assert C.record_window("C20-METAR-0851") == (0.0, 0.0, 1.0, 1.0)
    assert C.record_window("S-130")[1] == 0.0                                   # a tall page shows its masthead


def test_the_pose_is_straight_down_over_the_window_and_fills_the_frame_with_it():
    import shot_v5c as SH
    for rec in C.RECORDS:
        eye, tgt = SH.record_pose(rec)
        x0, x1, y0, y1 = C.record_window_m(rec)
        assert np.allclose(eye[:2], tgt[:2]) and np.allclose(tgt[:2], [(x0 + x1) / 2, (y0 + y1) / 2])
        width_at_sheet = (eye[2] - tgt[2]) * C.SENSOR_W / C.LENS_MM
        assert abs(width_at_sheet - (x1 - x0)) < 1e-9
        assert abs((x1 - x0) / (y1 - y0) - 16 / 9) < 0.01 * 16 / 9


def test_the_exposure_eases_onto_the_record_inside_the_tail_and_within_the_slew():
    import shot_v5c as SH
    fps = 30000 / 1001
    meter = list(np.linspace(-2.0, 1.0, 1000)) + [1.0] * 91
    k_from = 1061
    ev, f0 = SH.ease_exposure(meter, k_from, 2.75, fps, slew=1.0)
    assert ev[:f0] == meter[:f0]                                                # untouched before the ease
    assert all(abs(v - (m + 2.75)) < 1e-6 for v, m in zip(ev[k_from:], meter[k_from:]))   # settled at the pose
    d = np.abs(np.diff(np.array(ev[f0:]) - np.array(meter[f0:])))
    assert d.max() <= 1.0 / fps + 1e-9                                          # the ease itself moves <= 1 stop/s
    same, f0z = SH.ease_exposure(meter, k_from, 0.0, fps)
    assert same == meter and f0z == k_from


def test_rect_seen_finds_the_record_only_at_the_open_and_the_end():
    if not BAKE.exists():
        return
    import shot_v5c as SH
    bake = json.loads(BAKE.read_text(encoding="utf-8"))
    rest = json.loads((BAKE.parent / "run-timing.json").read_text(encoding="utf-8"))["rest_sim_s"]
    fr = SH.shot(bake, 30000 / 1001, rest, "S-16928")
    seen = SH.rect_seen(fr, C.record_rect("S-16928"), C.felt_top())
    on = np.where(seen > 0)[0]
    assert on.min() == 0 and seen[-1] > 0.9                                    # its 16:9 window fills the last frame
    assert not any(100 < f < 900 for f in on)
    fr_rw = SH.shot(bake, 30000 / 1001, rest)
    tail = SH.tail_from(fr_rw)
    assert all(np.allclose(a["eye"], b["eye"]) for a, b in zip(fr[:tail], fr_rw[:tail]))   # one shared prefix


def test_the_record_is_dead_matte_and_the_scene_takes_the_record():
    s = (RUN / "scene_v5c.py").read_text(encoding="utf-8")
    assert '"record": "C20-METAR-0851"' in s and 'C.RECORDS[rec]["tex"]' in s
    assert 'rough=1.0, sheen=0.0' in s and 'float(A["rec_spec"])' in s and '"rec_spec": "0.0"' in s
