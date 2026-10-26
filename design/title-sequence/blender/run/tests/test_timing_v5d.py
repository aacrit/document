"""The Run v5d timing: the corrected arc length (past the lip only inside the well), events re-derived from the
unchanged bake, title t = sim t, and a Foley whose zones are the surfaces the marble is actually on."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import channel_v5c as C  # noqa: E402
import foley_v5c as FV  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v5c")
TIMELINE = Path("C:/Users/aacri/claudeprojects/Agentique/reports/briefs/title-v5d/marble-timeline.json")


def test_turn_one_past_x_243_is_not_the_well():
    # turn 1's apex (x 2.697, y 0.4926) and a point on its far side (x 2.43, y 0.835) are on the run, not in the well
    s, u = C.arc_s(2.697, 0.4926)
    t1 = [g for g in C.SEGMENTS if g["name"] == "turn 1"][0]
    assert t1["s0"] < s < t1["s0"] + t1["len"] and abs(u) < 0.01
    assert abs(s - 2.836) < 0.01                       # the timeline's corrected s at frame 290
    assert not C.past_lip(2.6024, 0.2408)
    # in the well it is: s runs on along reach 3's line
    assert C.past_lip(2.4891, 1.581)
    s, u = C.arc_s(2.4891, 1.581)
    assert abs(s - (C.LENGTH + 2.4891 - C.LIP_X)) < 1e-9 and abs(u) < 1e-9


def test_the_v5c_shot_keeps_the_arc_length_it_was_rendered_through():
    import shot_v5c as SH
    p = (2.6024, 0.2408, 0.0)
    assert SH.s_of_as_rendered_v5c(p) > C.LENGTH           # the bug, kept for the v5c masters' plans only
    assert SH.s_of(p) < 3.0                                 # the corrected one


def test_a_surface_is_named_by_the_word_after_onto_not_anywhere_in_the_name():
    # "L8 before the felt" is leather: the v5c Foley laid a felt bed over it (29.16-30.87 s)
    segs = FV.zone_segments([{"t": 29.163, "event": "onto leather (L8 before the felt)"},
                             {"t": 30.871, "event": "onto oak"}, {"t": 30.871, "event": "over the lip onto the felt"},
                             {"t": 30.892, "event": "onto felt"}])
    assert segs == [(0.0, "oak"), (29.163, "leather"), (30.871, "oak"), (30.871, "felt")]


def test_corrected_contacts_are_on_the_raw_clock_with_their_2997_frame():
    import timing_v5d as TD
    out = TD.corrected_contacts([{"t_s": 0.736, "frame": 17.66, "pair": "marble|oak 134", "v_n": 0.005},
                                 {"t_s": 0.2, "frame": 4.8, "pair": "marble|oak 1", "v_n": 0.01}], 0.5)
    assert out == [{"t_s": 0.236, "frame_2997": round(0.236 * 30000 / 1001, 2), "pair": "marble|oak 134",
                    "v_n": 0.005}]


def test_the_corrected_events_have_one_true_step_each_and_no_felt_before_the_lip():
    if not (SIM / "run-bake.json").exists():
        return
    import timing_v5d as TD
    rep = json.loads((SIM / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    t = TD.corrected_timing(rep, bake)
    ev = t["events"]
    assert t["release_title_s"] == 0.0 and all(e["title_t"] == round(e["t"], 3) for e in ev)
    steps = [e for e in ev if e["event"].startswith("step ")]
    assert [e["event"] for e in steps] == ["step 1 (the leaf)", "step 2 (the chart)"]
    assert abs(steps[0]["frame_2997"] - 475) < 1.5 and abs(steps[1]["frame_2997"] - 863) < 1.5
    zones = FV.zone_segments(ev)
    felt = [t_ for t_, z in zones if z == "felt"]
    assert felt and min(felt) > 30.8                     # the felt starts at the lip (frame 926), never in turn 1
    lip = [e for e in ev if e["event"] == "over the lip onto the felt"][0]
    assert abs(lip["frame_2997"] - 926) < 1.5
    if TIMELINE.exists():                                 # the analyst's corrected s agrees frame by frame
        tl = json.loads(TIMELINE.read_text(encoding="utf-8"))["marble_every_frame"]
        tr = TD.corrected_track(bake)
        T = [r[0] for r in tr]
        import numpy as np
        for row in tl[::25]:
            i = int(np.searchsorted(T, row["t"]))
            assert abs(tr[min(i, len(tr) - 1)][1] - row["s"]) < 0.01, row
