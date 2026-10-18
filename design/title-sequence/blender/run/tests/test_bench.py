"""The Run v4: the table and its plan (stdlib only). Every object lies on the table except the overhangs the plan
names, and the sheets lie in time order (older over newer) except the pairs the path needs."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

_D = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_D))
_spec = importlib.util.spec_from_file_location("bench_v4", _D / "bench.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

EPS = 0.002


def test_every_footprint_lies_on_the_table_except_the_named_overhangs():
    W, H = B.TABLE["size"]
    for name, poly in B.footprints().items():
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        allow = B.OVERHANGS.get(name, {})
        assert min(xs) >= -allow.get("x0", 0.0) - EPS, (name, min(xs))
        assert max(xs) <= W + allow.get("x1", 0.0) + EPS, (name, max(xs))
        assert min(ys) >= -allow.get("y0", 0.0) - EPS, (name, min(ys))
        assert max(ys) <= H + allow.get("y1", 0.0) + EPS, (name, max(ys))


def test_the_named_overhangs_do_overhang_and_keep_their_weight_on_the_table():
    W, H = B.TABLE["size"]
    fp = B.footprints()
    assert min(p[1] for p in fp["atlas1"]) < -0.04                     # board 1's near corner, about 5 cm
    assert max(p[1] for p in fp["stick"]) > H                          # the lattice over the far edge
    for name in B.OVERHANGS:
        cx = sum(p[0] for p in fp[name]) / 4
        cy = sum(p[1] for p in fp[name]) / 4
        assert 0 < cx < W and 0 < cy < H, name


def test_the_roof_tiles_lie_in_time_order():
    fp = B.footprints()
    S = B.SHEETS
    names = list(S)
    seen = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if S[a]["ledger"] == S[b]["ledger"] or not B.overlap(fp[a], fp[b]):
                continue
            over, under = (a, b) if S[a]["layer"] > S[b]["layer"] else (b, a)
            seen += 1
            if (over, under) in B.ROOF_EXCEPTIONS:
                continue
            assert S[over]["date"] <= S[under]["date"], f"{over} ({S[over]['date']}) lies over {under} ({S[under]['date']})"
    assert seen >= 8


def test_the_layers_are_a_strict_order_and_the_exceptions_really_overlap():
    layers = [s["layer"] for s in B.SHEETS.values()]
    assert len(set(layers)) == len(layers)
    fp = B.footprints()
    for over, under in B.ROOF_EXCEPTIONS:
        assert B.overlap(fp[over], fp[under]) and B.SHEETS[over]["layer"] > B.SHEETS[under]["layer"]


def test_props_keep_off_each_other_and_the_felt_stays_bare_oak_side():
    fp = B.footprints()
    assert not B.overlap(fp["tablet"], fp["atlas1"])
    assert not B.overlap(fp["stick"], fp["felt"])
    assert not B.overlap(fp["brass"], fp["stick"]) and not B.overlap(fp["brass"], fp["chart"])
    assert B.DARK_X0 > B.BRASS["at"][0] + B.BRASS["A"]


def test_the_latch_keeps_the_approved_local_frame_and_heads_minus_53():
    a = B.latch_to_table((0.0, 0.0))
    assert a == B.LATCH["disc"]
    p0 = B.latch_to_table((0.0, 0.0))
    d = math.radians(B.LATCH["path_local_deg"])
    p1 = B.latch_to_table((math.cos(d), math.sin(d)))
    assert math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) == B.LATCH["heading_deg"] or \
        abs(math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) - B.LATCH["heading_deg"]) < 1e-9


def test_the_hinge_runs_at_its_angle_and_board_1_is_on_the_minus_x_side():
    lo, hi = B.HINGE["lo"], B.HINGE["hi"]
    assert abs(math.degrees(math.atan2(lo[1] - hi[1], lo[0] - hi[0])) - B.HINGE["deg"]) < 1e-6
    assert -72.0 <= B.HINGE["deg"] <= -64.0
    assert B.SHEETS["atlas1"]["centre"][0] < B.SHEETS["atlas2"]["centre"][0]


def test_the_three_banks_are_named_edges_of_their_sheets():
    for b in B.BANKS.values():
        es = [e for e in B.SHEETS[b["sheet"]]["edges"] if e["edge"] == b["edge"]]
        assert es and es[0]["crest"] == b["crest"] and es[0]["run"] == b["run"]
        assert (b["in"] > 0) != (b["out"] > 0)                      # each turns the lateral heading round


def test_the_clock_and_the_tails():
    assert B.PREFIX_FRAMES == 936
    assert [B.tail_frames(r) for r in ("S-130", "S-16928", "C20-METAR-0851")] == [252, 264, 276]
    assert [B.total_frames(r) for r in ("S-130", "S-16928", "C20-METAR-0851")] == [1308, 1320, 1332]
    assert B.DESIGN["brass_hit"] == 866 and B.DESIGN["brass_slap"] == 926
    n = B.frames_at(B.total_frames("C20-METAR-0851") / 24, B.NTSC)
    assert abs(n * 1001 / 30000 - 55.5) <= 0.5 * 1001 / 30000


def test_records_are_laid_across_their_shorter_side_along_x_and_felt_is_after_1931():
    for rec in B.FILMS:
        (sx, sy), _ = B.record_size(rec)
        assert sx <= sy
        assert B.felt_x0(rec) >= B.DARK_X0
    assert B.felt_x0("C20-METAR-0851") - B.felt_x0("S-130") == B.OAK_PER_YEAR * (2001 - 1947) or \
        abs(B.felt_x0("C20-METAR-0851") - B.felt_x0("S-130") - 0.054) < 1e-9


def test_the_plan_lists_every_beat_with_its_cause():
    beats = [p["beat"] for p in B.PLAN]
    assert beats[0] == "1 latch" and beats[-1] == "dark"
    assert sum(1 for b in beats if b.startswith("U")) == 3
    for p in B.PLAN:
        assert set(p) == {"beat", "object", "centre", "psi", "heading_in", "heading_out", "cause"} and p["cause"]
