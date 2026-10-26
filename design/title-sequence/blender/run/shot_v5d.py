"""The Run v5d: the one continuous shot from Fable's keys (camera-v5d-keys.json; numpy only, pure functions of the bake).

The physics bake is v5c's, unchanged. The camera is keyed on marble-timeline frames (52 keys): ``rel`` keys give the eye
from the marble (distance D, elevation, azimuth from the bake heading), ``abs`` keys give it in the table frame. Every
frame, the eye, the marble's screen place (sx, sy), the f-stop and the focus distance are smootherstep-interpolated
between the two keys around it, and the aim is SOLVED from the marble's actual position so that it lands at (sx, sy):
look_at is never interpolated. The opening blends the eye from key 0 over frames 0-90 and the aim from key 0's look_at
over 0-48. From frame 927 the pose blends onto record_pose(rec) exactly as shot_v5c does (same b(t), up from +z to +y,
f/5.6, focus onto the sheet), reaching it at 1061 and holding to 1090; the follow component under that blend is the
keys' 926 -> 941 interpolation, then the 941 key held.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import channel_v5c as C
import shot_v5c as SH

HERE = Path(__file__).resolve().parent
KEYS = HERE / "camera-v5d-keys.json"
END_HOLD = SH.END_HOLD
TX, TY = C.SENSOR_W / C.LENS_MM, C.SENSOR_H / C.LENS_MM     # a frame-width / frame-height fraction -> tangent


def smootherstep(t):
    t = min(max(float(t), 0.0), 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)


def load_keys(path=KEYS):
    k = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = sorted(k["keys"], key=lambda x: x["f"])
    return k, keys


def headings(P):
    """Per frame, the marble's heading: atan2 of the position 3 frames ahead minus 3 frames behind (the keys'
    convention); where the marble is still, the last heading it had."""
    n = len(P)
    out = np.zeros(n)
    last = 0.0
    for f in range(n):
        d = P[min(f + 3, n - 1)] - P[max(f - 3, 0)]
        if math.hypot(d[0], d[1]) > 1e-6:
            last = math.atan2(d[1], d[0])
        out[f] = last
    return out


def rel_eye(p, h, rig):
    D, el, az = rig["D_m"], math.radians(rig["elev_deg"]), h + math.radians(rig["az_from_heading_deg"])
    return np.asarray(p, float) + D * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])


def basis(fwd, up=(0.0, 0.0, 1.0)):
    fwd = np.asarray(fwd, float) / np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    return fwd, right, np.cross(right, fwd)


def aim(eye, m, sx, sy):
    """The forward direction (up = +z, no roll) that puts the point m at (sx, sy) of the frame: fractions of the width
    and height from the centre, + right / + up. Closed form: pitch from the vertical component, then yaw."""
    d = np.asarray(m, float) - np.asarray(eye, float)
    d /= np.linalg.norm(d)
    xc, yc = sx * TX, sy * TY                       # the marble's direction in camera coordinates: (xc, yc, 1)
    n = math.sqrt(1 + xc * xc + yc * yc)
    A = math.hypot(1.0, yc)
    th = math.asin(max(-1.0, min(1.0, n * d[2] / A))) - math.atan2(yc, 1.0)
    a = math.cos(th) - yc * math.sin(th)            # the forward-horizontal and right components of the ray
    ps = math.atan2(d[1], d[0]) - math.atan2(-xc, a)
    fwd = np.array([math.cos(th) * math.cos(ps), math.cos(th) * math.sin(ps), math.sin(th)])
    gx, gy, z = screen_of(eye, fwd, m)
    if z <= 0 or abs(gx - sx) > 1e-6 or abs(gy - sy) > 1e-6:
        # only when the point is nearly straight below the eye and the frame would have to tip past the nadir
        raise ValueError(f"no roll-free aim puts {tuple(np.round(m, 4))} at ({sx}, {sy}) from {tuple(np.round(eye, 4))}")
    return fwd


def screen_of(eye, fwd, m, up=(0.0, 0.0, 1.0)):
    """Where the point m lands: (sx, sy) as fractions of the frame from the centre, and its depth along fwd."""
    f, r, u = basis(fwd, up)
    d = np.asarray(m, float) - np.asarray(eye, float)
    z = float(d @ f)
    return float(d @ r) / z / TX, float(d @ u) / z / TY, z


def coc_px(fstop, focus, dist, width=1920):
    """The circle of confusion of a point at ``dist`` with the lens focused at ``focus`` (thin lens), in pixels."""
    fl = C.LENS_MM / 1000.0
    c = (fl / fstop) * abs(dist - focus) / dist * fl / max(focus - fl, 1e-6)
    return c / (C.SENSOR_W / 1000.0) * width


def focus_of(key, eye, m, points):
    """A key's focus distance from this frame's eye: the marble, a point (a rack), a split (the harmonic mean of the
    marble's and the point's distances), or a fixed distance (the opening's)."""
    tgt = key.get("focus_target", "marble")
    dm = float(np.linalg.norm(np.asarray(m) - eye))
    if tgt == "marble":
        return dm
    if tgt.startswith("split:"):
        dp = float(np.linalg.norm(np.asarray(points[tgt[6:]], float) - eye))
        return 2 * dm * dp / (dm + dp)
    if tgt in points:
        return float(np.linalg.norm(np.asarray(points[tgt], float) - eye))
    return float(key["focus_m"])


def eye_of(key, p, h):
    return rel_eye(p, h, key["rig"]) if key["rig"]["mode"] == "rel" else np.asarray(key["eye"], float)


def bracket(keys, f):
    """The keys either side of frame f and the smootherstep weight between them (after the last key: the last, held)."""
    if f >= keys[-1]["f"]:
        return keys[-1], keys[-1], 0.0
    for a, b in zip(keys[:-1], keys[1:]):
        if a["f"] <= f < b["f"]:
            return a, b, smootherstep((f - a["f"]) / (b["f"] - a["f"]))
    return keys[0], keys[0], 0.0


def follow(keys, f, p, h, points, eyes="rig"):
    """The keyed camera at frame f (before the ending's blend): eye, forward, (sx, sy), f-stop, focus distance.

    eyes="rig" (the build): a rel key is the rig's offset from the marble at THIS frame, so between two rel keys the
    eye orbits the moving marble (D, elevation, azimuth interpolated) and keeps its speed through every key.
    eyes="points": every key's eye taken as the fixed point it has at its own frame, smootherstep between them (what
    the keys file's samples_every_10_frames hold); the eye then comes to rest at every key, so it is kept only to
    measure that difference, never rendered."""
    a, b, u = bracket(keys, f)
    if eyes == "points":
        eye = np.asarray(a["eye"], float) * (1 - u) + np.asarray(b["eye"], float) * u
    elif a["rig"]["mode"] == "rel" and b["rig"]["mode"] == "rel":
        rig = {"mode": "rel", **{k: a["rig"][k] * (1 - u) + b["rig"][k] * u
                                  for k in ("D_m", "elev_deg", "az_from_heading_deg")}}
        eye = rel_eye(p, h, rig)                     # an orbit about the marble, not a chord across it
    else:
        eye = eye_of(a, p, h) * (1 - u) + eye_of(b, p, h) * u
    sx = a["marble_screen"][0] * (1 - u) + b["marble_screen"][0] * u
    sy = a["marble_screen"][1] * (1 - u) + b["marble_screen"][1] * u
    fwd = aim(eye, p, sx, sy)
    fstop = a["fstop"] * (1 - u) + b["fstop"] * u
    focus = focus_of(a, eye, p, points) * (1 - u) + focus_of(b, eye, p, points) * u
    return eye, fwd, (sx, sy), fstop, focus


def shot(bake, fps, t_rest, rec="C20-METAR-0851", keys_path=KEYS, eyes="rig"):
    """Per frame: dict(t, p, q, eye, tgt, up, focus, fstop, sx, sy, open, end, close) as shot_v5c.shot returns (so
    scene_v5c.animate, rect_seen and the tail plan read it unchanged), plus the marble's image size and blur."""
    spec, keys = load_keys(keys_path)
    points = spec["conventions"]["focus_points"]
    t_end = t_rest + C.RUNTIME["arrive"]
    n = int(math.ceil(t_end * fps))
    mt = SH.marble_track(bake, [f / fps for f in range(n)])
    P = np.array([p for p, _ in mt])
    H = headings(P)
    k0 = keys[0]
    o_eye, o_tgt = np.asarray(k0["eye"], float), np.asarray(k0["look_at"], float)
    open_f = keys[1]["f"]                          # 90: the eye's blend; the aim's is 48 (the keys' convention)
    r_eye, r_tgt = SH.record_pose(rec)
    out = []
    for f in range(n):
        t = f / fps
        p, q = mt[f]
        eye, fwd, (sx, sy), fstop, focus = follow(keys, f, p, H[f], points, eyes)
        dist = float(np.linalg.norm(p - eye))
        tgt = eye + fwd * dist
        if f < open_f:
            a2 = smootherstep(f / 48.0)
            tgt = o_tgt * (1 - a2) + tgt * a2
        b = float(SH._smooth((t - (t_rest - 0.5)) / (t_end - END_HOLD - (t_rest - 0.5))))     # shot_v5c's ending
        e = eye * (1 - b) + r_eye * b
        g = tgt * (1 - b) + r_tgt * b
        up = np.array([0.0, 0.0, 1.0]) * (1 - b) + np.array([0.0, 1.0, 0.0]) * b
        up /= np.linalg.norm(up)
        fs = fstop * (1 - b) + 5.6 * b
        if b > 0:
            # as shot_v5c: the follow's focus (the marble at 941) taken from the blended eye, onto the sheet
            a, bb, u = bracket(keys, f)
            ff = focus_of(a, e, p, points) * (1 - u) + focus_of(bb, e, p, points) * u
            fo = ff * (1 - b) + float(np.linalg.norm(r_tgt - e)) * b
        else:
            fo = focus
        dm = float(np.linalg.norm(p - e))
        out.append({"t": t, "p": p, "q": q, "eye": e, "tgt": g, "up": up, "focus": fo, "fstop": fs,
                    "sx": sx, "sy": sy, "close": 0.0, "open": 1 - smootherstep(f / open_f), "end": b,
                    "marble_m": dm, "marble_px": C.marble_px(dm), "marble_blur_px": coc_px(fs, fo, dm)})
    return out
