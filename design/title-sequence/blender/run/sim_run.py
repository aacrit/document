"""The Run v4: the labyrinth as one chain. One continuous MuJoCo simulation on the table of bench.py, from the bronze
disc's settle to the marbles' rest at each film's record (runs in the D: venv, D:/document-media/tools/run-venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_run.py [--fall 1.0]
        [--films C20-METAR-0851,...] [--resume N] [--prefix-only]

The table is the composed heightfield of relief.py (world.npz), cut into one MuJoCo hfield per topmost surface (each with
its own rolling resistance), over the oak's plane: the sheets' thickness, cockle troughs, curls, lifts, the Atlas's
hinge valley and Ino's crease are geometry, so every turn is the records' own relief. Gravity is tilted by the fall
(bench.FALL_DEG along +x, the one tuning knob); the approved latch's 2.5 degree zone runs along the release heading.
The approved latch opens it unchanged in its own local frame, turned and placed on the table (bench.latch_to_table):
the bronze disc analytic (moffatt.py) and driven into MuJoCo as a moving collider.

Props are placed by roll-out (a copy of the state stepped ahead, nothing kept), as the design allows: the knots beside
the lead's line, the galley's mouth on its leg at 12 degrees, the reels' rims at an impact parameter of 0.6, the card,
the 35 mm strip and the platen across or beside the line, the lattice's entry within 5 cm, the brass disc on the line,
and in each tail the record's near edge 7 mm before the lead's free stop. Then the real state is stepped through them.

Contacts are stiff (dt 0.25 ms, solref 1 ms): a soft contact presses the marble into the heightfield's triangle seams
and adds a speed-dependent drag (measured, work/v4proto: 20% of the speed lost over 4 s at 2 mm cells); stiff, the
heightfield rolls within 2% of an analytic plane.

Writes D:/document-media/title-sequence/run/sim/v4/run-{bake.json,layout.json,events.jsonl,contacts-1khz.jsonl,
checks.json} and per film run-tail-<record>-{bake.json,events.jsonl}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import eventlog as E  # noqa: E402
import moffatt as MF  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/sim/v4")
WORK = Path("D:/document-media/title-sequence/run/work/v4")
RELIEF = Path("D:/document-media/title-sequence/run/relief")
TEX = Path("D:/document-media/title-sequence/tex")
DT = 0.00025
T0 = 2.5                                    # the latch's simulated start (the proof's), title seconds
R = B.R
PARK = (-3.0, -3.0)
QUAD = B.QUAD
QM = 10400 * 8 * QUAD[0] * QUAD[1] * QUAD[2]
N_Q = 12
GAPS = np.linspace(0.014, 0.008, N_Q)
FLOOR_T = 0.0005
RAMP_L = 0.020 + B.GALLEY["mouth_widen"]
STEP_H = 0.003
STOP = (0.0012, 0.026, 0.01015)
STOP_M = 8400 * 8 * STOP[0] * STOP[1] * STOP[2]
STOP_Y = 0.018
PAIR_Y = (0.0175, 0.0345)
LEAD_LINE_Y = -0.0068
LEAF_EDGE_LOCAL = 0.222
FREE = ["lead", "pair1", "pair2"] + [f"quad{i + 1}" for i in range(N_Q)] + ["stop", "brass"]
HINGED = ["reel_reg", "reel_film"]
MARBLES = ["lead", "pair1", "pair2"]
SURF = {"papyrus": "papyrus", "atlas1": "vellum", "atlas2": "vellum", "piri": "parchment", "leaf": "leaf",
        "ino": "washi", "page": "page", "chart": "chart"}
B_IMPACT = 0.6                              # the reels' glance (design: 0.5 to 0.6, at least 0.45)


def tf(frame):
    return frame / B.FPS


def qz(deg):
    a = math.radians(deg) / 2
    return (math.cos(a), 0.0, 0.0, math.sin(a))


def qy(rad):
    return (math.cos(rad / 2), 0.0, math.sin(rad / 2), 0.0)


def qx(rad):
    return (math.cos(rad / 2), math.sin(rad / 2), 0.0, 0.0)


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def fr(surface, slide=0.5):
    return f"{slide} 0.0005 {B.RR[surface] * R:.3e}"


def hdg(v):
    return math.degrees(math.atan2(v[1], v[0]))


# ------------------------------------------------------------------------------------------------ the table


class World:
    """The composed table top (relief.py), sampled where props stand, and cut into per-surface hfields."""

    def __init__(self):
        w = np.load(RELIEF / "world.npz")
        self.top, self.sid = w["top"], w["sid"]
        self.x0, self.y0, self.tx = float(w["x0"]), float(w["y0"]), float(w["texel"])
        self.names = [str(s) for s in w["surfaces"]]

    def z(self, x, y):
        i = int(np.clip((x - self.x0) / self.tx, 0, self.top.shape[1] - 1))
        j = int(np.clip((y - self.y0) / self.tx, 0, self.top.shape[0] - 1))
        return float(self.top[j, i])

    def zmax(self, x, y, r):
        """The highest point of the table top within radius r of (x, y): what a prop's base rests on."""
        n = int(r / self.tx) + 1
        i = int((x - self.x0) / self.tx)
        j = int((y - self.y0) / self.tx)
        return float(self.top[max(0, j - n):j + n + 1, max(0, i - n):i + n + 1].max())

    def surface(self, x, y):
        i = int(np.clip((x - self.x0) / self.tx, 0, self.top.shape[1] - 1))
        j = int(np.clip((y - self.y0) / self.tx, 0, self.top.shape[0] - 1))
        return self.names[int(self.sid[j, i])]

    def hfields(self):
        """One hfield per surface over the cells where it is topmost on the table (x 0..2.2, y 0..1.0), 3 cells
        of margin; elsewhere in its box 3 mm below the true top, so the neighbouring surface carries the marble."""
        WORK.mkdir(parents=True, exist_ok=True)
        W, H = B.TABLE["size"]
        i0, i1 = int((0 - self.x0) / self.tx), int((W - self.x0) / self.tx)
        j0, j1 = int((0 - self.y0) / self.tx), int((H - self.y0) / self.tx)
        top, sid = self.top[j0:j1, i0:i1], self.sid[j0:j1, i0:i1]
        out = {}
        for k, name in enumerate(self.names):
            if name == "oak":
                continue
            m = sid == k
            if not m.any():
                continue
            js, is_ = np.nonzero(m)
            a, b = max(js.min() - 3, 0), min(js.max() + 4, top.shape[0])
            c, d = max(is_.min() - 3, 0), min(is_.max() + 4, top.shape[1])
            hf = np.where(m[a:b, c:d], top[a:b, c:d], top[a:b, c:d] - 0.003).astype(np.float32)
            lo, hi = float(hf.min()), float(hf.max())
            data = hf.tobytes()
            p = WORK / f"hf-{name}-{hashlib.sha1(data).hexdigest()[:12]}.bin"     # MuJoCo caches assets by path
            if not p.exists():
                p.write_bytes(struct.pack("ii", hf.shape[0], hf.shape[1]) + data)
            xa = self.x0 + (i0 + c + 0.5) * self.tx
            xb = self.x0 + (i0 + d - 1 + 0.5) * self.tx
            ya = self.y0 + (j0 + a + 0.5) * self.tx
            yb = self.y0 + (j0 + b - 1 + 0.5) * self.tx
            out[name] = {"file": str(p).replace("\\", "/"), "size": ((xb - xa) / 2, (yb - ya) / 2, max(hi - lo, 1e-6), 0.004),
                         "pos": ((xa + xb) / 2, (ya + yb) / 2, lo), "surface": SURF[name]}
        return out


# ------------------------------------------------------------------------------------------------ the galley (M1's)


def galley_local():
    xs, x = [], 0.0
    for i in range(N_Q):
        xs.append(x)
        x += 2 * QUAD[0] + GAPS[i]
    x_stop = xs[-1] + QUAD[0] + GAPS[-1] + STOP[0]
    lip = x_stop + STOP[0]
    return {"quad_x": xs, "stop_x": x_stop, "lip_x": lip, "galley": {"x": (-0.05, lip + 0.035), "y": (-0.03, 0.06)},
            "step_a": {"x": (xs[-1] + QUAD[0] + 0.001, lip), "y": (STOP_Y - STOP[1], 0.008)},
            "step_b": {"x": (lip - 0.045, lip), "y": (0.008, STOP_Y + STOP[1])},
            "pair": [(lip - 2 * STOP[0] - R - 0.0003, PAIR_Y[0]), (lip - 2 * STOP[0] - R - 0.0003, PAIR_Y[1])]}


# ------------------------------------------------------------------------------------------------ the run


class Run:
    def __init__(self, fall):
        self.fall = fall
        self.world = World()
        self.geoms: dict[str, dict] = {}
        self.hfields = self.world.hfields()
        self.hinge_pos = {h: (PARK[0] - 0.2 * i, PARK[1], 0.0) for i, h in enumerate(HINGED)}
        self.layout: dict = {"stations": {}, "fall_deg": fall}
        self.contacts: list[dict] = []
        self.poses: dict[str, list] = {b: [] for b in FREE + HINGED + ["disc"]}
        self.next_bake = None
        self.brass_hand = None
        self.brass_watch = False
        self.v = SimpleNamespace()
        self.m = self.d = None
        self.add("oak", {"type": "plane", "size": (5, 5, 0.1), "pos": (1.1, 0.5, 0), "friction": fr("oak", 0.45)})
        for name, h in self.hfields.items():
            self.add(f"hf_{name}", {"type": "hfield", "hfield": name, "pos": h["pos"], "friction": fr(h["surface"])})
        t = B.TABLET
        self.add("tablet", {"type": "box", "size": (t["size"][0] / 2, t["size"][1] / 2, t["size"][2] / 2),
                            "pos": (t["centre"][0], t["centre"][1], t["size"][2] / 2), "quat": qz(t["psi"]),
                            "friction": "0.6 0.001 0.0001"})
        # the approved fall ran along the latch's local +x (the release then heads 6.5 degrees right of it)
        a = math.radians(B.LATCH["rot_deg"])
        self.hd = np.array([math.cos(a), math.sin(a)])

    # -------------------------------------------------------------- model

    def add(self, name, spec):
        spec.setdefault("quat", (1, 0, 0, 0))
        spec.setdefault("condim", 6)
        self.geoms[name] = spec

    def obox(self, name, c, half, psi, z0, z1, friction, ghost=False):
        """A box on the table: centre (x, y), half extents (along its own x, y), turned psi, from z0 to z1."""
        self.add(name, {"type": "box", "size": (half[0], half[1], (z1 - z0) / 2), "pos": (c[0], c[1], (z0 + z1) / 2),
                        "quat": qz(psi), "friction": friction, "ghost": ghost})

    def xml(self):
        g = []
        for n, s in self.geoms.items():
            extra = ""
            if s["type"] == "hfield":
                extra = f' hfield="{s["hfield"]}"'
            else:
                extra = f' size="{" ".join(f"{v:.7g}" for v in s["size"])}"'
            ghost = ' contype="0" conaffinity="0"' if s.get("ghost") else ""
            g.append(f'<geom name="{n}" type="{s["type"]}"{extra} pos="{" ".join(f"{v:.7g}" for v in s["pos"])}" '
                     f'quat="{" ".join(f"{v:.9g}" for v in s["quat"])}" friction="{s["friction"]}" condim="{s["condim"]}"{ghost}/>')
        assets = "".join(f'<hfield name="{n}" file="{h["file"]}" size="{" ".join(f"{v:.7g}" for v in h["size"])}"/>'
                         for n, h in self.hfields.items())
        free = []
        for i, b in enumerate(FREE):
            px, py = PARK[0] - 0.06 * i, PARK[1]
            if b in MARBLES:
                mass = B.MASS if b == "lead" else B.MASS_PAIR
                geom = f'<geom name="{b}" type="sphere" size="{R}" mass="{mass}" friction="0.4 0.0002 1e-7" condim="6"/>'
                z = R
            elif b.startswith("quad"):
                geom = (f'<geom name="{b}" type="box" size="{QUAD[0]} {QUAD[1]} {QUAD[2]}" mass="{QM}" '
                        f'friction="0.3 0.002 0.0001" condim="4"/>')
                z = QUAD[2]
            elif b == "stop":
                geom = (f'<geom name="stop" type="box" size="{STOP[0]} {STOP[1]} {STOP[2]}" mass="{STOP_M}" '
                        f'friction="0.6 0.002 0.0001" condim="4"/>')
                z = STOP[2]
            else:
                bm = B.BRASS["rho"] * math.pi * B.BRASS["A"] ** 2 * 2 * B.BRASS["T"]
                geom = (f'<geom name="brass" type="cylinder" size="{B.BRASS["A"]} {B.BRASS["T"]}" mass="{bm}" '
                        f'friction="0.3 0.001 {B.RR["brass"] * R:.3e}" condim="6"/>')
                z = B.BRASS["T"]
            free.append(f'<body name="{b}" pos="{px} {py} {z}"><freejoint/>{geom}</body>')
        hinged = []
        for h in HINGED:
            p = B.REEL_REG if h == "reel_reg" else B.REEL_FILM
            hp = self.hinge_pos[h]
            # the reel: its flange disc (rim) on a hub; the hub stands on the paper, the flange 2 mm above it
            hinged.append(f'<body name="{h}" pos="{hp[0]} {hp[1]} {hp[2]}">'
                          f'<joint name="{h}" type="hinge" axis="0 0 1" damping="{p["damp"]}" frictionloss="{p["fric"]}"/>'
                          f'<geom name="{h}" type="cylinder" size="{p["r"]} {p["h"] / 2}" pos="0 0 {p["h"] / 2 + 0.0005}" '
                          f'mass="{p["mass"]}" friction="0.3 0.001 0.0001" condim="4"/></body>')
        th = math.radians(self.fall)
        return f"""
<mujoco model="the run v4">
  <compiler angle="radian"/>
  <option timestep="{DT}" gravity="{B.G * math.sin(th):.7f} 0 {-B.G * math.cos(th):.7f}" integrator="implicitfast"
          cone="elliptic" impratio="10"/>
  <default><geom solref="0.001 1" solimp="0.95 0.99 0.0005"/></default>
  <asset>{assets}</asset>
  <worldbody>
    {"".join(g)}
    <body name="disc" mocap="true" pos="{PARK[0]} {PARK[1]} {MF.T / 2}">
      <geom name="disc" type="cylinder" size="{MF.A} {MF.T / 2}" friction="0.3 0.0005 {B.RR['bronze'] * R:.3e}" condim="6"/>
    </body>
    {"".join(free)}
    {"".join(hinged)}
  </worldbody>
</mujoco>"""

    def compile(self, first=False):
        m = mujoco.MjModel.from_xml_string(self.xml())
        d = mujoco.MjData(m)
        if not first and self.d is not None:
            old = self.d
            d.time = old.time
            d.qpos[:] = old.qpos
            d.qvel[:] = old.qvel
            d.qacc_warmstart[:] = old.qacc_warmstart
            d.mocap_pos[:] = old.mocap_pos
            d.mocap_quat[:] = old.mocap_quat
            # a hinged reel moved by a re-lay starts still at its new place (its joint angle is kept)
        self.m, self.d = m, d
        mujoco.mj_forward(m, d)
        self.bid = {b: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b) for b in FREE + HINGED + ["disc"]}
        self.mass = {b: float(m.body_subtreemass[self.bid[b]]) for b in FREE}
        self.gname = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or f"g{i}" for i in range(m.ngeom)]
        self._disc_mid = m.body_mocapid[self.bid["disc"]]

    def place_free(self, name, pos, quat=(1, 0, 0, 0)):
        j = self.m.body_jntadr[self.bid[name]]
        a, v = self.m.jnt_qposadr[j], self.m.jnt_dofadr[j]
        self.d.qpos[a:a + 3] = pos
        self.d.qpos[a + 3:a + 7] = quat
        self.d.qvel[v:v + 6] = 0
        mujoco.mj_forward(self.m, self.d)

    # -------------------------------------------------------------- the latch's zone and the disc

    def apply(self, m, d):
        """The approved 2.5 degree fall by the disc, along the release heading, to the papyrus's edge: the extra over
        the table's own fall, on the marbles inside the zone."""
        d.xfrc_applied[:] = 0
        # local falls (bench.FALL_ZONES): the extra over the table's own fall, smoothly to the zone's edge
        for z in B.FALL_ZONES:
            c = np.array(z["centre"])
            extra = math.sin(math.radians(z["deg"])) - math.sin(math.radians(self.fall))
            for b in FREE:
                i = self.bid[b]
                rr = float(np.linalg.norm(d.xpos[i][:2] - c))
                if rr < z["r"]:
                    w = 1.0 if rr < 0.7 * z["r"] else (z["r"] - rr) / (0.3 * z["r"])
                    d.xfrc_applied[i, 0] += self.mass[b] * B.G * extra * w
        dz = np.array(B.LATCH["disc"])
        for b in MARBLES:
            i = self.bid[b]
            p = d.xpos[i][:2] - dz
            s = float(p @ self.hd)
            if -0.06 <= s <= B.LATCH["zone_len"] and abs(p[0] * self.hd[1] - p[1] * self.hd[0]) < 0.12:
                mg = self.mass[b] * B.G
                f = mg * math.sin(math.radians(B.LATCH["fall_deg"])) * self.hd
                f -= mg * math.sin(math.radians(self.fall)) * np.array([1.0, 0.0])
                d.xfrc_applied[i, 0:2] += f

    def disc_pose(self, t):
        p = MF.pose(t)
        n, u = np.array(p["normal"]), np.array(p["u"])
        w = np.cross(n, u)
        if t < MF.T_SLAP:
            ps = MF.spin(t, T0, n=200)
        else:
            if not hasattr(self, "_psi_slap"):
                self._psi_slap = MF.spin(MF.T_SLAP, T0, n=2000)
            ps = self._psi_slap
        c, s = math.cos(ps), math.sin(ps)
        u2, w2 = c * u + s * w, -s * u + c * w
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, np.array([u2, w2, n]).T.ravel())
        # the approved latch's local frame onto the table
        qr = np.array(qz(B.LATCH["rot_deg"]))
        q2 = np.zeros(4)
        mujoco.mju_mulQuat(q2, qr, q)
        cx, cy = B.latch_to_table(p["centre"][:2])
        return np.array([cx, cy, p["centre"][2]]), q2

    def drive(self, d, t):
        if t > MF.T_SLAP + 0.6:
            return {}
        c, q = self.disc_pose(t)
        c2, q2 = self.disc_pose(t + 1e-4)
        d.mocap_pos[self._disc_mid] = c
        d.mocap_quat[self._disc_mid] = q
        qc, qd, dq = np.zeros(4), np.zeros(4), np.zeros(3)
        mujoco.mju_negQuat(qc, q)
        mujoco.mju_mulQuat(qd, q2, qc)
        mujoco.mju_quat2Vel(dq, qd, 1e-4)
        return {self.bid["disc"]: ((c2 - c) / 1e-4, dq, c)}

    # -------------------------------------------------------------- stepping (1 ms a tick)

    def _ms(self, m, d, mv):
        self.apply(m, d)
        for _ in range(4):
            mv = (self.drive(d, d.time + DT) or mv) if d.time < MF.T_SLAP + 0.6 else {}
            mujoco.mj_step(m, d)
        return mv

    def _vel_at(self, m, d, bid, p, mv):
        if bid in mv:
            lin, ang, origin = mv[bid]
            return lin + np.cross(ang, p - origin)
        res = np.zeros(6)
        mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, bid, res, 0)
        return res[3:] + np.cross(res[:3], p - d.xpos[bid])

    def scan(self, m, d, mv, out):
        f6 = np.zeros(6)
        for ci in range(d.ncon):
            c = d.contact[ci]
            p = np.array(c.pos)
            if p[0] < -1.0:
                continue
            mujoco.mj_contactForce(m, d, ci, f6)
            n = np.array(c.frame[:3])
            b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
            v = self._vel_at(m, d, b2, p, mv) - self._vel_at(m, d, b1, p, mv)
            out.append({"t_s": round(d.time, 4), "pair": "|".join(sorted((self.gname[c.geom1], self.gname[c.geom2]))),
                        "v_n": float(-np.dot(v, n)), "f_n": float(f6[0])})

    def advance(self, t_end):
        m, d = self.m, self.d
        mv = {}
        while d.time < t_end - 1e-9:
            mv = self._ms(m, d, mv)
            self.scan(m, d, mv, self.contacts)
            if self.brass_watch:
                self.watch_brass()
            if d.time >= self.next_bake - 1e-9:
                t = round(d.time, 6)
                for b in self.poses:
                    i = self.bid[b]
                    if d.xpos[i][0] > -1.0:
                        self.poses[b].append([t] + [float(v) for v in d.xpos[i]] + [float(v) for v in d.xquat[i]])
                self.next_bake += 1.0 / 240

    def rollout(self, t_end, watch=None, track=None):
        m = self.m
        d = mujoco.MjData(m)
        mujoco.mj_copyData(d, m, self.d)
        mv, nb = {}, d.time
        tr = {b: [] for b in (track or [])}
        while d.time < t_end - 1e-9:
            mv = self._ms(m, d, mv)
            if watch:
                cs = []
                self.scan(m, d, mv, cs)
                if watch(d.time, cs):
                    break
            if track and d.time >= nb:
                for b in track:
                    res = np.zeros(6)
                    mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, self.bid[b], res, 0)
                    tr[b].append([d.time] + [float(v) for v in d.xpos[self.bid[b]]] + [float(res[3]), float(res[4])])
                nb += 1.0 / 240
        return d, tr

    def pos(self, d, b="lead"):
        return np.array(d.xpos[self.bid[b]])

    def vel(self, d, b="lead"):
        res = np.zeros(6)
        mujoco.mj_objectVelocity(self.m, d, mujoco.mjtObj.mjOBJ_BODY, self.bid[b], res, 0)
        return np.array(res[3:5])

    def log(self, msg, **kw):
        kw["now"] = {b: [round(float(self.d.xpos[self.bid[b]][0]), 3), round(float(self.d.xpos[self.bid[b]][1]), 3),
                         round(float(np.linalg.norm(self.vel(self.d, b))), 3)] for b in MARBLES
                     if self.d.xpos[self.bid[b]][0] > -1.0}
        print(f"[{self.d.time:6.2f}s f{self.d.time * 24:6.1f}] {msg} " + json.dumps(kw, default=float), flush=True)

    def when(self, track, pred, b="lead", t_after=0.0):
        """The first tracked row of body b (t, x, y, z, vx, vy) at or after t_after where pred(row) holds."""
        for r in track[b]:
            if r[0] >= t_after and pred(r):
                return r
        return None

    def stalled(self, track, t_from, x_felt=9.0):
        """A marble moving under 0.03 m/s for more than 0.5 s before the felt (after it first moved)."""
        for b in MARBLES:
            rows = [r for r in track.get(b, []) if r[0] >= t_from and r[1] < x_felt]
            slow = 0.0
            for r in rows:
                slow = slow + 1 / 240 if math.hypot(r[4], r[5]) < 0.03 else 0.0
                if slow > 0.5:
                    return b, r
        return None

    # -------------------------------------------------------------- the prefix

    def start(self):
        self.compile(first=True)
        x, y = B.latch_to_table((-(MF.A + R + 0.0004), 0.0))
        self.place_free("lead", (x, y, R + 0.0002))
        self.d.time = T0
        self.next_bake = T0
        self.drive(self.d, T0)
        mujoco.mj_forward(self.m, self.d)

    def advance_until(self, cond, t_max, step=1 / 60):
        """Step the real state until cond(position, velocity) holds for the lead, or t_max; returns whether it did."""
        while self.d.time < t_max - 1e-9:
            self.advance(min(self.d.time + step, t_max))
            p, v = self.pos(self.d), self.vel(self.d)
            if cond(p, v):
                return True
        return False

    def run_prefix(self, resume=0, stop_after=99):
        """Event-driven: each U-turn is waited for, then the props that lie ahead of it are laid by roll-out."""
        st = self.layout["stations"]
        self.stop_after = stop_after
        T_END = tf(B.PREFIX_FRAMES) - 1e-6
        if resume < 1:
            self.start()
            # the latch, the papyrus, the hinge, to U1: the lead's lateral heading turns at Piri Reis's curl
            self.advance(tf(150))
            low = {"y": 9.0}

            def u1(p, v):
                low["y"] = min(low["y"], p[1])
                return low["y"] < 0.15 and v[1] > 0.03
            ok = self.advance_until(u1, T_END)
            self.log("U1 turned" if ok else "U1 NOT reached")
            self.checkpoint(1)
            if stop_after <= 1:
                return
        if resume < 2:
            self.lay_knots()
            self.lay_galley()
            if getattr(self, "until_frame", None):
                # milestone A (reduced, coordinator 2026-10-18): the working stretch only, latch to galley
                self.advance(tf(self.until_frame))
                self.log(f"stopped at f{self.until_frame} (the working stretch)")
                self.checkpoint(2)
                return
            hi = {"y": -9.0}

            def u2(p, v):
                hi["y"] = max(hi["y"], p[1])
                return hi["y"] > 0.75 and v[1] < -0.03
            ok = self.advance_until(u2, T_END)
            self.log("U2 turned" if ok else "U2 NOT reached")
            self.checkpoint(2)
            if stop_after <= 2:
                return
        if resume < 3:
            self.lay_tape()
            self.lay_reel("reel_reg", side=-1, y_cross=B.REEL_REG["at"][1], before="ino")
            self.lay_card()
            self.lay_reel("reel_film", side=+1, y_cross=B.REEL_FILM["at"][1], before="page")
            self.lay_strip()
            low = {"y": 9.0}

            def u3(p, v):
                if p[0] > 1.35:
                    low["y"] = min(low["y"], p[1])
                return low["y"] < 0.15 and v[1] > 0.03
            ok = self.advance_until(u3, T_END)
            self.log("U3 turned" if ok else "U3 NOT reached")
            self.checkpoint(3)
            if stop_after <= 3:
                return
        if resume < 4:
            self.lay_platen()
            self.lay_stick()
            self.lay_brass()
            self.advance(T_END)
            self.log("prefix end")
            self.checkpoint(4)
        _ = st

    def ahead(self, t_ahead=8.0, watch=None):
        _, tr = self.rollout(self.d.time + t_ahead, track=MARBLES, watch=watch)
        return tr

    def lay_knots(self):
        """The khipu's seven knots beside the lead's line on the U1 return leg (y 0.18 to 0.40), each 7.4 mm off its
        line so the knot glances it; the cord threads them and runs on past both ends."""
        st = self.layout["stations"]
        tr = self.ahead(10.0)
        lead = tr["lead"]
        # the return leg: after the lead's lowest y (U1), rising
        i_lo = int(np.argmin([r[2] if r[0] > self.d.time else 9 for r in lead]))
        y0, y1 = B.KHIPU["span"][0][1], B.KHIPU["span"][1][1]
        rk, rc = B.KHIPU["knot_r"], B.KHIPU["cord_r"]
        knots = []
        for k in range(B.KHIPU["knots"]):
            yk = y0 + (y1 - y0) * (k / (B.KHIPU["knots"] - 1)) ** 0.9
            r = next((r for r in lead[i_lo:] if r[2] >= yk), None)
            if r is None:
                break
            # the leg's direction over the span, and the path's widest swing to the left near this knot: the knot sits
            # just outside it, so it is ticked at the crest of a swing, never met square
            span = np.array([q[1:3] for q in lead[i_lo:] if y0 - 0.05 <= q[2] <= y1 + 0.05])
            u = span[-1] - span[0]
            u = u / (np.linalg.norm(u) + 1e-9)
            nrm = np.array([-u[1], u[0]])
            base = np.array(r[1:3])
            near = [q for q in span if abs((q - base) @ u) < 0.04]
            lat = max(float((q - base) @ nrm) for q in near) if near else 0.0
            c = base + u * 0.004 + nrm * (lat + 0.0078)
            z = self.world.zmax(c[0], c[1], rk)
            knots.append((float(c[0]), float(c[1]), z + rk))
        for i, kp in enumerate(knots):
            self.add(f"knot{i + 1}", {"type": "sphere", "size": (rk,), "pos": kp, "friction": "0.7 0.002 0.0002"})
        # the cord threads the knots and leaves them away from the path at both ends (never along it)
        e0 = np.array(knots[0][:2]) - u * 0.04 + nrm * 0.03
        e1 = np.array(knots[-1][:2]) + u * 0.05 + nrm * 0.03
        pts = [(e0[0], e0[1], knots[0][2])] + knots + [(e1[0], e1[1], knots[-1][2])]
        for i in range(len(pts) - 1):
            (x0, y0_, z0), (x1, y1_, z1) = pts[i], pts[i + 1]
            ln = math.hypot(x1 - x0, y1_ - y0_)
            ang = math.atan2(y1_ - y0_, x1 - x0)
            q = qmul(qz(math.degrees(ang)), qy(math.pi / 2))
            zc = self.world.zmax((x0 + x1) / 2, (y0_ + y1_) / 2, 0.003) + rc
            self.add(f"cord{i}", {"type": "capsule", "size": (rc, ln / 2), "pos": ((x0 + x1) / 2, (y0_ + y1_) / 2, zc),
                                  "quat": q, "friction": "0.7 0.002 0.0002"})
        self.compile()
        st["khipu"] = {"knots": knots, "cord": [p[:2] for p in pts]}
        self.log("knots", n=len(knots))

    def lay_galley(self):
        """The galley on the leaf, its open end on the leg at 12 degrees to it. Searched by roll-out: the galley's
        offset across its own axis so the lead strikes quad 1 first (the approved composition), the row falls, the
        stop goes, the pair leaves the lip."""
        st = self.layout["stations"]
        GL = galley_local()
        tr = self.ahead(10.0)
        r = self.when(tr, lambda r: r[2] >= B.GALLEY["from"][1] - 0.03, t_after=self.d.time)
        if r is None:
            for q in tr["lead"][::60]:
                print(f"  t{q[0]:.2f} f{q[0] * 24:.0f} x {q[1]:.3f} y {q[2]:.3f} v {math.hypot(q[4], q[5]):.3f}")
            print("knots", self.layout["stations"].get("khipu", {}).get("knots"))
            sys.exit("galley: the lead never reaches the leaf")
        # the leg's heading averaged over the last 6 cm of path (the marble wobbles in its trough)
        i_r = tr["lead"].index(r)
        back = next((q for q in reversed(tr["lead"][:i_r]) if math.dist(q[1:3], r[1:3]) >= 0.06), tr["lead"][0])
        leg = hdg(np.array(r[1:3]) - np.array(back[1:3]))
        psi = leg - B.GALLEY["mouth_deg_to_leg"]
        best = None
        for dy in (0.0, -0.004, 0.004, -0.008, 0.008, -0.012):
            u = np.array([math.cos(math.radians(psi)), math.sin(math.radians(psi))])
            n = np.array([-u[1], u[0]])
            # the galley's origin: the lead's point, then forward to the mouth, across so the lead runs on its line
            o = np.array(r[1:3]) + u * (0.05 + 0.025) - n * (LEAD_LINE_Y + dy)
            self.galley_geoms(o, psi, GL)
            self.compile()
            self.galley_bodies(o, psi, GL)
            hits = {}

            def w(t, cs):
                for c in cs:
                    if c["v_n"] > 0.002 and c["pair"] not in hits:
                        hits[c["pair"]] = t
                return False
            d_, tr2 = self.rollout(self.d.time + 12.0, watch=w, track=MARBLES)
            q1 = hits.get("lead|quad1")
            first_q = min((t for p, t in hits.items() if p.startswith("lead|quad")), default=None)
            moved = {b: float(np.linalg.norm(self.pos(d_, b)[:2] - self.pos(self.d, b)[:2])) for b in ("pair1", "pair2")}
            tilts = [round(math.degrees(math.acos(min(1.0, abs(d_.xmat[self.bid[f"quad{i + 1}"]][8])))), 0) for i in range(N_Q)]
            stop_moved = round(float(np.linalg.norm(self.pos(d_, "stop")[:2] - self.pos(self.d, "stop")[:2])), 4)
            self.log("galley row", tilts=tilts, stop_moved=stop_moved)
            ok = q1 is not None and q1 == first_q and all(mv > 0.15 for mv in moved.values())
            score = (0 if ok else 10) + abs(dy) * 10
            self.log("galley try", dy=dy, quad1=q1, first=first_q, pair_moved=moved, ok=ok, rise_mm=self.v.galley_rise * 1000,
                     lead_path=[[round(q[1], 3), round(q[2], 3), round(math.hypot(q[4], q[5]), 3)] for q in tr2["lead"][::48][:14]],
                     contacts=sorted(hits, key=hits.get)[:12])
            if best is None or score < best[0]:
                best = (score, dy, o, q1)
            if ok:
                break
        _, dy, o, q1 = best
        self.galley_geoms(o, psi, GL)
        self.compile()
        self.galley_bodies(o, psi, GL)
        st["galley"] = {"origin": o.tolist(), "psi": psi, "leg_deg": leg, "dy": dy, "t_quad1": q1, "z": self.v.galley_z,
                        "local": {k: (list(v_) if isinstance(v_, (list, tuple)) else v_) for k, v_ in GL.items()},
                        "floor_t": FLOOR_T, "step_h": STEP_H, "quad_half": QUAD, "stop_half": STOP, "stop_y": STOP_Y,
                        "ramp_l": RAMP_L}
        self.log("galley", origin=o.tolist(), psi=psi, t_quad1=q1, rise_mm=self.v.galley_rise * 1000)

    def galley_geoms(self, o, psi, GL):
        brass = f"0.3 0.001 {B.RR['brass'] * R:.3e}"
        gx, gy = GL["galley"]["x"], GL["galley"]["y"]
        u = np.array([math.cos(math.radians(psi)), math.sin(math.radians(psi))])
        n = np.array([-u[1], u[0]])
        P = lambda lx, ly: o + u * lx + n * ly  # noqa: E731
        # the brass galley is heavy: it presses the paper under it flat and rests at about its upper third
        z0 = float(np.percentile([self.world.z(*P(lx, ly)) for lx in np.linspace(gx[0], gx[1], 12)
                                  for ly in np.linspace(gy[0], gy[1], 6)], 70))
        self.v.galley_z = z0
        ft = z0 + FLOOR_T

        def lbox(name, x0, x1, y0, y1, za, zb):
            c = P((x0 + x1) / 2, (y0 + y1) / 2)
            self.obox(name, c, ((x1 - x0) / 2, (y1 - y0) / 2), psi, za, zb, brass)
        lbox("galley", gx[0], gx[1], gy[0], gy[1], z0, ft)
        # the bevelled open end: from the paper's own height at the mouth up to the galley's floor
        zm = min(self.world.z(*P(gx[0] - RAMP_L, ly)) for ly in np.linspace(gy[0], gy[1], 5))
        rise = ft - zm
        a = math.atan2(rise, RAMP_L)
        ln, ht = math.hypot(RAMP_L, rise), 0.002
        c = P(gx[0] - RAMP_L / 2, (gy[0] + gy[1]) / 2)
        self.add("galley_ramp", {"type": "box", "size": (ln / 2, (gy[1] - gy[0]) / 2, ht / 2),
                                 "pos": (c[0], c[1], (zm + ft) / 2 - ht / 2 * math.cos(a)),
                                 "quat": qmul(qz(psi), qy(-a)), "friction": brass})
        self.v.galley_rise = rise
        lbox("rail", gx[0], gx[1], gy[0], gy[0] + 0.003, ft, ft + 0.006)
        lbox("rail2", gx[0], gx[1], gy[1] - 0.003, gy[1], ft, ft + 0.006)
        sx, sy = GL["step_a"]["x"], GL["step_a"]["y"]
        lbox("step", sx[0], sx[1], sy[0], sy[1], ft, ft + STEP_H)
        sx, sy = GL["step_b"]["x"], GL["step_b"]["y"]
        lbox("shelf", sx[0], sx[1], sy[0], sy[1], ft, ft + STEP_H)

    def galley_bodies(self, o, psi, GL):
        u = np.array([math.cos(math.radians(psi)), math.sin(math.radians(psi))])
        n = np.array([-u[1], u[0]])
        ft = self.v.galley_z + FLOOR_T
        q = qz(psi)
        for i, x in enumerate(GL["quad_x"]):
            p = o + u * x
            self.place_free(f"quad{i + 1}", (p[0], p[1], ft + QUAD[2]), q)
        p = o + u * GL["stop_x"] + n * STOP_Y
        self.place_free("stop", (p[0], p[1], ft + STEP_H + STOP[2]), q)
        for k, (x, y) in enumerate(GL["pair"]):
            p = o + u * x + n * y
            self.place_free(f"pair{k + 1}", (p[0], p[1], ft + STEP_H + R))

    def lay_tape(self):
        """Morse's tape in Ino's crease valley (drawn, not collided: 0.08 mm of paper; as a box its long edge rubbed a
        slow marble to a crawl in M1)."""
        c = B.SHEETS["ino"]["crease"]
        (x0, y0), (x1, y1) = c["from"], c["to"]
        L = math.hypot(x1 - x0, y1 - y0) * 0.55
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        mid = (x0 + (x1 - x0) * 0.42, y0 + (y1 - y0) * 0.42)
        z = self.world.z(*mid)
        self.obox("tape", mid, (L / 2, B.SMALL["tape"]["w"] / 2), ang, z, z + B.SMALL["tape"]["t"], fr("tape"), ghost=True)
        self.layout["stations"]["tape"] = {"centre": mid, "len": L, "deg": ang, "z": z}

    def lay_reel(self, name, side, y_cross, before):
        """A reel standing on its hub beside the line, its rim glancing the lead (impact parameter B_IMPACT): placed
        where the lead, rolled out, crosses y_cross. side +1: left of the path, -1: right."""
        P = B.REEL_REG if name == "reel_reg" else B.REEL_FILM
        tr = self.ahead(12.0)
        r = self.when(tr, lambda r: r[2] <= y_cross and r[5] < 0, t_after=self.d.time)
        if r is None:
            sys.exit(f"{name}: the lead never crosses y {y_cross}")
        v = np.array(r[4:6])
        u = v / np.linalg.norm(v)
        nrm = np.array([-u[1], u[0]]) * side
        dy = B_IMPACT * (R + P["r"])
        c = np.array(r[1:3]) + nrm * dy + u * 0.03
        z = self.world.zmax(c[0], c[1], P["hub_r"])
        self.hinge_pos[name] = (float(c[0]), float(c[1]), z)
        self.compile()
        self.layout["stations"][name] = {"centre": [float(c[0]), float(c[1]), z], "r": P["r"], "h": P["h"],
                                         "hub_r": P["hub_r"], "impact": B_IMPACT, "side": side, "v": float(np.linalg.norm(v))}
        self.log(name, centre=c, z=z)
        _ = before

    def lay_card(self):
        """The blank Hollerith card across the line on Ino, its long side across the path, one corner lifted 3 mm."""
        tr = self.ahead(12.0)
        r = self.when(tr, lambda r: r[2] <= 0.36 and r[5] < 0, t_after=self.d.time)
        if r is None:
            sys.exit("card: the lead never reaches y 0.36")
        u = np.array(r[4:6]) / np.linalg.norm(r[4:6])
        ang = hdg(u) + 90.0
        c = np.array(r[1:3]) + u * 0.02
        z = self.world.zmax(c[0], c[1], 0.09)
        W, H = B.SMALL["card"]["size"]
        self.obox("card", c, (W / 2, H / 2), ang, z, z + B.SMALL["card"]["t"], fr("card"))
        self.layout["stations"]["card"] = {"centre": c.tolist(), "deg": ang, "size": [W, H], "z": z}
        self.compile()

    def lay_strip(self):
        """The 35 mm strip across the line on the typed page: its picture band and its perforations (film between the
        holes) are the bumps the marbles feel."""
        tr = self.ahead(12.0)
        r = self.when(tr, lambda r: r[2] <= 0.13 and r[5] < 0 and r[1] > 1.40, t_after=self.d.time)
        if r is None:
            sys.exit("strip: the lead never reaches y 0.13 on the page")
        u = np.array(r[4:6]) / np.linalg.norm(r[4:6])
        ang = hdg(u)                        # the strip's width runs along the path, its length across it
        S = B.SMALL["strip"]
        w, ln, t = S["w"], S["len"], S["t"]
        pw, ph, pitch = S["perf"]
        c = np.array(r[1:3]) + u * 0.01
        z = self.world.zmax(c[0], c[1], 0.02)
        nrm = np.array([-u[1], u[0]])
        self.obox("strip_c", c, (w / 2 - pw - 0.0005, ln / 2), ang, z, z + t, fr("film"))
        k = 0
        for row, off in enumerate((-(w / 2 - pw / 2), w / 2 - pw / 2)):
            for i in range(int(ln / pitch)):
                p = c + u * off + nrm * (-ln / 2 + (i + 0.5) * pitch + ph / 2)
                self.obox(f"strip_p{row}_{i}", p, (pw / 2 + 0.00025, (pitch - ph) / 2), ang, z, z + t, fr("film"))
                k += 1
        self.compile()
        self.layout["stations"]["strip"] = {"centre": c.tolist(), "deg": ang, "w": w, "len": ln, "z": z}

    def lay_platen(self):
        """The platen, pinned, lying beside the line after U3, grazed on its right at 13 degrees."""
        tr = self.ahead(10.0)
        lead = tr["lead"]
        # after U3: the lead rising again on the chart
        r = self.when(tr, lambda r: r[5] > 0 and r[1] > 1.5 and r[2] > 0.10, t_after=self.d.time)
        if r is None:
            sys.exit("platen: no rise after U3")
        u = np.array(r[4:6]) / np.linalg.norm(r[4:6])
        ang = hdg(u) - 13.0
        pr, pl = B.PLATEN["r"], B.PLATEN["len"]
        ua = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
        nrm = np.array([ua[1], -ua[0]])                    # its right side, toward the path
        c = np.array(r[1:3]) + u * 0.06 - nrm * (R + pr - 0.002) + ua * (pl / 2 - 0.05)
        z = self.world.zmax(c[0], c[1], 0.02)
        q = qmul(qz(ang), qy(math.pi / 2))
        self.add("platen", {"type": "cylinder", "size": (pr, pl / 2), "pos": (c[0], c[1], z + pr), "quat": q,
                            "friction": "0.6 0.0005 1e-6"})
        self.compile()
        self.layout["stations"]["platen"] = {"centre": [float(c[0]), float(c[1]), z + pr], "deg": ang, "r": pr, "len": pl,
                                             "pinned": True}
        _ = lead

    def lay_stick(self):
        """The Rebbelib lattice (T-19), rib for rib from its photograph (the keyed image's opaque pixels at 1 mm),
        raised on its shells, at the plan's place; its entry chosen within 5 cm by roll-out: the most rib ticks with
        no marble stalled."""
        from PIL import Image
        W, H = B.STICK["size"]
        png = WORK / "stick-hfield.png"
        if not png.exists():
            im = Image.open(TEX / "T-19_keyed.png").getchannel("A").resize((int(W * 1000), int(H * 1000)), Image.BOX)
            # hfield row 0 is local -y: flipped so the image stands upright (its top at local +y)
            Image.fromarray(np.flipud((np.asarray(im) > 110).astype(np.uint8) * 255)).save(png)
        zmax = B.STICK["raise"] + B.STICK["rib_h"]
        self.hfields["ribs"] = {"file": str(png).replace("\\", "/"), "size": (W / 2, H / 2, zmax, 0.002), "surface": "chart"}
        cx, cy = B.STICK["centre"]
        best = None
        for dy in (0.0, -0.02, 0.02, -0.04, 0.04):
            zc = self.world.zmax(cx, cy + dy, 0.3) - 0.0005
            self.add("ribs", {"type": "hfield", "hfield": "ribs", "pos": (cx, cy + dy, zc), "quat": qz(B.STICK["psi"]),
                              "friction": fr("chart")})
            self.compile()
            ticks = {b: 0 for b in MARBLES}

            def w(t, cs):
                for c in cs:
                    a_, b_ = c["pair"].split("|")
                    if "ribs" in (a_, b_) and c["v_n"] > 0.004:
                        mm = b_ if a_ == "ribs" else a_
                        if mm in ticks:
                            ticks[mm] += 1
                return False
            _, tr = self.rollout(tf(B.DESIGN["brass_hit"] - 6), watch=w, track=MARBLES)
            st = self.stalled(tr, self.d.time)
            n_t = sum(ticks.values())
            score = (100 if st else 0) + abs(min(n_t, 12) - 6) + (0 if n_t >= 3 else 20) + abs(dy) * 20
            self.log("stick try", dy=dy, ticks=ticks, stalled=bool(st), score=score)
            if best is None or score < best[0]:
                best = (score, dy, zc, dict(ticks))
        _, dy, zc, ticks = best
        self.add("ribs", {"type": "hfield", "hfield": "ribs", "pos": (cx, cy + dy, zc), "quat": qz(B.STICK["psi"]),
                          "friction": fr("chart")})
        self.compile()
        self.layout["stations"]["stick"] = {"cx": cx, "cy": cy + dy, "z": zc, "psi": B.STICK["psi"], "W": W, "H": H,
                                            "dy": dy, "ticks": ticks, "zmax": zmax}

    def lay_brass(self):
        """The brass disc standing on its rim on bare oak at the plan's x, on the lead's line, struck 9 mm off its
        centre line so the blow turns it as it tips."""
        tr = self.ahead(tf(B.PREFIX_FRAMES) - self.d.time)
        x_b = B.BRASS["at"][0]
        r = self.when(tr, lambda r: r[1] >= x_b - 0.06, t_after=self.d.time)
        if r is None:
            sys.exit("brass: the lead never reaches the oak past the chart")
        A, T = B.BRASS["A"], B.BRASS["T"]
        lean = math.radians(B.BRASS["lean_deg"])
        u = np.array(r[4:6]) / np.linalg.norm(r[4:6])
        # where the lead's line meets x_b
        s = (x_b - r[1]) / max(u[0], 0.2)
        y = r[2] + u[1] * s + 0.009
        q = qmul(qz(hdg(u)), qy(math.pi / 2 + lean))
        z0 = self.world.z(x_b, y)
        self.place_free("brass", (x_b + A * math.sin(lean), y, z0 + A * math.cos(lean) + T * math.sin(lean)), q)
        self.layout["stations"]["brass"] = {"x": x_b, "y": float(y), "lean_deg": B.BRASS["lean_deg"]}
        self.brass_watch = True
        self.log("brass", y=y)

    def watch_brass(self):
        d = self.d
        i = self.bid["brass"]
        n = d.xmat[i].reshape(3, 3)[:, 2]
        tilt = math.acos(min(1.0, abs(n[2])))
        if tilt <= math.radians(B.BRASS["alpha_land_deg"]):
            c = np.array(d.xpos[i])
            nn = n if n[2] > 0 else -n
            e = np.array([nn[0], nn[1], 0.0])
            ph = math.atan2(-e[1], -e[0]) if np.linalg.norm(e) > 1e-9 else 0.0
            self.brass_hand = {"t": float(d.time), "centre": c.tolist(), "tilt": tilt, "phase": ph}
            self.brass_watch = False
            self.place_free("brass", (PARK[0], PARK[1] - 1.0, B.BRASS["T"]))
            self.log("brass lands: the analytic settle takes over", **self.brass_hand)

    # -------------------------------------------------------------- tails

    def run_tail(self, rec, state):
        """From the prefix's last state: bare oak for the years crossed in the dark, then black felt to the table's
        end; the record laid across (its shorter side along x) with its near edge 7 mm before the lead's free stop."""
        F = B.FILMS[rec]
        self.restore(state)
        x_felt = B.felt_x0(rec)
        y0, y1 = B.FELT_Y
        self.obox("felt", ((x_felt + B.FELT_X1) / 2, (y0 + y1) / 2), ((B.FELT_X1 - x_felt) / 2, (y1 - y0) / 2), 0.0,
                  0.0, B.FELT_T, fr("felt"))
        self.compile()
        t_end = tf(B.PREFIX_FRAMES + F["tail"][0] + F["tail"][1])
        _, tr = self.rollout(t_end, track=MARBLES)
        lead = tr["lead"]
        rest = next((r for r in lead if r[1] > x_felt and math.hypot(r[4], r[5]) < 0.002), lead[-1])
        (sx, sy), upright = B.record_size(rec)
        x_rec = rest[1] - 0.007 + math.sqrt(2 * R * B.RECORD_T)
        # the marble rests at the record's near edge low down, clear of its text: the record's lower edge 12 mm
        # below the marble's line
        yc = min(max(rest[2] + sy / 2 - 0.012, y0 + sy / 2), y1 - sy / 2)
        self.obox("record", (x_rec + sx / 2, yc), (sx / 2, sy / 2), 0.0, B.FELT_T, B.FELT_T + B.RECORD_T, fr("page"))
        self.compile()
        self.contacts, self.poses = [], {b: [] for b in self.poses}
        self.next_bake = self.d.time + 1.0 / 240
        self.advance(t_end)
        info = {"felt_x": x_felt, "record": {"x0": x_rec, "y": yc, "W": sx, "H": sy, "z": B.FELT_T + B.RECORD_T,
                                             "upright": upright},
                "free_stop": rest[:3], "lead_final": self.pos(self.d).tolist(),
                "marbles_final": {b: self.pos(self.d, b).tolist() for b in MARBLES}}
        info["lead_touches_record"] = abs(info["lead_final"][0] + R - x_rec) < 0.004
        return info

    # -------------------------------------------------------------- state

    def checkpoint(self, n):
        if getattr(self, "probe", False):
            self.log(f"checkpoint {n}")
        (WORK / "ckpt").mkdir(parents=True, exist_ok=True)
        d = self.d
        blob = {k: getattr(self, k) for k in ("geoms", "hinge_pos", "layout", "hfields", "contacts", "poses",
                                              "next_bake", "brass_watch", "brass_hand", "fall")}
        blob["v"] = vars(self.v)
        blob["state"] = {k: np.array(getattr(d, k)) for k in ("qpos", "qvel", "qacc_warmstart", "mocap_pos", "mocap_quat")}
        blob["time"] = float(d.time)
        (WORK / "ckpt" / f"{n:02d}.pkl").write_bytes(pickle.dumps(blob))

    def load_checkpoint(self, n):
        blob = pickle.loads((WORK / "ckpt" / f"{n:02d}.pkl").read_bytes())
        for k, val in blob.items():
            if k not in ("v", "state", "time"):
                setattr(self, k, val)
        self.v = SimpleNamespace(**blob["v"])
        self.d = None
        self.compile(first=True)
        for k, a in blob["state"].items():
            getattr(self.d, k)[:] = a
        self.d.time = blob["time"]
        mujoco.mj_forward(self.m, self.d)
        print(f"resumed after step {n} at t {self.d.time:.2f}", flush=True)

    def snapshot(self):
        d = mujoco.MjData(self.m)
        mujoco.mj_copyData(d, self.m, self.d)
        return {"d": d, "geoms": json.loads(json.dumps(self.geoms)), "hinge": dict(self.hinge_pos),
                "next_bake": self.next_bake, "hfields": dict(self.hfields)}

    def restore(self, s):
        self.geoms = json.loads(json.dumps(s["geoms"]))
        self.hinge_pos = dict(s["hinge"])
        self.hfields = dict(s["hfields"])
        self.d = s["d"]
        self.compile()
        self.brass_watch = False


# ------------------------------------------------------------------------------------------------ analytic brass


def brass_analytic(hand, t_end):
    """Moffatt's settle for the brass disc from the tilt where MuJoCo's toppled rim caught, to its slap."""
    A, T = B.BRASS["A"], B.BRASS["T"]
    C = B.BRASS["C_HZ"]
    a1 = 4 * B.G / (A * (2 * math.pi * C) ** 2)
    t_land, al = hand["t"], hand["tilt"]
    t_slap = t_land + (al / a1) ** 3
    k = 2 * math.pi * C * 6 / 5
    phi_slap = hand["phase"] + k * (t_slap - t_land) ** (5 / 6)
    cx, cy, cz0 = hand["centre"]
    zb = cz0 - (A * math.sin(al) + T * math.cos(al))         # the oak under it
    rows, psi, t = [], 0.0, t_land
    while t <= t_end:
        if t < t_slap:
            alpha = a1 * (t_slap - t) ** (1 / 3)
            om = 2 * math.pi * C * (t_slap - t) ** (-1 / 6)
            ph = phi_slap - k * (t_slap - t) ** (5 / 6)
            psi -= om * (1 - math.cos(alpha)) / 240
        else:
            alpha, ph = 0.0, phi_slap
        e = np.array([math.cos(ph), math.sin(ph), 0.0])
        ca, sa = math.cos(alpha), math.sin(alpha)
        n = sa * e + np.array([0, 0, ca])
        u = ca * e - np.array([0, 0, sa])
        w = np.cross(n, u)
        c_, s_ = math.cos(psi), math.sin(psi)
        u2, w2 = c_ * u + s_ * w, -s_ * u + c_ * w
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, np.array([u2, w2, n]).T.ravel())
        rows.append([round(t, 6), cx, cy, zb + A * sa + T * ca, *[float(v) for v in q]])
        t += 1 / 240
    return rows, {"t_land": t_land, "t_slap": t_slap, "C_hz": C, "alpha_land_deg": math.degrees(al),
                  "frame_land": t_land * 24, "frame_slap": t_slap * 24}


# ------------------------------------------------------------------------------------------------ checks


def checks(poses, events, layout, brass_info):
    """The ticket's event-log checks: the hand-offs in order, no stall before the felt, the three U-turns each reversing
    the lateral heading within 15 frames, the brass hit and slap on the clock, the reels' impact parameters."""
    out = {}
    lead = np.array(poses["lead"])
    t, x, y = lead[:, 0], lead[:, 1], lead[:, 2]
    vy = np.gradient(y, t)
    vx = np.gradient(x, t)
    sp = np.hypot(vx, vy)
    # the U-turns: lateral reversals of the lead, near each bank's edge (U1, U3: near side; U2: far side)
    turns = []
    for name, near in (("U1", True), ("U2", False), ("U3", True)):
        lo = [i for i in range(2, len(t) - 2) if (vy[i - 1] < 0 <= vy[i] if near else vy[i - 1] > 0 >= vy[i])
              and ((y[i] < 0.12) if near else (y[i] > 0.78))]
        turns.append({"bank": name, "frame": round(float(t[lo[0]] * 24), 1) if lo else None,
                      "x": round(float(x[lo[0]]), 3) if lo else None, "y": round(float(y[lo[0]]), 3) if lo else None})
    for tn in turns:
        if tn["frame"] is None:
            tn["reverses_within_15_frames"] = False
            continue
        f = tn["frame"] / 24
        w = (t > f - 15 / 24) & (t < f + 15 / 24)
        tn["reverses_within_15_frames"] = bool((vy[w] < -0.02).any() and (vy[w] > 0.02).any())
    out["turns"] = turns
    out["turn_order_ok"] = all(a["frame"] and b["frame"] and a["frame"] < b["frame"] for a, b in zip(turns, turns[1:]))
    # hand-offs: the first contact of each named object with any marble, in the plan's order
    order = ["hf_papyrus", "hf_atlas", "hf_piri", "knot", "quad1", "hf_leaf", "hf_ino", "reel_reg", "card", "hf_page",
             "reel_film", "strip", "hf_chart", "platen", "ribs", "brass"]
    first = {}
    for e in events:
        a, b = e["pair"].split("|")[0], e["pair"].split("|")[-1]
        if not ({a, b} & set(MARBLES)):
            continue
        o = b if a in MARBLES else a
        for k in order:
            if o.startswith(k) and k not in first:
                first[k] = e["frame"]
    seq = [(k, first.get(k)) for k in order]
    out["handoffs"] = seq
    got = [f for _, f in seq if f is not None]
    out["handoffs_all_present"] = all(f is not None for _, f in seq)
    out["handoffs_in_order"] = got == sorted(got)
    # stall: under 0.03 m/s for more than 0.5 s after the release, before the felt
    moving = t > 121 / 24 + 0.5
    slow = (sp < 0.03) & moving & (x < B.DARK_X0)
    run_, worst = 0, 0
    for s in slow:
        run_ = run_ + 1 if s else 0
        worst = max(worst, run_)
    out["longest_slow_s"] = round(worst / 240, 2)
    out["no_stall"] = worst / 240 <= 0.5
    hit = next((e["frame"] for e in events if "brass" in e["pair"] and set(e["pair"].split("|")) & set(MARBLES)), None)
    out["brass_hit"] = hit
    out["brass_slap"] = round(brass_info.get("frame_slap", 0), 1) if brass_info else None
    out["brass_ok"] = bool(hit and abs(hit - B.DESIGN["brass_hit"]) <= B.BRASS_TOL and out["brass_slap"]
                           and abs(out["brass_slap"] - B.DESIGN["brass_slap"]) <= B.BRASS_TOL)
    # the shared prefix: no marble reaches the nearest film's felt before f935
    x_min_felt = min(B.felt_x0(r) for r in B.FILMS)
    out["prefix_clear_of_felt"] = all(max(r[1] for r in poses[b] if r[0] <= tf(B.PREFIX_FRAMES)) < x_min_felt - R
                                      for b in MARBLES if poses.get(b))
    out["reels"] = {n: layout["stations"][n].get("impact") for n in HINGED if n in layout["stations"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fall", type=float, default=B.FALL_DEG)
    ap.add_argument("--films", default="C20-METAR-0851,S-130,S-16928")
    ap.add_argument("--resume", type=int, default=0)
    ap.add_argument("--prefix-only", action="store_true")
    ap.add_argument("--stop-after", type=int, default=99, help="probe: stop after this step and print the lead's path")
    ap.add_argument("--until-frame", type=int, default=0, help="bake the prefix only to this frame (after the galley)")
    a = ap.parse_args()
    t_start = time.time()
    run = Run(a.fall)
    if a.resume:
        run.load_checkpoint(a.resume)
    run.until_frame = a.until_frame or None
    run.run_prefix(resume=a.resume, stop_after=a.stop_after)
    if a.stop_after < 99:
        lead = run.poses["lead"]
        for r in lead[::48]:
            print(f"  f{r[0] * 24:6.1f} x {r[1]:.3f} y {r[2]:.3f} z {r[3] * 1000:5.2f}mm")
        tr = run.ahead(8.0)
        print("ahead:")
        for r in tr["lead"][::48]:
            print(f"  f{r[0] * 24:6.1f} x {r[1]:.3f} y {r[2]:.3f} v {math.hypot(r[4], r[5]):.3f} hd {math.degrees(math.atan2(r[5], r[4])):5.0f}")
        return
    st = run.layout["stations"]
    brass_rows, brass_info = [], {}
    if run.brass_hand:
        brass_rows, brass_info = brass_analytic(run.brass_hand, tf(B.PREFIX_FRAMES) + 12.0)
        run.poses["brass"] = [r for r in run.poses["brass"] if r[0] < run.brass_hand["t"]] + \
            [r for r in brass_rows if r[0] <= tf(B.PREFIX_FRAMES)]
        st.setdefault("brass", {}).update(brass_info)
    # the bronze disc and the waiting marble before the simulation starts (f0 to f60): analytic (one take from f0)
    pre = []
    for k in range(int(T0 * 240)):
        t = k / 240
        c, q = run.disc_pose(t)
        pre.append([round(t, 6), *[float(v) for v in c], *[float(v) for v in q]])
    run.poses["disc"] = pre + run.poses["disc"]
    lx, ly = B.latch_to_table((-(MF.A + R + 0.0004), 0.0))
    run.poses["lead"] = [[round(k / 240, 6), lx, ly, R, 1.0, 0.0, 0.0, 0.0] for k in range(int(T0 * 240))] + run.poses["lead"]
    OUT.mkdir(parents=True, exist_ok=True)
    E.write_jsonl(run.contacts, OUT / "run-contacts-1khz.jsonl")
    ev = E.events(run.contacts)
    if brass_info:
        ev = [e for e in ev if not ("brass" in e["pair"] and e["t_s"] > brass_info["t_land"])]
        ev.append({"t_s": round(brass_info["t_slap"], 4), "frame": round(brass_info["t_slap"] * 24, 2),
                   "pair": "brass|oak (analytic slap)", "v_n": 0.05, "impulse": 0.0})
        ev.sort(key=lambda e: e["t_s"])
    E.write_jsonl(ev, OUT / "run-events.jsonl")
    ck = checks(run.poses, ev, run.layout, brass_info)
    ck["fall_deg"] = a.fall
    (OUT / "run-checks.json").write_text(json.dumps(ck, indent=1, default=float), encoding="utf-8")
    print("CHECKS " + json.dumps(ck, default=float), flush=True)
    state = run.snapshot()
    meta = {"t0": T0, "dt": DT, "fall_deg": a.fall, "rr": B.RR, "hfields": run.hfields, "geoms": run.geoms,
            "hinge": run.hinge_pos, "layout": run.layout, "brass_rows_after": brass_rows,
            "wall_s": round(time.time() - t_start, 1)}
    (OUT / "run-bake.json").write_text(json.dumps({"meta": meta, "poses": run.poses}, default=float), encoding="utf-8")
    tails = {}
    if not a.prefix_only and not a.until_frame:
        for rec in [r for r in a.films.split(",") if r]:
            info = run.run_tail(rec, state)
            tev = E.events(run.contacts)
            E.write_jsonl(tev, OUT / f"run-tail-{rec}-events.jsonl")
            (OUT / f"run-tail-{rec}-bake.json").write_text(json.dumps({"meta": info, "geoms": run.geoms, "poses": run.poses},
                                                                      default=float), encoding="utf-8")
            tails[rec] = info
            print("TAIL", rec, json.dumps(info, default=float), flush=True)
    (OUT / "run-layout.json").write_text(json.dumps({"stations": st, "tails": tails, "geoms": state["geoms"],
                                                     "hinge": run.hinge_pos, "hfields": run.hfields, "fall_deg": a.fall,
                                                     "checks": ck, "wall_s": round(time.time() - t_start, 1)},
                                                    default=float, indent=1), encoding="utf-8")
    print("events:", len(ev), "wall", round(time.time() - t_start, 1), "s")


if __name__ == "__main__":
    main()
