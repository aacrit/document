"""Title v6, days 2-3: the roll-out placement and the end-to-end bake (sim_v6's model; D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/bake_v6.py [--no-lock]

Five stages, each in its own short HEAVY.lock window (released between them, so a film render can take the machine):
1. roll to the galley with nothing placed; set the row on the ball's line and search the impact parameter on sort 1
   for a 5-8 degree turn to the right;
2. from a snapshot past the row, set the weights on the ball's right at s 1.50 and search the impact parameter for a
   25 degree turn to the left (the spec's 20-30);
3. from a snapshot past the weights, try the globe's foot on the ball's left at four stations and five impact
   parameters; keep those that turn it 15-25 degrees right and bring it to rest; refine for the record's centre
   line; then search the felt's rolling resistance (0.03-0.06) for the 7 mm stop;
4. lay the coins and the jeton at 3 cm from the ball's actual track (close passes);
5. the bake: from f0, everything in place, one run. Only this run is the bake; the snapshots only chose positions.

Writes D:/document-media/title-sequence/v6/bake/: bake.json, track.json, contacts-1khz.jsonl, events.jsonl,
placement.json, placement-log.json.
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
import eventlog as E  # noqa: E402
import sim_v6 as V  # noqa: E402
import table_v6 as T  # noqa: E402

OUT = V.OUT
CLEAR = 0.03                                       # the close passes: 3 cm from the ball's surface (spec 3.6)
S_WEIGHTS = 1.50
GLOBE_STATIONS = (1.95, 2.00, 2.05, 2.10)
GLOBE_B = (0.55, 0.65, 0.75, 0.85, 0.92)


def left_of(v):
    v = np.asarray(v, float) / np.linalg.norm(v)
    return np.array([-v[1], v[0]])


def feet(w):
    """The globe's feet in its own frame: centres (k, 2) and each foot's radius at the ball's equator band, from the
    parts' lowest 5 mm clustered by angle about the footprint centre."""
    v = w.local_band("globe")
    c0 = (v[:, :2].max(0) + v[:, :2].min(0)) / 2
    low = v[v[:, 2] < 0.005]
    ang = np.arctan2(low[:, 1] - c0[1], low[:, 0] - c0[0])
    groups = {}
    for k, a in enumerate(ang):
        q = int(((a + math.pi) / (2 * math.pi)) * 36) % 36
        groups.setdefault(q, []).append(k)
    # merge neighbouring angular bins into feet
    bins = sorted(groups)
    feet_, cur = [], [bins[0]]
    for b in bins[1:]:
        if b - cur[-1] <= 1:
            cur.append(b)
        else:
            feet_.append(cur)
            cur = [b]
    if feet_ and (cur[-1] == 35 and feet_[0][0] == 0):
        feet_[0] = cur + feet_[0]
    else:
        feet_.append(cur)
    band = v[np.abs(v[:, 2] - T.R) < 0.004]
    cs, radii = [], []
    for fb in feet_:
        idx = [k for b in fb for k in groups[b]]
        if len(idx) < 10:
            continue
        c = low[idx, :2].mean(0)
        near = band[np.linalg.norm(band[:, :2] - c, axis=1) < 0.04]
        cs.append(c)
        radii.append(float(np.max(np.linalg.norm(near[:, :2] - c, axis=1))) if len(near) else 0.02)
    return np.array(cs), radii


def stage_line(w, st, s_at):
    d = V.restore(w, st)
    rec = V.run(w, d, 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= s_at + 0.03)
    p, v, t = V.line_at(rec, s_at)
    A = V.track_array(rec)
    i = int(np.argmin(np.abs(A[:, 0] - t)))
    return p, v, float(np.linalg.norm(A[i, 4:6]))


def place_weights(w, p, v, b):
    right = -left_of(v)
    r = V.band_radius(w, "weights", -right)
    c = p + right * b * (T.R + r)
    w.place("weights", float(c[0]), float(c[1]), 0.0)
    return {"b": b, "r_band": r}


def place_globe(w, p, v, b, foot_k=0):
    cs, radii = feet(w)
    left = left_of(v)
    r = radii[foot_k]
    F = p + left * b * (T.R + r)
    a_foot = math.atan2(cs[foot_k][1], cs[foot_k][0])
    yaw = math.atan2(-left[1], -left[0]) - a_foot
    c, s = math.cos(yaw), math.sin(yaw)
    fw = np.array([c * cs[foot_k][0] - s * cs[foot_k][1], s * cs[foot_k][0] + c * cs[foot_k][1]])
    C = F - fw
    w.place("globe", float(C[0]), float(C[1]), yaw)
    return {"b": b, "foot": foot_k, "r_foot_band": r, "foot_xy": F.tolist(), "n_feet": len(cs)}


def run_to_rest(w, st):
    return V.run(w, V.restore(w, st), T.DURATION)


def data_at(w, st, pred):
    d = V.restore(w, st)
    V.run(w, d, 40.0, stop_at=pred)
    return d


def lay_close_passes(w, A):
    out = {}
    xy = A[:, 1:3]
    s = T.along(xy[:, 0], xy[:, 1])
    v = A[:, 4:6]
    for pref, s_at, yaw in (("coin dupondius", 1.66, 0.3), ("coin sestertius", 1.74, 1.1)):
        i = int(np.argmax(s >= s_at))
        right = -left_of(v[i])
        band = w.local_band(pref)
        r = float(np.max(np.linalg.norm(band[:, :2] - band[:, :2].mean(0), axis=1)))
        c = xy[i] + right * (T.R + CLEAR + r)
        w.place(pref, float(c[0]), float(c[1]), yaw)
        out[pref] = {"xy": c.tolist(), "r": r}
    x0, x1, y0, y1 = T.BY_NAME["chart"]["rect"]
    band = w.local_band("jeton")
    r = float(np.max(np.linalg.norm(band[:, :2] - band[:, :2].mean(0), axis=1)))
    cands = []
    for cx, cy in ((x0 + r + 0.004, y0 + r + 0.004), (x0 + r + 0.004, y1 - r - 0.004),
                   (x1 - r - 0.03, y0 + r + 0.004), (x1 - r - 0.03, y1 - r - 0.004)):
        cands.append((cx, cy, float(np.min(np.linalg.norm(xy - [cx, cy], axis=1))) - T.R - r))
    ok = [c for c in cands if c[2] >= CLEAR * 0.9]
    best = min(ok, key=lambda c: c[2]) if ok else max(cands, key=lambda c: c[2])
    w.place("jeton", best[0], best[1], 0.2)
    out["jeton"] = {"xy": [best[0], best[1]], "r": r, "clear_m": best[2]}
    return out


def write_bake(w, rec, log, galley):
    meta = {"fps": T.FPS, "t_release": T.T_RELEASE, "bake_hz": V.BAKE_HZ, "dt": V.DT, "fall_deg": T.FALL_DEG,
            "sags": T.SAGS, "felt_mu_r": w.felt_mu, "roll_len_m": w.roll, "placed": w.placed, "galley": galley,
            "status": rec.status, "t_rest": rec.t_rest, "mujoco": mujoco.__version__}
    (OUT / "bake.json").write_text(json.dumps({"meta": meta, "poses": rec.poses}), encoding="utf-8")
    E.write_jsonl(rec.contacts, OUT / "contacts-1khz.jsonl")
    ev = E.events(rec.contacts, v_min=0.0)
    for e in ev:
        e["frame"] = round(e["t_s"] * T.FPS, 2)
        e["class"] = T.contact_class(e["pair"])
    E.write_jsonl(ev, OUT / "events.jsonl")
    (OUT / "track.json").write_text(json.dumps(rec.track), encoding="utf-8")
    (OUT / "placement.json").write_text(json.dumps({"placed": w.placed, "felt_mu_r": w.felt_mu, "galley": galley,
                                                    "log": log}, indent=1, default=float), encoding="utf-8")


def main():
    import machine_v6 as MV
    use_lock = "--no-lock" not in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(**kv):
        kv["wall"] = time.strftime("%H:%M:%S")
        log.append(kv)
        print(json.dumps(kv, default=float), flush=True)
        (OUT / "placement-log.json").write_text(json.dumps(log, indent=1, default=float), encoding="utf-8")

    w = V.World(felt_mu=float(np.mean(T.FELT_MU_R)))
    for pref in ("weights", "globe", "coin dupondius", "coin sestertius", "jeton"):
        w.park(pref)
    note(stage="model", ngeom=w.m.ngeom, nbody=w.m.nbody, fall_deg=T.FALL_DEG, roll=w.roll)

    with MV.heavy("v6 bake 1/5: the galley glance (MuJoCo)", enabled=use_lock):
        t0 = time.time()
        d = V.new_data(w)
        rec = V.run(w, d, 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= V.SORT1_S - 0.10)
        A = V.track_array(rec)
        note(stage="to galley", status=rec.status, t=d.time + T.T_RELEASE, s=V.ball_s(w, d), wall_s=time.time() - t0,
             v=float(np.linalg.norm(d.qvel[:3])), v_ramp_exit=float(np.max(np.linalg.norm(A[:, 4:6], axis=1))))
        if rec.status != "stop":
            raise SystemExit(f"the ball did not reach the galley: {rec.status}")
        stA = V.snapshot(w, d)
        p, v, sp = stage_line(w, stA, V.SORT1_S)
        nb = float(T.across(*p))

        def galley_turn(b):
            dd = V.restore(w, stA)
            w.place_galley(dd, V.SORT1_S, nb + b * (T.R + V.SORT[1]))
            r_ = V.run(w, dd, 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= V.SORT1_S + 0.30)
            g = V.glance(r_, 3)
            return g["turn_deg"] if g else 0.0
        b_g, turn_g, hist = V.search(galley_turn, 0.70, 0.97, -6.5, 0.6, n=8)
        note(stage="galley", b=b_g, turn=turn_g, hist=hist, n_ball=nb, v_at=sp)
    galley = {"s1": V.SORT1_S, "n_row": nb + b_g * (T.R + V.SORT[1]), "b": b_g}

    with MV.heavy("v6 bake 2/5: the weights glance (MuJoCo)", enabled=use_lock):
        d = V.restore(w, stA)
        w.place_galley(d, galley["s1"], galley["n_row"])
        rec = V.run(w, d, 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= 1.36)
        note(stage="past galley", status=rec.status, t=d.time + T.T_RELEASE, glance=V.glance(rec, 3))
        stB = V.snapshot(w, d)
        p, v, sp = stage_line(w, stB, S_WEIGHTS)

        def weights_turn(b):
            place_weights(w, p, v, b)
            r_ = V.run(w, V.restore(w, stB), 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= S_WEIGHTS + 0.15)
            g = V.glance(r_, 4)
            return g["turn_deg"] if g else 0.0
        b_w, turn_w, hist = V.search(weights_turn, 0.99, 0.55, 25.0, 1.5, n=10)
        wi = place_weights(w, p, v, b_w)
        note(stage="weights", b=b_w, turn=turn_w, hist=hist, v_at=sp, **wi, placed=w.placed["weights"])

    with MV.heavy("v6 bake 3/5: the globe glance and the stop (MuJoCo)", enabled=use_lock):
        d = V.restore(w, stB)
        rec = V.run(w, d, 40.0, stop_at=lambda d_: V.ball_s(w, d_) >= 1.80)
        note(stage="past weights", status=rec.status, t=d.time + T.T_RELEASE)
        stC = V.snapshot(w, d)
        best = None
        for s_g in GLOBE_STATIONS:
            p, v, sp = stage_line(w, stC, s_g)
            for b in GLOBE_B:
                place_globe(w, p, v, b)
                r_ = run_to_rest(w, stC)
                g = V.glance(r_, 5)
                rest = V.track_array(r_)[-1, 1:3]
                row = {"s_g": s_g, "b": b, "turn": g["turn_deg"] if g else None, "status": r_.status,
                       "rest": rest.tolist(), "off_mm": (rest[1] - T.REST_TARGET[1]) * 1000,
                       "short_mm": (T.RECORD_RECT[0] - rest[0] - T.R) * 1000}
                note(stage="globe try", **row)
                ok = g is not None and -25.0 <= g["turn_deg"] <= -15.0 and r_.status == "rest"
                if ok and (best is None or abs(row["off_mm"]) < abs(best["off_mm"])):
                    best = dict(row, p=p.tolist(), v=v.tolist())
        if best is None:
            raise SystemExit("no globe placement turns the ball 15-25 degrees right and brings it to rest")
        p, v = np.array(best["p"]), np.array(best["v"])

        def off_of(b):
            place_globe(w, p, v, b)
            r_ = run_to_rest(w, stC)
            g = V.glance(r_, 5)
            if g is None or not (-25.0 <= g["turn_deg"] <= -15.0) or r_.status != "rest":
                return 1e3 if b > best["b"] else -1e3
            return (V.track_array(r_)[-1, 2] - T.REST_TARGET[1]) * 1000
        b_gl, off, hist = V.search(off_of, max(0.5, best["b"] - 0.08), min(0.97, best["b"] + 0.08), 0.0, 1.0, n=10)
        gi = place_globe(w, p, v, b_gl)
        note(stage="globe", b=b_gl, off_mm=off, hist=hist, s_g=best["s_g"], **gi, placed=w.placed["globe"])
        dD = data_at(w, stC, lambda d_: d_.xpos[w.ball][0] >= T.LIP_X - 0.02)
        stD = V.snapshot(w, dD)
        felt = w.gid["felt"]

        def short_of(mu):
            w.m.geom_friction[felt][2] = mu * T.R
            r2 = run_to_rest(w, stD)
            return (T.RECORD_RECT[0] - V.track_array(r2)[-1, 1] - T.R) * 1000 if r2.status == "rest" else -1e3
        mu_f, short, hist = V.search(short_of, T.FELT_MU_R[0], T.FELT_MU_R[1], 7.0, 0.8, n=10)
        w.m.geom_friction[felt][2] = mu_f * T.R
        w.felt_mu = mu_f
        note(stage="felt", mu_r=mu_f, short_mm=short, hist=hist)

    with MV.heavy("v6 bake 4/5: the close passes (MuJoCo)", enabled=use_lock):
        A = V.track_array(run_to_rest(w, stC))
        note(stage="close passes", **lay_close_passes(w, A))

    with MV.heavy("v6 bake 5/5: the end-to-end bake from f0 (MuJoCo)", enabled=use_lock):
        t0 = time.time()
        d = V.new_data(w)
        w.place_galley(d, galley["s1"], galley["n_row"])
        rec = V.run(w, d, T.DURATION)
        note(stage="bake", status=rec.status, t_rest=rec.t_rest, wall_s=time.time() - t0)
    write_bake(w, rec, log, galley)


if __name__ == "__main__":
    main()
