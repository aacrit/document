"""The Run v5d camera: the aim solved every frame from the marble's own position, Fable's keys honoured at their
frames, the ending and the pose exactly v5c's, the rack limits, and layout L0 (the jeton moved, nothing the marble
touches moved)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import channel_v5c as C  # noqa: E402
import shot_v5d as SD  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v5c")
FPS = 30000 / 1001


def _bake():
    p = SIM / "run-bake.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_the_aim_puts_the_marble_where_the_key_says():
    rng = np.random.default_rng(7)
    for _ in range(200):
        m = np.array([rng.uniform(0, 3), rng.uniform(0, 1.7), 0.0])
        az, h = rng.uniform(0, 2 * math.pi), rng.uniform(0.3, 1.0)
        eye = m + np.array([h * math.cos(az), h * math.sin(az), h * rng.uniform(0.05, 1.7)])   # up to 60 deg up
        sx, sy = rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4)
        fwd = SD.aim(eye, m, sx, sy)
        gx, gy, z = SD.screen_of(eye, fwd, m)
        assert z > 0 and abs(gx - sx) < 1e-9 and abs(gy - sy) < 1e-9
    import pytest
    with pytest.raises(ValueError):                   # straight below, at the frame's edge: no roll-free aim
        SD.aim(np.array([1.0, 1.0, 1.0]), np.array([1.0, 1.0001, 0.0]), 0.45, -0.1)


def test_the_blur_is_the_thin_lens_circle_the_keys_measure():
    # key 190: f/4, focus 0.679 m on the Atlas, the marble at 0.4183 m: 33.3 px at 1080p
    assert abs(SD.coc_px(4.0, 0.679, 0.4183) - 33.3) < 0.3
    assert SD.coc_px(8.0, 0.5, 0.5) == 0.0


def test_the_keys_are_one_prime_and_hold_the_rack_limits():
    spec, keys = SD.load_keys()
    assert spec["lens"]["focal_mm"] == 50 == C.LENS_MM
    assert [k["f"] for k in keys] == sorted({k["f"] for k in keys}) and keys[0]["f"] == 0 and keys[-1]["f"] == 941
    import check_v5d as K
    sheets = {"atlas_near", "leaf_near", "piri_near", "weights_top", "ino_near"}       # the plan's five racks
    rk = [r for r in K.racks(keys) if r[1]["focus_target"] in sheets]
    assert len(rk) == 5
    for m0, p0, p1, m1 in rk:
        assert (p0["f"] - m0["f"]) / FPS <= 0.5 and (p1["f"] - p0["f"]) / FPS <= 0.5 and (m1["f"] - p1["f"]) / FPS <= 0.4


def test_the_shot_meets_the_keys_and_ends_on_v5cs_pose():
    bake = _bake()
    if bake is None:
        return
    import shot_v5c as SH
    fr = SD.shot(bake, FPS, 31.4)
    assert len(fr) == 1091
    _, keys = SD.load_keys()
    for k in keys[1:]:
        if k["rig"]["mode"] == "rel" and "builder_note" not in k:
            assert np.linalg.norm(fr[k["f"]]["eye"] - np.array(k["eye"])) < 0.002, k["f"]
        if k["rig"]["mode"] == "abs" and k["f"] < 927:
            assert np.linalg.norm(fr[k["f"]]["eye"] - np.array(k["eye"])) < 1e-6, k["f"]
        if k["f"] < 927:
            sx, sy, _ = SD.screen_of(fr[k["f"]]["eye"], fr[k["f"]]["tgt"] - fr[k["f"]]["eye"], fr[k["f"]]["p"])
            assert abs(sx - k["marble_screen"][0]) < 1e-6 and abs(sy - k["marble_screen"][1]) < 1e-6, k["f"]
    v5c = SH.shot(bake, FPS, 31.4)
    assert all(f["end"] == 0 for f in fr[:927]) and fr[927]["end"] > 0
    for f in range(1061, 1091):                       # the pose: POSE_EV, the albedo and A7 carry over
        for key in ("eye", "tgt", "up"):
            assert np.allclose(fr[f][key], v5c[f][key], atol=1e-9), (f, key)
        assert abs(fr[f]["fstop"] - v5c[f]["fstop"]) < 1e-9 and abs(fr[f]["focus"] - v5c[f]["focus"]) < 1e-9
    assert all(abs(fr[f]["end"] - v5c[f]["end"]) < 1e-12 for f in range(1091))


def test_the_checker_passes_the_shot():
    bake = _bake()
    if bake is None:
        return
    import check_v5d as K
    fr = SD.shot(bake, FPS, 31.4)
    _, keys = SD.load_keys()
    res = K.check(fr, keys, K.marble_speed(bake, len(fr)))
    assert res["pass"], {k: v for k, v in res.items() if isinstance(v, dict) and not v.get("pass", True)}
    assert len(res["racks"]) == 5 and all(r["pass"] for r in res["racks"])


def test_layout_l0_moves_only_the_jeton_onto_the_atlas_clear_of_the_groove():
    v5c, l0 = C.items("v5c"), C.items("L0")
    assert {k for k in v5c if v5c[k] != l0[k]} == {"jeton"}
    j = l0["jeton"]
    assert j["at"] == (2.300, 0.700) and j["on"] == "atlas" and j["spin_deg"] == 10.0
    x0, x1, y0, y1 = C.ITEMS["atlas"]["rect"]
    r = j["dia"] / 2
    assert x0 < j["at"][0] - r and j["at"][0] + r < x1 and y0 < j["at"][1] - r and j["at"][1] + r < y1
    X, Y = np.meshgrid(np.linspace(j["at"][0] - r, j["at"][0] + r, 40), np.linspace(j["at"][1] - r, j["at"][1] + r, 40))
    s, u, _ = C.project(X, Y)
    near = np.isfinite(u)
    if near.any():                                                               # >= 10 mm off the groove
        assert (np.abs(u[near]) > C.groove_half_width(s[near].ravel()).max() + 0.010).all()
    ov = C.planned_overlaps("L0")
    assert ("jeton", "atlas") in ov and ("jeton", "admiralty") not in ov
    assert C.LAYOUTS["L0"]["admiralty_lift"] == 0.0015 and C.LAYOUTS["v5c"]["admiralty_lift"] == 0.0


def test_the_physics_never_reads_the_jeton_or_the_sheets():
    src = (RUN / "sim_v5c.py").read_text(encoding="utf-8")
    assert "jeton" not in src and "admiralty" not in src and "C.items(" not in src
    scene = (RUN / "scene_v5c.py").read_text(encoding="utf-8")
    assert 'build("L0" if A["cam"] == "v5d" else "v5c")' in scene and "SD.shot(" in scene
    assert math.isclose(C.LAYOUTS["L0"]["jeton"]["z_top"], 0.0155)
