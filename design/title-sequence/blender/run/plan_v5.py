"""The Run v5: the desk plan, top-down and to scale (PIL; runs in the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/plan_v5.py

Writes D:/document-media/title-sequence/run/layout/v5-desk-plan.png: the 2.2 x 1.0 m desk at 600 px a metre, every item
of desk_v5.ITEMS at its real footprint, the lead's path (the v4.1 roll-out) with a tick each second, the close passes,
the hand-offs, the lamp and its pool (lines of equal exposure, in stops against the record), the wall and what hangs on it.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import desk_v5 as D  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/layout/v5-desk-plan.png")
S = 600.0                                   # px a metre
MX, MY = 90, 330                            # margins: left, top (the wall and lamp above the desk)
W_IMG, H_IMG = int(MX + 2.2 * S + 200), int(MY + 1.0 * S + 200)

BG, INK, MUTED = (24, 20, 16), (237, 226, 207), (160, 150, 135)
OAK, OAK_LINE = (112, 76, 44), (84, 56, 32)
PAPER, PAPER_EDGE = (226, 214, 188), (120, 104, 80)
OBJ, TOOL, FELT = (150, 112, 60), (190, 150, 70), (14, 14, 14)
PATH, PASS, HAND = (207, 115, 68), (203, 161, 78), (237, 226, 207)


def font(size, bold=False):
    for f in (("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"), "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_T, F_L, F_S = font(22, True), font(15), font(13)


def px(x, y):
    return (MX + x * S, MY + (1.0 - y) * S)


def poly(d, pts, fill=None, outline=None, width=1):
    d.polygon([px(*p) for p in pts], fill=fill, outline=outline, width=width)


def main():
    im = Image.new("RGB", (W_IMG, H_IMG), BG)
    d = ImageDraw.Draw(im, "RGBA")
    W, H = D.DESK["size"]
    # the wall, 0.40 m behind the back edge, and the stick chart hanging on it (drawn as its span, dashed)
    wy = px(0, D.ROOM["wall_y"])[1]
    d.line([(MX - 60, wy), (MX + W * S + 60, wy)], fill=MUTED, width=3)
    d.text((MX - 60, wy - 22), "wall (plaster), 0.40 m behind the back edge", font=F_S, fill=MUTED)
    st = D.WALL["stick"]
    x0, x1 = px(st["x"][0], 0)[0], px(st["x"][1], 0)[0]
    for xx in range(int(x0), int(x1), 14):
        d.line([(xx, wy + 6), (min(xx + 7, x1), wy + 6)], fill=PASS, width=3)
    d.text((x0, wy + 10), "T-19 stick chart, hung on the wall (0.80 m)", font=F_S, fill=PASS)
    # the desk: four boards and the breadboard ends
    poly(d, [(0, 0), (W, 0), (W, H), (0, H)], fill=OAK, outline=OAK_LINE, width=3)
    bb = D.B.TABLE["breadboard"]
    for k in range(1, 4):
        y = k * 0.25
        d.line([px(bb, y), px(W - bb, y)], fill=OAK_LINE, width=1)
    for x in (bb, W - bb):
        d.line([px(x, 0), px(x, H)], fill=OAK_LINE, width=2)
    # the lamp's pool: lines of equal exposure against the record (stops)
    for stop, a in ((-0.5, 70), (-1.0, 55), (-1.5, 45), (-2.0, 35)):
        pts = []
        for i in range(0, 361):
            ang = math.radians(i)
            lo, hi = 0.0, 3.0
            lx, ly, _ = D.LAMP["pos"]
            for _ in range(40):
                r = (lo + hi) / 2
                if D.lamp_falloff_stops(lx + r * math.cos(ang), ly + r * math.sin(ang)) > stop:
                    lo = r
                else:
                    hi = r
            x, y = lx + lo * math.cos(ang), ly + lo * math.sin(ang)
            if -0.05 <= x <= W + 0.05 and -0.05 <= y <= H + 0.05:
                pts.append(px(x, y))
            elif pts:
                if len(pts) > 1:
                    d.line(pts, fill=PASS + (a,), width=1)
                pts = []
        if len(pts) > 1:
            d.line(pts, fill=PASS + (a,), width=1)
        lab = None
        for i in range(180, 300):
            ang = math.radians(i)
            lo, hi = 0.0, 3.0
            for _ in range(40):
                r = (lo + hi) / 2
                if D.lamp_falloff_stops(lx + r * math.cos(ang), ly + r * math.sin(ang)) > stop:
                    lo = r
                else:
                    hi = r
            x, y = lx + lo * math.cos(ang), ly + lo * math.sin(ang)
            if 0.02 < x < W - 0.02 and 0.02 < y < 0.98:
                lab = (x, y)
                break
        if lab:
            d.text(px(*lab), f"{stop:+.1f}", font=F_S, fill=PASS + (200,))
    # items, lowest first
    order = ["felt", "atlas1", "atlas2", "piri", "papyrus", "leaf", "khipu", "ino", "tape", "strip", "card", "page",
             "chart", "record", "tablet", "tray", "galley", "weights", "disc", "globe"]
    for n in order:
        it = D.ITEMS[n]
        c = D.corners(it)
        if n in ("globe", "weights"):
            cx, cy = it["centre"]
            r = it["size"][0] / 2
            box = [px(cx - r, cy + r), px(cx + r, cy - r)]
            d.ellipse(box, fill=OBJ, outline=INK, width=2)
            if n == "globe":
                r2 = 0.225                         # the horizon ring above, dashed
                b2 = [px(cx - r2, cy + r2), px(cx + r2, cy - r2)]
                d.ellipse(b2, outline=OBJ + (200,), width=2)
            continue
        if n == "disc":
            cx, cy = it["centre"]
            r = 0.0225
            d.ellipse([px(cx - r, cy + r), px(cx + r, cy - r)], fill=TOOL, outline=INK)
            continue
        kind = it["kind"]
        fill = {"record": PAPER + (235,), "tool": TOOL + (235,), "object": OBJ, "surface": FELT}[kind]
        if n == "tablet":
            fill = (150, 120, 92)
        if n == "record":
            fill = (245, 242, 232)
        if n in ("tape", "strip"):
            fill = (40, 30, 22) if n == "strip" else (230, 222, 196)
        poly(d, c, fill=fill, outline=PAPER_EDGE if kind == "record" else INK, width=2)
    # the coin row in the groove
    tray = D.ITEMS["tray"]
    g = tray["groove"]
    d.line([px(g["x"][0], D.LINE_Y), px(g["x"][1], D.LINE_Y)], fill=(60, 40, 22), width=int(g["w"] * S))
    for k, (_sid, dia) in enumerate(D.COIN_ROW):
        x = D.COIN_X0 + k * D.COIN_PITCH
        d.line([px(x, D.LINE_Y - dia / 2), px(x, D.LINE_Y + dia / 2)], fill=(196, 160, 96), width=3)
    # the lead's path: the v4.1 roll-out, a tick each second
    pts = [px(x, y) for _t, x, y in D.LEAD_V41]
    d.line(pts, fill=PATH, width=4, joint="curve")
    for t, x, y in D.LEAD_V41:
        if abs(t - round(t)) < 0.13:
            p = px(x, y)
            d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=PATH)
            d.text((p[0] + 6, p[1] - 8), f"{round(t)}", font=F_S, fill=INK)
    # close passes: a halo along their stretch
    for name, t0, t1, _how in D.PASSES:
        seg = [px(x, y) for t, x, y in D.LEAD_V41 if t0 <= t <= t1]
        if name == "latch":
            seg = [px(*D.B.LATCH["disc"])]
        if len(seg) == 1:
            p = seg[0]
            d.ellipse([p[0] - 22, p[1] - 22, p[0] + 22, p[1] + 22], outline=PASS, width=3)
        elif len(seg) > 1:
            d.line(seg, fill=PASS + (110,), width=16, joint="curve")
    # labels
    lab = {
        "tablet": ("T-01 Umma tablet (oldest; squared, near-left)", (0.02, 0.33)),
        "papyrus": ("T-02a Turin papyrus on linen", (0.36, 0.78)),
        "atlas1": ("T-03 Catalan Atlas, open (2 boards)", (0.22, 0.52)),
        "piri": ("T-04 Piri Reis over the Atlas", (0.83, 0.05)),
        "leaf": ("T-06 leaf", (1.30, 0.69)),
        "galley": ("galley (glass pair)", (1.15, 0.43)),
        "khipu": ("khipu", (0.88, 0.40)),
        "weights": ("Krakow weights on Piri's corner", (1.00, 0.955)),
        "tray": ("coin tray, 6 coins on edge", (1.47, 0.955)),
        "ino": ("T-08 Ino, folded (1821)", (1.475, 0.64)),
        "tape": ("T-09 tape", (1.43, 0.10)),
        "card": ("card (1890)", (1.57, 0.035)),
        "strip": ("35 mm", (1.70, 0.22)),
        "page": ("T-18 page (1921)", (1.76, 0.385)),
        "chart": ("T-20 chart (1931)", (1.87, 0.46)),
        "felt": ("felt pad, film record", (1.92, 0.73)),
        "globe": ("Doppelmayr globe (1728)", (1.84, -0.02)),
        "disc": ("latch: bronze disc", (0.40, 0.955)),
    }
    for n, (text, (x, y)) in lab.items():
        d.text(px(x, y), text, font=F_L, fill=INK)
    # the lamp: the shade over the desk from behind the back-right
    lx, ly, lz = D.LAMP["pos"]
    p = px(lx, ly)
    r = D.LAMP["shade_d"] / 2 * S
    d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], outline=PASS, width=3)
    a = px(*D.LAMP["aim"][:2])
    d.line([p, a], fill=PASS + (150,), width=2)
    d.text((p[0] + r + 8, p[1] - 30), f"the one lamp: {lz:.2f} m over the top, {D.LAMP['kelvin']:.0f} K, 0.26 m shade",
           font=F_L, fill=PASS)
    # axes and scale
    for k in range(0, 23):
        x = k * 0.1
        q = px(x, 0)
        d.line([q, (q[0], q[1] + (8 if k % 5 == 0 else 4))], fill=MUTED)
        if k % 2 == 0:
            d.text((q[0] - 8, q[1] + 10), f"{x:.1f}", font=F_S, fill=MUTED)
    for k in range(0, 11, 2):
        y = k * 0.1
        q = px(0, y)
        d.text((q[0] - 40, q[1] - 8), f"{y:.1f}", font=F_S, fill=MUTED)
    d.text((MX, 18), "The Run v5: the collector's desk, top-down, to scale (2.2 x 1.0 m oak; 1 m = 600 px)", font=F_T,
           fill=INK)
    d.text((MX, 50), "near side (y = 0) is the sitter's and the camera's side; time runs +x down the 0.95 degree fall; "
           "orange: the lead (v4.1 roll-out, a tick each second); gold halo: close passes; gold lines: the lamp's pool "
           "in stops against the record", font=F_S, fill=MUTED)
    yb = MY + H * S + 46
    notes = [
        "The spread being compared (fixed by the tuned chain): the open Atlas, the papyrus on its left board, Piri Reis "
        "over its right board, the leaf and galley on Piri, the weights on Piri's far corner.",
        "Put away squared: the tablet (near-left), the coin tray at the back on the lead's line, the late papers dealt "
        "left to right by date on bare oak (Ino, tape, card, 35 mm, page, chart), the globe at the right hand.",
        "The reading place: the black felt pad at the back-right, under the lamp, the film's record on it where the "
        "lead stops (x 1.976).",
        "Out of v5: both reels and the platen (no scan, never touched), the standing brass disc (staged; the last coin "
        "falls and whirs instead), the gold. The stick chart hangs on the wall.",
        f"Path hand-offs: latch, papyrus, hinge, U1 (Piri's curl), knots, galley strike (pair released), weights' "
        f"glance, coin row, felt, record. Runtime aimed at {D.runtime_estimate():.1f} s.",
    ]
    for i, line in enumerate(notes):
        d.text((MX, yb + i * 22), line, font=F_S, fill=INK if i < 3 else MUTED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)
    print(OUT, im.size)


if __name__ == "__main__":
    main()
