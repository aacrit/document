"""Title v6, day 1: the approved latch re-proved for the 30 mm, 27 g clay ball (D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/latch_v6.py [--no-lock]

The approved latch (sim_latch.py, founder 2026-10-17) was proved for a 16 mm, 4 g marble: the bronze disc (45 x 3 mm,
about 42 g) settles analytically (Moffatt) and is driven into MuJoCo as a kinematic collider; the marble rests
against its uphill rim on the latch's 2.5 degree fall, the disc slaps flat at f120 and skitters 8 mm, and the marble,
no longer held, rolls round the rim and away. The 27 g ball is 0.65 of the disc's mass, so a kinematic disc is only
honest if the ball cannot move a real one. This runs the same proof with the 30 mm ball and checks:

1. held: the ball moves under 1 mm before the slap;
2. released: after the slap it rolls away, round the rim, and is clear of the disc within 1.5 s;
3. honest: during the hold the horizontal force the ball puts on the disc stays under the friction that holds a real
   42 g bronze disc on oak (mu_s 0.35 times its weight plus the ball's own vertical push), with a factor of safety
   reported; and the impulse the ball gives the disc over the whole proof is small against the disc's own momentum
   scale (its mass times its rim speed near the slap);
4. nothing else: the ball touches only the oak and the disc (the tablet stands beside it untouched).

Writes D:/document-media/title-sequence/v6/latch/latch-30mm.json (and the 16 mm baseline run the same way).
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
import moffatt as MF  # noqa: E402
import sim_latch as SL  # noqa: E402
import simlib as S  # noqa: E402

OUT = Path("D:/document-media/title-sequence/v6/latch")
DISC_MASS = 8800.0 * math.pi * MF.A ** 2 * MF.T          # bronze, 42 g
MU_S_BRONZE_OAK = 0.35


def configure(r, mass):
    SL.R = r
    SL.MASS = mass
    SL.ROLL = {"oak": 0.002 * r, "papyrus": 0.006 * r, "bronze": 0.001 * r}


def proof(r, mass):
    configure(r, mass)
    m = mujoco.MjModel.from_xml_string(SL.model_xml(None))
    d = mujoco.MjData(m)
    drive = SL.drive_disc(m, d)
    ball = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "marble")
    gball = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "marble")
    gdisc = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "disc")
    gname = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(m.ngeom)]
    steps = int(round((SL.T1 - SL.T0) / S.DT_SIM))
    f6 = np.zeros(6)
    rows, pairs = [], set()
    impulse = np.zeros(3)
    drive(SL.T0, m, d)
    mujoco.mj_forward(m, d)
    p0 = d.xpos[ball].copy()
    for k in range(steps):
        t = SL.T0 + k * S.DT_SIM
        fh = fv = 0.0
        for ci in range(d.ncon):
            c = d.contact[ci]
            if gball not in (c.geom1, c.geom2):
                continue
            pairs.add("|".join(sorted((gname[c.geom1], gname[c.geom2]))))
            if gdisc in (c.geom1, c.geom2):
                mujoco.mj_contactForce(m, d, ci, f6)
                Rc = np.array(c.frame).reshape(3, 3)              # rows: normal, tangent 1, tangent 2 (world)
                fw = Rc.T @ f6[:3]                                 # force on geom2 from geom1 in world (MuJoCo's sign)
                if c.geom1 == gball:
                    fw = fw                                       # on the disc (geom2) from the ball
                else:
                    fw = -fw
                fh += float(np.hypot(fw[0], fw[1]))
                fv += float(-fw[2])                               # the ball pressing down on the disc
                impulse += fw * S.DT_SIM
        if k % 10 == 0:
            rows.append([t, *d.xpos[ball].tolist(), float(np.linalg.norm(d.qvel[:3])), fh, fv])
        drive(t + S.DT_SIM, m, d)
        mujoco.mj_step(m, d)
    A = np.array(rows)
    T_ = A[:, 0]
    hold = T_ < MF.T_SLAP - 0.02
    moved_hold = float(np.max(np.linalg.norm(A[hold, 1:4] - p0, axis=1)))
    disc_c = np.array(MF.pose(SL.T1)["centre"])
    clear = None
    for row in rows:
        if row[0] > MF.T_SLAP and math.hypot(row[1] - disc_c[0], row[2] - disc_c[1]) > MF.A + r + 0.002:
            clear = row[0] - MF.T_SLAP
            break
    fh_hold = A[hold, 5]
    capacity = MU_S_BRONZE_OAK * (DISC_MASS * 9.81 + A[hold, 6])
    with np.errstate(divide="ignore", invalid="ignore"):
        safety = float(np.min(np.where(fh_hold > 1e-9, capacity / fh_hold, np.inf)))
    rim_speed = MF.A * MF.omega(MF.T_SLAP - 0.05)
    after = T_ > MF.T_SLAP
    v_after = A[after, 4]
    j = int(np.argmax(v_after))
    out = {"r_m": r, "mass_kg": mass, "disc_mass_kg": DISC_MASS, "ratio_to_disc": mass / DISC_MASS,
           "moved_during_hold_mm": moved_hold * 1000, "held": moved_hold < 0.001,
           "clear_of_disc_s_after_slap": clear, "released": clear is not None and clear < 1.5,
           "v_peak_after_slap_m_s": float(v_after[j]), "t_peak_after_slap_s": float(T_[after][j] - MF.T_SLAP),
           "v_end_m_s": float(A[-1, 4]), "xy_end": A[-1, 1:3].tolist(),
           "hold_force_max_N": float(fh_hold.max()), "hold_capacity_min_N": float(capacity.min()),
           "safety_factor_min": safety, "honest_hold": safety > 1.0,
           "impulse_on_disc_N_s": float(np.linalg.norm(impulse[:2])),
           "disc_momentum_scale_N_s": DISC_MASS * rim_speed,
           "impulse_share": float(np.linalg.norm(impulse[:2]) / (DISC_MASS * rim_speed)),
           "ball_contacts": sorted(pairs),
           "only_oak_and_disc": all(p in ("disc|marble", "marble|oak") for p in pairs)}
    out["pass"] = bool(out["held"] and out["released"] and out["honest_hold"] and out["only_oak_and_disc"])
    return out, rows


def main():
    import machine_v6 as MV
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with MV.heavy("v6 latch re-proof at 30 mm (MuJoCo, CPU)", enabled="--no-lock" not in sys.argv):
        base, _ = proof(0.008, 1900.0 * 4 / 3 * math.pi * 0.008 ** 3)
        v6, rows = proof(0.015, 0.027)
    rep = {"what": "the approved latch (sim_latch.py) re-proved at 30 mm / 27 g, with the 16 mm baseline run the same way",
           "baseline_16mm": base, "ball_30mm": v6, "wall_s": round(time.time() - t0, 1)}
    (OUT / "latch-30mm.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (OUT / "latch-30mm-track.json").write_text(json.dumps(rows), encoding="utf-8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
