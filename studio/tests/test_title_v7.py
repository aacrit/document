"""Title v7 "The Record Stands" (design/title-sequence/blender/v7): the plan's keyed kinematics and the analytic
acceptance tests that need no render (v7-acceptance.md A3, A4, A6, B1, B2, B3, C4). Numpy only; no Blender."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_D = Path(__file__).resolve().parents[2] / "design/title-sequence/blender/v7"
sys.path.insert(0, str(_D))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _D / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


P = _load("plan_v7")
C = _load("checks_v7")


def test_the_globe_is_scaled_by_its_measured_texel_density():
    meas = json.loads((_D / "globe-measure.json").read_text(encoding="utf-8"))
    assert meas["density_at_4m"]["median_px_per_mm"] == pytest.approx(P.DENSITY_AT_4M, abs=1e-3)
    assert P.D == pytest.approx(4.0 * P.DENSITY_AT_4M / P.DESIGN_DENSITY, abs=1e-3)
    assert P.DENSITY == pytest.approx(P.DESIGN_DENSITY, abs=1e-3)


def test_the_registration_is_a_rotation_and_its_pole_lies_in_the_ring_plane():
    R = P.registration()
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)
    fit = json.loads((_D / "registration-fit.json").read_text(encoding="utf-8"))
    assert fit["rms_deg"] <= 2.0                      # the spec's tolerance
    pole_native = R[:, 2]
    assert abs(math.degrees(math.asin(pole_native @ C.RING_NORMAL_NATIVE))) < 0.5


@pytest.mark.parametrize("bid", [b["id"] for b in P.BOARDS])
def test_each_rise_starts_on_a_bar_lasts_46_frames_and_settles_once_by_1_to_3_degrees(bid):
    b = P.board(bid)
    assert b["rise"] in P.BAR_STARTS
    a0 = P.rest_angle(bid)
    assert P.rise_angle(bid, b["rise"]) == pytest.approx(a0)
    assert P.rise_angle(bid, b["rise"] + P.RISE_FRAMES) == pytest.approx(P.LEAN_UP_DEG)
    track = [P.rise_angle(bid, b["rise"] + k / 8) for k in range(8 * P.RISE_FRAMES + 1)]
    assert 1.0 <= max(track) - P.LEAN_UP_DEG <= 3.0
    # one settle: the track crosses 60 once upward and once back down
    above = np.array(track) > P.LEAN_UP_DEG + 1e-9
    assert np.count_nonzero(np.diff(above.astype(int)) == 1) == 1


def test_a_prefix_board_lies_on_the_ball_and_the_record_rests_level_on_its_stand():
    for bid in ("T-08", "T-20"):
        q = P.panels(bid, P.board(bid)["rise"] - 1)[0]
        far = q["centre"] + q["ey"]                     # the top edge's middle, far from the hinge
        assert np.linalg.norm(far) == pytest.approx(P.R, abs=0.01)
    # the diptych's panels sit off the board's centre line, so the ball's sideways curve lifts them a little
    for q in P.panels("T-03", 59):
        assert np.linalg.norm(q["centre"] + q["ey"]) == pytest.approx(P.R, abs=0.03)
    assert P.rest_angle("C20-METAR-0851") == 0.0


def test_the_prefix_rise_gaps_shorten_twelve_then_six_seconds():
    s = [b["rise"] for b in P.BOARDS if not b.get("tail")]
    assert [round((s[i + 1] - s[i]) / P.FPS, 1) for i in range(2)] == [12.0, 6.0]


def test_the_cut_and_the_pose_sit_on_bar_lines():
    assert P.CUT in P.BAR_STARTS and P.POSE_FROM in P.BAR_STARTS


def test_the_record_never_shows_before_the_cut_and_no_prefix_board_after():
    rec = P.board("C20-METAR-0851")
    assert not P.in_shot(rec, P.CUT - 1) and P.in_shot(rec, P.CUT)
    for b in P.BOARDS[:3]:
        assert P.in_shot(b, P.CUT - 1) and not P.in_shot(b, P.CUT)


def test_the_pose_fills_the_frame_with_the_record_and_holds_still():
    c, u, n, W = P.board_centre_up("C20-METAR-0851")
    cam = P.camera_at(P.POSE_FROM)
    assert np.allclose(cam["E"], P.camera_at(P.FRAMES - 1)["E"])
    pts = np.vstack([P.corners(p) for p in P.panels("C20-METAR-0851", P.POSE_FROM)])
    px, _ = P.project(pts, cam)
    assert px[:, 0].min() == pytest.approx(0.0, abs=1.0) and px[:, 0].max() == pytest.approx(P.RES_REVIEW[0], abs=1.0)
    assert px[:, 1].min() == pytest.approx(0.0, abs=1.5) and px[:, 1].max() == pytest.approx(P.RES_REVIEW[1], abs=1.5)
    assert P.hold_mix(P.RAMP_FROM - 1) == 0.0 and P.hold_mix(P.POSE_FROM) == 1.0
    assert P.dust_scale(P.POSE_FROM - 1) == 0.0


def test_pchip_is_monotone_between_monotone_keys():
    x = np.array([0.0, 10.0, 30.0, 31.0, 60.0])
    y = np.array([0.0, 1.0, 5.0, 5.5, 9.0])
    v = P._pchip(x, y, np.linspace(0, 60, 601))
    assert np.all(np.diff(v) >= -1e-12) and v.min() >= 0.0 and v.max() <= 9.0


@pytest.mark.parametrize("bid", ["T-03", "T-08", "T-20"])
def test_each_prefix_record_is_read_square_at_half_the_frame_for_2_4_s(bid):
    r = C.read_stats(bid)
    assert r["good_s"] >= 2.4
    assert r["width_min"] >= 0.5
    assert r["square_max"] <= 12.0


def test_fill_pan_limb_and_rises_hold_on_the_analytic_pass():
    res, _ = C.run(step=3)
    assert res["B2"]["pass"], res["B2"]
    assert res["A2"]["pass"], res["A2"]
    assert res["C4"]["pass"], res["C4"]
    assert res["B3"]["pass"]
    assert all(r["pass"] for r in res["A4_A6"]["rises"].values())


def test_the_scene_never_turns_on_a_denoiser():
    src = (_D / "scene_v7.py").read_text(encoding="utf-8")
    assert "use_denoising = False" in src and "use_preview_denoising = False" in src
    assert "use_denoising = True" not in src
