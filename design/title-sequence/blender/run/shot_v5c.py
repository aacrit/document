"""The Run v5c: the one continuous shot, frame by frame (numpy only; pure functions of the physics bake).

The marble's pose comes from the MuJoCo bake (240 Hz). The camera is a motion-control rig (plan section 4): a critically
damped spring follow (omega 3.2 rad/s) of a point ahead of the marble, from 0.45 m at 26 degrees and 155 degrees from the
heading, coming in to 0.16 m at 16 degrees, f/2.8, over each leather strip (the close passes), on the outside of each
bank, and on the near side of each reach. It opens on the oblique wide from 1.6 m and descends to the follow over 3 s;
after the marble rests it continues down past the marble onto the record and settles on the record's pose (the whole
16:9 sheet filling the frame, looked at straight down), held 1 s. No cut, no fade, no time remap.
"""

from __future__ import annotations

import math

import numpy as np

import channel_v5c as C

LEAD_RAMP = 0.12                         # metres of run over which the camera eases into and out of a close pass
AZ_SWAP = 0.40                           # metres after a bank over which the camera crosses behind the marble
END_HOLD = 1.0


def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)


def closeness(s):
    """0 in the follow, 1 over a leather strip (the close pass), eased over LEAD_RAMP each side."""
    s = np.asarray(s, float)
    w = np.zeros(s.shape)
    for lz in C.LEATHER:
        a, b = lz["s"]
        w = np.maximum(w, _smooth((s - (a - LEAD_RAMP)) / LEAD_RAMP) * (1 - _smooth((s - b) / LEAD_RAMP)))
    return w


def az_offset_deg(s):
    """The eye's azimuth from the marble's heading: -155 (behind, to its right) on reach 1, turn 1 (its outside), turn 2
    (its inside: the globe stands on the outside, so it is seen behind the marble as it banks) and reach 3; -205
    (behind, to its left) on reach 2. It crosses behind the marble over AZ_SWAP after turn 1 and before turn 2. Right of
    the heading is the near side on reaches 1 and 3, left on reach 2."""
    s = np.asarray(s, float)
    t1 = [g for g in C.SEGMENTS if g["name"] == "turn 1"][0]
    t2 = [g for g in C.SEGMENTS if g["name"] == "turn 2"][0]
    e1, b2 = t1["s0"] + t1["len"], t2["s0"]
    return -155.0 - 50.0 * _smooth((s - e1) / AZ_SWAP) + 50.0 * _smooth((s - (b2 - AZ_SWAP)) / AZ_SWAP)


def marble_track(bake, times):
    P = np.array(bake["poses"]["marble"])
    T = P[:, 0]
    out = []
    for t in times:
        i = int(np.clip(np.searchsorted(T, t), 1, len(T) - 1))
        a = (t - T[i - 1]) / max(T[i] - T[i - 1], 1e-9)
        a = min(max(a, 0.0), 1.0)
        p = P[i - 1, 1:4] * (1 - a) + P[i, 1:4] * a
        q0, q1 = P[i - 1, 4:8], P[i, 4:8]
        if np.dot(q0, q1) < 0:
            q1 = -q1
        q = q0 * (1 - a) + q1 * a
        out.append((p, q / np.linalg.norm(q)))
    return out


def s_of(p):
    if p[0] > C.LIP_X - 1e-4:
        return C.LENGTH + float(p[0] - C.LIP_X)
    s, u, k = C.project(np.array([p[0]]), np.array([p[1]]))
    return float(s[0]) if np.isfinite(u[0]) else 0.0


def record_pose():
    """The record's pose: straight down over its centre at the distance where its 16:9 width fills the 50 mm frame."""
    x0, x1, y0, y1 = C.ITEMS["record"]["rect"]
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, C.felt_top() + C.ITEMS["record"]["h"]])
    dist = (x1 - x0) * C.LENS_MM / C.SENSOR_W
    return c + np.array([0, 0, dist]), c


def shot(bake, fps, t_rest):
    """Per frame: dict(t, marble pos, quat, eye, target, up, focus, fstop). The frame count runs to t_rest + arrive."""
    t_end = t_rest + C.RUNTIME["arrive"]
    n = int(math.ceil(t_end * fps))
    dt = 1.0 / 240
    ts = np.arange(0.0, t_end + dt, dt)
    mt = marble_track(bake, ts)
    om = C.FOLLOW["omega"]
    eye = tgt = None
    ve = np.zeros(3)
    vt = np.zeros(3)
    fine = []
    # the rig's feed-forward: a critically damped spring trails a steady move by 2/omega, so the track is laid that far
    # ahead along the marble's (smoothed) velocity; the spring then only absorbs the changes of speed
    Pm = np.array([p for p, _ in mt])
    Vm = np.gradient(Pm, dt, axis=0)
    k = np.exp(-0.5 * (np.arange(-48, 49) / 16.0) ** 2)
    k /= k.sum()
    Vm = np.stack([np.convolve(np.pad(Vm[:, j], 48, mode="edge"), k, mode="valid") for j in range(3)], 1)
    lag = 2.0 / om
    for (t, (p, q)), vel in zip(zip(ts, mt), Vm):
        s = s_of(p)
        _, _, h = C.point(min(s, C.LENGTH))
        w = float(closeness(s))
        D = C.FOLLOW["D"] + (C.CLOSE["D"] - C.FOLLOW["D"]) * w
        el = math.radians(C.FOLLOW["elev"] + (C.CLOSE["elev"] - C.FOLLOW["elev"]) * w)
        az = h + math.radians(float(az_offset_deg(s)))
        ahead = C.FOLLOW["lead_ahead"] * D / C.FOLLOW["D"]
        td = np.array([p[0] + ahead * math.cos(h), p[1] + ahead * math.sin(h), p[2] - C.R * 0.5])
        ed = td + D * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        ff = np.array([vel[0], vel[1], 0.0]) * lag
        td, ed = td + ff, ed + ff
        if eye is None:
            eye, tgt = ed.copy(), td.copy()
        # critically damped springs (the rig's track absorbs the timing): x'' = w^2 (xd - x) - 2 w x'
        ve += (om * om * (ed - eye) - 2 * om * ve) * dt
        eye = eye + ve * dt
        vt += (om * om * (td - tgt) - 2 * om * vt) * dt
        tgt = tgt + vt * dt
        fine.append((t, p, q, eye.copy(), tgt.copy(), w))
    o_eye, o_tgt = C.opening_eye()
    r_eye, r_tgt = record_pose()
    frames = []
    FT = np.array([f[0] for f in fine])
    for f in range(n):
        t = f / fps
        i = int(np.clip(np.searchsorted(FT, t), 0, len(fine) - 1))
        _, p, q, e, g, w = fine[i]
        a = float(_smooth(t / C.OPEN["descend_s"]))                  # the opening's descent
        e = o_eye * (1 - a) + e * a
        g = o_tgt * (1 - a) + g * a
        b = float(_smooth((t - (t_rest - 0.5)) / (t_end - END_HOLD - (t_rest - 0.5))))   # down onto the record
        e = e * (1 - b) + r_eye * b
        g = g * (1 - b) + r_tgt * b
        up = np.array([0.0, 0.0, 1.0]) * (1 - b) + np.array([0.0, 1.0, 0.0]) * b
        up /= np.linalg.norm(up)
        fstop = C.FOLLOW["fstop"] + (C.CLOSE["fstop"] - C.FOLLOW["fstop"]) * w
        fstop = C.OPEN["fstop"] * (1 - a) + fstop * a
        fstop = fstop * (1 - b) + 5.6 * b
        focus = float(np.linalg.norm(p - e)) * (1 - b) + float(np.linalg.norm(r_tgt - e)) * b
        frames.append({"t": t, "p": p, "q": q, "eye": e, "tgt": g, "up": up, "focus": focus, "fstop": fstop,
                       "close": w, "open": 1 - a, "end": b})
    return frames
