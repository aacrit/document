"""The Run: shared MuJoCo plumbing for the proofs (runs in the D: venv, D:/document-media/tools/run-venv).

Steps a model at DT_SIM, drives kinematic (mocap) bodies from analytic functions, samples every contact once a
millisecond into the 1 kHz contact log {t_s, pair, v_n, f_n}, and records every free body's pose at 240 Hz for the
Blender bake (keys at tenth-frames, so the 180-degree shutter blurs between true poses). Title time is carried
throughout: t_s is seconds from the title's f0.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np

DT_SIM = 0.0005
LOG_HZ = 1000
BAKE_HZ = 240
FPS = 24
TILT_DEG = 0.8                     # the bench's fall, far end to near end, along +x
G = 9.81


def gravity_xml() -> str:
    th = math.radians(TILT_DEG)
    return f"{G * math.sin(th):.6f} 0 {-G * math.cos(th):.6f}"


def _vel_at(m, d, bid: int, p: np.ndarray, mocap_vel: dict) -> np.ndarray:
    if bid in mocap_vel:
        lin, ang, origin = mocap_vel[bid]
        return lin + np.cross(ang, p - origin)
    res = np.zeros(6)
    mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, bid, res, 0)
    return res[3:] + np.cross(res[:3], p - d.xpos[bid])


def run(m, d, t0: float, t1: float, drive=None, bodies=(), log_from: float | None = None) -> dict:
    """Simulate from title time t0 to t1. drive(t, m, d) sets mocap poses and returns {body_id: (lin, ang, origin)}
    velocities for them. Returns {"contacts": [...], "poses": {name: [[t, x, y, z, qw, qx, qy, qz], ...]}}."""
    steps = int(round((t1 - t0) / DT_SIM))
    per_log = int(round(1 / (LOG_HZ * DT_SIM)))
    per_bake = 1 / BAKE_HZ
    contacts, poses = [], {b: [] for b in bodies}
    bid = {b: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b) for b in bodies}
    gname = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or f"g{i}" for i in range(m.ngeom)]
    next_bake = t0
    f6 = np.zeros(6)
    mv = drive(t0, m, d) if drive else {}
    mujoco.mj_forward(m, d)
    for k in range(steps + 1):
        t = t0 + k * DT_SIM
        if t >= next_bake - 1e-9:
            for b, i in bid.items():
                poses[b].append([round(t, 6)] + [float(v) for v in d.xpos[i]] + [float(v) for v in d.xquat[i]])
            next_bake += per_bake
        if k % per_log == 0 and (log_from is None or t >= log_from):
            for ci in range(d.ncon):
                c = d.contact[ci]
                mujoco.mj_contactForce(m, d, ci, f6)
                n = np.array(c.frame[:3])
                p = np.array(c.pos)
                b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
                v = _vel_at(m, d, b2, p, mv) - _vel_at(m, d, b1, p, mv)
                pair = "|".join(sorted((gname[c.geom1], gname[c.geom2])))
                contacts.append({"t_s": round(t, 4), "pair": pair, "v_n": float(-np.dot(v, n)), "f_n": float(f6[0])})
        if k == steps:
            break
        if drive:
            mv = drive(t + DT_SIM, m, d)
        mujoco.mj_step(m, d)
    return {"contacts": contacts, "poses": poses}


def save(out_dir, name: str, result: dict, meta: dict) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eventlog as E
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    E.write_jsonl(result["contacts"], out / f"{name}-contacts-1khz.jsonl")
    ev = E.events(result["contacts"])
    E.write_jsonl(ev, out / f"{name}-events.jsonl")
    (out / f"{name}-bake.json").write_text(json.dumps({"meta": meta, "poses": result["poses"]}), encoding="utf-8")
    return {"events": ev, "n_contact_samples": len(result["contacts"])}
