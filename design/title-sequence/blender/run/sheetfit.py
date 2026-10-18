"""The Run: lay each period sheet on the bench at its real size so the marble's path crosses it where the clock needs
(stdlib only).

A sheet is a W x H rectangle (W along its image's width) turned psi degrees from +x, centred at (cx, cy). The lead
marble's path is taken as the line y = yp across it. Roof tiles: each sheet's uphill part lies under the sheet before,
so a sheet must contain the path from `x_under` (a little before the previous edge) to its own downhill edge
`x_exit`, where the marble steps down. The fitter searches the turn and the sideways offset for a placement that
meets the edge exactly and keeps the sheet's turn near its preferred angle and the path near its middle. The
Catalan Atlas is two boards side by side with a hinge valley between them: its hinge must also cross the path at the
logged hinge position.
"""

from __future__ import annotations

import math


def chord(cx, cy, W, H, psi_deg, yp, u_range=None):
    """[xa, xb] where the line y = yp crosses the rectangle (or its local-u sub-range), or None."""
    p = math.radians(psi_deg)
    cu, su = math.cos(p), math.sin(p)
    lo, hi = -1e9, 1e9
    u0, u1 = u_range if u_range else (-W / 2, W / 2)
    dy = yp - cy
    # u = (x - cx) cu + dy su ; v = -(x - cx) su + dy cu
    for a, b, lim in ((cu, dy * su, (u0, u1)), (-su, dy * cu, (-H / 2, H / 2))):
        if abs(a) < 1e-12:
            if not (lim[0] <= b <= lim[1]):
                return None
            continue
        t0, t1 = (lim[0] - b) / a, (lim[1] - b) / a
        if t0 > t1:
            t0, t1 = t1, t0
        lo, hi = max(lo, t0), min(hi, t1)
    if lo >= hi:
        return None
    return (cx + lo, cx + hi)


def edge_normal_x(W, H, psi_deg, yp_local_v, side_u):
    """|n_x| of the rectangle edge the path leaves by: how square-on the marble meets it (1 = square)."""
    p = math.radians(psi_deg)
    return abs(math.cos(p)) if side_u else abs(math.sin(p))


def _exit_edge(cx, cy, W, H, psi_deg, yp, xb, u_range=None):
    p = math.radians(psi_deg)
    u = (xb - cx) * math.cos(p) + (yp - cy) * math.sin(p)
    v = -(xb - cx) * math.sin(p) + (yp - cy) * math.cos(p)
    u0, u1 = u_range if u_range else (-W / 2, W / 2)
    du = min(abs(u - u0), abs(u - u1))
    dv = min(abs(v - H / 2), abs(v + H / 2))
    on_u_edge = du <= dv
    return abs(math.cos(p)) if on_u_edge else abs(math.sin(p))


def fit_sheet(W, H, psi_pref, yp, x_exit, x_under=None, x_entry=None, span=35.0, max_off=None, keep_out=None):
    """Place one sheet. x_exit: the downhill edge on the path. Either x_under (the sheet must reach at least that far
    uphill, lying under the sheet before) or x_entry (the sheet's own uphill edge is exactly there: the papyrus,
    stepped up onto from bare oak). Returns {cx, cy, psi, chord, score} or None."""
    best = None
    max_off = max_off if max_off is not None else 0.5 * max(W, H)
    for k in range(int(2 * span) + 1):
        psi = psi_pref - span + k
        for j in range(-60, 61):
            off = max_off * j / 60.0
            c = chord(0.0, off, W, H, psi, 0.0)
            if c is None:
                continue
            length = c[1] - c[0]
            cx = x_exit - c[1]
            xa = cx + c[0]
            if x_entry is not None:
                err = abs(xa - x_entry)
                if err > 0.0015:
                    continue
                pen = err * 100
            else:
                if xa > x_under:
                    continue
                pen = 0.4 * max(0.0, (x_under - xa) - 0.08)
            sq = _exit_edge(cx, yp + off, W, H, psi, yp, x_exit)
            if sq < 0.35 or not clear_of(cx, yp + off, W, H, psi, keep_out):
                continue
            score = abs(psi - psi_pref) / 10.0 + abs(off) / max(W, H) * 2.0 + pen + (1 - sq)
            if best is None or score < best["score"]:
                best = {"cx": cx, "cy": yp + off, "psi": psi, "chord": [xa, x_exit], "score": round(score, 4)}
    return best


def fit_hinged(W, H, gap, psi_pref, yp, x_hinge, x_exit, x_under, span=40.0, keep_out=None):
    """Two boards side by side along their width (board 1 uphill, board 2 downhill), the hinge line at local u = 0:
    the path crosses the hinge at x_hinge and leaves board 2 at x_exit; board 1 reaches x_under."""
    best = None
    for k in range(int(2 * span) + 1):
        psi = psi_pref - span + k
        for j in range(-80, 81):
            off = 0.6 * H * j / 80.0
            b1 = chord(0.0, off, 2 * W + gap, H, psi, 0.0, u_range=(-W - gap / 2, -gap / 2))
            b2 = chord(0.0, off, 2 * W + gap, H, psi, 0.0, u_range=(gap / 2, W + gap / 2))
            if b1 is None or b2 is None or not (b1[1] <= b2[0] + 1e-9):
                continue
            cx = x_exit - b2[1]
            hinge = cx + 0.5 * (b1[1] + b2[0])
            err = abs(hinge - x_hinge)
            if err > 0.002 or cx + b1[0] > x_under:
                continue
            sq = _exit_edge(cx, yp + off, 2 * W + gap, H, psi, yp, x_exit, u_range=(gap / 2, W + gap / 2))
            if sq < 0.35 or not clear_of(cx, yp + off, 2 * W + gap, H, psi, keep_out):
                continue
            score = err * 200 + abs(psi - psi_pref) / 10.0 + abs(off) / H + (1 - sq)
            if best is None or score < best["score"]:
                best = {"cx": cx, "cy": yp + off, "psi": psi, "board1": [cx + b1[0], cx + b1[1]],
                        "board2": [cx + b2[0], cx + b2[1]], "hinge": hinge, "score": round(score, 4)}
    return best


def fit_hinged_free(W, H, gap, psi_pref, yp, x_hinge, x_target, x_under, x_min, keep_out=None):
    """The Atlas's two boards placed by the hinge alone: the hinge crosses the path at x_hinge, board 1 reaches
    x_under, nothing lies on the latch's bare oak; the path then leaves board 2 wherever the boards' real size puts
    its edge, preferably near x_target (the clock's frame) and never before x_min. Returns the fit with its exit."""
    best = None
    for k in range(0, 360, 1):
        psi = float(k - 180)
        for j in range(-100, 101):
            off = H * j / 100.0
            b1 = chord(0.0, off, 2 * W + gap, H, psi, 0.0, u_range=(-W - gap / 2, -gap / 2))
            b2 = chord(0.0, off, 2 * W + gap, H, psi, 0.0, u_range=(gap / 2, W + gap / 2))
            if b1 is None or b2 is None or not (b1[1] <= b2[0] + 1e-9):
                continue
            cx = x_hinge - 0.5 * (b1[1] + b2[0])
            exit_ = cx + b2[1]
            if cx + b1[0] > x_under or exit_ < x_min:
                continue
            sq = _exit_edge(cx, yp + off, 2 * W + gap, H, psi, yp, exit_, u_range=(gap / 2, W + gap / 2))
            if sq < 0.35 or not clear_of(cx, yp + off, 2 * W + gap, H, psi, keep_out):
                continue
            score = abs(exit_ - x_target) * 10 + abs(((psi - psi_pref + 180) % 360) - 180) / 30.0 + abs(off) / H + (1 - sq)
            if best is None or score < best["score"]:
                best = {"cx": cx, "cy": yp + off, "psi": psi, "board1": [cx + b1[0], cx + b1[1]],
                        "board2": [cx + b2[0], cx + b2[1]], "hinge": x_hinge, "exit": exit_, "score": round(score, 4)}
    return best


def _sat_overlap(poly_a, poly_b):
    """Separating-axis test for two convex polygons [(x, y), ...]."""
    for poly in (poly_a, poly_b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            ax, ay = y2 - y1, x1 - x2
            pa = [ax * x + ay * y for x, y in poly_a]
            pb = [ax * x + ay * y for x, y in poly_b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def clear_of(cx, cy, W, H, psi_deg, keep_out, u_range=None):
    """True when the sheet does not overlap any keep-out box (x0, x1, y0, y1): the bare oak the latch is framed on."""
    if not keep_out:
        return True
    poly = corners(cx, cy, W, H, psi_deg, u_range)
    for x0, x1, y0, y1 in keep_out:
        if _sat_overlap(poly, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]):
            return False
    return True


def corners(cx, cy, W, H, psi_deg, u_range=None):
    p = math.radians(psi_deg)
    cu, su = math.cos(p), math.sin(p)
    u0, u1 = u_range if u_range else (-W / 2, W / 2)
    out = []
    for u, v in ((u0, -H / 2), (u1, -H / 2), (u1, H / 2), (u0, H / 2)):
        out.append((cx + u * cu - v * su, cy + u * su + v * cu))
    return out
