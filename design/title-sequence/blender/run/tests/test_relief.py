"""The Run v4, ticket 2: the sheets' heightmaps (reads the EXRs relief.py wrote; numpy only)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_D = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_D))
import bench as B  # noqa: E402
import relief as RL  # noqa: E402

OUT = RL.OUT
pytestmark = pytest.mark.skipif(not (OUT / "world.npz").exists(), reason="run relief.py first")


def test_exr_round_trip(tmp_path):
    a = np.random.default_rng(1).random((7, 5)).astype(np.float32)
    p = RL.write_exr(tmp_path / "t.exr", {"R": a, "G": -a})
    back = RL.read_exr(p)
    assert np.array_equal(back["R"], a) and np.array_equal(back["G"], -a)


@pytest.mark.parametrize("name", list(B.SHEETS))
def test_each_sheet_has_its_heightmap_without_nan_and_its_extents_match_the_plan(name):
    ex = RL.read_exr(OUT / f"{name}.exr")
    side = json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))
    for ch in "RGBA":
        assert not np.isnan(ex[ch]).any()
    assert side["texel"] == 0.002 and list(ex["R"].shape) == side["shape"]
    want = B.sheet_corners(name)
    for (x, y), (a, b) in zip(want, side["extents"]):
        assert math.dist((x, y), (a, b)) < 1e-9
    assert (ex["G"] >= ex["B"] - 1e-9).all()


@pytest.mark.parametrize("bank", list(B.BANKS))
def test_the_relief_max_is_the_named_curl(bank):
    b = B.BANKS[bank]
    ex = RL.read_exr(OUT / f"{b['sheet']}.exr")
    assert abs(float(ex["R"].max()) - b["crest"]) <= 0.0005


def test_the_hinge_valley_is_1_5_mm():
    for n in ("atlas1", "atlas2"):
        ex = RL.read_exr(OUT / f"{n}.exr")
        assert abs(float(ex["R"].min()) + B.HINGE["depth"]) <= 0.0001


def test_the_world_is_the_sheets_set_down():
    w = np.load(OUT / "world.npz")
    assert not np.isnan(w["top"]).any() and w["top"].min() >= 0
    assert 0.018 <= w["top"].max() <= 0.025
