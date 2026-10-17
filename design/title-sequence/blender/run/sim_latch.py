"""The Run, proof 1 "the latch" (f96-167): MuJoCo for the clay marble, the bronze disc analytic (moffatt.py) and
driven into MuJoCo as a moving collider, so the marble's release is a real contact.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_latch.py

The marble rests against the disc's uphill rim on the bench's 0.8 degree fall. The disc settles, slaps flat at f120
and skitters 8 mm across the slope along its contact path's last tangent; the marble, no longer held square, rolls
round the rim and away downhill, out of the disc's shadow, and steps up onto the Turin papyrus's edge. The papyrus is
placed where the marble is at f167, found by a first run without it (so the edge tick lands on the design's frame
from the physics, not by forcing the marble). Writes to D:/document-media/title-sequence/run/sim/.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import moffatt as MF  # noqa: E402
import simlib as S  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/sim")
R = 0.008                                   # clay marble, 16 mm
RHO_CLAY = 1900.0
MASS = RHO_CLAY * 4 / 3 * math.pi * R ** 3  # 4.07 g
T0, T1 = 2.5, 7.4                           # title seconds simulated (the proof is 4.0-7.0)
PAPYRUS_T = 0.00025
ROLL = {"oak": 0.002 * R, "papyrus": 0.006 * R, "bronze": 0.001 * R}
TABLET = (0.155, 0.1525, 0.025)             # T-01 half extents (31 x 30.5 x 5 cm, ledger)


# The latch's own fall (founder, 2026-10-17, re-proof: "a steeper fall so the release reads"): the bench falls 2.5
# degrees here, by the disc, where the marble must visibly get going; the galley keeps the bench's 0.8.
TILT = 2.5


def model_xml(papyrus_x: float | None) -> str:
    pap = ""
    if papyrus_x is not None:
        pap = (f'<geom name="papyrus" type="box" size="0.30 0.115 {PAPYRUS_T / 2}" pos="{papyrus_x + 0.30} -0.135 '
               f'{PAPYRUS_T / 2}" friction="0.5 0.0005 {ROLL["papyrus"]}" condim="6"/>')
    return f"""
<mujoco model="latch">
  <option timestep="{S.DT_SIM}" gravity="{S.gravity_xml(TILT)}" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <worldbody>
    <geom name="oak" type="plane" size="2 2 0.1" friction="0.45 0.0005 {ROLL['oak']}" condim="6"/>
    <geom name="tablet" type="box" size="{TABLET[0]} {TABLET[1]} {TABLET[2]}" pos="-0.16 0.215 {TABLET[2]}"
          friction="0.6 0.001 0.0001" condim="6"/>
    {pap}
    <body name="disc" mocap="true" pos="0 0 {MF.T / 2}">
      <geom name="disc" type="cylinder" size="{MF.A} {MF.T / 2}" friction="0.3 0.0005 {ROLL['bronze']}" condim="6"/>
    </body>
    <body name="marble" pos="{-(MF.A + R + 0.0004)} 0 {R}">
      <freejoint/>
      <geom name="marble" type="sphere" size="{R}" mass="{MASS}" friction="0.4 0.0002 1e-7" condim="6"/>
    </body>
  </worldbody>
</mujoco>"""


def quat_from_frame(u, w, n):
    """Quaternion (w, x, y, z) of the rotation whose columns are the disc's local x (u), y (w), z (n)."""
    R_ = np.array([u, w, n]).T
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, R_.ravel())
    return q


def drive_disc(m, d):
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "disc")
    mid = m.body_mocapid[bid]
    state = {}

    def pose_q(t):
        p = MF.pose(t)
        n, u = np.array(p["normal"]), np.array(p["u"])
        w = np.cross(n, u)
        ps = MF.spin(t, T0, n=200) if t < MF.T_SLAP else state.setdefault("psi_slap", MF.spin(MF.T_SLAP, T0, n=2000))
        c, s = math.cos(ps), math.sin(ps)
        u2, w2 = c * u + s * w, -s * u + c * w
        return np.array(p["centre"]), quat_from_frame(u2, w2, n)

    def drive(t, m, d):
        c, q = pose_q(t)
        c2, q2 = pose_q(t + 1e-4)
        d.mocap_pos[mid] = c
        d.mocap_quat[mid] = q
        lin = (c2 - c) / 1e-4
        dq = np.zeros(3)
        qc = np.zeros(4)
        mujoco.mju_negQuat(qc, q)
        qd = np.zeros(4)
        mujoco.mju_mulQuat(qd, q2, qc)
        mujoco.mju_quat2Vel(dq, qd, 1e-4)
        return {bid: (lin, dq, c)}
    return drive


def simulate(papyrus_x):
    m = mujoco.MjModel.from_xml_string(model_xml(papyrus_x))
    d = mujoco.MjData(m)
    res = S.run(m, d, T0, T1, drive=drive_disc(m, d), bodies=("marble", "disc"), log_from=3.5)
    return res


def at(poses, t):
    a = np.array(poses)
    return np.array([np.interp(t, a[:, 0], a[:, k]) for k in range(1, 8)])


def main():
    import time
    t_start = time.time()
    first = simulate(None)
    x167 = at(first["poses"]["marble"], 167 / S.FPS)[0]
    papyrus_x = float(x167 - R * 0.35)       # the marble's leading contact meets the edge at f167
    res = simulate(papyrus_x)
    mpos = np.array(res["poses"]["marble"])
    info = {"papyrus_x": round(papyrus_x, 5), "marble_x_f167_no_papyrus": round(float(x167), 5),
            "mass_g": round(MASS * 1000, 3), "sim_s": [T0, T1], "dt_sim": S.DT_SIM, "tilt_deg": TILT,
            "roll_m": ROLL, "moffatt": {"A": MF.A, "T": MF.T, "C_HZ": MF.C_HZ, "T_SLAP": MF.T_SLAP,
                                        "alpha_deg_f96": round(math.degrees(MF.alpha(4.0)), 2),
                                        "rate_hz_f96": round(MF.rate_hz(4.0), 1),
                                        "rate_hz_f119": round(MF.rate_hz(119 / 24), 1)},
            "tablet_half_m": TABLET, "wall_s": None}
    disc_poses = [[t] + list(MF.pose(t)["centre"]) for t in np.arange(T0, T1, 1 / 240)]
    out = S.save(OUT, "latch", res, info)
    v = np.diff(mpos[:, 1:4], axis=0) * 240
    sp = np.linalg.norm(v, axis=1)
    i121 = int((121 / 24 - T0) * 240)
    info["marble_speed_m_s"] = {f"f{f}": round(float(sp[int((f / 24 - T0) * 240)]), 4) for f in (110, 121, 130, 145, 160, 167)}
    info["marble_xy_f167"] = [round(float(v_), 4) for v_ in at(res["poses"]["marble"], 167 / 24)[:3]]
    info["wall_s"] = round(time.time() - t_start, 1)
    (OUT / "latch-bake.json").write_text(json.dumps({"meta": info, "poses": res["poses"]}), encoding="utf-8")
    print(json.dumps(info, indent=1))
    print("events in the proof window (f96-167):")
    for e in out["events"]:
        if 96 <= e["frame"] <= 170:
            print("  ", e)


if __name__ == "__main__":
    main()
