"""The Run, the full take: one continuous MuJoCo simulation from the bronze disc's settle to the marbles' rest on the
felt, the stations laid by the clock (runs in the D: venv, D:/document-media/tools/run-venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_run.py [--films C20-METAR-0851,...]

The approved latch (proof 1) opens it unchanged: the bronze disc analytic (moffatt.py) and driven into MuJoCo as a
moving collider, the 2.5 degree fall by the disc. From there one simulation carries every body to the end of the
prefix (f935), and each film's tail continues the same state onto its own oak and felt.

How the stations are laid: before each station's design frame the simulation is rolled out ahead (a copy of the
state, nothing kept) to see where the lead marble will be at that frame, and the station is put there: a sheet's
downhill edge (each period sheet at its real size, turned on the bench so the path crosses it where the clock needs;
sheetfit.py), a fold, a khipu knot, the galley, a reel's rim, the card, the film strip, the platen, the stick chart,
the brass disc, and in each tail the record's near edge where the lead marble comes to rest. Then the real state is
stepped on through it. Nothing is scripted: every contact, fall time and exit comes out of the simulation and its
1 kHz contact log. Two hand-offs are analytic by the design (section 7): the bronze disc's settle, and the brass
disc's wobble after MuJoCo has toppled it (from the tilt where its rim catches, Moffatt's settle to the slap).

The bench's fall and each surface's rolling resistance are the tuning knobs (bench.py). The fall is applied per body
by its own position (the bench's local fall), as a force along +x; gravity is vertical.

Writes D:/document-media/title-sequence/run/sim/run-{bake.json,layout.json,events.jsonl,contacts-1khz.jsonl} and,
per film, run-tail-<record>-{bake.json,events.jsonl}.
"""

from __future__ import annotations

import argparse
import pickle
from types import SimpleNamespace
import json
import math
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import eventlog as E  # noqa: E402
import moffatt as MF  # noqa: E402
import sheetfit as SF  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/sim")
WORK = Path("D:/document-media/title-sequence/run/work")
CK = WORK / "ckpt"
TEX = Path("D:/document-media/title-sequence/tex")
DT = 0.0005
T0 = 2.5                                    # the latch's simulated start (the proof's), title seconds
R = B.R
FAR = 4.0
PARK_X = -8.0
TABLET = (0.155, 0.1525, 0.025)
QUAD = B.QUAD
QM = 10400 * 8 * QUAD[0] * QUAD[1] * QUAD[2]
N_Q = 12
GAPS = np.linspace(0.014, 0.008, N_Q)
FLOOR_T = 0.0005
RAMP_L = 0.020                              # the galley floor's bevelled open end
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


def tf(frame):
    return frame / B.FPS


def qz(deg):
    a = math.radians(deg) / 2
    return (math.cos(a), 0.0, 0.0, math.sin(a))


def qy(rad):
    return (math.cos(rad / 2), 0.0, math.sin(rad / 2), 0.0)


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def fr(surface, slide=0.5):
    """A surface's friction, resolved when the model is compiled (so a tuned rolling resistance reaches every sheet
    already laid, checkpoints included)."""
    return f"@{surface}@{slide}"


def fr_resolve(f):
    if f.startswith("@"):
        _, surface, slide = f.split("@")
        return f"{slide} 0.0005 {B.RR[surface] * R:.3e}"
    return f


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


class Run:
    def __init__(self):
        self.geoms: dict[str, dict] = {}
        self.hinge_pos = {h: (PARK_X - 2 - i, 1.0, 0.0) for i, h in enumerate(HINGED)}
        self.zones: list[dict] = []                     # fall and valley zones along x
        self.layout: dict = {"stations": {}, "sheets": {}}
        self.hfields: dict[str, dict] = {}
        self.m = None
        self.d = None
        self.contacts: list[dict] = []
        self.poses: dict[str, list] = {b: [] for b in FREE + HINGED + ["disc"]}
        self.next_bake = None
        self.brass_hand = None
        self.brass_watch = False
        self.v = SimpleNamespace()
        self.add("oak", {"type": "plane", "size": "30 30 0.1", "pos": (0, 0, 0), "friction": fr("oak", 0.45)})
        self.add("tablet", {"type": "box", "size": TABLET, "pos": (-0.16, 0.215, TABLET[2]), "friction": "0.6 0.001 0.0001"})

    # ------------------------------------------------------------------ model

    def add(self, name, spec):
        spec.setdefault("quat", (1, 0, 0, 0))
        spec.setdefault("condim", 6)
        self.geoms[name] = spec

    def box(self, name, x0, x1, y0, y1, z0, z1, friction, psi=0.0, cx=None, cy=None, condim=6):
        if cx is None:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.add(name, {"type": "box", "size": ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2),
                        "pos": (cx, cy, (z0 + z1) / 2), "quat": qz(psi), "friction": friction, "condim": condim})

    def xml(self):
        g = []
        for n, s in self.geoms.items():
            size = s["size"] if isinstance(s["size"], str) else " ".join(f"{v:.7g}" for v in s["size"])
            extra = f' hfield="{s["hfield"]}"' if s["type"] == "hfield" else ""
            g.append(f'<geom name="{n}" type="{s["type"]}"{"" if s["type"] == "hfield" else f" size={chr(34)}{size}{chr(34)}"}'
                     f'{extra} pos="{" ".join(f"{v:.7g}" for v in s["pos"])}" quat="{" ".join(f"{v:.9g}" for v in s["quat"])}" '
                     f'friction="{fr_resolve(s["friction"])}" condim="{s["condim"]}"/>')
        assets = "".join(f'<hfield name="{n}" file="{h["file"]}" size="{h["size"]}"/>' for n, h in self.hfields.items())
        free = []
        for i, b in enumerate(FREE):
            px = PARK_X - 0.06 * i
            if b in MARBLES:
                geom = f'<geom name="{b}" type="sphere" size="{R}" mass="{B.MASS}" friction="0.4 0.0002 1e-7" condim="6"/>'
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
            free.append(f'<body name="{b}" pos="{px} 0 {z}"><freejoint/>{geom}</body>')
        hinged = []
        for h in HINGED:
            p = REEL = B.REEL_REG if h == "reel_reg" else B.REEL_FILM
            hp = self.hinge_pos[h]
            hinged.append(f'<body name="{h}" pos="{hp[0]} {hp[1]} {hp[2] + p["h"] / 2}">'
                          f'<joint name="{h}" type="hinge" axis="0 0 1" damping="{p["damp"]}" frictionloss="{p["fric"]}"/>'
                          f'<geom name="{h}" type="cylinder" size="{p["r"]} {p["h"] / 2}" mass="{p["mass"]}" '
                          f'friction="0.3 0.001 0.0001" condim="4"/></body>')
            del REEL
        return f"""
<mujoco model="the run">
  <compiler angle="radian"/>
  <option timestep="{DT}" gravity="0 0 {-B.G}" integrator="implicitfast" cone="elliptic" impratio="10"/>
  <default><geom solref="0.004 1"/></default>
  <asset>{assets}</asset>
  <worldbody>
    {"".join(g)}
    <body name="disc" mocap="true" pos="0 0 {MF.T / 2}">
      <geom name="disc" type="cylinder" size="{MF.A} {MF.T / 2}" friction="0.3 0.0005 {B.RR['bronze'] * R:.3e}" condim="6"/>
    </body>
    {"".join(free)}
    {"".join(hinged)}
  </worldbody>
</mujoco>"""

    def compile(self, first=False):
        m = mujoco.MjModel.from_xml_string(self.xml())
        d = mujoco.MjData(m)
        if first:
            self.m, self.d = m, d
            mujoco.mj_forward(m, d)
        else:
            old = self.d
            d.time = old.time
            d.qpos[:] = old.qpos
            d.qvel[:] = old.qvel
            d.qacc_warmstart[:] = old.qacc_warmstart
            d.mocap_pos[:] = old.mocap_pos
            d.mocap_quat[:] = old.mocap_quat
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

    # ------------------------------------------------------------------ forces and the disc

    def fall(self, x):
        if x < PARK_X + 3:
            return 0.0
        deg = B.FALL_DEG
        for z in self.zones:
            if z["kind"] == "fall" and z["x0"] <= x < z["x1"]:
                deg = z["deg"]
        return math.sin(math.radians(deg))

    def lateral(self, x, y):
        s = 0.0
        for z in self.zones:
            if z["kind"] == "valley" and z["x0"] <= x < z["x1"]:
                s += -math.sin(math.radians(z["deg"])) * math.tanh((y - z["y"]) / z["w"])
        return s

    def apply(self, m, d):
        for b in FREE:
            i = self.bid[b]
            x, y = d.xpos[i][0], d.xpos[i][1]
            mg = self.mass[b] * B.G
            d.xfrc_applied[i, 0] = mg * self.fall(x)
            d.xfrc_applied[i, 1] = mg * self.lateral(x, y)

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
        return np.array(p["centre"]), q

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

    # ------------------------------------------------------------------ stepping

    def _ms(self, m, d, mv):
        self.apply(m, d)
        for _ in range(2):
            mv = self.drive(d, d.time + DT) or mv if d.time < MF.T_SLAP + 0.6 else {}
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
            if p[0] < PARK_X + 3:
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
                    if d.xpos[i][0] > PARK_X + 3:
                        self.poses[b].append([t] + [float(v) for v in d.xpos[i]] + [float(v) for v in d.xquat[i]])
                self.next_bake += 1.0 / 240

    def rollout(self, t_end, watch=None, track=None):
        """Step a copy of the state to t_end (nothing kept). watch(t, contacts) sees each millisecond's contacts;
        track lists bodies whose positions are recorded at 240 Hz."""
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
                    tr[b].append([d.time] + [float(v) for v in d.xpos[self.bid[b]]])
                nb += 1.0 / 240
        return d, tr

    def pos(self, d, b="lead"):
        return np.array(d.xpos[self.bid[b]])

    def speed(self, d, b="lead"):
        res = np.zeros(6)
        mujoco.mj_objectVelocity(self.m, d, mujoco.mjtObj.mjOBJ_BODY, self.bid[b], res, 0)
        return float(np.linalg.norm(res[3:5]))

    def front(self, d):
        """The marble furthest down the bench: after the galley the freed pair can lead the file."""
        live = [b for b in MARBLES if d.xpos[self.bid[b]][0] > PARK_X + 3]
        return max(live, key=lambda b: d.xpos[self.bid[b]][0])

    def lead_at(self, frame, b="front"):
        d, _ = self.rollout(tf(frame))
        if b == "front":
            b = self.front(d)
            self.v.last_front = b
        v = self.speed(d, b)
        if b in MARBLES and v < 0.004:
            sys.exit(f"the lead marble has stalled before f{frame} at x={self.pos(d, b)[0]:.4f} (t {self.d.time:.2f})")
        return self.pos(d, b), v

    def first_contact(self, t_end, pred):
        hit = {}

        def w(t, cs):
            for c in cs:
                if pred(c["pair"]) and c["v_n"] > 0.002:
                    hit["t"] = t
                    return True
            return False
        self.rollout(t_end, watch=w)
        return hit.get("t")

    def log(self, msg, **kw):
        mm = {b: [round(float(self.d.xpos[self.bid[b]][0]), 3), round(self.speed(self.d, b), 3)] for b in MARBLES
              if self.d.xpos[self.bid[b]][0] > PARK_X + 3}
        kw["now"] = mm
        print(f"[{self.d.time:6.2f}s f{self.d.time * 24:6.1f}] {msg} " + json.dumps(kw, default=float), flush=True)

    # ------------------------------------------------------------------ sheets

    def sheet_prov(self, gid, x0, yp, name=None, psi=0.0):
        """A provisional sheet from x0 far downhill, until its own edge is laid."""
        g = B.GROUNDS[gid]
        nm = name or gid
        self.box(nm, x0, x0 + FAR, yp - 0.5, yp + 0.5, 0.0, g["level"], fr(g["surface"]))

    def sheet_fit(self, gid, fit, W, H, name=None, u_range=None):
        g = B.GROUNDS[gid]
        nm = name or gid
        p = math.radians(fit["psi"])
        u0, u1 = u_range if u_range else (-W / 2, W / 2)
        uc = (u0 + u1) / 2
        cx, cy = fit["cx"] + uc * math.cos(p), fit["cy"] + uc * math.sin(p)
        self.box(nm, cx - (u1 - u0) / 2, cx + (u1 - u0) / 2, cy - H / 2, cy + H / 2, 0.0, g["level"], fr(g["surface"]),
                 psi=fit["psi"], cx=cx, cy=cy)
        return {"cx": cx, "cy": cy, "psi": fit["psi"], "W": u1 - u0, "H": H, "level": g["level"]}

    def ridge(self, name, x, yp, level, h, length=0.25, r=0.003):
        # a fold: a low ridge across the path, its crest h above the sheet; placed where the marble's leading
        # contact meets the crest's flank
        self.add(name, {"type": "capsule", "size": (r, length / 2), "pos": (x, yp, level + h - r),
                        "quat": (math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0), "friction": fr("washi")})

    # ------------------------------------------------------------------ the prefix

    def run_prefix(self, resume=0):
        L = self.layout
        st = L["stations"]
        V = self.v
        if resume == 0:
            self.compile(first=True)
            lj = self.m.body_jntadr[self.bid["lead"]]
            a = self.m.jnt_qposadr[lj]
            self.d.qpos[a:a + 3] = (-(MF.A + R + 0.0004), 0.0, R)
            self.d.time = T0
            self.next_bake = T0
            self.drive(self.d, T0)
            mujoco.mj_forward(self.m, self.d)
            self.zones.append({"kind": "fall", "x0": -1.0, "x1": B.LATCH_ZONE_X, "deg": B.LATCH_FALL_DEG})
        if resume < 1:
            # 1 the papyrus's uphill edge, stepped up onto from bare oak at f167 (the latch's rule)
            p167, v167 = self.lead_at(B.DESIGN["papyrus_edge"])
            V.x_pap = float(p167[0] - R * 0.35)
            self.zones[-1]["x1"] = min(V.x_pap, B.LATCH_ZONE_X)
            self.sheet_prov("papyrus", V.x_pap, p167[1])
            self.compile()
            st["papyrus_edge"] = {"x": V.x_pap, "y": float(p167[1]), "v": v167}
            self.log("papyrus edge", x=V.x_pap, v=v167)
            self.advance(tf(150))

            self.checkpoint(1)
        if resume < 2:
            # 2 the papyrus's fold
            V.lv = B.GROUNDS["papyrus"]["level"]
            p, v = self.lead_at(B.DESIGN["papyrus_fold"])
            self.ridge("fold_pap", float(p[0]) + 0.0013, float(p[1]), V.lv, 0.00008)
            self.compile()
            st["papyrus_fold"] = {"x": float(p[0]) + 0.0013, "y": float(p[1]), "v": v}
            self.log("papyrus fold", x=p[0], v=v)
            self.advance(tf(190))

            self.checkpoint(2)
        if resume < 3:
            # 3 off the papyrus onto the Atlas's first board
            p, v = self.lead_at(B.DESIGN["vellum_edge"])
            g = B.GROUNDS["papyrus"]
            xe = float(p[0])
            fit = None
            while fit is None and xe > float(self.pos(self.d)[0]) + 0.01:
                fit = SF.fit_sheet(*g["size"], g["psi"], float(p[1]), xe, x_entry=V.x_pap)
                if fit is None:
                    xe -= 0.005
            if fit is None:
                sys.exit(f"papyrus: no fit for a crossing {V.x_pap:.3f}..{p[0]:.3f}")
            p = np.array([xe, p[1], p[2]])
            L["sheets"]["papyrus"] = self.sheet_fit("papyrus", fit, *g["size"])
            V.x239 = float(p[0])
            self.sheet_prov("atlas", V.x239 - 0.01, p[1], name="atlas1")
            self.compile()
            st["vellum_edge"] = {"x": V.x239, "y": float(p[1]), "v": v}
            self.log("vellum edge", x=V.x239, v=v, fit=fit)
            self.advance(tf(225))

            self.checkpoint(3)
        if resume < 4:
            # 4 the hinge valley between the Atlas's boards
            p, v = self.lead_at(B.DESIGN["hinge"])
            V.xh = float(p[0])
            gA = B.GROUNDS["atlas"]
            V.lvA = gA["level"]
            self.box("atlas1", V.xh - 2.0, V.xh - B.HINGE_GAP / 2, p[1] - 0.5, p[1] + 0.5, 0, V.lvA, fr("vellum"))
            self.box("atlas2", V.xh + B.HINGE_GAP / 2, V.xh + FAR, p[1] - 0.5, p[1] + 0.5, 0, V.lvA, fr("vellum"))
            self.compile()
            st["hinge"] = {"x": V.xh, "y": float(p[1]), "v": v}
            self.log("hinge", x=V.xh, v=v)
            self.advance(tf(290))

            self.checkpoint(4)
        if resume < 5:
            # 5 off the Atlas onto Piri Reis: fit both boards to the hinge and this edge
            p, v = self.lead_at(B.DESIGN["piri_edge"])
            W, H = gA["size"]
            fit = SF.fit_hinged(W, H, B.HINGE_GAP, gA["psi"], float(p[1]), V.xh, float(p[0]), V.x239 - gA["under"])
            if fit is None:
                sys.exit("atlas: no fit")
            L["sheets"]["atlas1"] = self.sheet_fit("atlas", fit, 2 * W + B.HINGE_GAP, H, name="atlas1",
                                                   u_range=(-W - B.HINGE_GAP / 2, -B.HINGE_GAP / 2))
            L["sheets"]["atlas2"] = self.sheet_fit("atlas", fit, 2 * W + B.HINGE_GAP, H, name="atlas2",
                                                   u_range=(B.HINGE_GAP / 2, W + B.HINGE_GAP / 2))
            V.x383 = float(p[0])
            self.sheet_prov("piri", V.x383 - 0.01, p[1])
            self.zones.append({"kind": "fall", "x0": V.x383, "x1": V.x383 + FAR, "deg": B.PIRI_FALL_DEG})
            self.compile()
            st["piri_edge"] = {"x": V.x383, "y": float(p[1]), "v": v, "hinge_fit": fit["hinge"]}
            self.log("piri edge", x=V.x383, v=v, fit={k: fit[k] for k in ("psi", "hinge", "score")})
            self.advance(tf(388))

            self.checkpoint(5)
        if resume < 6:
            # 6 the khipu's seven knots: each where the marble is at its frame, beside its line so the knot glances it
            V.lvP = B.GROUNDS["piri"]["level"]
            rk, rc = B.KHIPU["knot_r"], B.KHIPU["cord_r"]
            dcontact = math.sqrt((R + rk) ** 2 - (R - rk) ** 2)
            knots = []
            for i, f in enumerate(B.DESIGN["knots"]):
                p, v = self.lead_at(f)
                dy = 0.0074
                dx = math.sqrt(max(dcontact ** 2 - dy ** 2, 0.0))
                k = (float(p[0]) + dx, float(p[1]) + dy, V.lvP + rk)
                knots.append(k)
                self.add(f"knot{i + 1}", {"type": "sphere", "size": (rk,), "pos": k, "friction": "0.7 0.002 0.0002"})
                self.compile()
                self.advance(tf(f) - 0.05)
            # the cord threads the knots and runs on past them both ways
            pts = [(knots[0][0] - 0.08, knots[0][1] + 0.004)] + [(k[0], k[1]) for k in knots] + \
                  [(knots[-1][0] + 0.10, knots[-1][1] - 0.002)]
            for i in range(len(pts) - 1):
                (x0, y0), (x1, y1) = pts[i], pts[i + 1]
                ln = math.hypot(x1 - x0, y1 - y0)
                ang = math.atan2(y1 - y0, x1 - x0)
                q = qmul(qz(math.degrees(ang)), qy(math.pi / 2))
                self.add(f"cord{i}", {"type": "capsule", "size": (rc, ln / 2), "pos": ((x0 + x1) / 2, (y0 + y1) / 2, V.lvP + rc),
                                      "quat": q, "friction": "0.7 0.002 0.0002"})
            self.compile()
            st["khipu"] = {"knots": knots, "cord": pts}
            self.advance(tf(436))

            self.checkpoint(6)
        if resume < 7:
            # 7 the galley on the Gutenberg leaf; Piri Reis's edge onto the leaf before it
            self.lay_galley()
            self.advance(tf(505))

            self.checkpoint(7)
        if resume < 8:
            # 8 Ino: the valley its folds make, the folds themselves
            ys = [float(self.pos(self.d, b)[1]) for b in MARBLES]
            d_, _ = self.rollout(tf(520))
            ys = [float(self.pos(d_, b)[1]) for b in MARBLES]
            V.yv = float(np.mean(ys))
            V.gI = B.GROUNDS["ino"]
            V.lvI = V.gI["level"]
            V.x_ino0 = L["stations"]["galley"]["leaf_exit"]
            self.zones.append({"kind": "valley", "x0": V.x_ino0, "x1": V.x_ino0 + FAR, "y": V.yv, "deg": 0.6, "w": 0.004})
            st["valley"] = {"y": V.yv, "x0": V.x_ino0}
            self.compile()
            for i, f in enumerate(B.DESIGN["ino_folds"]):
                p, v = self.lead_at(f)
                self.ridge(f"fold_ino{i + 1}", float(p[0]) + 0.0013, V.yv, V.lvI, 0.00007)
                self.compile()
                st[f"ino_fold{i + 1}"] = {"x": float(p[0]) + 0.0013, "v": v}
                self.log("ino fold", i=i + 1, x=p[0], v=v)
                self.advance(tf(f) - 0.1)

            self.checkpoint(8)
        if resume < 9:
            # 9 Morse's tape in the valley
            p, v = self.lead_at(B.DESIGN["tape"])
            V.x_tape = float(p[0]) + 0.0012
            self.box("tape", V.x_tape, V.x_tape + 1.0, V.yv - B.TAPE["w"] / 2, V.yv + B.TAPE["w"] / 2, V.lvI, V.lvI + B.TAPE["t"], fr("tape"))
            self.compile()
            st["tape"] = {"x0": V.x_tape, "y": V.yv, "v": v}
            self.log("tape", x=V.x_tape, v=v)
            self.advance(tf(B.DESIGN["tape"]) - 0.1)

            self.checkpoint(9)
        if resume < 10:
            # 10 the register's reel, its rim clipped by the lead marble
            self.lay_reel("reel_reg", B.DESIGN["reel_reg"], V.lvI + B.TAPE["t"], side=+1)
            self.advance(tf(B.DESIGN["reel_reg"]) - 0.2)

            self.checkpoint(10)
        if resume < 11:
            # 11 off Ino onto the blank card: a tile in the roof like the sheets (Ino's edge lies over its uphill side,
            # its downhill side over the page), laid across the path, its short side along it; the tape ends before
            p, v = self.lead_at(B.DESIGN["card"])
            V.x_card = float(p[0])
            fit = SF.fit_sheet(*V.gI["size"], V.gI["psi"], V.yv, V.x_card, x_under=V.x_ino0 - V.gI["under"])
            if fit is None:
                sys.exit("ino: no fit")
            L["sheets"]["ino"] = self.sheet_fit("ino", fit, *V.gI["size"])
            self.zones[-1]["x1"] = V.x_card
            # past Ino the bench's own top keeps the file: an old bench is worn very slightly hollow along its middle
            # (here 0.35 degrees across, under any visible depth), so the three marbles stay near one line
            self.zones.append({"kind": "valley", "x0": V.x_card, "x1": V.x_card + FAR, "y": V.yv, "deg": 0.35, "w": 0.006})
            self.box("tape", V.x_tape, V.x_card - 0.012, V.yv - B.TAPE["w"] / 2, V.yv + B.TAPE["w"] / 2, V.lvI,
                     V.lvI + B.TAPE["t"], fr("tape"))
            lvK = B.CARD["level"]
            self.box("card", V.x_card - 0.01, V.x_card - 0.01 + B.CARD["len"], V.yv - B.CARD["w"] / 2,
                     V.yv + B.CARD["w"] / 2, 0.0, lvK, fr("card"))
            L["sheets"]["card"] = {"cx": V.x_card - 0.01 + B.CARD["len"] / 2, "cy": V.yv, "psi": 90.0, "W": B.CARD["w"],
                                   "H": B.CARD["len"], "level": lvK}
            self.compile()
            st["card"] = {"x0": V.x_card, "x1": V.x_card - 0.01 + B.CARD["len"], "y": V.yv, "v": v}
            self.log("card", x=V.x_card, v=v)
            self.advance(tf(B.DESIGN["card"]) - 0.1)

            self.checkpoint(11)
        if resume < 12:
            # 12 off the card onto the typed page
            x_pe = st["card"]["x1"]
            self.sheet_prov("page", x_pe - 0.01, V.yv)
            self.compile()
            st["page_edge"] = {"x": x_pe}
            self.log("page edge", x=x_pe)
            # the typed page is small (a letter sheet): its downhill edge onto the chart goes where the file is at
            # f776 if the page reaches that far, else as far as the page reaches
            p, v = self.lead_at(B.DESIGN["chart_edge"])
            gG = B.GROUNDS["page"]
            fit = None
            V.x_ce = float(p[0])
            while V.x_ce > x_pe + 0.02:
                fit = SF.fit_sheet(*gG["size"], gG["psi"], float(p[1]), V.x_ce, x_under=x_pe - gG["under"], span=70)
                if fit is not None:
                    break
                V.x_ce -= 0.005
            if fit is None:
                sys.exit("page: no fit")
            L["sheets"]["page"] = self.sheet_fit("page", fit, *gG["size"])
            self.sheet_prov("chart", V.x_ce - 0.01, p[1])
            self.compile()
            st["chart_edge"] = {"x": V.x_ce, "v": v, "x_design": float(p[0])}
            self.log("chart edge", x=V.x_ce, v=v)
            V.lvG = B.GROUNDS["page"]["level"]
            self.checkpoint(12)
        if resume < 13:
            # 13 the Lumiere spool, clipped
            self.lay_reel("reel_film", B.DESIGN["reel_film"], V.lvG, side=+1)
            self.advance(tf(B.DESIGN["reel_film"]) - 0.2)

            self.checkpoint(13)
        if resume < 14:
            # 14 the film strip across the path (its perforations are the bumps)
            p, v = self.lead_at(B.DESIGN["strip"])
            self.lay_strip(float(p[0]) + 0.0012, float(p[1]), V.lvG)
            st["strip"]["v"] = v
            self.advance(tf(B.DESIGN["strip"]) - 0.1)

            self.checkpoint(14)
        if resume < 15:
            # 15 the platen, a free roller lying along the path's edge: glanced by the lead marble
            p, v = self.lead_at(B.DESIGN["platen"])
            pr, pl = B.PLATEN["r"], B.PLATEN["len"]
            # lying across the path's edge, its axis across the bench. The design's rule: a 300 g roller glanced by a
            # 4 g marble turns about (m v / M) / r; under a sixth of a turn it is pinned and only sounds. It would turn
            # well under a hundredth of a turn, and pinned, its cap's rim stops a slow file dead (found in the bake),
            # so it lies just clear of the file's line (3 mm), a landmark the marbles pass
            d740, _ = self.rollout(tf(B.DESIGN["platen"]))
            y_side = max(float(self.pos(d740, b)[1]) for b in MARBLES)
            yp = y_side + R + 0.003 + pl / 2
            xp = float(p[0]) + 0.004
            self.add("platen", {"type": "cylinder", "size": (pr, pl / 2), "pos": (xp, yp, V.lvG + pr),
                                "quat": (math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0), "friction": "0.6 0.0005 1e-6"})
            self.compile()
            # the design's rule: a free 300 g roller glanced by a 4 g marble at v turns by about (m v / M) / r per
            # second of drift before rolling resistance stops it; under a sixth of a turn it is pinned and only sounds
            turn = (B.MASS * v / 0.3) / pr * 0.5 / (2 * math.pi)
            st["platen"] = {"x": xp, "y_axis": yp, "axis": "y", "r": pr, "len": pl, "v": v, "free_turn_est": turn, "pinned": turn < 1 / 6}
            self.log("platen", x=p[0], v=v, turn=turn)
            self.advance(tf(B.DESIGN["platen"]) - 0.1)

            self.checkpoint(15)
        if resume < 16:
            # 16 off the page onto Admiralty chart 983 (laid at the page's own station, 12)
            self.log("chart edge passed", x=st["chart_edge"]["x"])

            self.checkpoint(16)
        if resume < 17:
            # 17 the stick chart beside the path: the file runs along its border, ticking its stick ends and shells
            self.lay_stick()
            self.advance(tf(B.DESIGN["lattice"]) + 1.0)

            self.checkpoint(17)
        if resume < 18:
            # 18 off the chart onto bare oak
            p, v = self.lead_at(B.DESIGN["oak_edge"])
            gC = B.GROUNDS["chart"]
            x_oe = max(float(p[0]), st["stick"]["x_end"] + 0.03)
            fit = SF.fit_sheet(*gC["size"], gC["psi"], float(p[1]), x_oe, x_under=V.x_ce - gC["under"])
            if fit is None:
                sys.exit("chart: no fit")
            L["sheets"]["chart"] = self.sheet_fit("chart", fit, *gC["size"])
            self.compile()
            st["oak_edge"] = {"x": x_oe, "v": v}
            self.log("oak edge", x=x_oe, v=v)
            self.advance(min(tf(B.DESIGN["oak_edge"]), self.d.time + 0.5))

            self.checkpoint(18)
        if resume < 19:
            # 19 the brass disc standing on its rim, struck by the lead marble
            self.lay_brass()
            self.advance(tf(B.PREFIX_FRAMES) - 1e-6)
            self.log("prefix end", lead=self.pos(self.d).tolist())


            self.checkpoint(19)

    def lay_galley(self):
        st = self.layout["stations"]
        GL = galley_local()
        lvL = B.GROUNDS["leaf"]["level"]
        p, v = self.lead_at(B.DESIGN["quad1"], b="lead")
        xg, yg = float(p[0]) + R + QUAD[0] + 0.001, float(p[1]) - LEAD_LINE_Y
        tgt = tf(B.DESIGN["quad1"])
        for it in range(6):
            self.galley_geoms(xg, yg, lvL, GL)
            p448, _ = self.lead_at(B.DESIGN["leaf_edge"], b="lead")
            leaf_x0 = xg + LEAF_EDGE_LOCAL - 0.42
            x_pe = min(max(float(p448[0]), leaf_x0 + 0.04), xg - 0.075)
            x_pe = max(x_pe, float(self.pos(self.d)[0]) + 0.012)
            gP = B.GROUNDS["piri"]
            fit = SF.fit_sheet(*gP["size"], gP["psi"], float(p448[1]), x_pe, x_under=st["piri_edge"]["x"] - gP["under"])
            if fit is None:
                sys.exit("piri: no fit")
            self.layout["sheets"]["piri"] = self.sheet_fit("piri", fit, *gP["size"])
            self.compile()
            self.galley_bodies(xg, yg, lvL, GL)
            tc = self.first_contact(tgt + 1.5, lambda pr: pr == "lead|quad1")
            self.log("galley try", it=it, xg=xg, t_contact=tc, target=tgt)
            if tc is None:
                xg -= 0.01
                continue
            if abs(tc - tgt) < 1.5 / 24:
                break
            xg -= v * (tc - tgt) * 0.9
        for z in self.zones:
            if z["kind"] == "fall" and z["deg"] == B.PIRI_FALL_DEG:
                z["x1"] = xg + LEAF_EDGE_LOCAL
        st["galley"] = {"x": xg, "y": yg, "level": lvL, "leaf_exit": xg + LEAF_EDGE_LOCAL, "t_quad1": tc,
                        "piri_exit": x_pe, "local": {k: (list(v_) if isinstance(v_, (list, tuple)) else v_)
                                                     for k, v_ in GL.items()}, "floor_t": FLOOR_T, "step_h": STEP_H,
                        "quad_half": QUAD, "stop_half": STOP, "stop_y": STOP_Y}
        self.sheet_prov("ino", xg + LEAF_EDGE_LOCAL - 0.01, yg)
        self.zones.append({"kind": "fall", "x0": xg + LEAF_EDGE_LOCAL, "x1": xg + LEAF_EDGE_LOCAL + FAR, "deg": B.LOWER_FALL_DEG})
        self.compile()

    def galley_geoms(self, xg, yg, z0, GL):
        brass = f"0.3 0.001 {B.RR['brass'] * R:.3e}"
        gx, gy = GL["galley"]["x"], GL["galley"]["y"]
        ft = z0 + FLOOR_T
        X = lambda a: xg + a  # noqa: E731
        Y = lambda a: yg + a  # noqa: E731
        # the leaf: portrait, its head uphill, the galley near its downhill edge (as in the proof)
        lw, lh = B.GROUNDS["leaf"]["size"]
        self.box("leaf", X(LEAF_EDGE_LOCAL - lh), X(LEAF_EDGE_LOCAL), Y(0.015 - lw / 2), Y(0.015 + lw / 2), 0.0, z0, fr("leaf"))
        self.layout["sheets"]["leaf"] = {"cx": X(LEAF_EDGE_LOCAL - lh / 2), "cy": Y(0.015), "psi": 90.0, "W": lw, "H": lh,
                                         "level": z0}
        self.box("galley", X(gx[0]), X(gx[1]), Y(gy[0]), Y(gy[1]), z0, ft, brass)
        a = math.atan2(FLOOR_T, RAMP_L)
        ln, ht = math.hypot(RAMP_L, FLOOR_T), 0.002
        self.add("galley_ramp", {"type": "box", "size": (ln / 2, (gy[1] - gy[0]) / 2, ht / 2),
                                 "pos": (X(-0.05 - RAMP_L / 2) + ht / 2 * math.sin(a), Y((gy[0] + gy[1]) / 2), z0 + FLOOR_T / 2 - ht / 2 * math.cos(a)),
                                 "quat": qy(-a), "friction": brass})
        self.box("rail", X(gx[0]), X(gx[1]), Y(gy[0]), Y(gy[0] + 0.003), ft, ft + 0.006, brass)
        self.box("rail2", X(gx[0]), X(gx[1]), Y(gy[1] - 0.003), Y(gy[1]), ft, ft + 0.006, brass)
        for nm in ("step_a", "step_b"):
            sx, sy = GL[nm]["x"], GL[nm]["y"]
            self.box(nm.replace("_a", "").replace("_b", "shelf") if False else ("step" if nm == "step_a" else "shelf"),
                     X(sx[0]), X(sx[1]), Y(sy[0]), Y(sy[1]), ft, ft + STEP_H, brass)

    def galley_bodies(self, xg, yg, z0, GL):
        ft = z0 + FLOOR_T
        for i, x in enumerate(GL["quad_x"]):
            self.place_free(f"quad{i + 1}", (xg + x, yg, ft + QUAD[2]))
        self.place_free("stop", (xg + GL["stop_x"], yg + STOP_Y, ft + STEP_H + STOP[2]))
        for k, (x, y) in enumerate(GL["pair"]):
            self.place_free(f"pair{k + 1}", (xg + x, yg + y, ft + STEP_H + R))

    def lay_reel(self, name, frame, level, side=+1):
        P = B.REEL_REG if name == "reel_reg" else B.REEL_FILM
        p, v = self.lead_at(frame)
        overlap = 0.003
        dy = R + P["r"] - overlap
        dx = math.sqrt((R + P["r"]) ** 2 - dy ** 2)
        c = (float(p[0]) + dx, float(p[1]) + side * dy, level)
        self.hinge_pos[name] = c
        self.compile()
        self.layout["stations"][name] = {"centre": c, "v": v, "r": P["r"], "h": P["h"]}
        self.log(name, centre=c, v=v)

    def lay_strip(self, x0, yp, level):
        w, ln, t = B.STRIP["w"], B.STRIP["len"], B.STRIP["t"]
        pw, ph, pitch = B.STRIP["perf"]
        frs = fr("page")
        z1 = level + t
        # the picture band, continuous; the two perforation rows, film between the holes
        self.box("strip_c", x0 + pw + 0.0005, x0 + w - pw - 0.0005, yp - ln / 2, yp + ln / 2, level, z1, frs)
        n = int(ln / pitch)
        k = 0
        for row, (xa, xb) in enumerate(((x0, x0 + pw + 0.0005), (x0 + w - pw - 0.0005, x0 + w))):
            for i in range(n):
                ya = yp - ln / 2 + i * pitch
                self.box(f"strip_p{row}_{i}", xa, xb, ya + ph, ya + pitch, level, z1, frs)
                k += 1
        self.compile()
        self.layout["stations"]["strip"] = {"x0": x0, "y": yp, "w": w, "len": ln, "level": level}
        self.log("strip", x=x0)

    def lay_stick(self):
        """The Rebbelib stick chart (T-19), rib for rib from its photograph: the keyed image's opaque pixels at 1 mm
        are the sticks, lashings and shells, raised on the shells; to a 16 mm marble they are walls. It lies beside the
        path, its top border along the file's line at a slight angle, so the marbles meet the stick ends and shells
        that stand out past the border, tick along them and leave in a line. The placement is searched by rollout."""
        from PIL import Image
        st = self.layout["stations"]
        W, H = B.STICK["size"]
        png = WORK / "stick-hfield.png"
        if not png.exists():
            im = Image.open(TEX / "T-19_keyed.png").getchannel("A").resize((int(W * 1000), int(H * 1000)), Image.BOX)
            a = (np.asarray(im) > 110).astype(np.uint8) * 255
            WORK.mkdir(parents=True, exist_ok=True)
            Image.fromarray(a).save(png)
        mask = np.asarray(Image.open(png)) > 0
        # the border's outermost opaque pixel per column, image top = +y: how far each column reaches
        cols = mask.shape[1]
        top = np.array([np.argmax(mask[:, c]) if mask[:, c].any() else mask.shape[0] for c in range(cols)])
        lvC = B.GROUNDS["chart"]["level"]
        zmax = B.STICK["raise"] + B.STICK["rib_h"] + 0.0005
        self.hfields["ribs"] = {"file": str(png).replace("\\", "/"), "size": f"{W / 2} {H / 2} {zmax} 0.002"}
        p792, v792 = self.lead_at(B.DESIGN["lattice"])
        # the file's lowest line (smallest y) while it crosses the chart's stretch: the border runs just below it,
        # so every marble passes along the border and the lowest ticks its stick ends and shells
        _, trk = self.rollout(tf(850), track=MARBLES)
        y_low = min(r[2] for b in MARBLES for r in trk[b] if r[1] > float(p792[0]) - 0.05)
        best = None
        for ang in (0.0, 1.5):
            for c_entry in (0.12, 0.30):
                for gap in (-0.004, -0.010, -0.016, -0.024):
                    # the column at c_entry (fraction of the width) has its top border at the file's line when the
                    # lead arrives (f792): the border then converges on the path by `ang` degrees
                    ci = int(c_entry * cols)
                    reach = H / 2 - top[ci] / 1000.0              # the border's +y reach above the chart's centre
                    cx = float(p792[0]) + (W / 2 - c_entry * W) + 0.01
                    cy = y_low - reach - R + gap - (c_entry * W - W / 2) * math.sin(math.radians(ang))
                    self.add("ribs", {"type": "hfield", "hfield": "ribs", "size": "", "pos": (cx, cy, lvC - 0.0005),
                                      "quat": qz(ang), "friction": fr("chart")})
                    self.compile()
                    ticks = {b: 0 for b in MARBLES}

                    def w(t, cs):
                        for c in cs:
                            a_, b_ = c["pair"].split("|")
                            if "ribs" in (a_, b_) and c["v_n"] > 0.004:
                                m_ = b_ if a_ == "ribs" else a_
                                if m_ in ticks:
                                    ticks[m_] += 1
                        return False
                    d_, trk2 = self.rollout(tf(B.PREFIX_FRAMES), watch=w, track=MARBLES)
                    xs = [float(self.pos(d_, b)[0]) for b in MARBLES]
                    vs = [self.speed(d_, b) for b in MARBLES]
                    x_end = cx + W / 2 * math.cos(math.radians(ang))
                    # stuck: a marble that ends the prefix slow while still beside the stick chart
                    x_end_c = cx + W / 2
                    slow = sum(max(0.0, 0.05 - v_) for v_, x_ in zip(vs, xs) if cx - W / 2 - 0.02 < x_ < x_end_c + 0.02)
                    moving = sum(1 for v_ in vs if v_ > 0.025)
                    n_t = sum(ticks.values())
                    score = slow * 400 + abs(min(n_t, 12) - 7) + (0 if n_t >= 3 else 10)
                    self.log("stick try", ang=ang, c=c_entry, gap=gap, ticks=ticks, moving=moving, score=score)
                    if best is None or score < best["score"]:
                        best = {"score": score, "cx": cx, "cy": cy, "ang": ang, "ticks": ticks, "x_end": x_end,
                                "c_entry": c_entry, "gap": gap}
        self.add("ribs", {"type": "hfield", "hfield": "ribs", "size": "", "pos": (best["cx"], best["cy"], lvC - 0.0005),
                          "quat": qz(best["ang"]), "friction": fr("chart")})
        self.compile()
        best.update(W=W, H=H, level=lvC, z=lvC - 0.0005, zmax=zmax, v=v792)
        st["stick"] = best
        self.log("stick chart", **{k: best[k] for k in ("cx", "cy", "ang", "ticks", "score")})

    def lay_brass(self):
        st = self.layout["stations"]
        p, v = self.lead_at(B.DESIGN["brass_hit"])
        A, T = B.BRASS["A"], B.BRASS["T"]
        lean = math.radians(B.BRASS["lean_deg"])
        # standing on its rim, its face square to the path, leaning a little downhill; struck 9 mm off its centre
        # line so the blow turns it as it tips
        x = float(p[0]) + R + T + 0.0004
        y = float(p[1]) + 0.009
        q = qy(math.pi / 2 + lean)
        zc = A * math.cos(lean) + T * math.sin(lean)
        xc = x + A * math.sin(lean)
        self.place_free("brass", (xc, y, zc), q)
        st["brass"] = {"x": xc, "y": y, "v": v, "lean_deg": B.BRASS["lean_deg"]}
        self.brass_watch = True
        self.log("brass", x=xc, v=v)

    def watch_brass(self):
        d = self.d
        i = self.bid["brass"]
        n = d.xmat[i].reshape(3, 3)[:, 2]
        tilt = math.acos(min(1.0, abs(n[2])))
        if tilt <= math.radians(B.BRASS["alpha_land_deg"]):
            c = np.array(d.xpos[i])
            # the rim's lowest point: the contact azimuth
            nn = n if n[2] > 0 else -n
            e = np.array([nn[0], nn[1], 0.0])
            ph = math.atan2(-e[1], -e[0]) if np.linalg.norm(e) > 1e-9 else 0.0
            self.brass_hand = {"t": float(d.time), "centre": c.tolist(), "tilt": tilt, "phase": ph}
            self.brass_watch = False
            self.place_free("brass", (PARK_X + 1.0, 2.0, B.BRASS["T"]))
            self.log("brass lands: the analytic settle takes over", **self.brass_hand)

    # ------------------------------------------------------------------ tails

    def run_tail(self, rec, state, x_prefix_view):
        """From the prefix's last state: bare oak for the years crossed in the dark, then black felt; the record laid
        where the lead marble comes to rest, its near edge just touching it."""
        F = B.FILMS[rec]
        self.restore(state)
        st = {}
        lead = self.pos(self.d, self.front(self.d))
        x_felt = x_prefix_view + B.OAK_PER_YEAR * (F["year"] - 1931)
        yv = float(lead[1])
        self.box("felt", x_felt, x_felt + B.FELT_LEN, yv - 0.6, yv + 0.6, 0, B.FELT_T, fr("felt"))
        self.compile()
        t_app = tf(B.PREFIX_FRAMES + F["tail"][0])
        d_, tr = self.rollout(t_app, track=MARBLES)
        fb = self.front(d_)
        a = np.array(tr[fb])
        sp = np.r_[0, np.linalg.norm(np.diff(a[:, 1:3], axis=0), axis=1) * 240]
        rest = 10 + int(np.argmax(sp[10:] < 0.002)) if (sp[10:] < 0.002).any() else len(a) - 1
        x_stop = float(a[rest, 1])
        Wr = F["width_m"]
        img = {"R-S-130": (1284, 1987), "R-S-16928": (2874, 1686), "R-C20-METAR-0851": (3840, 2160)}[F["tex"]]
        Hr = Wr * img[1] / img[0]
        x_rec = x_stop + math.sqrt(2 * R * B.RECORD_T) - 0.0002
        self.box("record", x_rec, x_rec + Wr, yv - Hr / 2, yv + Hr / 2, B.FELT_T, B.FELT_T + B.RECORD_T, fr("page"))
        self.compile()
        self.contacts, self.poses = [], {b: [] for b in self.poses}
        self.next_bake = self.d.time + 1.0 / 240
        self.advance(tf(B.PREFIX_FRAMES + sum(F["tail"][:2])))
        st.update(felt_x=x_felt, record={"x0": x_rec, "y": yv, "W": Wr, "H": Hr, "z": B.FELT_T + B.RECORD_T},
                  stop_rollout_t=float(a[rest, 0]), front=fb, lead_final=self.pos(self.d).tolist(),
                  marbles_final={b: self.pos(self.d, b).tolist() for b in MARBLES})
        return st

    def checkpoint(self, n):
        CK.mkdir(parents=True, exist_ok=True)
        d = self.d
        blob = {k: getattr(self, k) for k in ("geoms", "hinge_pos", "zones", "layout", "hfields", "contacts", "poses",
                                              "next_bake", "brass_watch", "brass_hand")}
        blob["v"] = vars(self.v)
        blob["state"] = {k: np.array(getattr(d, k)) for k in ("qpos", "qvel", "qacc_warmstart", "mocap_pos", "mocap_quat")}
        blob["time"] = float(d.time)
        (CK / f"{n:02d}.pkl").write_bytes(pickle.dumps(blob))

    def load_checkpoint(self, n):
        blob = pickle.loads((CK / f"{n:02d}.pkl").read_bytes())
        for k, val in blob.items():
            if k not in ("v", "state", "time"):
                setattr(self, k, val)
        self.v = SimpleNamespace(**blob["v"])
        self.compile(first=True)
        for k, a in blob["state"].items():
            getattr(self.d, k)[:] = a
        self.d.time = blob["time"]
        mujoco.mj_forward(self.m, self.d)
        print(f"resumed after station {n} at t {self.d.time:.2f}", flush=True)

    def snapshot(self):
        d = mujoco.MjData(self.m)
        mujoco.mj_copyData(d, self.m, self.d)
        return {"d": d, "geoms": json.loads(json.dumps(self.geoms)), "hinge": dict(self.hinge_pos),
                "zones": json.loads(json.dumps(self.zones)), "next_bake": self.next_bake}

    def restore(self, s):
        self.geoms = json.loads(json.dumps(s["geoms"]))
        self.hinge_pos = dict(s["hinge"])
        self.zones = json.loads(json.dumps(s["zones"]))
        self.d = s["d"]
        m0 = self.m
        self.compile()
        _ = m0
        self.brass_watch = False


def brass_analytic(hand, t_end):
    """Moffatt's settle for the brass disc from the tilt where MuJoCo's toppled rim caught, to its slap."""
    A, T = B.BRASS["A"], B.BRASS["T"]
    C = B.BRASS["C_HZ"]
    a1 = 4 * B.G / (A * (2 * math.pi * C) ** 2)              # tilt 1 s before the slap
    t_land, al = hand["t"], hand["tilt"]
    t_slap = t_land + (al / a1) ** 3
    k = 2 * math.pi * C * 6 / 5
    phi_slap = hand["phase"] + k * (t_slap - t_land) ** (5 / 6)
    cx, cy = hand["centre"][0], hand["centre"][1]
    rows = []
    psi = 0.0
    t = t_land
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
        centre = (cx, cy, A * sa + T * ca)
        rows.append([round(t, 6), *centre, *[float(v) for v in q]])
        t += 1 / 240
    return rows, {"t_land": t_land, "t_slap": t_slap, "C_hz": C, "alpha_land_deg": math.degrees(al),
                  "frame_land": t_land * 24, "frame_slap": t_slap * 24}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default="C20-METAR-0851,S-130,S-16928")
    ap.add_argument("--resume", type=int, default=0, help="continue from the checkpoint after this station")
    a = ap.parse_args()
    t_start = time.time()
    run = Run()
    if a.resume:
        run.load_checkpoint(a.resume)
    run.run_prefix(resume=a.resume)
    st = run.layout["stations"]
    brass_rows, brass_info = ([], {})
    if run.brass_hand:
        brass_rows, brass_info = brass_analytic(run.brass_hand, tf(B.PREFIX_FRAMES) + 12.0)
        run.poses["brass"] = [r for r in run.poses["brass"] if r[0] < run.brass_hand["t"]] + \
            [r for r in brass_rows if r[0] <= tf(B.PREFIX_FRAMES)]
    st["brass"].update(brass_info)
    # the bronze disc before the simulation starts (f36 to f60): analytic
    pre = []
    for k in range(int((T0 - 1.4) * 240)):
        t = 1.4 + k / 240
        c, q = run.disc_pose(t)
        pre.append([round(t, 6), *[float(v) for v in c], *[float(v) for v in q]])
    run.poses["disc"] = pre + run.poses["disc"]
    lead0 = [-(MF.A + R + 0.0004), 0.0, R]
    run.poses["lead"] = [[round(1.4 + k / 240, 6), *lead0, 1.0, 0.0, 0.0, 0.0] for k in range(int((T0 - 1.4) * 240))] + run.poses["lead"]
    OUT.mkdir(parents=True, exist_ok=True)
    E.write_jsonl(run.contacts, OUT / "run-contacts-1khz.jsonl")
    ev = E.events(run.contacts)
    if brass_info:
        ev = [e for e in ev if not ("brass" in e["pair"] and e["t_s"] > brass_info["t_land"])]
        ev.append({"t_s": round(brass_info["t_slap"], 4), "frame": round(brass_info["t_slap"] * 24, 2),
                   "pair": "brass|oak (analytic slap)", "v_n": 0.05, "impulse": 0.0})
        ev.sort(key=lambda e: e["t_s"])
    E.write_jsonl(ev, OUT / "run-events.jsonl")
    state = run.snapshot()
    prefix_meta = {"t0": T0, "dt": DT, "fall_deg": B.FALL_DEG, "latch_fall_deg": B.LATCH_FALL_DEG, "rr": B.RR,
                   "zones": run.zones, "geoms": run.geoms, "hinge": run.hinge_pos, "layout": run.layout,
                   "brass_rows_after": brass_rows, "wall_s": round(time.time() - t_start, 1)}
    (OUT / "run-bake.json").write_text(json.dumps({"meta": prefix_meta, "poses": run.poses}), encoding="utf-8")
    # the frame's right edge at f935 is about half a top-down field ahead of the brass disc: the felt starts past it
    x_view = st["brass"]["x"] + 0.47
    tails = {}
    for rec in [r for r in a.films.split(",") if r]:
        info = run.run_tail(rec, state, x_view)
        tev = E.events(run.contacts)
        E.write_jsonl(tev, OUT / f"run-tail-{rec}-events.jsonl")
        (OUT / f"run-tail-{rec}-bake.json").write_text(json.dumps({"meta": info, "geoms": run.geoms,
                                                                     "poses": run.poses}), encoding="utf-8")
        tails[rec] = info
        print("TAIL", rec, json.dumps(info, default=float), flush=True)
    (OUT / "run-layout.json").write_text(json.dumps({"stations": st, "sheets": run.layout["sheets"], "zones": run.zones,
                                                     "tails": tails, "geoms": state["geoms"], "hinge": run.hinge_pos,
                                                     "wall_s": round(time.time() - t_start, 1)}, default=float, indent=1),
                                         encoding="utf-8")
    print("events:", len(ev), "wall", round(time.time() - t_start, 1), "s")


if __name__ == "__main__":
    main()
