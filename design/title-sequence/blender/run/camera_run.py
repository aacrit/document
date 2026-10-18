"""The Run: the camera, a function of title seconds (numpy only: Blender, the render driver and pytest import it).

One rig on the `rostrum` idea: it cruises and never springs. Its target is the leading marble 0.4 s ahead (the design's
lookahead), smoothed, and then limited by the founder's 7-second pan guide: the target never moves faster than 10.5 px
a frame across the frame's width (11 is the limit) or 5.7 px a frame up it (6), at 24 fps, measured at the focus
plane, and it eases in and out of every move. Holds: the latch's approved framing (f36-f167), the brass disc's settle
(f864-f928); in the tail it finds the marbles, then the record, and descends until the record fills the frame.

Height and angle follow the design's crane (bench level at the latch, top-down at 1.2 m by f780) by keyframes in
seconds. The lamp rides the arm. `measure` replays the camera at any rate and reports the pan speed per beat: the
frame-centre speed (what the limiter holds) and the largest ground-point speed over a 3 x 3 grid in the frame's
middle half (orbit and zoom move the edges even when the centre holds).
"""

from __future__ import annotations

import math

import numpy as np

FPS = 24
SENSOR_W, LENS = 36.0, 50.0
SENSOR_H = SENSOR_W * 9 / 16
KW = SENSOR_W / LENS                        # field width per metre of distance (0.72)
KH = SENSOR_H / LENS
CAP_X_PX, CAP_Y_PX = 10.5, 5.7              # per frame at 24 fps: the guide's 11 and 6 with a margin
LOOKAHEAD = 0.4
LATCH = {"eye_off": (0.035, -0.205, 0.096), "aim_off": (0.019, 0.0, 0.006), "a0": (0.0, 0.0, 0.010)}

# the crane, (frame at 24 fps, distance to the target m, pitch down deg, yaw deg: the azimuth the camera looks along,
# f-stop); between keys a smoothstep in seconds
CRANE = [(130, 0.22446, 23.639, 94.463, 4.0), (167, 0.22446, 23.639, 94.463, 4.0), (230, 0.42, 22.0, 92.0, 4.0), (300, 0.50, 26.0, 92.0, 4.0),
         (383, 0.62, 32.0, 90.0, 4.0), (456, 0.80, 45.0, 90.0, 4.5), (528, 1.10, 65.0, 90.0, 5.0),
         (600, 1.35, 82.0, 90.0, 5.6), (684, 1.50, 89.0, 90.0, 5.6), (935, 1.50, 89.0, 90.0, 5.6)]


def smoothstep(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def keyed(keys, t, col):
    """Smoothstep between keyframes [(frame, ...)] at title second t, column col."""
    ts = [k[0] / FPS for k in keys]
    if t <= ts[0]:
        return keys[0][col]
    for i in range(len(keys) - 1):
        if t <= ts[i + 1]:
            u = smoothstep((t - ts[i]) / (ts[i + 1] - ts[i]))
            return keys[i][col] + (keys[i + 1][col] - keys[i][col]) * u
    return keys[-1][col]


def interp_track(rows, t):
    a = np.asarray(rows)
    return np.array([np.interp(t, a[:, 0], a[:, k]) for k in (1, 2, 3)])


def front_track(poses, names, ts, rear=False):
    """The leading (largest x) marble's position at each time (rear=True: the last moving one)."""
    out = []
    start = {}
    for n in names:
        rows = poses.get(n) or []
        if rows:
            a = np.asarray(rows)
            moved = np.linalg.norm(a[:, 1:3] - a[0, 1:3], axis=1) > 0.003
            # a marble counts from the moment it first moves (the freed pair waits on the galley's step until then)
            start[n] = float(a[int(np.argmax(moved)), 0]) if moved.any() else 1e9
    for t in ts:
        best = None
        for n in names:
            rows = poses.get(n) or []
            if not rows or t < start.get(n, 1e9) - 1e-9:
                continue
            p = interp_track(rows, min(t, rows[-1][0]))
            if best is None or (p[0] < best[0] if rear else p[0] > best[0]):
                best = p
        if best is None:
            rows = poses.get(names[0]) or []
            best = interp_track(rows, min(max(t, rows[0][0]), rows[-1][0]))
        out.append(best)
    return np.array(out)


def limit(path, ts, cap_x, cap_y, ease_s=0.8, locked=None):
    """Follow `path` (N x 2) as closely as the speed caps allow (m/s, per sample), with acceleration bounded so a move
    eases in and out over about ease_s seconds: forward and backward passes, the backward one so the camera starts
    early enough to arrive (it anticipates, as the design's lookahead does) instead of lagging."""
    n = len(ts)
    lk = np.zeros(n, bool) if locked is None else np.asarray(locked)
    dt = np.diff(ts, prepend=ts[0] - (ts[1] - ts[0]))
    out = path.copy()
    for axis, cap in ((0, cap_x), (1, cap_y)):
        # backward first (so a move starts early enough to arrive: the camera anticipates), then forward from the
        # pinned start (so speed, acceleration and continuity hold everywhere); the forward pass is the result
        y = path[:, axis].copy()
        v2 = np.zeros(n)
        for i in range(n - 2, -1, -1):
            vmax = cap[i]
            amax = vmax / ease_s
            want = (y[i + 1] - path[i, axis]) / dt[i + 1]
            want = (path[i + 1, axis] - path[i, axis]) / dt[i + 1] if lk[i] else (y[i + 1] - path[i, axis]) / dt[i + 1]
            lo, hi = v2[i + 1] - amax * dt[i + 1], v2[i + 1] + amax * dt[i + 1]
            v2[i] = min(max(want, lo, -vmax), hi, vmax)
            y[i] = path[i, axis] if lk[i] else y[i + 1] - v2[i] * dt[i + 1]
        x = y.copy()
        v = np.zeros(n)
        for i in range(1, n):
            if lk[i]:
                x[i] = path[i, axis]
                v[i] = (x[i] - x[i - 1]) / dt[i]
                continue
            vmax = cap[i]
            amax = vmax / ease_s
            want = (y[i] - x[i - 1]) / dt[i]
            lo, hi = v[i - 1] - amax * dt[i], v[i - 1] + amax * dt[i]
            v[i] = min(max(want, lo, -vmax), hi, vmax)
            x[i] = x[i - 1] + v[i] * dt[i]
        out[:, axis] = x
    return out


def gauss(x, ts, sigma):
    if sigma <= 0:
        return x
    dt = ts[1] - ts[0]
    k = int(3 * sigma / dt)
    w = np.exp(-0.5 * (np.arange(-k, k + 1) * dt / sigma) ** 2)
    w /= w.sum()
    pad = np.pad(x, ((k, k), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, j], w, mode="valid") for j in range(x.shape[1])], 1)


def eye_from(target, D, pitch_deg, yaw_deg):
    p, y = math.radians(pitch_deg), math.radians(yaw_deg)
    fwd = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), -math.sin(p)])
    return np.asarray(target) - D * fwd


def plan(prefix_poses, layout, tail=None, t_end=None, dt=1 / 240):
    """The camera at 240 Hz: rows {t, eye, target, focus, fstop, D, pitch, yaw}, plus the lamp. tail: {poses,
    record: {x0, y, W, H, z}, windows (approach, close, dissolve, tour) in frames} for a film."""
    st = layout["stations"]
    t0 = 1.4
    if t_end is None:
        t_end = (935 + 1) / FPS
    ts = np.arange(t0, t_end + 1e-9, dt)
    names = ["lead", "pair1", "pair2"]
    poses = {n: list(prefix_poses.get(n) or []) for n in names}
    if tail:
        for n in names:
            poses[n] = poses[n] + [r for r in tail["poses"].get(n, []) if r[0] > poses[n][-1][0]]
    tl = np.minimum(ts + LOOKAHEAD, max(r[-1][0] for r in poses.values() if r))
    fr = front_track(poses, names, tl)
    rr_ = front_track(poses, names, tl, rear=True)
    D = np.array([keyed(CRANE, t, 1) for t in ts])
    # the camera frames the file: midway between its first and last marble, but never so far back that the
    # first leaves the frame's right third
    want = 0.5 * (fr[:, :2] + rr_[:, :2])
    want[:, 0] = np.maximum(want[:, 0], fr[:, 0] - 0.30 * KW * D)
    pitch = np.array([keyed(CRANE, t, 2) for t in ts])
    yaw = np.array([keyed(CRANE, t, 3) for t in ts])
    fstop = np.array([keyed(CRANE, t, 4) for t in ts])
    # lead room: the marble sits a little left of centre, the frame ahead of it
    want[:, 0] += 0.12 * KW * D
    # holds and hand-offs
    m167 = interp_track(poses["lead"], 167 / FPS)
    a0 = np.array(LATCH["a0"][:2])
    a1 = np.array([m167[0] * 0.15, m167[1] * 0.15])
    brass = st.get("brass", {})
    b_xy = np.array([brass.get("x", 0.0), brass.get("y", 0.0)])
    for i, t in enumerate(ts):
        f = t * FPS
        if f <= 130:
            want[i] = a0
        elif f <= 167:
            u = smoothstep((f - 130) / (179 - 130))
            want[i] = a0 + (a1 - a0) * u
        if 852 <= f <= 940:
            # hold on the brass disc through its settle, the marbles running on out of the frame's right side
            k = smoothstep((f - 852) / 14.0) * (1 - smoothstep((f - 928) / 12.0))
            want[i] = want[i] * (1 - k) + (b_xy + np.array([0.10 * KW * D[i], 0.0])) * k
    # the tail: approach, then the record, then the descent that fills the frame with it
    if tail:
        rec = tail["record"]
        a_, c_, d_, tour_ = tail["windows"]
        f_app0, f_close0 = 936, 936 + a_
        f_close1 = f_close0 + c_
        rec_c = np.array([rec["x0"] + rec["W"] / 2, rec["y"]])
        # final close pose: a 16:9 crop inside the record, 5 mm in from its near (left) edge, at 70% of its width
        fw_end = min(0.70 * rec["W"], (rec["H"] - 0.012) * 16 / 9)
        end_c = np.array([rec["x0"] + 0.005 + fw_end / 2 + 0.004, rec["y"]])
        D_app = max(min((rec["W"] * 1.55) / KW, 1.5), 0.35)
        D920 = keyed(CRANE, 920 / FPS, 1)
        for i, t in enumerate(ts):
            f = t * FPS
            if f >= 920:
                # the crane stays up while the camera travels to the record, and comes down over the approach's
                # last second and a half
                u = smoothstep((f - (f_close0 - 36)) / 36.0)
                D[i] = D920 + (D_app - D920) * u
                pitch[i], yaw[i] = 89.0, 90.0
                # frame the record in the right two thirds as it arrives, the marbles entering from the left
                hold = rec_c + np.array([-0.18 * KW * D[i], 0.0])
                k = smoothstep((f - 948) / 40.0)
                want[i] = want[i] * (1 - k) + hold * k
            if f >= f_close0:
                u = smoothstep((f - f_close0) / c_)
                D[i] = D_app + (fw_end / KW - D_app) * u
                hold = rec_c + np.array([-0.18 * KW * D_app, 0.0])
                want[i] = hold + (end_c - hold) * u
                fstop[i] = 5.6 + (8.0 - 5.6) * u
    smooth = gauss(want, ts, 0.5)
    fw = KW * D
    fh_ground = KH * D / np.maximum(np.sin(np.radians(pitch)), 0.2)
    cap_x = CAP_X_PX * FPS / 1920 * fw
    cap_y = CAP_Y_PX * FPS / 1080 * fh_ground
    # the latch is the approved proof's framing exactly: pinned through f167, the limiter carries on from it
    locked = ts * FPS <= 167
    smooth[locked] = want[locked]
    tgt2 = limit(smooth, ts, cap_x, cap_y, locked=locked)
    rows = []
    for i, t in enumerate(ts):
        f = t * FPS
        tz = 0.006
        T = np.array([tgt2[i][0], tgt2[i][1], tz])
        # the latch's approved framing aims right of and above the track (the subject at 0.38 of the width); the
        # offset eases out after f167 as the crane takes over. Eye = aim - D * forward (the latch's own geometry:
        # eye offset (0.035, -0.205, 0.096) from the track is D 0.2242 m at 23.7 deg down, yaw 94.46)
        u = smoothstep((f - 167) / 90.0)
        aim = T + np.array(LATCH["aim_off"]) * (1 - u)
        e = eye_from(aim, D[i], pitch[i], yaw[i])
        rows.append({"t": round(float(t), 6), "eye": e.tolist(), "target": aim.tolist(), "D": float(D[i]),
                     "pitch": float(pitch[i]), "yaw": float(yaw[i]), "fstop": float(fstop[i])})
    # focus: on the leading marble while it is in frame at the latch (founder: the subject stays sharp through its
    # exit), else on the target
    for r in rows:
        e = np.array(r["eye"])
        r["focus"] = float(np.linalg.norm(np.array(r["target"]) - e))
        if r["t"] * FPS <= 200:
            m = interp_track(poses["lead"], r["t"])
            if r["t"] * FPS < 121:
                m = np.array([0.0, 0.0, 0.0015])
            if in_frame(r, m):
                r["focus"] = float(np.linalg.norm(m - e))
    return rows


def cam_basis(r):
    e, t = np.array(r["eye"]), np.array(r["target"])
    f = t - e
    f /= np.linalg.norm(f)
    up_w = np.array([0.0, 0.0, 1.0]) if abs(f[2]) < 0.995 else np.array([0.0, 1.0, 0.0])
    # Blender's to_track_quat('-Z', 'Y'): the camera's up is world Z projected (or +Y when looking straight down)
    right = np.cross(f, up_w)
    right /= np.linalg.norm(right)
    up = np.cross(right, f)
    return e, f, right, up


def project(r, p):
    """World point -> (px_x, px_y) in a 1920 x 1080 frame (origin top left), or None behind the camera."""
    e, f, right, up = cam_basis(r)
    d = np.asarray(p) - e
    z = d @ f
    if z <= 1e-6:
        return None
    x = (d @ right) / z * LENS / SENSOR_W * 1920 + 960
    y = -(d @ up) / z * LENS / SENSOR_W * 1920 + 540
    return np.array([x, y])


def in_frame(r, p, margin=0.0):
    q = project(r, p)
    return q is not None and -margin <= q[0] <= 1920 + margin and -margin <= q[1] <= 1080 + margin


def ray_to_bench(r, px, py, z=0.0):
    e, f, right, up = cam_basis(r)
    x = (px - 960) / 1920 * SENSOR_W / LENS
    y = -(py - 540) / 1920 * SENSOR_W / LENS
    d = f + x * right + y * up
    if abs(d[2]) < 1e-9:
        return None
    s = (z - e[2]) / d[2]
    return e + s * d if s > 0 else None


def at(rows, t):
    ts = np.array([r["t"] for r in rows])
    i = int(np.clip(np.searchsorted(ts, t), 1, len(ts) - 1))
    a, b = rows[i - 1], rows[i]
    u = 0.0 if b["t"] == a["t"] else (t - a["t"]) / (b["t"] - a["t"])
    u = min(max(u, 0.0), 1.0)
    out = {"t": t}
    for k in ("eye", "target"):
        out[k] = (np.array(a[k]) * (1 - u) + np.array(b[k]) * u).tolist()
    for k in ("D", "pitch", "yaw", "fstop", "focus"):
        out[k] = a[k] * (1 - u) + b[k] * u
    return out


BEATS = [("0 black", 0, 35), ("1 clay", 36, 167), ("2 papyrus", 168, 239), ("3 atlas", 240, 383), ("4 cord", 384, 455),
         ("5 type", 456, 527), ("6 survey", 528, 599), ("7 wire", 600, 647), ("8 count", 648, 683),
         ("9 reel", 684, 731), ("10 platen", 732, 779), ("11 swell", 780, 863), ("12 exhaust", 864, 935)]


def measure(rows, f0, f1, fps=24.0):
    """Pan speed per frame between consecutive frames f0..f1 at fps, as px a frame scaled to 24p-equivalent
    (px per frame at this rate times fps / 24, so the guide's numbers apply at any rate): the centre's motion and
    the largest motion of a 3 x 3 grid of bench points in the frame's middle half."""
    out = []
    grid = [(960 + dx * 480, 540 + dy * 270) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    prev = None
    for f in range(f0, f1 + 1):
        r = at(rows, f / fps)
        if prev is not None:
            cx = cy = gx = gy = 0.0
            for k, (px, py) in enumerate(grid):
                g = ray_to_bench(prev, px, py)
                if g is None:
                    continue
                q = project(r, g)
                if q is None:
                    continue
                ddx, ddy = abs(q[0] - px) * fps / 24.0, abs(q[1] - py) * fps / 24.0
                gx, gy = max(gx, ddx), max(gy, ddy)
                if k == 4:
                    cx, cy = ddx, ddy
            out.append({"f": f, "cx": cx, "cy": cy, "gx": gx, "gy": gy})
        prev = r
    return out


def beat_maxima(rows, f_end=935, fps=24.0, extra=()):
    m = measure(rows, 0, int(round(f_end * fps / 24.0)), fps)
    res = []
    for name, a, b in list(BEATS) + list(extra):
        sel = [x for x in m if a * fps / 24.0 <= x["f"] <= b * fps / 24.0]
        if not sel:
            continue
        res.append({"beat": name, "frames": [a, b], "centre_x": round(max(x["cx"] for x in sel), 2),
                    "centre_y": round(max(x["cy"] for x in sel), 2), "grid_x": round(max(x["gx"] for x in sel), 2),
                    "grid_y": round(max(x["gy"] for x in sel), 2)})
    return res
