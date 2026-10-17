"""The Run: the bronze disc's settle, analytic (Moffatt 2000), stdlib only (Blender, MuJoCo driver and pytest all
import it).

A disc of radius A and thickness T rolling on its rim with a small tilt ALPHA from flat: its contact point circles
the (nearly fixed) centre at the precession rate OMEGA, with OMEGA^2 = 4 g / (A * ALPHA) for small ALPHA. Moffatt's
viscous spin-down gives a finite-time singularity: ALPHA ~ (t0 - t)^(1/3), so OMEGA ~ (t0 - t)^(-1/6): the whir
quickens and stops at t0 (the slap). The level comes from the chosen real recording (Freesound 197214, Yuval, CC0):
its pulse rate one second before its stop is C_HZ, and its stop (the slap) is placed at the design's f120. The
exponent is Moffatt's, not fitted: that recording's pulse train is too irregular to fit a free exponent (see the
proof report).

Pose: the contact point P = C + A cos(ALPHA) e(phi) on the bench, e(phi) = (cos phi, sin phi, 0); the disc's in-plane
direction to P is u = cos(ALPHA) e - sin(ALPHA) z, its normal n = sin(ALPHA) e + cos(ALPHA) z, so the rim's lowest
corner touches the bench exactly. The body also turns slowly about its own normal (rolling without slip):
d psi / dt = -OMEGA (1 - cos ALPHA). After the slap the disc skitters: the slap's tangential impulse slides it a
short way along the contact path's last tangent under kinetic friction, then it lies still.
"""

from __future__ import annotations

import math

G = 9.81
FPS = 24
A = 0.0225                 # 45 mm bronze disc
T = 0.003                  # 3 mm thick
C_HZ = 24.0                # precession rate 1 s before the slap (Hz), from the recording's pulse train
T_SLAP = 120 / FPS         # title time of the slap: f120 (5.0 s)
PHI_SLAP = 0.0             # phase at the slap, so the last tangent (and the skitter) runs across the slope (+y)
SKITTER = 0.008            # m slid after the slap
MU_K = 0.25                # bronze on oak, kinetic


def rate_hz(t: float) -> float:
    """Precession rate (Hz) at title time t < T_SLAP."""
    return C_HZ * max(T_SLAP - t, 1e-9) ** (-1.0 / 6.0)


def omega(t: float) -> float:
    return 2.0 * math.pi * rate_hz(t)


def alpha(t: float) -> float:
    """Tilt from flat (rad): 4 g / (A OMEGA^2), so ALPHA ~ (t0 - t)^(1/3); 0 from the slap on."""
    if t >= T_SLAP:
        return 0.0
    return 4.0 * G / (A * omega(t) ** 2)


def phase(t: float) -> float:
    """Contact-point azimuth: the closed-form integral of OMEGA, equal to PHI_SLAP at the slap."""
    tt = min(t, T_SLAP)
    k = 2.0 * math.pi * C_HZ * 6.0 / 5.0
    return PHI_SLAP - k * (T_SLAP - tt) ** (5.0 / 6.0)


def spin(t: float, t_ref: float = 0.0, n: int = 4000) -> float:
    """The body's own rotation about its normal since t_ref (rad), integrated: -OMEGA (1 - cos ALPHA)."""
    tt = min(t, T_SLAP)
    if tt <= t_ref:
        return 0.0
    h = (tt - t_ref) / n
    s = 0.0
    for i in range(n):
        m = t_ref + (i + 0.5) * h
        s -= omega(m) * (1.0 - math.cos(alpha(m))) * h
    return s


def skitter(t: float) -> float:
    """Distance slid after the slap (m): constant deceleration MU_K g from v0 = sqrt(2 MU_K g SKITTER)."""
    if t <= T_SLAP:
        return 0.0
    a = MU_K * G
    v0 = math.sqrt(2.0 * a * SKITTER)
    tau = min(t - T_SLAP, v0 / a)
    return v0 * tau - 0.5 * a * tau * tau


def pose(t: float, centre=(0.0, 0.0)) -> dict:
    """The disc at title time t: centre (x, y, z), unit normal, in-plane unit u (towards the contact), contact
    point P, and the tangent direction of the contact path."""
    al = alpha(t)
    ph = phase(t)
    e = (math.cos(ph), math.sin(ph), 0.0)
    tan = (-math.sin(ph), math.cos(ph), 0.0)
    ps = (-math.sin(PHI_SLAP), math.cos(PHI_SLAP), 0.0)       # the last tangent: the skitter's direction
    d = skitter(t)
    cx, cy = centre[0] + ps[0] * d, centre[1] + ps[1] * d
    ca, sa = math.cos(al), math.sin(al)
    cz = A * sa + 0.5 * T * ca
    n = (sa * e[0], sa * e[1], ca)
    u = (ca * e[0], ca * e[1], -sa)
    p = (cx + A * ca * e[0], cy + A * ca * e[1], 0.0)
    return {"centre": (cx, cy, cz), "normal": n, "u": u, "contact": p, "alpha": al, "phase": ph, "tangent": tan}


def lowest_point_z(t: float, k: int = 720) -> float:
    """The lowest point of the disc's solid (its two rim circles) at time t: zero while it rolls."""
    pz = pose(t)
    cx, cy, cz = pz["centre"]
    n, u = pz["normal"], pz["u"]
    w = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    best = 1e9
    for side in (-0.5, 0.5):
        for i in range(k):
            th = 2 * math.pi * i / k
            z = cz + side * T * n[2] + A * (math.cos(th) * u[2] + math.sin(th) * w[2])
            best = min(best, z)
    return best
