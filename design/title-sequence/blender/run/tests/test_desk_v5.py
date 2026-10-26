"""The Run v5: the desk is a real working desk (stdlib only). Everything lies on the desk except the one named
overhang, every overlap is a named resting-on relation, the chain's fixed poses are bench.py's, the records run in
date order along the fall, everything off the spread is squared, the lamp is one constant source whose pool keeps the
path within the exposure meter's clamp, and the lead stays legible at the follow and close distances."""

from __future__ import annotations

import sys
from pathlib import Path

_D = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_D))
import bench as B  # noqa: E402
import desk_v5 as D  # noqa: E402


def test_everything_lies_on_the_desk_but_the_atlas_corner():
    W, H = D.DESK["size"]
    for name, poly in D.footprints().items():
        allow = D.OVERHANGS.get(name, {})
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        assert min(xs) >= -allow.get("x0", 0) - D.EPS and max(xs) <= W + D.EPS, name
        assert min(ys) >= -allow.get("y0", 0) - D.EPS and max(ys) <= H + D.EPS, name


def test_every_overlap_is_a_named_resting_relation():
    for a, b in D.overlaps():
        assert (a, b) in D.PLANNED or (b, a) in D.PLANNED, f"{a} and {b} overlap and the layout does not say why"


def test_the_chain_keeps_its_tuned_poses():
    for name in ("papyrus", "atlas1", "atlas2", "piri", "leaf"):
        it, s = D.ITEMS[name], B.SHEETS[name]
        assert it["fixed"] and tuple(it["centre"]) == tuple(s["centre"]) and it["psi"] == s["psi"], name
    assert D.ITEMS["disc"]["centre"] == B.LATCH["disc"]
    assert D.ITEMS["weights"]["centre"] == (1.294, 0.841)          # the v4.1 roll-out's glance (f335)


def test_records_run_in_date_order_along_the_fall():
    rows = D.records_in_date_order()
    # loose order inside the spread being compared (its sheets overlap within 0.25 m); strict after it
    for (n0, d0, x0), (n1, d1, x1) in zip(rows, rows[1:]):
        assert x1 >= x0 - 0.25, (n0, n1)
    late = [r for r in rows if r[1] >= 1821]
    assert [r[2] for r in late if r[0] not in ("tape", "card", "strip")] == sorted(
        r[2] for r in late if r[0] not in ("tape", "card", "strip"))
    assert rows[0][0] == "tablet" and rows[-1][0] == "record"


def test_everything_off_the_spread_is_squared():
    for name, it in D.ITEMS.items():
        if it["fixed"] or name in ("galley", "khipu"):
            continue
        assert it["psi"] % 90.0 == 0.0, f"{name} lies at {it['psi']} degrees: squared to the desk or not at all"


def test_every_item_says_why_it_is_there():
    for name, it in D.ITEMS.items():
        assert len(it.get("why", "")) > 30, name


def test_the_coin_row_is_gated_scans_in_the_groove_on_the_leads_line():
    import json
    led = {i["id"]: i for i in json.loads((_D.parents[1] / "run-scan-ledger.json").read_text(encoding="utf-8"))["items"]}
    for sid, _d in D.COIN_ROW:
        assert led[sid]["gate"] == "pass", sid
    for sid in ("globe", "weights"):
        assert led[D.ITEMS[sid]["scan"]]["gate"] == "pass"
    tray = D.ITEMS["tray"]
    assert abs(tray["groove_y"] - D.LINE_Y) < 0.003
    gx0, gx1 = tray["groove"]["x"]
    last = D.COIN_X0 + (len(D.COIN_ROW) - 1) * D.COIN_PITCH
    assert gx0 < D.COIN_X0 and last < gx1
    assert D.COIN_PITCH < min(d for _s, d in D.COIN_ROW)          # spaced closer than they stand tall: a domino row


def test_the_galley_mouth_is_on_the_leads_line():
    mx, my = D.ITEMS["galley"]["mouth"]
    pts = [(x, y) for _t, x, y in D.LEAD_V41]

    def seg(a, b):
        (ax, ay), (bx, by) = a, b
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        u = max(0.0, min(1.0, ((mx - ax) * (bx - ax) + (my - ay) * (by - ay)) / L2)) if L2 else 0.0
        return ((ax + u * (bx - ax) - mx) ** 2 + (ay + u * (by - ay) - my) ** 2) ** 0.5

    best = min(seg(a, b) for a, b in zip(pts, pts[1:]))
    assert best < 0.006, best


def test_one_lamp_keeps_the_path_inside_the_meters_clamp():
    path = [(x, y) for _t, x, y in D.LEAD_V41]
    stops = [D.lamp_falloff_stops(x, y) for x, y in path]
    assert max(stops) - min(stops) <= 1.5
    assert abs(D.lamp_falloff_stops(*D.ITEMS["record"]["centre"])) < 1e-9      # the record is in the pool's measure
    elev = [D.lamp_elevation_deg(x, y) for x, y in path]
    assert 40 <= min(elev) and max(elev) <= 80                                # off-axis: shadows have length
    assert D.ROOM["world"] == 0.0                                             # no second source: fill is the room's


def test_the_lead_stays_legible():
    assert D.marble_px(D.FOLLOW["D"]) >= 28
    assert D.marble_px(D.CLOSE["D"]) >= 150
    assert D.FOLLOW["fstop"] >= D.CLOSE["fstop"]


def test_the_runtime_lands_in_the_accepted_window():
    assert 34.0 <= D.runtime_estimate() <= 40.0


def test_the_out_list_drops_nothing_the_rulings_require():
    for keep in ("galley", "tray", "globe", "weights", "felt", "record"):
        assert keep in D.ITEMS and keep not in D.OUT
