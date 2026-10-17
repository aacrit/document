"""Title B "Chart": the analytic motion, pure maths (stdlib only, so Blender and pytest both import it).

The unroll (beats 2-6). A sheet of length L (north to south) lies rolled at the far edge and unrolls toward camera, rolling without
slip. The roll is an Archimedean spiral of layer pitch H around a hollow core of radius R_CORE, so the paper area is
conserved: pi * (r^2 - R_CORE^2) = H * (L - s), where s is the laid length and r the roll's outer radius. Rolling
without slip means ds = r * dtheta, which integrates to theta = 2 pi (r_start - r) / H: the roll turns once for every
layer it sheds. The roll's linear speed is v = V0 * (r / r_start)^ALPHA with 0 < ALPHA < 1, so the roll slows while
its turns per second, v / (2 pi r), rise as the radius falls (design 2.3, beat 5). Time to radius has a closed form,
t(r) = K * (r_start^(2-ALPHA) - r^(2-ALPHA)), and so does its inverse. A 1 mm eccentric core lopes the roll: the
rotation is warped once per turn, theta = theta_m + LOPE * sin(theta_m) (pinned at both ends), which keeps it monotone (LOPE < 1) and
keeps no-slip exact, because s and r are functions of theta. The laid sheet keeps a residual curl that decays over
1.0 s from laydown.

The record slide (beats 8-9). A rigid sheet slides in under constant (kinetic friction) deceleration and stops at
the solved pose at T_STOP: y(t) = y_f - a (T - t)^2 / 2, v(t) = a (T - t), with a = 2 D / T^2. Its small yaw decays
the same way (constant angular deceleration) and is exactly zero at the stop.
"""

from __future__ import annotations

import math

FPS = 24

# ---------------------------------------------------------------- the sheet (C-01, Moll 1719) and the roll
L = round(0.97 * 4952 / 8440, 4)   # 0.5691 m: the map's short side (north to south), laid toward camera, so north
W = 0.97                      # is the far edge and reads up in a top-down view; the roll's axis is the long side
H = 0.50e-3                   # layer pitch of a loosely rolled sheet: 0.13 mm laid paper plus air
R_CORE = 7.0e-3               # the hollow core left by a sheet rolled by hand
ALPHA = 0.5                   # v proportional to r^ALPHA: slower roll, faster turns
F_ZERO = 24                   # title frame at which s = 0 (before beat 2, so the roll is already turning at f48)
F_LAST = 636                  # title frame at which the roll is spent (r = R_CORE): beat 6, the last turn
LOPE = 0.05                   # once-per-turn rotation warp from the eccentric core
ECC = 1.0e-3                  # the core's eccentricity (m)
CONE_DEG = 0.5                # the roll's full cone angle
CURL = 1.6e-3                 # residual-curl lift at its peak (m), decaying over 1.0 s from laydown
CURL_RISE, CURL_DECAY = 0.06, 0.25   # s


def r_of_s(s: float) -> float:
    """Outer radius of the roll when s metres are laid (area conserved)."""
    s = min(max(s, 0.0), L)
    return math.sqrt(R_CORE ** 2 + H * (L - s) / math.pi)


R_START = r_of_s(0.0)


def s_of_r(r: float) -> float:
    return min(L, max(0.0, L - math.pi * (r * r - R_CORE ** 2) / H))


def theta_of_r(r: float) -> float:
    """Rotation (rad) from the start: the integral of ds / r."""
    return 2.0 * math.pi * (R_START - r) / H


def r_of_theta(theta: float) -> float:
    return max(R_CORE, R_START - H * theta / (2.0 * math.pi))


THETA_END = theta_of_r(R_CORE)
T_TOTAL = (F_LAST - F_ZERO) / FPS
_E = 2.0 - ALPHA
K_TIME = T_TOTAL / (R_START ** _E - R_CORE ** _E)
V0 = 2.0 * math.pi * R_START ** ALPHA / (H * K_TIME * _E)     # speed at r = R_START (m/s)


def t_of_r(r: float) -> float:
    return K_TIME * (R_START ** _E - r ** _E)


def r_mean(t: float) -> float:
    """Outer radius at time t (s from F_ZERO) on the mean (unloped) motion."""
    t = min(max(t, 0.0), T_TOTAL)
    if t >= T_TOTAL:
        return R_CORE
    return max(R_CORE, (R_START ** _E - t / K_TIME) ** (1.0 / _E))


def speed_of_r(r: float) -> float:
    """Linear speed of the roll (m/s) on the mean motion: V0 (r / R_START)^ALPHA."""
    return V0 * (r / R_START) ** ALPHA


def turns_per_s_of_r(r: float) -> float:
    return speed_of_r(r) / (2.0 * math.pi * r)


def lope(theta_m: float) -> float:
    """Once-per-turn warp, pinned at both ends (0 and THETA_END map to themselves)."""
    return theta_m + LOPE * (math.sin(theta_m) - math.sin(THETA_END) * theta_m / THETA_END)


def unlope(theta: float) -> float:
    """Inverse of lope (Newton; monotone since LOPE < 1)."""
    x = theta
    for _ in range(30):
        f = lope(x) - theta
        x -= f / (1.0 + LOPE * (math.cos(x) - math.sin(THETA_END) / THETA_END))
        if abs(f) < 1e-12:
            break
    return x


def roll_state(frame: float) -> dict:
    """The roll at a (fractional) title frame: rotation, radius, laid length, speed and turn rate."""
    t = (frame - F_ZERO) / FPS
    th_m = theta_of_r(r_mean(t))
    th = min(lope(th_m), THETA_END)
    r = r_of_theta(th)
    s = s_of_r(r)
    rm = r_mean(t)
    return {"t": t, "theta": th, "theta_mean": th_m, "r": r, "s": s, "v_mean": speed_of_r(rm),
            "turns_per_s_mean": turns_per_s_of_r(rm), "r_mean": rm}


def laid_time(sigma: float) -> float:
    """Time (s from F_ZERO) at which the material at sigma (m from the far edge) was laid, on the loped motion."""
    th = theta_of_r(r_of_s(sigma))
    return t_of_r(r_of_theta(unlope(th)))


def curl(age: float) -> float:
    """Residual-curl lift behind the roll (m): zero at the contact line, a short rise, gone 1.0 s after laydown."""
    if age <= 0.0:
        return 0.0
    return CURL * (1.0 - math.exp(-age / CURL_RISE)) * math.exp(-age / CURL_DECAY) / _CURL_PEAK


def _curl_peak() -> float:
    best = 0.0
    for i in range(1, 2000):
        a = i * 0.001
        best = max(best, (1.0 - math.exp(-a / CURL_RISE)) * math.exp(-a / CURL_DECAY))
    return best


_CURL_PEAK = _curl_peak()


def spiral(lam: float, r: float) -> tuple[float, float]:
    """A point lam metres into the roll from the contact line, for outer radius r: (phi, rho), the angle round the
    core from the contact and the radius there. Arc length of the spiral rho = r - H phi / 2 pi is exact:
    lam = r phi - H phi^2 / 4 pi, so rho = sqrt(r^2 - H lam / pi)."""
    rho = math.sqrt(max(R_CORE ** 2, r * r - H * lam / math.pi))
    return 2.0 * math.pi * (r - rho) / H, rho


# ---------------------------------------------------------------- the record slide (P1, beats 8-9)
SLIDE_F0 = 888                 # title frame: the record enters (beat 8)
SLIDE_STOP = 948               # it stops (2.5 s of slide)
SLIDE_D = 0.50                 # m travelled, from beyond the chart's near edge
SLIDE_YAW0 = math.radians(3.0)
HOLD_BLEND = 12                # flat-hold: the last 12 frames of the slide
SLIDE_T = (SLIDE_STOP - SLIDE_F0) / FPS
SLIDE_A = 2.0 * SLIDE_D / SLIDE_T ** 2          # m/s^2: constant deceleration
SLIDE_MU = SLIDE_A / 9.81                        # the effective friction it implies (an air-cushioned glide)


def slide_state(frame: float) -> dict:
    """Offset from the solved pose (m, along the slide; negative = still short of it), speed and yaw."""
    t = min(max((frame - SLIDE_F0) / FPS, 0.0), SLIDE_T)
    rem = SLIDE_T - t
    return {"offset": -0.5 * SLIDE_A * rem * rem, "v": SLIDE_A * rem, "yaw": SLIDE_YAW0 * (rem / SLIDE_T) ** 2,
            "stopped": rem <= 0.0}


def hold_mix(frame: float) -> float:
    """Flat-hold shader weight: 0 (lit diffuse) until 12 frames before the stop, 1 (pure emission) from the stop."""
    u = (frame - (SLIDE_STOP - HOLD_BLEND)) / HOLD_BLEND
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)
