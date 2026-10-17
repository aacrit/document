"""The Run, proof 2 "the galley" (f456-527): MuJoCo for the marbles, the twelve blank quads and the end stop.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_galley.py

On the Gutenberg leaf lies a brass galley, open on its downhill side. Twelve pieces of blank 36-point type stand in
a row across the slope, the gaps tapering 14 to 8 mm. The design named em quads (12.7 x 12.7 x 23.3 mm, 37 g), but a
4 g clay marble at about 0.3 m/s cannot topple one (that needs about 1.7 m/s: the marble's angular momentum about the
quad's pivot edge against the 0.59 mJ that lifts its centre of mass), so the row is 36-point four-to-em spaces
(3.2 x 12.7 x 20.3 mm, 8.6 g), the thinnest honest blank type, which a marble topples like a domino. Past quad 12 a brass end stop stands on
a raised step (3 mm), flush with its downhill lip; behind it, uphill on the step, two clay marbles wait in file. The
lead marble arrives across the slope and strikes quad 1; the row falls; quad 12 topples the end stop off the side of
the step; the pair roll off the lip; three marbles leave the leaf's downhill edge onto Ino's sheet. Nothing is
scripted: the fall times, the release and the exits come out of the simulation and its 1 kHz contact log.
Writes D:/document-media/title-sequence/run/sim/galley-{bake.json,contacts-1khz.jsonl,events.jsonl}.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import simlib as S  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/sim")
R = 0.008
MASS = 1900.0 * 4 / 3 * math.pi * R ** 3
Q = (0.0016, 0.00635, 0.01015)            # 36-pt 4-to-em space, half extents: 3.2 (x) x 12.7 (y) x 20.3 mm
QM = 10400 * 8 * Q[0] * Q[1] * Q[2]          # type metal, 8.6 g
N_Q = 12
GAPS = np.linspace(0.014, 0.008, N_Q)      # gap after piece i (the last is piece 12 to the end stop)
LEAF_T, INO_T = 0.0002, 0.00015
FLOOR_T = 0.0012                           # galley floor plate
STEP_H = 0.003
STOP = (0.0012, 0.026, 0.01015)            # end stop: a brass plate 2.4 x 52 x 20.3 mm standing on the lip
STOP_M = 8400 * 8 * STOP[0] * STOP[1] * STOP[2]
STOP_Y = 0.018                             # it spans the row's end (y -8 to 44 mm) and the pair beside it
PAIR_Y = (0.0175, 0.0345)
LEAF_EDGE_X = 0.222
T0, T1 = 18.95, 22.15                      # title seconds (the proof is f456-527, 19.0-22.0)
V_IN = (0.30, 0.0)                         # the lead marble arrives downhill along the row's line
ROLL = {"leaf": 0.006 * R, "ino": 0.006 * R, "brass": 0.001 * R, "oak": 0.002 * R}


def layout() -> dict:
    xs, x = [], 0.0
    for i in range(N_Q):
        xs.append(x)
        x += 2 * Q[0] + GAPS[i]
    x_stop = xs[-1] + Q[0] + GAPS[-1] + STOP[0]
    lip = x_stop + STOP[0]
    floor_top = INO_T + LEAF_T + FLOOR_T
    return {"quad_x": xs, "stop_x": x_stop, "floor_top": floor_top, "lip_x": lip,
            "galley": {"x": (-0.05, lip + 0.035), "y": (-0.03, 0.06)},
            "step_a": {"x": (xs[-1] + Q[0] + 0.001, lip), "y": (STOP_Y - STOP[1], 0.008)},
            "step_b": {"x": (lip - 0.045, lip), "y": (0.008, STOP_Y + STOP[1])},
            "pair": [(lip - 2 * STOP[0] - R - 0.0003, PAIR_Y[0]), (lip - 2 * STOP[0] - R - 0.0003, PAIR_Y[1])],
            "lead": (-0.075, -0.0068)}


def _box(name, xr, yr, z0, h, fr):
    return (f'<geom name="{name}" type="box" size="{(xr[1] - xr[0]) / 2} {(yr[1] - yr[0]) / 2} {h / 2}" '
            f'pos="{(xr[0] + xr[1]) / 2} {(yr[0] + yr[1]) / 2} {z0 + h / 2}" friction="{fr}" condim="6"/>')


def model_xml(L) -> str:
    gx, gy = L["galley"]["x"], L["galley"]["y"]
    ft = L["floor_top"]
    brass = f"0.3 0.001 {ROLL['brass']}"
    quads = "\n".join(
        f'<body name="quad{i + 1}" pos="{x} 0 {ft + Q[2]}"><freejoint/>'
        f'<geom name="quad{i + 1}" type="box" size="{Q[0]} {Q[1]} {Q[2]}" mass="{QM}" friction="0.3 0.002 0.0001" '
        f'condim="4"/></body>' for i, x in enumerate(L["quad_x"]))
    marbles = [("lead", L["lead"][0], L["lead"][1], INO_T + LEAF_T + R)]
    marbles += [(f"pair{k + 1}", x, y, ft + STEP_H + R) for k, (x, y) in enumerate(L["pair"])]
    mxml = "\n".join(
        f'<body name="{n}" pos="{x} {y} {z}"><freejoint/><geom name="{n}" type="sphere" size="{R}" mass="{MASS}" '
        f'friction="0.4 0.0002 1e-7" condim="6"/></body>' for n, x, y, z in marbles)
    return f"""
<mujoco model="galley">
  <option timestep="{S.DT_SIM}" gravity="{S.gravity_xml()}" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <default><geom solref="0.004 1"/></default>
  <worldbody>
    <geom name="oak" type="plane" size="2 2 0.1" friction="0.45 0.0005 {ROLL['oak']}" condim="6"/>
    {_box("ino", (LEAF_EDGE_X - 0.02, LEAF_EDGE_X + 0.6), (-0.30, 0.30), 0.0, INO_T, f"0.5 0.0005 {ROLL['ino']}")}
    {_box("leaf", (-0.20, LEAF_EDGE_X), (-0.20, 0.25), INO_T, LEAF_T, f"0.5 0.0005 {ROLL['leaf']}")}
    {_box("galley", gx, gy, INO_T + LEAF_T, FLOOR_T, brass)}
    {_box("rail", gx, (gy[0], gy[0] + 0.003), ft, 0.006, brass)}
    {_box("rail2", gx, (gy[1] - 0.003, gy[1]), ft, 0.006, brass)}
    {_box("step", L["step_a"]["x"], L["step_a"]["y"], ft, STEP_H, brass)}
    {_box("shelf", L["step_b"]["x"], L["step_b"]["y"], ft, STEP_H, brass)}
    <body name="stop" pos="{L['stop_x']} {STOP_Y} {ft + STEP_H + STOP[2]}"><freejoint/>
      <geom name="stop" type="box" size="{STOP[0]} {STOP[1]} {STOP[2]}" mass="{STOP_M}" friction="0.6 0.002 0.0001" condim="4"/>
    </body>
    {quads}
    {mxml}
  </worldbody>
</mujoco>"""


def main():
    t_start = time.time()
    L = layout()
    m = mujoco.MjModel.from_xml_string(model_xml(L))
    d = mujoco.MjData(m)
    lid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "lead")
    adr = m.jnt_dofadr[m.body_jntadr[lid]]
    d.qvel[adr:adr + 3] = [V_IN[0], V_IN[1], 0.0]
    d.qvel[adr + 3:adr + 6] = [-V_IN[1] / R, V_IN[0] / R, 0.0]        # rolling, not sliding
    bodies = ["lead", "pair1", "pair2", "stop"] + [f"quad{i + 1}" for i in range(N_Q)]
    res = S.run(m, d, T0, T1, bodies=bodies, log_from=T0 + 0.03)
    meta = {"layout": {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in L.items()},
            "gaps_m": GAPS.tolist(), "quad": {"half_m": Q, "mass_kg": QM}, "stop": {"half_m": STOP, "mass_kg": STOP_M},
            "marble": {"r_m": R, "mass_kg": MASS}, "v_in": V_IN, "leaf_edge_x": LEAF_EDGE_X, "sim_s": [T0, T1],
            "dt_sim": S.DT_SIM, "tilt_deg": S.TILT_DEG, "roll_m": ROLL, "floor_t": FLOOR_T, "step_h": STEP_H,
            "leaf_t": LEAF_T, "ino_t": INO_T}
    out = S.save(OUT, "galley", res, meta)
    ev = out["events"]
    fall = [e for e in ev if e["pair"].startswith("quad") and "quad" in e["pair"].split("|")[1] or "lead|quad1" == e["pair"]]
    print("wall", round(time.time() - t_start, 1), "s; contact samples", out["n_contact_samples"])
    for e in ev:
        if e["v_n"] > 0.02 or "stop" in e["pair"] or "ino" in e["pair"]:
            print("  ", e)
    P = res["poses"]
    for b in ("lead", "pair1", "pair2"):
        a = np.array(P[b])
        on_ino = a[a[:, 1] > LEAF_EDGE_X]
        print(b, "leaves the leaf at", round(on_ino[0, 0] * 24, 1) if len(on_ino) else None,
              "final xy", np.round(a[-1, 1:3], 3).tolist())


if __name__ == "__main__":
    main()
