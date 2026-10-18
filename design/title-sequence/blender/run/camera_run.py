"""The Run v4: the camera, a function of title seconds (numpy and bench only; Blender, the render driver and pytest
import it). Design section 5: the approved latch turned onto the table, the exempt tracking on beats 2-3, holds on
the three banks, closer dips on the knots and the reels, the rise to the full top-down at f935, and in each tail find,
descend and close. What follows is M1's description of the rig, which stands:

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
    es = np.broadcast_to(np.asarray(ease_s, dtype=float), (n,))
    dt = np.diff(ts, prepend=ts[0] - (ts[1] - ts[0]))
    out = path.copy()
    for axis, cap in ((0, cap_x), (1, cap_y)):
        # backward first (so a move starts early enough to arrive: the camera anticipates), then forward from the
        # pinned start (so speed, acceleration and continuity hold everywhere); the forward pass is the result
        y = path[:, axis].copy()
        v2 = np.zeros(n)
        for i in range(n - 2, -1, -1):
            vmax = cap[i]
            amax = vmax / es[i]
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
            amax = vmax / es[i]
            want = (y[i] - x[i - 1]) / dt[i]
            lo, hi = v[i - 1] - amax * dt[i], v[i - 1] + amax * dt[i]
            v[i] = min(max(want, lo, -vmax), hi, vmax)
            x[i] = x[i - 1] + v[i] * dt[i]
        out[:, axis] = x
    return out


def rec_yaw(rec):
    """The camera's yaw that reads the record upright: 90 (up = +y) for a record laid upright, 180 (up = -x) for one
    turned 90 degrees (its image's width along +y, its top toward -x, the marbles' side)."""
    return 90.0 if rec.get("upright", True) else 180.0


def _img_to_table(rec, u, v):
    """A point on the record's image, (u from its left, v from its top) in metres, to table (x, y)."""
    if rec.get("upright", True):
        return rec["x0"] + u, rec["y"] + rec["H"] / 2 - v
    return rec["x0"] + v, rec["y"] - rec["H"] / 2 + u


def a7_window(rec):
    """The tour's resting pose (the A7 window): the largest 16:9 crop of the sheet, centred across; a sheet taller
    than 16:9 shows its full width and its top (masthead, title block), one wider its full height, centred. Returned
    in table metres (x0, y0, x1, y1) and as fractions of the scan (x0, y0, x1, y1, image rows from the top)."""
    iw, ih = (rec["W"], rec["H"]) if rec.get("upright", True) else (rec["H"], rec["W"])
    if iw / ih >= 16 / 9:
        cw, ch = ih * 16 / 9, ih
        u0 = (iw - cw) / 2
    else:
        cw, ch = iw, iw * 9 / 16
        u0 = 0.0
    pts = [_img_to_table(rec, u0, 0.0), _img_to_table(rec, u0 + cw, ch)]
    bench = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    frac = (u0 / iw, 0.0, (u0 + cw) / iw, ch / ih)
    return bench, frac


def close_pose(rec):
    """Where the close ends: 82% of the A7 window (its width along the image's width), its marbles' side 5 mm inside
    the record's near edge, centred on the window across; the marbles lie outside it."""
    iw, ih = (rec["W"], rec["H"]) if rec.get("upright", True) else (rec["H"], rec["W"])
    (_, frac) = a7_window(rec)
    cw = (frac[2] - frac[0]) * iw
    ch = (frac[3] - frac[1]) * ih
    fw = 0.82 * cw
    fh = fw * 9 / 16
    uc = (frac[0] + frac[2]) / 2 * iw
    if rec.get("upright", True):
        # the marbles come from -x: the frame's left edge 5 mm inside the record
        u_left = max(frac[0] * iw, 0.005)
        x, y = _img_to_table(rec, u_left + fw / 2, ch / 2)
    else:
        # the marbles come from -x, the image's top: the frame's top edge 5 mm inside the record
        x, y = _img_to_table(rec, uc, max(0.005, 0.0) + fh / 2)
    return np.array([x, y]), fw


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


EXEMPT = (130, 330)                         # beats 2-3 as laid (papyrus and hinge): the founder's exemption
EXEMPT_CAP = 0.40                           # m/s there (enough to keep the lead marble in frame)
WIDE_D = 3.40                               # the full top-down at f935: the 2.2 m table with 5% margins each side
TABLE_C = (1.10, 0.50)


def _rot(v, deg):
    a = math.radians(deg)
    return np.array([v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)])


def bump(f, fa, fb, ramp):
    return smoothstep((f - (fa - ramp)) / ramp) * (1 - smoothstep((f - fb) / ramp))


def first_cross(poses, names, pred):
    best = None
    for n in names:
        for r in poses.get(n) or []:
            if pred(r):
                best = r[0] if best is None else min(best, r[0])
                break
    return best


def stations(st, poses, names):
    """(from frame, to frame, anchor xy, close distance): the knots and the two reels, framed closer (24-frame dips)."""
    out = []
    kh = st.get("khipu")
    if kh:
        k = np.array(kh["knots"])
        c = k[:, :2].mean(0)
        tc = first_cross(poses, names, lambda r: math.dist(r[1:3], c) < 0.10)
        if tc:
            out.append((tc * FPS, tc * FPS + 30, (float(c[0]), float(c[1])), 0.5))
    for nm in ("reel_reg", "reel_film"):
        r = st.get(nm)
        if r:
            c = r["centre"]
            tc = first_cross(poses, names, lambda row: math.dist(row[1:3], c[:2]) < r["r"] + 0.03)
            if tc:
                out.append((tc * FPS - 6, tc * FPS + 18, (c[0], c[1]), 0.60))
    return out


def plan(prefix_poses, layout, tail=None, t_end=None, dt=1 / 240):
    """The camera at 240 Hz: rows {t, eye, target, focus, fstop, D, pitch, yaw, phase}. tail: {poses, record: {x0, y,
    W, H, z}, windows (find, descend, close, dissolve, tour)} for a film. Design section 5."""
    import bench as B
    st = layout["stations"]
    turns = {t_["bank"]: t_ for t_ in (layout.get("checks") or {}).get("turns", []) if t_.get("frame")}
    t0 = 1.4
    if t_end is None:
        t_end = (935 + 1) / FPS
    ts = np.arange(t0, t_end + 1e-9, dt)
    fr = ts * FPS
    names = ["lead", "pair1", "pair2"]
    poses = {n: list(prefix_poses.get(n) or []) for n in names}
    if tail:
        for n in names:
            poses[n] = poses[n] + [r for r in tail["poses"].get(n, []) if r[0] > poses[n][-1][0]]
    lead = poses["lead"]
    # ---- the approved latch, its local frame turned onto the table
    rot = B.LATCH["rot_deg"]
    disc = np.array(B.LATCH["disc"])
    a0 = disc.copy()
    m167 = interp_track(lead, 167 / FPS)[:2]
    a1 = disc + 0.15 * (m167 - disc)
    eo = _rot(LATCH["eye_off"][:2], rot)
    ao = _rot(LATCH["aim_off"][:2], rot)
    e_l = np.array([eo[0], eo[1], LATCH["eye_off"][2]])
    d_l = np.array([ao[0], ao[1], LATCH["aim_off"][2]]) - e_l
    D_l = float(np.linalg.norm(d_l))
    pitch_l = math.degrees(math.asin(-d_l[2] / D_l))
    yaw_l = math.degrees(math.atan2(d_l[1], d_l[0]))
    # ---- the design's clock onto the bake's (section 4: "the bake replaces it"): piecewise linear through the events
    pts = [(0.0, 0.0), (167.0, 167.0)]
    if "U1" in turns:
        pts.append((342.0, float(turns["U1"]["frame"])))
    if st.get("galley", {}).get("t_quad1"):
        pts.append((432.0, float(st["galley"]["t_quad1"]) * FPS))
    pts.append((935.0, 935.0))
    pts = [p for i, p in enumerate(pts) if i == 0 or (p[0] > pts[i - 1][0] and p[1] > pts[i - 1][1])]
    xs_, ys_ = [p[0] for p in pts], [p[1] for p in pts]

    def W(fd):
        return float(np.interp(fd, xs_, ys_))
    EX = (EXEMPT[0], W(EXEMPT[1]))
    # ---- the crane (frame, distance, pitch down, yaw, f-stop): section 5
    CR_ = [(167, D_l, pitch_l, yaw_l, 4.0), (230, 0.34, 32.0, yaw_l - 8, 4.0), (300, 0.50, 40.0, yaw_l - 19, 4.5),
           (340, 0.60, 45.0, yaw_l - 19, 4.5), (352, 0.60, 45.0, yaw_l - 12, 4.5), (400, 0.50, 50.0, yaw_l, 5.0),
           (430, 1.00, 60.0, 75.0, 5.0), (500, 1.10, 60.0, 85.0, 5.6), (532, 1.25, 82.0, 90.0, 5.6),
           (700, 1.50, 89.0, 90.0, 5.6), (724, 1.50, 89.0, 90.0, 5.6), (760, 1.20, 89.0, 90.0, 5.6),
           (852, 1.60, 89.0, 90.0, 8.0), (935, WIDE_D, 89.0, 90.0, 8.0)]
    CR_ = [(W(k[0]) if k[0] > 167 else k[0],) + tuple(k[1:]) for k in CR_]
    D = np.array([keyed(CR_, t, 1) for t in ts])
    pitch = np.array([keyed(CR_, t, 2) for t in ts])
    yaw = np.array([keyed(CR_, t, 3) for t in ts])
    fstop = np.array([keyed(CR_, t, 4) for t in ts])
    # ---- where the frame wants to be: the file, then each beat's anchor in its window
    fl = front_track(poses, names, np.minimum(ts + LOOKAHEAD, lead[-1][0]))
    rr = front_track(poses, names, np.minimum(ts + LOOKAHEAD, lead[-1][0]), rear=True)
    want = 0.5 * (fl[:, :2] + rr[:, :2])
    lm = np.array([interp_track(lead, min(t + 0.15, lead[-1][0]))[:2] for t in ts])
    anchors = []
    for bank, (fa, fb) in (("U1", (330, 352)), ("U2", (500, 532)), ("U3", (700, 724))):
        if bank in turns and turns[bank]["frame"] > 167:
            anchors.append((W(fa), W(fb), (turns[bank]["x"], turns[bank]["y"])))
    if st.get("khipu"):
        k = np.array(st["khipu"]["knots"])
        anchors.append((W(352), W(430), tuple(k[:, :2].mean(0))))
    g = st.get("galley")
    if g:
        u = np.array([math.cos(math.radians(g["psi"])), math.sin(math.radians(g["psi"]))])
        anchors.append((W(430), W(500), tuple(np.array(g["origin"]) + u * 0.10)))
    b_xy = np.array([st["brass"]["x"], st["brass"]["y"]]) if st.get("brass", {}).get("x") else np.array(B.BRASS["at"])
    for i, f in enumerate(fr):
        ex = bump(f, EX[0] + 37, EX[1], 18.0)                       # tracking the lead itself on beats 2-3
        if ex > 0:
            want[i] = want[i] * (1 - ex) + lm[i] * ex
        for fa, fb, c in anchors:
            w = bump(f, fa, fb, 10.0)
            if w > 0:
                want[i] = want[i] * (1 - w) + np.asarray(c) * w
        if f >= 852:
            # the rise: hold the brass disc through its settle, the centre drifting to the table's centre
            u = smoothstep((f - 852) / (935 - 852))
            want[i] = b_xy + (np.array(TABLE_C) - b_xy) * u
    for (fa, fb, anchor, Dc) in stations(st, poses, names):
        for i, f in enumerate(fr):
            w = bump(f, fa, fb, 12.0)
            if w > 0:
                D[i] = D[i] + (min(Dc, D[i]) - D[i]) * w
                want[i] = want[i] * (1 - w) + np.asarray(anchor) * w
    # ---- the latch: the approved framing exactly, pinned through f167
    locked = fr <= 167
    for i, f in enumerate(fr):
        if f <= 130:
            want[i] = a0
        elif f <= 167:
            want[i] = a0 + (a1 - a0) * smoothstep((f - 130) / (179 - 130))
    phase = np.array(["prefix"] * len(ts), dtype=object)
    # ---- the tail: find (24 held wide, then to the record), descend (a straight dolly down), close
    if tail:
        a_, dsc, c_, d_, tour_ = tail["windows"]
        rec = tail["record"]
        end_c, fw_end = close_pose(rec)
        f_find, f_desc, f_close = 936, 936 + a_, 936 + a_ + dsc
        for i, f in enumerate(fr):
            if f < f_find:
                continue
            pitch[i], fstop[i] = 89.0, 8.0
            yaw[i] = 90.0 + (rec_yaw(rec) - 90.0) * smoothstep((f - f_desc) / dsc)
            if f < f_desc:
                phase[i] = "find"
                D[i] = WIDE_D
                u = smoothstep((f - (f_find + 24)) / max(a_ - 30, 1))
                want[i] = np.array(TABLE_C) + (end_c - np.array(TABLE_C)) * u
            else:
                want[i] = end_c
                locked[i] = True
                phase[i] = "descend" if f < f_close else "close"
                D[i] = WIDE_D + (fw_end / KW - WIDE_D) * smoothstep((f - f_desc) / dsc) if f < f_close else fw_end / KW
    # ---- smooth, then the pan guide (exempt on beats 2-3), measured at the focus plane
    smooth = gauss(want, ts, 0.35)
    smooth[locked] = want[locked]
    fw = KW * D
    fh = KH * D / np.maximum(np.sin(np.radians(pitch)), 0.2)
    cap_x = CAP_X_PX * FPS / 1920 * fw
    cap_y = CAP_Y_PX * FPS / 1080 * fh
    ex = np.array([bump(f, EX[0] + 37, EX[1], 18.0) for f in fr])
    cap_x = cap_x * (1 - ex) + EXEMPT_CAP * ex
    cap_y = cap_y * (1 - ex) + EXEMPT_CAP * ex
    ease = 0.8 * (1 - ex) + 0.45 * ex
    tgt = limit(smooth, ts, cap_x, cap_y, locked=locked, ease_s=ease)
    rows = []
    for i, t in enumerate(ts):
        f = fr[i]
        if f <= 167:
            T = np.array([tgt[i][0], tgt[i][1], 0.010])
            e = T + e_l
            aim = T + np.array([ao[0], ao[1], LATCH["aim_off"][2]])
        else:
            u = smoothstep((f - 167) / 60.0)
            aim = np.array([tgt[i][0], tgt[i][1], 0.010]) + np.array([ao[0], ao[1], LATCH["aim_off"][2]]) * (1 - u)
            e = eye_from(aim, D[i], pitch[i], yaw[i])
        rows.append({"t": round(float(t), 6), "eye": e.tolist(), "target": aim.tolist(), "D": float(D[i]),
                     "pitch": float(pitch[i]), "yaw": float(yaw[i]), "fstop": float(fstop[i]), "phase": str(phase[i])})
    # focus: on the lead marble while it is in frame through the latch and beats 2-3 (the subject stays sharp), else on
    # the target
    for r in rows:
        e = np.array(r["eye"])
        r["focus"] = float(np.linalg.norm(np.array(r["target"]) - e))
        f = r["t"] * FPS
        if f <= W(352):
            m = interp_track(lead, r["t"]) if f >= 121 else np.array([disc[0], disc[1], 0.0015])
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


BEATS = [("0 black", 0, 35), ("1 latch", 36, 167), ("2-3 papyrus, hinge (exempt)", 168, 330), ("U1", 331, 352),
         ("4 cord", 353, 430), ("5 galley", 431, 500), ("U2", 501, 532), ("6 survey, wire, count", 533, 650),
         ("7 reel, type", 651, 700), ("U3", 701, 724), ("8 swell", 725, 852), ("9 exhaust, the rise", 853, 935)]


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
