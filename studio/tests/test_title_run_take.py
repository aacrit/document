"""The Run, the full take (design/title-sequence/blender/run): the sheet fitter, the camera's pan-guide limiter and
measure, the clock's frame counts at both rates. Pure maths; no Blender, no MuJoCo."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_D = Path(__file__).resolve().parents[2] / "design/title-sequence/blender/run"
sys.path.insert(0, str(_D))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"run_take_{name}", _D / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SF = _load("sheetfit")
CR = _load("camera_run")
B = _load("bench")


def test_a_fitted_sheet_meets_its_edge_and_reaches_under_the_sheet_before():
    fit = SF.fit_sheet(0.65, 0.867, 9.0, 0.02, 1.30, x_under=1.05)
    assert fit is not None
    c = SF.chord(fit["cx"], fit["cy"], 0.65, 0.867, fit["psi"], 0.02)
    assert c[1] == pytest.approx(1.30, abs=1e-9) and c[0] <= 1.05


def test_the_papyrus_is_stepped_onto_exactly_at_its_entry():
    fit = SF.fit_sheet(0.60, 0.108, 0.0, 0.0, 0.45, x_entry=0.21)
    c = SF.chord(fit["cx"], fit["cy"], 0.60, 0.108, fit["psi"], 0.0)
    assert c[0] == pytest.approx(0.21, abs=0.0016) and c[1] == pytest.approx(0.45, abs=1e-9)


def test_the_atlas_boards_put_their_hinge_where_the_clock_crossed_it():
    W, H, g = 0.5, 0.688, 0.0015
    fit = SF.fit_hinged(W, H, g, -14.0, 0.0, 0.58, 0.69, 0.40)
    assert fit is not None and fit["hinge"] == pytest.approx(0.58, abs=0.002)
    assert fit["board2"][1] == pytest.approx(0.69, abs=1e-9) and fit["board1"][0] <= 0.40


def test_the_limiter_holds_the_pan_guide_and_eases():
    ts = np.arange(0, 10, 1 / 240)
    path = np.stack([np.where(ts < 2, 0.0, 0.3 * (ts - 2)), np.zeros_like(ts)], 1)    # a jump to 0.3 m/s
    cap = np.full_like(ts, 0.05)
    out = CR.limit(path, ts, cap, cap)
    v = np.diff(out[:, 0]) * 240
    assert v.max() <= 0.05 + 1e-9
    a = np.diff(v) * 240
    assert np.abs(a).max() <= 0.05 / 0.8 + 1e-6


def test_a_locked_stretch_is_kept_exactly():
    ts = np.arange(0, 6, 1 / 240)
    path = np.stack([0.02 * np.sin(ts), np.zeros_like(ts)], 1)
    lock = ts < 3
    out = CR.limit(path, ts, np.full_like(ts, 0.1), np.full_like(ts, 0.1), locked=lock)
    assert np.array_equal(out[lock, 0], path[lock, 0])


def test_measure_reads_a_known_pan_in_pixels_a_frame():
    # top-down at 1 m: a target moving 0.01 m a frame along x crosses 0.01 / 0.72 * 1920 = 26.7 px a frame
    rows = [{"t": f / 24, "eye": [0.01 * f, 0.0, 1.0], "target": [0.01 * f, 1e-4, 0.0], "D": 1.0, "pitch": 89.99,
             "yaw": 90.0, "fstop": 4.0, "focus": 1.0} for f in range(0, 30)]
    m = CR.measure(rows, 2, 20)
    assert m[5]["cx"] == pytest.approx(0.01 / 0.72 * 1920, rel=0.02)


def test_frame_counts_at_both_rates():
    assert B.frames_at(54.0, 24) == 1296
    n = B.frames_at(54.0, B.NTSC)
    assert abs(n * 1001 / 30000 - 54.0) <= 0.5 * 1001 / 30000
    assert B.total_frames("C20-METAR-0851") == 1296 and B.total_frames("S-130") == 1272


def test_the_eye_sits_behind_the_target_at_its_distance_and_angle():
    e = CR.eye_from((1.0, 0.0, 0.0), 0.5, 30.0, 90.0)
    assert math.dist(e, (1.0, 0.0, 0.0)) == pytest.approx(0.5)
    assert e[2] == pytest.approx(0.25) and e[1] < 0
