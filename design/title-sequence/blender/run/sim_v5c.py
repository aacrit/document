"""The Run v5c: the physics proof. One clay marble down the carved channel, MuJoCo, nothing scripted after t = 0.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_v5c.py [--video] [--no-lock]

The table top is a heightfield sampled from channel_v5c.height at 1.5 mm cells (the cove, the banks, the steps, the
release block and the felt well are all elevation). The leather strips are flush box geoms in shallow rebates of the
floor with their own rolling resistance; the felt is a box in the well; the record lies on it. The marble is a 16 mm
sphere at 1900 kg/m3, condim 6. The latch is an initial condition only: the marble at rest in the cup at t = 0 (title
time T_RELEASE); from there gravity and contact decide everything. Timestep 0.5 ms; poses at 240 Hz; contacts at 1 kHz.

Writes D:/document-media/title-sequence/run/sim/v5c/ (bake, contacts, events) and the timing report
D:/document-media/title-sequence/run/layout/v5c-physics.json; with --video, a top-down OpenGL viewer render of the run
(MuJoCo's own renderer, not Cycles) at layout/v5c-physics.mp4. Runs behind HEAVY.lock (one heavy job at a time).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import os  # noqa: E402
if os.environ.get("V5C_CRR_LEATHER"):            # tuning only: the committed value lives in channel_v5c.CRR
    C.CRR["leather"] = float(os.environ["V5C_CRR_LEATHER"])
import eventlog as E  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/sim/v5c")
LAYOUT = Path("D:/document-media/title-sequence/run/layout")
DT = 0.0005
BAKE_HZ = 240
LOG_HZ = 1000
T_MAX = float(__import__("os").environ.get("V5C_TMAX", "45"))
REBATE = 0.0                                # the leather is the facets' own surface (no rebate needed)
SOLREF = "0.002 1"
# torsional (spin) friction, metres: the sliding coefficient times the contact patch radius (about 0.06 mm on oak, more
# on the softer leather and felt). MuJoCo's default (0.005 m) would brake a ball rolling in a cove through its tilted
# contact normals far beyond any real wood.
SPIN = {"oak": 3e-5, "leather": 1e-4, "felt": 5e-4}


def heightfield():
    """(nrow, ncol, data in metres) on the table grid: column c at x = c * CELL, row r at y = r * CELL."""
    W, H = C.TABLE["size"]
    ncol = int(round(W / C.CELL)) + 1
    nrow = int(H / C.CELL) + 1
    xs = np.arange(ncol) * C.CELL
    ys = np.arange(nrow) * C.CELL
    Z = np.zeros((nrow, ncol))
    for r0 in range(0, nrow, 128):
        Y, X = np.meshgrid(ys[r0:r0 + 128], xs, indexing="ij")
        z = C.height(X, Y)
        s, u, k = C.project(X, Y)
        reb = C.on_leather(s, u) & (np.abs(u) <= 0.0016) & np.isfinite(u)
        Z[r0:r0 + 128] = np.where(reb, z - REBATE, z)
    return nrow, ncol, Z


U_KNOTS = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.5, 8.0, 10.0, 12.0, 14.0, 16.5]) / 1000.0


def along_knots():
    """Piece boundaries along the run: long pieces where the floor is a straight line and the section constant; 2 mm
    pieces over the ramp and the steps; 6 mm through the bank transitions; 1 degree of arc in the turns; every
    leather end a boundary."""
    ks = [0.0, C.LENGTH]
    lines = [g for g in C.SEGMENTS if g["kind"] == "line"]
    for g in lines:
        a, b = g["s0"], g["s0"] + g["len"]
        ks += list(np.arange(a, b, 0.25)) + [b]
    ks += list(np.arange(0.0, C.launch_len() + 0.004, 0.002))
    for st in C.STEPS:
        ks += list(np.arange(st["s"] - 0.014, st["s"] + 0.014, 0.002))
    for g in C.SEGMENTS:
        if g["kind"] != "arc":
            continue
        a, b = g["s0"], g["s0"] + g["len"]
        ks += list(np.arange(a - C.BLEND, a, 0.006)) + list(np.arange(b, b + C.BLEND + 1e-9, 0.006))
        ks += list(np.linspace(a, b, int(round(abs(g["a1"] - g["a0"]) / math.radians(1.0))) + 1))
    for lz in C.LEATHER:
        ks += list(lz["s"])
    ks = np.unique(np.round(np.clip(ks, 0.0, C.LENGTH), 7))
    return ks


def _frame(s):
    x, y, h = C.point(s)
    t = np.array([math.cos(h), math.sin(h), 0.0])
    n = np.array([-math.sin(h), math.cos(h), 0.0])           # left of the heading
    return np.array([x, y]), t, n


def facet_boxes():
    """The carved cove as exact box facets (the contact surface): for each piece along the run and each chord of the
    cross-section, a 2 mm thick box whose top face is that chord swept along the piece. Returns dicts with pos, quat
    (w x y z), half sizes and surface ("oak" or "leather")."""
    ks = along_knots()
    us = np.concatenate([-U_KNOTS[:0:-1], U_KNOTS])
    out = []
    th = 0.002
    for sa, sb in zip(ks[:-1], ks[1:]):
        if sb - sa < 1e-6:
            continue
        sm = (sa + sb) / 2
        (pa, ta, na), (pb, tb, nb), (pm, tm, nm) = _frame(sa), _frame(sb), _frame(sm)
        za = C.groove_z(np.full(us.shape, sa), us)
        zb = C.groove_z(np.full(us.shape, sb), us)
        leather = bool(C.on_leather(np.array([sm]))[0])
        for i in range(len(us) - 1):
            if not (np.isfinite(za[i]) and np.isfinite(za[i + 1]) and np.isfinite(zb[i]) and np.isfinite(zb[i + 1])):
                continue
            um = (us[i] + us[i + 1]) / 2
            # the four corners of the facet in the world
            P = []
            for p_, n_, z_ in ((pa, na, za), (pb, nb, zb)):
                for j in (i, i + 1):
                    P.append(np.array([*(p_ + n_[:2] * us[j]), z_[j]]))
            P = np.array(P)                                  # a_i, a_i1, b_i, b_i1
            c = P.mean(0)
            e1 = (P[2] + P[3]) / 2 - (P[0] + P[1]) / 2      # along
            L = float(np.linalg.norm(e1))
            e1 /= L
            e2 = (P[1] + P[3]) / 2 - (P[0] + P[2]) / 2      # across (toward +u)
            w = float(np.linalg.norm(e2))
            e2 -= e1 * float(e2 @ e1)
            e2 /= np.linalg.norm(e2)
            e3 = np.cross(e1, e2)
            if e3[2] < 0:
                e2, e3 = -e2, -e3
            Rm = np.stack([e1, e2, e3], 1)
            q = np.zeros(4)
            mujoco.mju_mat2Quat(q, Rm.ravel())
            pos = c - e3 * th / 2
            surf = "leather" if leather and abs(um) <= C.LEATHER_HALF_W else "oak"
            out.append({"pos": pos, "quat": q, "half": (L / 2 + 0.0002, w / 2 + 0.00005, th / 2), "surface": surf})
    return out


def model_xml(nrow, ncol, zmin, zmax):
    rx, ry = (ncol - 1) * C.CELL / 2, (nrow - 1) * C.CELL / 2
    rz = zmax - zmin
    roll = {k: v * C.R for k, v in C.CRR.items()}
    geoms = []
    for k, f in enumerate(facet_boxes()):
        p, q, h = f["pos"], f["quat"], f["half"]
        rgba = "0.36 0.20 0.10 1" if f["surface"] == "leather" else "0.5 0.35 0.2 0"
        geoms.append(f'<geom name="{f["surface"]} {k}" type="box" size="{h[0]:.6f} {h[1]:.6f} {h[2]:.6f}" '
                     f'pos="{p[0]:.6f} {p[1]:.6f} {p[2]:.7f}" quat="{q[0]:.8f} {q[1]:.8f} {q[2]:.8f} {q[3]:.8f}" '
                     f'rgba="{rgba}" friction="0.6 {SPIN[f["surface"]]:.1e} {roll[f["surface"]]:.3e}" condim="6" solref="{SOLREF}"/>')
    # the cup's round back wall, so the latch's side of the cup is solid
    x0, y0, _ = C.point(0.0)
    geoms.append(f'<geom name="oak cup wall" type="box" size="0.002 0.012 0.008" pos="{x0 - C.R - 0.0021:.6f} {y0:.6f} '
                 f'{float(C.floor_z(0.0)) + 0.008:.6f}" rgba="0 0 0 0" condim="3"/>')
    # the well's walls (the marble should never reach them)
    wx, wy = C.WELL["x"], C.WELL["y"]
    for nm, sx, sy, cx, cy in (("far", 0.002, (wy[1] - wy[0]) / 2, wx[1] + 0.002, (wy[0] + wy[1]) / 2),
                               ("back", (wx[1] - wx[0]) / 2, 0.002, (wx[0] + wx[1]) / 2, wy[1] + 0.002),
                               ("front", (wx[1] - wx[0]) / 2, 0.002, (wx[0] + wx[1]) / 2, wy[0] - 0.002)):
        geoms.append(f'<geom name="oak well {nm}" type="box" size="{sx:.5f} {sy:.5f} 0.015" pos="{cx:.5f} {cy:.5f} '
                     f'{C.felt_top() + 0.012:.5f}" rgba="0 0 0 0" condim="3"/>')
    wx, wy = C.WELL["x"], C.WELL["y"]
    ft = C.felt_top()
    geoms.append(f'<geom name="felt" type="box" size="{(wx[1] - wx[0]) / 2:.5f} {(wy[1] - wy[0]) / 2:.5f} '
                 f'{C.WELL["felt_t"] / 2:.5f}" pos="{(wx[0] + wx[1]) / 2:.5f} {(wy[0] + wy[1]) / 2:.5f} '
                 f'{ft - C.WELL["felt_t"] / 2:.6f}" rgba="0.03 0.03 0.03 1" friction="0.9 {SPIN["felt"]:.1e} {roll["felt"]:.3e}" '
                 f'condim="6" solref="0.004 1"/>')
    r = C.ITEMS["record"]["rect"]
    geoms.append(f'<geom name="record" type="box" size="{(r[1] - r[0]) / 2:.5f} {(r[3] - r[2]) / 2:.5f} 0.00006" '
                 f'pos="{(r[0] + r[1]) / 2:.5f} {(r[2] + r[3]) / 2:.5f} {ft + 0.00006:.6f}" rgba="0.9 0.88 0.8 1" '
                 f'friction="0.5 {SPIN["oak"]:.1e} {roll["oak"]:.3e}" condim="6" solref="{SOLREF}"/>')
    s_start = 0.006
    x0, y0, _ = C.point(s_start)
    z0 = float(C.floor_z(s_start)) + C.R + 0.00002
    W, H = C.TABLE["size"]
    return f"""<mujoco model="the run v5c">
  <compiler angle="radian"/>
  <option timestep="{DT}" gravity="0 0 -{C.G}" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <visual><global offwidth="1280" offheight="720"/><quality shadowsize="4096"/>
    <headlight ambient="0.35 0.35 0.35" diffuse="0.6 0.6 0.6"/></visual>
  <asset><hfield name="top" nrow="{nrow}" ncol="{ncol}" size="{rx:.6f} {ry:.6f} {rz:.6f} 0.02"/></asset>
  <worldbody>
    <light pos="1.55 2.02 3.0" dir="0 -0.3 -1" directional="false" diffuse="0.5 0.5 0.5"/>
    <camera name="top" pos="{W / 2} {H / 2} 3.0" xyaxes="1 0 0 0 1 0" fovy="{math.degrees(2 * math.atan(0.93 / 3.0)):.3f}"/>
    <geom name="oak top (visual)" type="hfield" hfield="top" pos="{rx:.6f} {ry:.6f} {zmin:.7f}" rgba="0.55 0.38 0.22 1" contype="0" conaffinity="0"
          friction="0.5 0.002 {roll['oak']:.3e}" condim="6" solref="{SOLREF}"/>
    {chr(10).join('    ' + g for g in geoms)}
    <body name="marble" pos="{x0:.6f} {y0:.6f} {z0:.7f}">
      <freejoint/>
      <geom name="marble" type="sphere" size="{C.R}" density="{C.RHO_CLAY}" rgba="0.80 0.45 0.25 1"
            friction="0.5 0 0" condim="6" solref="{SOLREF}"/>
    </body>
  </worldbody>
</mujoco>"""


def surface_of(s, u, z_marble):
    if s > C.LENGTH + 0.004:
        return "felt"
    if C.on_leather(np.array([s]), np.array([u]))[0]:
        return "leather"
    return "oak"


def run(m, d):
    mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "marble")
    gname = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or f"g{i}" for i in range(m.ngeom)]
    per_log = int(round(1 / (LOG_HZ * DT)))
    poses, contacts, track = [], [], []
    f6 = np.zeros(6)
    next_bake = 0.0
    still_since = None
    k = 0
    while d.time < T_MAX:
        t = d.time
        if t >= next_bake - 1e-9:
            p = d.xpos[mid].copy()
            q = d.xquat[mid].copy()
            v = d.qvel[:3].copy()
            poses.append([round(t, 6), *map(float, p), *map(float, q)])
            s, u, kk = C.project(np.array([p[0]]), np.array([p[1]]))
            s, u = float(s[0]), float(u[0])
            if p[0] > C.LIP_X - 1e-4:                    # past the lip: measured on into the well along the line
                s, u = C.LENGTH + float(p[0] - C.LIP_X), float(p[1] - C.REACH_Y[2])
            track.append([round(t, 5), s, u if np.isfinite(u) else None, float(np.linalg.norm(v)), float(p[2])])
            next_bake += 1 / BAKE_HZ
        if k % per_log == 0:
            for ci in range(d.ncon):
                c = d.contact[ci]
                mujoco.mj_contactForce(m, d, ci, f6)
                n = np.array(c.frame[:3])
                vb = np.zeros(6)
                mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, mid, vb, 0)
                vel = vb[3:] + np.cross(vb[:3], np.array(c.pos) - d.xpos[mid])
                sgn = 1.0 if m.geom_bodyid[c.geom2] == mid else -1.0
                contacts.append({"t_s": round(t, 4), "pair": "|".join(sorted((gname[c.geom1], gname[c.geom2]))),
                                 "v_n": float(-sgn * np.dot(vel, n)), "f_n": float(f6[0])})
        speed = float(np.linalg.norm(d.qvel[:3]))
        if speed < 0.001 and d.xpos[mid][0] > C.LIP_X:
            still_since = t if still_since is None else still_since
            if t - still_since > 0.5:
                break
        else:
            still_since = None
        mujoco.mj_step(m, d)
        k += 1
    return poses, contacts, track, (still_since if still_since is not None else d.time)


def events_from_track(track, t_rest):
    """The run's own events, read off the trajectory: surface changes, the steps, the turns, speed extrema, the lip,
    the felt, the rest. Title time = sim time + T_RELEASE."""
    T = np.array([r[0] for r in track])
    S = np.array([r[1] for r in track])
    U = np.array([r[2] if r[2] is not None else np.nan for r in track])
    V = np.array([r[3] for r in track])
    ev = [{"t": 0.0, "event": "latch opens: the marble leaves the cup"}]
    prev = "oak"
    for i in range(1, len(T)):
        cur = "felt" if S[i] > C.LENGTH + 0.004 else ("leather" if C.on_leather(np.array([S[i]]))[0] else "oak")
        if cur != prev:
            name = ""
            if cur == "leather":
                name = [lz["name"] for lz in C.LEATHER if lz["s"][0] - 0.01 <= S[i] <= lz["s"][1]][0]
            ev.append({"t": float(T[i]), "event": f"onto {cur}" + (f" ({name})" if name else ""), "s": float(S[i]),
                       "v": float(V[i])})
            prev = cur
    for st in C.STEPS:
        i = int(np.searchsorted(S, st["s"]))
        if i < len(T):
            ev.append({"t": float(T[i]), "event": st["name"], "s": float(S[i]), "v": float(V[i])})
    for sg in C.SEGMENTS:
        if sg["kind"] != "arc":
            continue
        a, b = sg["s0"], sg["s0"] + sg["len"]
        ia, ib = int(np.searchsorted(S, a)), int(np.searchsorted(S, b))
        if ib <= ia:
            continue
        uu = np.abs(U[ia:ib])
        j = ia + int(np.nanargmax(uu))
        ev.append({"t": float(T[ia]), "event": f"into {sg['name']} (bank)", "s": a, "v": float(V[ia])})
        ev.append({"t": float(T[j]), "event": f"{sg['name']}: highest on the outer wall", "u_mm": float(uu.max() * 1000),
                   "v": float(V[j])})
        ev.append({"t": float(T[ib]), "event": f"out of {sg['name']}", "s": b, "v": float(V[ib])})
    i = int(np.searchsorted(S, C.LENGTH))
    if i < len(T):
        ev.append({"t": float(T[i]), "event": "over the lip onto the felt", "v": float(V[i])})
    run_ = (S < C.LENGTH) & (T > 0.5)
    if run_.any():
        j = int(np.argmax(np.where(run_, V, -1)))
        ev.append({"t": float(T[j]), "event": "fastest", "v": float(V[j])})
        j = int(np.argmin(np.where(run_, V, 9)))
        ev.append({"t": float(T[j]), "event": "slowest (on the run)", "v": float(V[j])})
    ev.append({"t": float(t_rest), "event": "at rest on the felt"})
    for e in ev:
        e["title_t"] = round(e["t"] + C.T_RELEASE, 3)
        e["frame_24"] = round(e["title_t"] * 24, 1)
    return sorted(ev, key=lambda e: e["t"])


def video(m, poses, path):
    """A cheap top-down viewer render (MuJoCo OpenGL), 24 fps, the marble's trail drawn by the renderer's own frames."""
    d = mujoco.MjData(m)
    r = mujoco.Renderer(m, 720, 1280)
    P = np.array(poses)
    n = int(P[-1, 0] * 24) + 24
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720",
                           "-r", "24", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(path)],
                          stdin=subprocess.PIPE)
    trail = []
    from PIL import Image, ImageDraw
    for f in range(n):
        t = min(f / 24, P[-1, 0])
        i = min(int(np.searchsorted(P[:, 0], t)), len(P) - 1)
        d.qpos[:3] = P[i, 1:4]
        d.qpos[3:7] = P[i, 4:8]
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera="top")
        img = Image.fromarray(r.render())
        dr = ImageDraw.Draw(img)
        trail.append(P[i, 1:3])
        # the trail and the clock, drawn over the viewer frame (engineering proof, not the film)
        cam_h, fov = 3.0, 2 * math.atan(0.93 / 3.0)
        sc = 720 / (2 * cam_h * math.tan(fov / 2))
        W, H = C.TABLE["size"]
        pts = [(640 + (x - W / 2) * sc, 360 - (y - H / 2) * sc) for x, y in trail[::2]]
        if len(pts) > 1:
            dr.line(pts, fill=(237, 226, 207), width=1)
        dr.text((16, 12), f"t {t + C.T_RELEASE:5.2f} s (title)   sim {t:5.2f} s", fill=(237, 226, 207))
        ff.stdin.write(img.tobytes())
    ff.stdin.close()
    ff.wait()
    r.close()


def main():
    use_lock = "--no-lock" not in sys.argv
    if use_lock:
        import render_still_v5 as RL
        RL.take_lock("v5c physics proof (MuJoCo, CPU)")
    try:
        t0 = time.time()
        nrow, ncol, Z = heightfield()
        zmin, zmax = float(Z.min()), float(Z.max())
        m = mujoco.MjModel.from_xml_string(model_xml(nrow, ncol, zmin, zmax))
        m.hfield_data[:] = ((Z - zmin) / (zmax - zmin)).astype(np.float32).ravel()
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        # orientation check: a ray onto the groove floor at a reach must find the floor, not the top
        x, y, _ = C.point(1.0)
        geomid = np.zeros(1, np.int32)
        dist = mujoco.mj_ray(m, d, np.array([x, y + 0.03, 0.2]), np.array([0, 0, -1.0]), None, 1, -1, geomid)
        dist2 = mujoco.mj_ray(m, d, np.array([x, y, 0.2]), np.array([0, 0, -1.0]), None, 1, -1, geomid)
        assert abs((0.2 - dist) - 0.0) < 0.0005 and abs((0.2 - dist2) - float(C.floor_z(1.0))) < 0.0012, (dist, dist2)
        t_build = time.time() - t0
        poses, contacts, track, t_rest = run(m, d)
        t_sim = time.time() - t0 - t_build
        OUT.mkdir(parents=True, exist_ok=True)
        E.write_jsonl(contacts, OUT / "run-contacts-1khz.jsonl")
        cev = E.events(contacts, t_offset=C.T_RELEASE)
        E.write_jsonl(cev, OUT / "run-contact-events.jsonl")
        (OUT / "run-bake.json").write_text(json.dumps({"meta": {"t_release": C.T_RELEASE, "bake_hz": BAKE_HZ,
                                                                 "frame": "table, top z = 0", "dt": DT},
                                                        "poses": {"marble": poses}, "track": track}), encoding="utf-8")
        ev = events_from_track(track, t_rest)
        S = np.array([r[1] for r in track])
        V = np.array([r[3] for r in track])
        U = np.array([abs(r[2]) if r[2] is not None else np.nan for r in track])
        Tt = np.array([r[0] for r in track])
        final = poses[-1]
        rec = C.ITEMS["record"]["rect"]
        on_run = (S < C.LENGTH) & (Tt > 0.5)
        title_rest = t_rest + C.T_RELEASE
        total = title_rest + C.RUNTIME["arrive"]
        rep = {
            "what": "The Run v5c physics proof: MuJoCo heightfield channel, one clay marble, nothing scripted after t=0",
            "mujoco": mujoco.__version__, "timestep_s": DT, "cell_m": C.CELL, "hfield": [nrow, ncol],
            "crr": C.CRR, "rolling_length_m": {k: v * C.R for k, v in C.CRR.items()},
            "path_m": C.LENGTH, "release_title_s": C.T_RELEASE, "rest_sim_s": round(t_rest, 3),
            "rest_title_s": round(title_rest, 3), "title_total_s": round(total, 3),
            "window_s": [C.RUNTIME["min"], C.RUNTIME["max"]],
            "margin_s": {"to_min": round(total - C.RUNTIME["min"], 2), "to_max": round(C.RUNTIME["max"] - total, 2)},
            "rest_xy": [round(final[1], 4), round(final[2], 4)],
            "rest_into_felt_m": round(final[1] - C.LIP_X, 4),
            "clear_of_record_m": round(rec[0] - (final[1] + C.R), 4),
            "in_well": bool(C.WELL["x"][0] < final[1] < C.WELL["x"][1] and C.WELL["y"][0] < final[2] < C.WELL["y"][1]),
            "v_max": round(float(V[on_run].max()), 4), "v_min_on_run": round(float(V[on_run & (Tt > 1.0)].min()), 4),
            "max_lateral_mm": round(float(np.nanmax(U[on_run])) * 1000, 2),
            "reached_felt": bool(S.max() > C.LENGTH), "record_touched": any("record" in c["pair"] for c in contacts),
            "events": ev, "n_contact_events": len(cev), "build_s": round(t_build, 1), "sim_wall_s": round(t_sim, 1),
            "design_1d_rest_s": round(C.roll_1d()["t_rest"], 2), "plan_notes": C.PLAN_NOTES,
        }
        LAYOUT.mkdir(parents=True, exist_ok=True)
        (LAYOUT / "v5c-physics.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        (OUT / "run-timing.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print("V5C-SIM " + json.dumps({k: rep[k] for k in ("rest_title_s", "title_total_s", "margin_s", "rest_xy",
                                                            "rest_into_felt_m", "clear_of_record_m", "v_max",
                                                            "v_min_on_run", "max_lateral_mm", "reached_felt",
                                                            "record_touched", "sim_wall_s", "design_1d_rest_s")}))
        if "--video" in sys.argv and rep["reached_felt"]:
            video(m, poses, LAYOUT / "v5c-physics.mp4")
            print("video", LAYOUT / "v5c-physics.mp4")
    finally:
        if use_lock:
            RL.drop_lock()


if __name__ == "__main__":
    main()
