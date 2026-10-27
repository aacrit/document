"""Title v6, day 1: rolling resistance for the 30 mm clay ball on each paper, measured in MuJoCo (D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/murr_v6.py [--no-lock]

What is measured, and how (state it plainly, as the ticket asks): this is a SIM CALIBRATION to a physically scaled
target, not a bench measurement of real paper. No published coefficient for a fired-clay ball on vellum, rag paper,
parchment or washi was found. The targets are table_v6.MU_R_TARGET: bench.RR (M1's coefficients for the 16 mm marble)
scaled to 30 mm by Tabor's hysteresis law (mu_r proportional to R^(1/3) for one material). For each surface the ball
(30 mm, 1900 kg/m3) is set rolling at 0.20 m/s on a level plate of that paper, built exactly as the bake builds it
(a height field at the bake's cell, contact settings, timestep and integrator), and its deceleration over 1.5 s is
read: mu_r = -a / (5/7 g). MuJoCo's rolling coefficient is then corrected until the measurement equals the target
(MuJoCo's soft contact adds its own loss, which v5c measured as 0.00055 for the 16 mm marble on facets). The check is
repeated at 0.12 and 0.30 m/s: rolling resistance must not depend on speed.

Writes D:/document-media/title-sequence/v6/murr/murr.json (per surface: target, MuJoCo coefficient, measured mu_r at
each speed, iterations). sim_v6 reads it.
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
import table_v6 as T  # noqa: E402

OUT = Path("D:/document-media/title-sequence/v6/murr")
DT = 0.00025
SOLREF = "0.001 1"
SPIN = 3e-5                                 # torsional friction (m): sliding coefficient times the patch radius
SURFACES = ["vellum", "leaf", "parchment", "washi", "chart", "oak"]


def plate_xml(roll_len, spin=SPIN, solref=SOLREF, v0=0.20):
    n = 401
    return f"""<mujoco model="murr">
  <option timestep="{DT}" gravity="0 0 -{T.G}" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <asset><hfield name="plate" nrow="{n}" ncol="{n}" size="0.3 0.3 0.001 0.01"/></asset>
  <worldbody>
    <geom name="plate" type="hfield" hfield="plate" pos="0.3 0 -0.001" friction="0.5 {spin:.2e} {roll_len:.4e}"
          condim="6" solref="{solref}"/>
    <body name="ball" pos="0.02 0 {T.R + 1e-6}">
      <freejoint/>
      <geom name="ball" type="sphere" size="{T.R}" density="{T.RHO_CLAY}" friction="0.5 0 0" condim="6"
            solref="{solref}" solmix="0.0001"/>
    </body>
  </worldbody>
</mujoco>"""


def measure(roll_len, v0=0.20, span=1.5, settle=0.05):
    m = mujoco.MjModel.from_xml_string(plate_xml(roll_len))
    m.hfield_data[:] = 1.0                    # a level plate at z = 0
    d = mujoco.MjData(m)
    d.qvel[0] = v0
    d.qvel[4] = v0 / T.R                      # rolling, not sliding (omega_y = v / R for +x)
    mujoco.mj_forward(m, d)
    ts, vs = [], []
    while d.time < settle + span:
        mujoco.mj_step(m, d)
        if d.time >= settle:
            ts.append(d.time)
            vs.append(float(np.linalg.norm(d.qvel[:2])))
    ts, vs = np.array(ts), np.array(vs)
    a = float(np.polyfit(ts, vs, 1)[0])
    return -a / (T.K_ROLL * T.G), {"v_end": float(vs[-1])}


def calibrate(target, iters=5):
    c = target * T.R
    hist = []
    for _ in range(iters):
        mu, info = measure(c)
        hist.append({"roll_len_m": c, "mu_r": mu})
        if abs(mu - target) / target < 0.002:
            break
        c *= target / mu
    return c, hist


def main():
    import machine_v6 as MV
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = {"what": "rolling resistance of the 30 mm clay ball, MuJoCo sim calibration to the Tabor-scaled targets",
           "basis": "bench.RR (M1, 16 mm) x (15/8)^(1/3) (Tabor 1955, hysteresis rolling friction of a sphere)",
           "kind": "sim calibration (no published bench value for these papers was found)",
           "mujoco": mujoco.__version__, "dt": DT, "solref": SOLREF, "spin_m": SPIN, "cell_m": 0.6 / 400,
           "surfaces": {}}
    with MV.heavy("v6 mu_r calibration (MuJoCo, CPU)", enabled="--no-lock" not in sys.argv):
        for sname in SURFACES:
            target = T.MU_R_TARGET[sname]
            c, hist = calibrate(target)
            at = {f"{v:.2f}": measure(c, v0=v)[0] for v in (0.12, 0.20, 0.30)}
            res["surfaces"][sname] = {"target_mu_r": target, "bench_rr_16mm": target / T.TABOR, "mujoco_roll_len_m": c,
                                      "measured_mu_r": at, "iterations": hist,
                                      "naive_roll_len_m": target * T.R,
                                      "contact_extra_mu_r": hist[0]["mu_r"] - target}
            print(f"{sname}: target {target:.5f}, MuJoCo roll {c:.4e} m, measured {at}")
    res["wall_s"] = round(time.time() - t0, 1)
    (OUT / "murr.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
