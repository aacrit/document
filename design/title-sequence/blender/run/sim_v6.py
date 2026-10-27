"""Title v6 (The Run with the instruments), days 2-3: the end-to-end path bake. MuJoCo only; nothing scripted after the
latch opens (D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/sim_v6.py [--no-lock]

One 30 mm clay ball from the latch's cup to rest on the felt. The ground is the records themselves: one height field
per plate (table_v6.stack_grid: each sheet at its real thickness, laid oldest over newest, draped over what is under
it) with that paper's measured rolling resistance (murr_v6), and the oak's own height field under them (the warp
that makes the two sags, the well cut to the felt). The fall is gravity tilted FALL_DEG along the path heading. The
latch is an initial condition (the ball at rest in the cup at f12, the disc already open, as v5c and v5d kept it);
the cup and the 25 degree ramp are a small oak block on board 1. The galley's twelve blank 4-to-em spaces are free
bodies on a brass floor plate; the weights and the globe are static convex parts (scans_v6 CoACD on their contact
band); the coins and the jeton are static hulls (close passes, never meant to be touched); the felt and the record
are v5c's boxes in v5d's well.

Placement by roll-out (spec section 3, as v4.1's cylinder glance was placed): every obstacle starts parked off the
table. A first pass rolls the ball with nothing in the way; the galley row is set so the ball's line meets sort 1 at
the spec's impact parameter; a second pass is snapshotted after the row, and the weights are set on the ball's right
at the impact parameter that turns it in the spec's range (searched); a third pass, snapshotted after the weights,
sets the globe's foot on the ball's left at the impact parameter and station that bring it to rest on the record's
centre line, the felt's rolling resistance (within the spec's 0.03-0.06) setting how far it rolls. The coins and the
jeton are then laid where the ball passes them at the spec's 3 cm. The bake is then run once more from f0 with
everything in place, and that run alone is the bake (the snapshots only choose positions).

Writes D:/document-media/title-sequence/v6/bake/ (bake.json: the ball and the sorts at 240 Hz; contacts-1khz.jsonl;
events.jsonl; placement.json; run.json: the measured run) for preview1_v6.py.
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
import table_v6 as T  # noqa: E402

OUT = Path("D:/document-media/title-sequence/v6/bake")
SCANS = Path("D:/document-media/title-sequence/v6/scans")
MURR = Path("D:/document-media/title-sequence/v6/murr/murr.json")
DT = 0.00025
SOLREF = "0.001 1"
BAKE_HZ = 240
LOG_HZ = 1000
T_MAX = 34.0
PARK = (-5.0, -5.0)

# restitution through MuJoCo's damping ratio: e = exp(-zeta pi / sqrt(1 - zeta^2))
def zeta_for(e):
    l = math.log(e)
    return -l / math.sqrt(math.pi ** 2 + l * l)


E_BRASS, E_WOOD, E_FELT = 0.5, 0.4, 0.1               # clay on brass (spec 3.4), on turned wood, on felt (3.7)
SPIN = {"paper": 3e-5, "oak": 3e-5, "felt": 5e-4}

# ------------------------------------------------------------------------------------------------ the galley

SORT = (0.0016, 0.00635, 0.01015)                    # 36-pt 4-to-em space, half extents (the proof's)
SORT_MASS = 0.0086
N_SORTS = 12
GAPS = np.linspace(0.013, 0.0105, N_SORTS - 1)        # the bd2dec0 taper, in the 0.5-0.65 of a sort's height range
FLOOR_T = 0.0010                                      # the brass floor plate
RAIL = (0.0015, 0.004)                                # far rail half width, half height
GALLEY_B = 0.85                                       # impact parameter of the glance on sort 1 (spec 3.3)
SORT1_S = 0.985                                       # sort 1's uphill face, along the path (on the leaf, past board 2)

# ------------------------------------------------------------------------------------------------ the latch

LATCH = {"cup_deg": 3.0, "cup_len": 0.012, "ramp_deg": 25.0, "drop": 0.0040, "ease": 0.008, "width": 0.050}
BALL_S0 = -0.004                                      # the ball's start station, in the cup (the open disc's place)


def latch_profile(n=2401):
    """The block's floor along the path, (s, z above the board): the cup falls 3 degrees forward from s = -cup_len
    (v5c's cup: the disc in front held the ball), eases into the 25 degree ramp and out of it onto the board, so the
    ball never meets a kink. The whole fall from the cup's back to the board is LATCH['drop']."""
    L = LATCH
    c3, c25 = math.tan(math.radians(L["cup_deg"])), math.tan(math.radians(L["ramp_deg"]))
    e = L["ease"]

    def sched(hold):
        ss = np.linspace(-L["cup_len"], 2 * e + hold, n)
        u = np.clip(ss / e, 0, 1)
        sl = np.where(ss >= 0, c3 + (c25 - c3) * u * u * (3 - 2 * u), c3)
        u2 = np.clip((ss - e - hold) / e, 0, 1)
        sl = np.where(ss >= e + hold, c25 * (1 - u2 * u2 * (3 - 2 * u2)), sl)
        drop = np.concatenate([[0.0], np.cumsum(0.5 * (sl[1:] + sl[:-1]) * np.diff(ss))])
        return ss, drop
    lo, hi = 0.0, 0.05
    for _ in range(60):
        mid = (lo + hi) / 2
        if sched(mid)[1][-1] < L["drop"]:
            lo = mid
        else:
            hi = mid
    ss, drop = sched(hi)
    return ss, np.maximum(L["drop"] - drop, 0.0)


# ------------------------------------------------------------------------------------------------ the model


def load_parts(sid):
    d = np.load(SCANS / f"{sid}-collider.npz")
    n = len([k for k in d.files if k.startswith("v")])
    return [(d[f"v{i}"], d[f"f{i}"]) for i in range(n)]


def murr():
    """MuJoCo rolling coefficients (m) per surface from the calibration (murr_v6)."""
    r = json.loads(MURR.read_text(encoding="utf-8"))
    return {k: v["mujoco_roll_len_m"] for k, v in r["surfaces"].items()}


def hfields():
    """[(name, surface, x0, y0, cell, Z)] for the oak and each plate."""
    xs, ys, wz, tops, cur = T.stack_grid()
    cell = xs[1] - xs[0]
    out = []
    X, Y = np.meshgrid(xs, ys)
    oak = wz.copy()
    inw = (X >= T.WELL["x"][0]) & (X <= T.WELL["x"][1]) & (Y >= T.WELL["y"][0]) & (Y <= T.WELL["y"][1])
    oak[inw] = T.FELT_TOP - T.WELL["felt_t"] - 0.002
    out.append(("oak", "oak", xs[0], ys[0], cell, oak))
    for sh in T.SHEETS:
        top = tops[sh["name"]]
        m = np.isfinite(top)
        jj, ii = np.nonzero(m)
        j0, j1, i0, i1 = jj.min() - 2, jj.max() + 3, ii.min() - 2, ii.max() + 3
        j0, i0 = max(j0, 0), max(i0, 0)
        sub = top[j0:j1, i0:i1]
        floor = min(np.nanmin(sub), float(np.min(cur[j0:j1, i0:i1])), float(np.min(oak[j0:j1, i0:i1]))) - 0.003
        out.append((sh["name"], sh["surface"], xs[i0], ys[j0], cell, np.where(np.isfinite(sub), sub, floor)))
    return out


def _mesh_xml(name, v, f):
    vs = " ".join(f"{a:.6f}" for a in np.asarray(v).ravel())
    fs = " ".join(str(int(a)) for a in np.asarray(f).ravel())
    return f'<mesh name="{name}" vertex="{vs}" face="{fs}"/>'


def model_xml(hf, roll, felt_mu):
    assets, geoms = [], []
    for k, (name, surf, x0, y0, cell, Z) in enumerate(hf):
        nrow, ncol = Z.shape
        rx, ry = (ncol - 1) * cell / 2, (nrow - 1) * cell / 2
        zmin, zmax = float(Z.min()), float(Z.max())
        assets.append(f'<hfield name="hf {name}" nrow="{nrow}" ncol="{ncol}" size="{rx:.6f} {ry:.6f} '
                      f'{max(zmax - zmin, 1e-5):.7f} 0.002"/>')
        spin = SPIN["oak" if surf == "oak" else "paper"]
        geoms.append(f'<geom name="{name}" type="hfield" hfield="hf {name}" pos="{x0 + rx:.6f} {y0 + ry:.6f} '
                     f'{zmin:.7f}" friction="0.5 {spin:.1e} {roll[surf]:.4e}" condim="6" solref="{SOLREF}"/>')
    # the latch block on board 1: the cup and the eased 25 degree ramp as box facets, each sitting on the board
    ss, zz = latch_profile()
    xs_, ys_, _wz, _tops, cur = T.stack_grid()
    hdg = math.radians(T.HEADING_DEG)

    def board(s_):
        x_, y_ = T.point(np.array([s_]))
        return float(T.sample(cur, xs_, ys_, x_, y_)[0])
    i0 = int(np.searchsorted(ss, 0.0))
    ks = np.unique(np.concatenate([np.linspace(0, i0, 4), np.linspace(i0, len(ss) - 1, 15)]).astype(int))
    for q, (a, b) in enumerate(zip(ks[:-1], ks[1:])):
        sa, sb = ss[a], ss[b]
        za, zb = board(sa) + zz[a], board(sb) + zz[b]
        L = math.hypot(sb - sa, zb - za)
        pitch = math.atan2(za - zb, sb - sa)            # downhill along +s
        th = 0.003
        # the facet's top face is the profile chord: its centre sits th/2 below the chord along the facet normal
        nx, nz = math.sin(pitch), math.cos(pitch)
        x, y = T.point(np.array([(sa + sb) / 2]))
        px, py = float(x[0]) - th / 2 * nx * math.cos(hdg), float(y[0]) - th / 2 * nx * math.sin(hdg)
        qw, qv = _quat_yaw_pitch(hdg, pitch)
        geoms.append(f'<geom name="latch {"cup" if sb <= 0 else "ramp"} {q}" type="box" size="{L / 2 + 0.0001:.6f} '
                     f'{LATCH["width"] / 2} {th / 2}" pos="{px:.6f} {py:.6f} {(za + zb) / 2 - th / 2 * nz:.6f}" '
                     f'quat="{qw:.8f} {qv[0]:.8f} {qv[1]:.8f} {qv[2]:.8f}" friction="0.5 {SPIN["oak"]:.1e} '
                     f'{roll["oak"]:.4e}" condim="6" solref="{SOLREF}" rgba="0.5 0.35 0.2 1"/>')
    z_ball = board(BALL_S0) + float(np.interp(BALL_S0, ss, zz)) + T.R + 2e-5
    # the galley: floor plate, far rail (parked; set by place_galley)
    bz = f"0.3 {SPIN['paper']:.1e} 1e-5"
    geoms.append(f'<geom name="galley floor" type="box" size="0.11 {SORT[1] + 0.001:.5f} {FLOOR_T / 2}" '
                 f'pos="{PARK[0]} {PARK[1]} {FLOOR_T / 2}" friction="{bz}" condim="4" solref="0.004 1" rgba="0.7 0.55 0.25 1"/>')
    geoms.append(f'<geom name="galley rail" type="box" size="0.11 {RAIL[0]} {RAIL[1]}" pos="{PARK[0]} {PARK[1] + 0.01} '
                 f'{FLOOR_T + RAIL[1]}" friction="{bz}" condim="4" solref="0.004 1" rgba="0.7 0.55 0.25 1"/>')
    bodies = []
    for i in range(N_SORTS):
        bodies.append(f'<body name="sort{i + 1}" pos="{PARK[0] - 0.2 + 0.016 * i} {PARK[1]} {FLOOR_T + SORT[2] + 1e-5}">'
                      f'<freejoint/><geom name="sort{i + 1}" type="box" size="{SORT[0]} {SORT[1]} {SORT[2]}" '
                      f'mass="{SORT_MASS}" friction="0.3 0.002 0.0001" condim="4" solref="0.004 1" '
                      f'rgba="0.55 0.55 0.58 1"/></body>')
    # the scans: convex parts (weights, globe) and hulls (coins, jeton), all parked
    obj = {"weights": (E_BRASS, "0.3"), "globe": (E_WOOD, "0.5"), "FS-coin-dupondius-octavian": (E_BRASS, "0.3"),
           "FS-coin-sesterce-trajan": (E_BRASS, "0.3"), "jeton": (E_BRASS, "0.3")}
    short = {"FS-coin-dupondius-octavian": "coin dupondius", "FS-coin-sesterce-trajan": "coin sestertius"}
    for sid, (e, mu) in obj.items():
        nm = short.get(sid, sid)
        for k, (v, f) in enumerate(load_parts(sid)):
            assets.append(_mesh_xml(f"m {nm} {k}", v, f))
            geoms.append(f'<geom name="{nm} {k}" type="mesh" mesh="m {nm} {k}" pos="{PARK[0]} {PARK[1]} 0" '
                         f'friction="{mu} {SPIN["paper"]:.1e} 1e-5" condim="6" solref="0.002 {zeta_for(e):.4f}" '
                         f'rgba="0.6 0.45 0.2 1"/>')
    # the well: felt, the record on it, the oak walls past and beside it (v5c's)
    wx, wy = T.WELL["x"], T.WELL["y"]
    ft = T.FELT_TOP
    geoms.append(f'<geom name="felt" type="box" size="{(wx[1] - wx[0]) / 2:.5f} {(wy[1] - wy[0]) / 2:.5f} '
                 f'{T.WELL["felt_t"] / 2:.5f}" pos="{(wx[0] + wx[1]) / 2:.5f} {(wy[0] + wy[1]) / 2:.5f} '
                 f'{ft - T.WELL["felt_t"] / 2:.6f}" friction="0.9 {SPIN["felt"]:.1e} {felt_mu * T.R:.4e}" condim="6" '
                 f'solref="0.004 {zeta_for(E_FELT):.4f}" rgba="0.03 0.03 0.03 1"/>')
    r = T.RECORD_RECT
    geoms.append(f'<geom name="record" type="box" size="{(r[1] - r[0]) / 2:.5f} {(r[3] - r[2]) / 2:.5f} 0.00006" '
                 f'pos="{(r[0] + r[1]) / 2:.5f} {(r[2] + r[3]) / 2:.5f} {ft + 0.00006:.6f}" friction="0.5 3e-5 1e-4" '
                 f'condim="6" solref="{SOLREF}" rgba="0.9 0.88 0.8 1"/>')
    for nm, sx, sy, cx, cy in (("far", 0.002, (wy[1] - wy[0]) / 2, wx[1] + 0.002, (wy[0] + wy[1]) / 2),
                               ("back", (wx[1] - wx[0]) / 2, 0.002, (wx[0] + wx[1]) / 2, wy[1] + 0.002),
                               ("front", (wx[1] - wx[0]) / 2, 0.002, (wx[0] + wx[1]) / 2, wy[0] - 0.002)):
        geoms.append(f'<geom name="well wall {nm}" type="box" size="{sx:.5f} {sy:.5f} 0.015" pos="{cx:.5f} {cy:.5f} '
                     f'{ft + 0.012:.5f}" condim="3" rgba="0 0 0 0"/>')
    x0, y0 = (float(a[0]) for a in T.point(np.array([BALL_S0])))
    z0 = z_ball
    g = T.gravity_vec()
    W, H = T.TABLE["size"]
    return f"""<mujoco model="title v6 the run with the instruments">
  <compiler angle="radian"/>
  <option timestep="{DT}" gravity="{g[0]:.7f} {g[1]:.7f} {g[2]:.7f}" integrator="implicitfast" cone="elliptic"
          impratio="10"/>
  <size memory="200M"/>
  <visual><global offwidth="1600" offheight="900"/></visual>
  <asset>
    {chr(10).join('    ' + a for a in assets)}
  </asset>
  <worldbody>
    <camera name="top" pos="{W / 2} {H / 2} 3.2" xyaxes="1 0 0 0 1 0" fovy="35"/>
    {chr(10).join('    ' + g_ for g_ in geoms)}
    {chr(10).join('    ' + b for b in bodies)}
    <body name="ball" pos="{x0:.6f} {y0:.6f} {z0:.7f}">
      <freejoint/>
      <geom name="ball" type="sphere" size="{T.R}" density="{T.RHO_CLAY}" friction="0.5 0 0" condim="6"
            solref="{SOLREF}" solmix="0.0001" rgba="0.80 0.45 0.25 1"/>
    </body>
  </worldbody>
</mujoco>"""


def _quat_yaw_pitch(yaw, pitch):
    """Quaternion of yaw about z then pitch about the yawed y (nose down positive), w first."""
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    qy = np.array([cy, 0, 0, sy])
    qp = np.array([cp, 0, sp, 0])
    q = np.zeros(4)
    mujoco.mju_mulQuat(q, qy, qp)
    return float(q[0]), q[1:]


class World:
    """The compiled model and the means to move what roll-out places."""

    def __init__(self, felt_mu=0.045):
        self.hf = hfields()
        self.roll = murr()
        self.felt_mu = felt_mu
        xml = model_xml(self.hf, self.roll, felt_mu)
        self.m = mujoco.MjModel.from_xml_string(xml)
        m = self.m
        for k, (name, surf, x0, y0, cell, Z) in enumerate(self.hf):
            hid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_HFIELD, f"hf {name}")
            adr, nr, nc = m.hfield_adr[hid], m.hfield_nrow[hid], m.hfield_ncol[hid]
            zmin, zmax = float(Z.min()), float(Z.max())
            m.hfield_data[adr:adr + nr * nc] = ((Z - zmin) / max(zmax - zmin, 1e-5)).astype(np.float32).ravel()
        self.gname = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or f"g{i}" for i in range(m.ngeom)]
        self.gid = {n: i for i, n in enumerate(self.gname)}
        self.ball = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "ball")
        self.sorts = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"sort{i + 1}") for i in range(N_SORTS)]
        # compiled offsets of every parked mesh part (MuJoCo moves a mesh to its inertial frame at compile)
        self.parts = {}
        for i, n in enumerate(self.gname):
            if m.geom_type[i] == mujoco.mjtGeom.mjGEOM_MESH:
                pref = n.rsplit(" ", 1)[0]
                self.parts.setdefault(pref, []).append((i, m.geom_pos[i].copy() - np.array([*PARK, 0.0]),
                                                        m.geom_quat[i].copy()))
        self.placed = {}
        self.ground = T.stack_grid()

    def z_ground(self, x, y):
        xs, ys, wz, tops, cur = self.ground
        return float(T.sample(cur, xs, ys, np.array([x]), np.array([y]))[0])

    def place(self, pref, x, y, yaw, z=None, support=None):
        """Set a scan down at (x, y), turned yaw (radians), its lowest point on the ground under its footprint (the
        highest support under any part's base, a rigid object resting on its highest point)."""
        m = self.m
        if z is None:
            zs = []
            for i, off, q in self.parts[pref]:
                v = self._part_vertices(i, off, q, x, y, yaw, 0.0)
                low = v[v[:, 2] < v[:, 2].min() + 0.0005]
                for p in low[:: max(1, len(low) // 40)]:
                    zs.append(self.z_ground(p[0], p[1]))
            z = max(zs)
        c, s = math.cos(yaw), math.sin(yaw)
        Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        qy = np.array([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)])
        for i, off, q in self.parts[pref]:
            m.geom_pos[i] = Rz @ off + np.array([x, y, z])
            qq = np.zeros(4)
            mujoco.mju_mulQuat(qq, qy, q)
            m.geom_quat[i] = qq
        self.placed[pref] = {"x": x, "y": y, "yaw_deg": math.degrees(yaw), "z": z}

    def park(self, pref):
        self.place(pref, PARK[0], PARK[1], 0.0, z=0.0)
        self.placed.pop(pref, None)

    def _part_vertices(self, i, off, q, x, y, yaw, z):
        m = self.m
        mid = m.geom_dataid[i]
        adr, n = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        v = m.mesh_vert[adr:adr + n].astype(float)
        R0 = np.zeros(9)
        mujoco.mju_quat2Mat(R0, q)
        c, s = math.cos(yaw), math.sin(yaw)
        Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        return (Rz @ (R0.reshape(3, 3) @ v.T)).T + Rz @ off + np.array([x, y, z])

    def outline(self, pref, z_band=(0.0, 0.03)):
        """The placed object's parts' vertices within a height band above its base (for plots and clearances)."""
        P = self.placed[pref]
        pts = []
        for i, off, q in self.parts[pref]:
            v = self._part_vertices(i, off, q, P["x"], P["y"], math.radians(P["yaw_deg"]), P["z"])
            pts.append(v[(v[:, 2] >= P["z"] + z_band[0]) & (v[:, 2] <= P["z"] + z_band[1])])
        return np.concatenate(pts) if pts else np.zeros((0, 3))

    def local_band(self, pref):
        """Parts' vertices in the object's own frame (unplaced, base at 0), for radii and directions."""
        pts = []
        for i, off, q in self.parts[pref]:
            pts.append(self._part_vertices(i, off, q, 0.0, 0.0, 0.0, 0.0))
        v = np.concatenate(pts)
        return v - np.array([0, 0, v[:, 2].min()])

    def place_galley(self, d, s1, n_row):
        """The floor plate, the far rail and the twelve sorts along the path's heading, the row's axis at n_row, sort
        1's uphill face at station s1 (flush with the plate's open mouth), the plate's near edge (the lip) flush with
        the sorts' near faces."""
        m = self.m
        hdg = math.radians(T.HEADING_DEG)
        u, nv = T.U, T.N
        centres, s = [], s1 + SORT[0]
        for i in range(N_SORTS):
            centres.append(s)
            if i < N_SORTS - 1:
                s += 2 * SORT[0] + GAPS[i]
        s_end = centres[-1] + SORT[0] + 2 * SORT[2] + 0.01
        L = s_end - s1
        cs = (s1 + s_end) / 2
        p = np.array(T.START) + cs * u + n_row * nv
        zf = max(self.z_ground(*(np.array(T.START) + ss * u + nn * nv)) for ss in np.linspace(s1, s_end, 9)
                 for nn in (n_row - SORT[1], n_row + SORT[1] + 0.003))
        fl = self.gid["galley floor"]
        m.geom_size[fl] = [L / 2, SORT[1] + 0.0015, FLOOR_T / 2]
        # the floor's near edge flush with the sorts' near faces: shift its centre 1.5 mm to the far side
        m.geom_pos[fl] = [*(p + 0.00075 * nv), zf + FLOOR_T / 2]
        qz = np.array([math.cos(hdg / 2), 0, 0, math.sin(hdg / 2)])
        m.geom_quat[fl] = qz
        rl = self.gid["galley rail"]
        m.geom_size[rl] = [L / 2, RAIL[0], RAIL[1]]
        m.geom_pos[rl] = [*(p + (SORT[1] + 0.0015 + RAIL[0]) * nv), zf + FLOOR_T + RAIL[1]]
        m.geom_quat[rl] = qz
        for i, bid in enumerate(self.sorts):
            adr = m.jnt_qposadr[m.body_jntadr[bid]]
            c = np.array(T.START) + centres[i] * u + n_row * nv
            d.qpos[adr:adr + 3] = [c[0], c[1], zf + FLOOR_T + SORT[2] + 2e-6]
            d.qpos[adr + 3:adr + 7] = qz
            dadr = m.jnt_dofadr[m.body_jntadr[bid]]
            d.qvel[dadr:dadr + 6] = 0.0
        self.placed["galley"] = {"s1": s1, "n_row": n_row, "z_floor": zf, "s_end": s_end,
                                 "sort_s": [float(c) for c in centres], "gaps_m": GAPS.tolist(), "b": GALLEY_B}


# ------------------------------------------------------------------------------------------------ running


def new_data(w):
    d = mujoco.MjData(w.m)
    mujoco.mj_forward(w.m, d)
    return d


class Recorder:
    def __init__(self, w):
        self.w = w
        self.poses = {"ball": []}
        self.poses.update({f"sort{i + 1}": [] for i in range(N_SORTS)})
        self.track = []
        self.contacts = []
        self.next_bake = 0.0

    def sample(self, d, t):
        w = self.w
        if t >= self.next_bake - 1e-9:
            p, q = d.xpos[w.ball], d.xquat[w.ball]
            v = d.qvel[w.m.jnt_dofadr[w.m.body_jntadr[w.ball]]:][:3]
            self.poses["ball"].append([round(t, 6), *map(float, p), *map(float, q)])
            self.track.append([round(t, 6), float(p[0]), float(p[1]), float(p[2]), float(v[0]), float(v[1]),
                               float(v[2])])
            for i, bid in enumerate(w.sorts):
                self.poses[f"sort{i + 1}"].append([round(t, 6), *map(float, d.xpos[bid]), *map(float, d.xquat[bid])])
            self.next_bake += 1.0 / BAKE_HZ

    def log_contacts(self, d, t):
        w = self.w
        m = w.m
        f6 = np.zeros(6)
        for ci in range(d.ncon):
            c = d.contact[ci]
            b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
            if b1 == 0 and b2 == 0:
                continue
            n1, n2 = w.gname[c.geom1], w.gname[c.geom2]
            if not ("ball" in (n1, n2) or n1.startswith("sort") or n2.startswith("sort")):
                continue
            mujoco.mj_contactForce(m, d, ci, f6)
            n = np.array(c.frame[:3])
            v1 = np.zeros(6)
            v2 = np.zeros(6)
            mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, b1, v1, 0)
            mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, b2, v2, 0)
            p = np.array(c.pos)
            va = v1[3:] + np.cross(v1[:3], p - d.xpos[b1])
            vb = v2[3:] + np.cross(v2[:3], p - d.xpos[b2])
            self.contacts.append({"t_s": round(t, 4), "pair": "|".join(sorted((n1, n2))),
                                  "v_n": float(-np.dot(vb - va, n)), "f_n": float(f6[0]),
                                  "pos": [round(float(a), 5) for a in p]})


def run(w, d, t_end, rec=None, stop_at=None, t0_title=T.T_RELEASE):
    """Step until title time t_end, the ball's rest in the well, a stall, or stop_at(d) returns True. Title time =
    d.time + t0_title (the latch opens at f12)."""
    rec = rec or Recorder(w)
    m = w.m
    per_log = int(round(1 / (LOG_HZ * DT)))
    still, stall = None, None
    k = 0
    status = "time"
    while d.time + t0_title < t_end:
        t = d.time + t0_title
        rec.sample(d, t)
        if k % per_log == 0:
            rec.log_contacts(d, t)
        p = d.xpos[w.ball]
        v = float(np.linalg.norm(d.qvel[m.jnt_dofadr[m.body_jntadr[w.ball]]:][:3]))
        in_well = T.WELL["x"][0] < p[0] < T.WELL["x"][1] and T.WELL["y"][0] < p[1] < T.WELL["y"][1]
        if v < 0.001 and in_well:
            still = t if still is None else still
            if t - still > 0.5:
                status = "rest"
                break
        else:
            still = None
        if v < 0.004 and not in_well and d.time > 1.0:
            stall = t if stall is None else stall
            if t - stall > 1.0:
                status = "stall"
                break
        else:
            stall = None
        if p[2] < T.FELT_TOP - 0.05 or not (-0.1 < p[0] < 3.1 and -0.1 < p[1] < 1.8):
            status = "lost"
            break
        if stop_at is not None and stop_at(d):
            status = "stop"
            break
        mujoco.mj_step(m, d)
        k += 1
    rec.status = status
    rec.t_rest = (still if status == "rest" else None)
    return rec


def snapshot(w, d):
    spec = mujoco.mjtState.mjSTATE_INTEGRATION
    st = np.zeros(mujoco.mj_stateSize(w.m, spec))
    mujoco.mj_getState(w.m, d, st, spec)
    return st


def restore(w, st):
    spec = mujoco.mjtState.mjSTATE_INTEGRATION
    d = mujoco.MjData(w.m)
    mujoco.mj_setState(w.m, d, st, spec)
    mujoco.mj_forward(w.m, d)
    return d


def ball_s(w, d):
    p = d.xpos[w.ball]
    return float(T.along(p[0], p[1]))


# ------------------------------------------------------------------------------------------------ reading a run


def track_array(rec):
    return np.array(rec.track)


def heading_around(A, t_a, t_b, before=True, span=0.04):
    """Mean velocity over a short window before t_a or after t_b."""
    T_ = A[:, 0]
    m = (T_ >= t_a - span) & (T_ < t_a) if before else (T_ > t_b) & (T_ <= t_b + span)
    v = A[m][:, 4:6].mean(0)
    return v


def contact_spans(contacts, pred):
    """First and last time of the ball contacts whose pair satisfies pred, or None."""
    ts = [c["t_s"] for c in contacts if pred(c["pair"])]
    return (min(ts), max(ts)) if ts else None


def glance(rec, cls):
    """Turn (deg, left positive) and speed kept over a designed glance, from the ball's velocity just before its
    first contact and just after its last."""
    sp = contact_spans(rec.contacts, lambda p: T.contact_class(p) == cls)
    if sp is None:
        return None
    A = track_array(rec)
    vb = heading_around(A, sp[0], sp[1], True)
    va = heading_around(A, sp[0], sp[1], False, span=0.06)
    return {"t": sp, "turn_deg": T.turn_deg(vb, va), "speed_kept": float(np.linalg.norm(va) / np.linalg.norm(vb)),
            "v_before": float(np.linalg.norm(vb)), "v_after": float(np.linalg.norm(va))}


# ------------------------------------------------------------------------------------------------ roll-out placement


def line_at(rec, s_at):
    """The ball's position and unit velocity where it first passes station s_at."""
    A = track_array(rec)
    s = T.along(A[:, 1], A[:, 2])
    i = int(np.argmax(s >= s_at))
    v = A[i, 4:6] / np.linalg.norm(A[i, 4:6])
    return A[i, 1:3], v, A[i, 0]


def band_radius(w, pref, direction, z=T.R):
    """The object's extent from its footprint centre toward `direction` (unit, object frame) at the ball's equator
    height (the band within 4 mm of it): the radius the ball meets."""
    v = w.local_band(pref)
    band = v[np.abs(v[:, 2] - z) < 0.004]
    return float(np.max(band[:, :2] @ direction))


def search(f, lo, hi, target, tol, n=14):
    """Bisection on a monotone-ish f between lo and hi for f(x) = target; returns (x, f(x), history)."""
    hist = []
    flo, fhi = f(lo), f(hi)
    hist += [(lo, flo), (hi, fhi)]
    if (flo - target) * (fhi - target) > 0:
        best = min(hist, key=lambda h: abs(h[1] - target))
        return best[0], best[1], hist
    for _ in range(n):
        mid = (lo + hi) / 2
        fm = f(mid)
        hist.append((mid, fm))
        if abs(fm - target) <= tol:
            return mid, fm, hist
        if (flo - target) * (fm - target) <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    best = min(hist, key=lambda h: abs(h[1] - target))
    return best[0], best[1], hist
