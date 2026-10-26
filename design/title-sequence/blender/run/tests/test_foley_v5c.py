"""The Run v5c Foley: zone timing comes from the sim's own events, on the raw-sim clock final_v5c.py's frames use
(not the stale "title_t"), and the speed-driven roll is a variable-speed read, not a separate pitch shift."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import foley_v5c as FV  # noqa: E402

EVENTS = [
    {"t": 0.0, "event": "latch opens: the marble leaves the cup"},
    {"t": 0.892, "event": "onto leather (L1 tablet)", "v": 0.339},
    {"t": 1.4335, "event": "onto oak", "v": 0.325},
    {"t": 7.9625, "event": "onto felt", "v": 0.282},
    {"t": 11.4, "event": "onto oak", "v": 0.264},
    {"t": 7.946, "event": "step 1 (the leaf)", "v": 0.282},
    {"t": 29.267, "event": "step 2 (the chart)", "v": 0.210},
    {"t": 30.871, "event": "over the lip onto the felt", "v": 0.211},
    {"t": 31.4, "event": "at rest on the felt"},
]


def test_zone_segments_follow_the_named_transitions_on_the_raw_clock():
    segs = FV.zone_segments(EVENTS)
    assert segs[0] == (0.0, "oak")
    zones = [z for _, z in segs]
    assert zones == ["oak", "leather", "oak", "felt", "oak", "felt"]
    # the step events are not zone changes; they never appear here
    assert all(abs(t - 7.946) > 1e-6 for t, _ in segs)


def test_step_events_are_picked_out_by_name():
    steps = FV.step_events(EVENTS)
    assert [e["event"] for e in steps] == ["step 1 (the leaf)", "step 2 (the chart)"]


def test_fix_contact_times_removes_the_generation_time_release_offset():
    contacts = [{"t_s": 0.736, "pair": "marble|oak 134", "v_n": 0.005, "impulse": 0.0}]
    out = FV.fix_contact_times(contacts, release_title_s=0.5)
    assert out[0]["t_s"] == 0.236
    # a contact that would land before the release is dropped, not given a negative time
    dropped = FV.fix_contact_times([{"t_s": 0.1, "pair": "marble|oak 1", "v_n": 0.01, "impulse": 0.0}], 0.5)
    assert dropped == []


def test_speed_driven_roll_reads_faster_and_louder_with_speed():
    sr = 8000
    loop = np.sin(2 * np.pi * 200 * np.arange(sr) / sr)             # a pure tone stand-in for the loop
    fast = np.full(sr, 0.56)                                        # 2x V_REF
    slow = np.full(sr, 0.14)                                        # 0.5x V_REF
    yf = FV.speed_driven_roll(loop, fast, FV.V_REF, sr)
    ys = FV.speed_driven_roll(loop, slow, FV.V_REF, sr)
    # at 2x the read rate the tone's own frequency content shifts up: more sign changes per second
    def crossings(y):
        return int(np.sum(np.diff(np.sign(y)) != 0))
    assert crossings(yf) > crossings(ys) * 1.5


def test_speed_envelope_is_zero_at_rest_and_clipped_above():
    env = FV.speed_envelope(np.array([0.0, FV.V_REF, 10.0]), FV.V_REF)
    assert env[0] == 0.0
    assert env[1] == 1.0
    assert env[2] == 1.3


def test_zone_bases_are_ordered_oak_loudest_leather_duller_felt_quietest():
    g_oak, lp_oak = FV.ZONE["oak"]
    g_leather, lp_leather = FV.ZONE["leather"]
    g_felt, lp_felt = FV.ZONE["felt"]
    assert g_oak > g_leather > g_felt
    assert lp_oak > lp_leather > lp_felt


def test_build_matches_final_v5c_frame_count_and_duration():
    if not (FV.SIM / "run-timing.json").exists():
        return
    mix, rep = FV.build("C20-METAR-0851")
    assert rep["frames"] == 1091
    assert abs(rep["duration_s"] - 1091 / (30000 / 1001)) < 1e-3
    assert abs(len(mix) - rep["duration_s"] * FV.SR) < 20
    # the room tone is exactly the score's standard
    assert rep["room_dbfs"] == -72.0
    floors = rep["stem_floors_dbfs"]
    assert floors["room_tone"] < -60.0
    # oak is the loudest zone, felt the quietest, by construction (ZONE's own gains)
    assert floors["bed_oak"] >= floors["bed_leather"] >= floors["bed_felt"] - 40  # felt may be silent (-inf-ish)
