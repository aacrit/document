"""Title v6, preview 1: the bake plot, the event log and the acceptance report (numpy, matplotlib; D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/preview1_v6.py

Reads the bake (bake_v6.py), the decompositions (scans_v6.py), the mu_r calibration (murr_v6.py) and the latch
re-proof (latch_v6.py). Checks section 9's preview-1 list on the bake itself, and writes to
D:/document-media/title-sequence/v6/preview1/: bake-plot.png (the path over the table and the records, coloured by
speed, every contact event marked, each record's reading window; under it the speed and tick timeline),
event-log.json and report.md. Every PASS in the report is computed here, never typed.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eventlog as E  # noqa: E402
import table_v6 as T  # noqa: E402

V6 = Path("D:/document-media/title-sequence/v6")
BAKE, OUT = V6 / "bake", V6 / "preview1"
INK = {"bg": "#181410", "surface": "#221c15", "cream": "#ede2cf", "forest": "#4f8064", "terracotta": "#cf7344",
       "burgundy": "#a8404f", "ochre": "#cba14e"}
TICK_ORDER = ["atlas2", "leaf", "piri", "ino", "chart"]


def load():
    track = np.array(json.loads((BAKE / "track.json").read_text(encoding="utf-8")))
    bake = json.loads((BAKE / "bake.json").read_text(encoding="utf-8"))
    contacts = E.read_jsonl(BAKE / "contacts-1khz.jsonl")
    return track, bake, contacts


def ball_events(contacts):
    """Onsets of every ball contact pair (any approach speed), each with its designed class."""
    ev = E.events([c for c in contacts if "ball" in c["pair"].split("|")], v_min=-1e9)
    for e in ev:
        e["frame"] = round(e["t_s"] * T.FPS, 2)
        e["class"] = T.contact_class(e["pair"])
    return ev


def row_events(contacts):
    return [dict(e, frame=round(e["t_s"] * T.FPS, 2)) for e in
            E.events([c for c in contacts if "ball" not in c["pair"].split("|")], v_min=0.005)]


def reading_windows(track):
    """Per record: the time span the ball is on it (its own ground), with the mean and least speed."""
    x, y = track[:, 1], track[:, 2]
    sheet = T.top_sheet(x, y)
    sp = np.linalg.norm(track[:, 4:6], axis=1)
    out = []
    for name in ["atlas1", "atlas2", "leaf", "piri", "ino", "chart", "well"]:
        m = sheet == name
        if not m.any():
            continue
        t = track[m, 0]
        out.append({"ground": name, "t0": float(t.min()), "t1": float(t.max()), "dur_s": float(t.max() - t.min()),
                    "v_mean": float(sp[m].mean()), "v_min": float(sp[m].min()),
                    "slow_s": float(np.sum(sp[m] < 0.2) / 240.0)})
    return out


def glance_of(track, contacts, cls, after=0.08):
    ts = [c["t_s"] for c in contacts if "ball" in c["pair"].split("|") and T.contact_class(c["pair"]) == cls]
    if not ts:
        return None
    t0, t1 = min(ts), max(ts)
    T_ = track[:, 0]
    vb = track[(T_ >= t0 - 0.04) & (T_ < t0)][:, 4:6].mean(0)
    va = track[(T_ > t1) & (T_ <= t1 + after)][:, 4:6].mean(0)
    return {"t0": t0, "t1": t1, "frame": round(t0 * T.FPS, 1), "turn_deg": T.turn_deg(vb, va),
            "speed_kept": float(np.linalg.norm(va) / np.linalg.norm(vb)), "v_before": float(np.linalg.norm(vb)),
            "v_after": float(np.linalg.norm(va))}


def sorts_fallen(bake):
    out = []
    for i in range(12):
        P = bake["poses"][f"sort{i + 1}"]
        q = np.array(P[-1][4:8])
        # the sort's own long axis (z) against the world vertical
        w_, x_, y_, z_ = q
        zz = 1 - 2 * (x_ * x_ + y_ * y_)
        out.append(float(math.degrees(math.acos(max(-1.0, min(1.0, zz))))))
    return out


def checks(track, bake, contacts):
    meta = bake["meta"]
    res = {}
    t = track[:, 0]
    xy = track[:, 1:3]
    sp = np.linalg.norm(track[:, 4:6], axis=1)
    s = T.along(xy[:, 0], xy[:, 1])
    # rest
    rest = xy[-1]
    r = T.check_rest(rest)
    res["rest"] = dict(r, status=meta["status"], xy=rest.tolist())
    # the roll: from the latch's opening (f12) to the lip
    i_lip = int(np.argmax(xy[:, 0] >= T.LIP_X))
    t_lip = float(t[i_lip]) if xy[:, 0].max() >= T.LIP_X else None
    roll = (t_lip - T.T_RELEASE) if t_lip else None
    t_rest = meta["t_rest"]
    b = T.check_budget(t_rest) if t_rest else {"pass": False}
    res["roll"] = {"t_lip": t_lip, "roll_s": roll, "t_rest": t_rest, "budget": b,
                   "pass": bool(roll is not None and T.ACCEPT["roll_s"][0] <= roll <= T.ACCEPT["roll_s"][1]
                                and b["pass"])}
    # least speed before the sag, after the ball leaves the ramp; the margin over each rise's stall speed
    off_ramp = np.argmax((s > 0.06) & (t > T.T_RELEASE + 0.2))
    pre = (np.arange(len(t)) >= off_ramp) & (s < T.S_LIP - T.SAGS[1]["len"])
    j = int(np.argmin(np.where(pre, sp, 9)))
    prof = T.ground_profile(np.clip(s[pre], 0, T.S_LIP - 0.002))
    # the ground under the ball's actual track (not the nominal line): rises and the speed at their feet
    xs, ys, wz, tops, cur = T.stack_grid()
    zg = T.sample(cur, xs, ys, xy[pre, 0], xy[pre, 1]) - T.sample(wz, xs, ys, xy[pre, 0], xy[pre, 1])
    rises = T.rises(s[pre], zg, h_min=2e-5)
    worst = []
    for rz in rises:
        k = int(np.argmin(np.abs(s[pre] - rz["s"])))
        vs = T.v_stall(rz["h"])
        worst.append({"s": rz["s"], "h_mm": rz["h"] * 1000, "v_stall": vs, "v_there": float(sp[pre][k]),
                      "margin": float(sp[pre][k] / vs - 1) if vs else None})
    marg_ok = all(w_["margin"] is None or w_["margin"] >= T.ACCEPT["margin"] for w_ in worst)
    v_min = float(sp[j])
    # section 9: "at least 0.10 m/s with a 15% margin over the stall speed at the next step": the floor is 0.10; the
    # margin is over each rise's stall speed sqrt(10/7 g h), at the speed the ball meets it
    res["speed"] = {"v_min": v_min, "at_s": float(s[j]), "at_t": float(t[j]), "rises_on_track": worst,
                    "least_margin_over_stall": min((w_["margin"] for w_ in worst if w_["margin"] is not None),
                                                   default=None),
                    "pass": bool(v_min >= T.ACCEPT["v_min"] and marg_ok)}
    # contacts: only the seven designed contacts, the ticks in date order
    ev = ball_events(contacts)
    stray = [e for e in ev if e["class"] is None]
    classes = sorted({e["class"] for e in ev if isinstance(e["class"], int)})
    ticks = []
    seen = set()
    for e in ev:
        o = [p for p in e["pair"].split("|") if p != "ball"][0]
        if e["class"] == 2 and o not in seen:
            seen.add(o)
            ticks.append({"onto": o, "t_s": e["t_s"], "frame": e["frame"], "v_n": e["v_n"]})
    tick_names = [k["onto"] for k in ticks if k["onto"] != "atlas1"]
    # repeated landings on one sheet (a bounce) are contacts the design does not have: count the re-onsets
    reonsets = {}
    for e in ev:
        if e["class"] == 2:
            reonsets[e["pair"]] = reonsets.get(e["pair"], 0) + 1
    res["contacts"] = {"classes_seen": classes, "stray": stray[:30], "n_stray": len(stray), "ticks": ticks,
                       "tick_order_ok": tick_names == TICK_ORDER, "sheet_onsets": reonsets,
                       "pass": bool(not stray and tick_names == TICK_ORDER and {1, 2, 3, 4, 5, 7} <= set(classes))}
    # the galley: twelve sorts fall, the ball keeps 90 percent past the row
    tilts = sorts_fallen(bake)
    g3 = glance_of(track, contacts, 3, after=0.15)
    row_end = bake["meta"]["galley"]
    gal = bake["meta"]["placed"].get("galley", {})
    s_end = gal.get("s_end", 1.2)
    k_end = int(np.argmax(s >= s_end))
    k_in = int(np.argmax(t >= (g3["t0"] - 0.04))) if g3 else 0
    kept_row = float(sp[k_end] / sp[k_in]) if g3 else None
    res["galley"] = {"tilts_deg": tilts, "fallen": int(sum(a > 60 for a in tilts)), "glance": g3,
                     "speed_kept_past_row": kept_row, "b": row_end.get("b"),
                     "pass": bool(sum(a > 60 for a in tilts) == 12 and kept_row is not None
                                  and kept_row >= T.ACCEPT["speed_kept"])}
    # the turns
    g4, g5 = glance_of(track, contacts, 4), glance_of(track, contacts, 5)
    lo4, hi4 = T.ACCEPT["turn_weights_deg"]
    lo5, hi5 = T.ACCEPT["turn_globe_deg"]
    res["turns"] = {"weights": g4, "globe": g5,
                    "pass": bool(g4 and lo4 <= g4["turn_deg"] <= hi4 and g5 and lo5 <= g5["turn_deg"] <= hi5)}
    # decompositions and mu_r
    sc = json.loads((V6 / "scans" / "report.json").read_text(encoding="utf-8"))["scans"]
    dec = {k: {"parts": sc[k].get("parts"), "air_mm": sc[k].get("air_m", 0) * 1000,
               "missing_mm": sc[k].get("missing_m", 0) * 1000, "ok": sc[k].get("gap_ok")} for k in ("weights", "globe")}
    # the side the ball meets: the sectors within 60 degrees of the direction from the object's centre to the ball at
    # its glance (the weights are turned to present their plain side; see bake_v6.place_weights)
    for k, cls in (("weights", 4), ("globe", 5)):
        P = bake["meta"]["placed"].get(k)
        g = glance_of(track, contacts, cls)
        if not P or not g or "sectors" not in sc[k]:
            continue
        i = int(np.argmin(np.abs(track[:, 0] - g["t0"])))
        a_world = math.degrees(math.atan2(track[i, 2] - P["y"], track[i, 1] - P["x"]))
        a_obj = (a_world - P["yaw_deg"] + 180) % 360 - 180
        worst_a = worst_m = 0.0
        for name, s_ in sc[k]["sectors"].items():
            lo_, hi_ = (float(x) for x in name.split(".."))
            mid = (lo_ + hi_) / 2
            if abs((mid - a_obj + 180) % 360 - 180) <= 60 + 15:
                worst_a, worst_m = max(worst_a, s_["air_m"]), max(worst_m, s_["missing_m"])
        dec[k].update({"ball_side_obj_deg": a_obj, "ball_side_air_mm": worst_a * 1000,
                       "ball_side_missing_mm": worst_m * 1000,
                       "ball_side_ok": max(worst_a, worst_m) <= T.ACCEPT["gap_m"]})
    for k in dec:
        sw = sc[k].get("swept") or {}
        dec[k].update({"swept_air_mm": sw.get("air_m", float("nan")) * 1000,
                       "swept_missing_mm": sw.get("missing_m", float("nan")) * 1000,
                       "swept_ok": bool(sw) and max(sw["air_m"], sw["missing_m"]) <= T.ACCEPT["gap_m"]})
    # the spec's check is the surfaces' own gap on the band (strict); the swept figure is where the ball itself stops,
    # reported beside it, never in its place
    res["decompositions"] = dict(dec, pass_=all(v["ok"] for v in dec.values()),
                                 swept_ok=all(v["swept_ok"] for v in dec.values()))
    mu = json.loads((V6 / "murr" / "murr.json").read_text(encoding="utf-8"))
    res["mu_r"] = {"kind": mu["kind"], "basis": mu["basis"],
                   "surfaces": {k: {"target": v["target_mu_r"], "measured": v["measured_mu_r"]}
                                for k, v in mu["surfaces"].items()},
                   "felt_mu_r": meta["felt_mu_r"], "fall_deg": meta["fall_deg"],
                   "spread_over_speeds": max((max(v["measured_mu_r"].values()) - min(v["measured_mu_r"].values()))
                                             / v["target_mu_r"] for v in mu["surfaces"].values()),
                   # measured per paper at 30 mm, at the bake's rolling speed, within 2 percent of its target
                   "pass": all(abs(v["measured_mu_r"]["0.13"] - v["target_mu_r"]) / v["target_mu_r"] < 0.02
                               for v in mu["surfaces"].values())}
    res["windows"] = reading_windows(track)
    res["rows"] = row_events(contacts)
    return res, ev


def plot(track, bake, ev, res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Polygon, Rectangle
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK["cream"],
                         "axes.labelcolor": INK["cream"], "xtick.color": INK["cream"], "ytick.color": INK["cream"]})
    fig = plt.figure(figsize=(16, 13), facecolor=INK["bg"])
    ax = fig.add_axes([0.04, 0.33, 0.92, 0.62], facecolor=INK["surface"])
    ax2 = fig.add_axes([0.06, 0.05, 0.88, 0.22], facecolor=INK["surface"])
    W, H = T.TABLE["size"]
    ax.add_patch(Rectangle((0, 0), W, H, fill=False, ec=INK["cream"], lw=0.8, alpha=0.6))
    for sh in T.SHEETS:
        _, cs = T.footprint(sh["name"])
        ax.add_patch(Polygon(cs, closed=True, fc=INK["cream"], alpha=0.07 + 0.02 * sh["layer"], ec=INK["cream"],
                             lw=0.6))
        c = np.mean(cs, axis=0)
        ax.text(c[0], c[1] - 0.13 if sh["name"] != "chart" else c[1] - 0.12, f"{sh['ledger']} {sh['name']} ({sh['date']})",
                ha="center", fontsize=8, alpha=0.75)
    wx, wy = T.WELL["x"], T.WELL["y"]
    ax.add_patch(Rectangle((wx[0], wy[0]), wx[1] - wx[0], wy[1] - wy[0], fc="#000000", alpha=0.5, ec=INK["cream"], lw=0.6))
    r = T.RECORD_RECT
    ax.add_patch(Rectangle((r[0], r[2]), r[1] - r[0], r[3] - r[2], fc=INK["cream"], alpha=0.35, ec=INK["cream"]))
    ax.text((r[0] + r[1]) / 2, r[3] + 0.02, "the record", ha="center", fontsize=8)
    placed = bake["meta"]["placed"]
    for k, p in placed.items():
        if k == "galley":
            continue
        ax.plot([p["x"]], [p["y"]], marker="+", color=INK["ochre"], ms=8)
        ax.text(p["x"] + 0.02, p["y"] + 0.02, k, fontsize=8, color=INK["ochre"])
    sp = np.linalg.norm(track[:, 4:6], axis=1)
    pts = track[:, 1:3]
    seg = np.stack([pts[:-1], pts[1:]], 1)
    lc = LineCollection(seg, cmap="viridis", norm=plt.Normalize(0.0, 0.45), lw=2.4)
    lc.set_array(sp[:-1])
    ax.add_collection(lc)
    cb = fig.colorbar(lc, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label("speed, m/s")
    shown = set()
    for e in ev:
        if not isinstance(e["class"], int) and e["class"] is not None:
            continue
        key = (e["pair"], e["class"])
        if e["class"] == 2 and key in shown:
            continue
        shown.add(key)
        i = int(np.argmin(np.abs(track[:, 0] - e["t_s"])))
        col = INK["burgundy"] if e["class"] is None else INK["terracotta"]
        ax.plot([track[i, 1]], [track[i, 2]], "o", ms=5, mfc="none", mec=col, mew=1.2)
        lab = f"{e['class'] if e['class'] is not None else 'STRAY'} f{e['frame']:.0f}"
        ax.text(track[i, 1] + 0.012, track[i, 2] - 0.035, lab, fontsize=7, color=col)
    for wnd in res["windows"]:
        m = (track[:, 0] >= wnd["t0"]) & (track[:, 0] <= wnd["t1"])
        c = track[m, 1:3].mean(0)
        ax.text(c[0], c[1] + 0.07, f"{wnd['ground']}: f{wnd['t0'] * T.FPS:.0f}-f{wnd['t1'] * T.FPS:.0f} "
                f"({wnd['dur_s']:.1f} s, mean {wnd['v_mean']:.2f} m/s)", fontsize=7, ha="center", color=INK["forest"])
    ax.set_xlim(-0.05, W + 0.05)
    ax.set_ylim(-0.05, H + 0.05)
    ax.set_aspect("equal")
    ax.set_title("Title v6, preview 1: the bake, top down (table frame, m). Circles: contact events (number = section 3 "
                 "contact); green: each record's reading window", color=INK["cream"], fontsize=10, loc="left")
    ax2.plot(track[:, 0], sp, color=INK["cream"], lw=1.2)
    ax2.axhline(T.ACCEPT["v_min"], color=INK["ochre"], lw=0.8, ls="--")
    ax2.axhline(T.ACCEPT["v_min"] * (1 + T.ACCEPT["margin"]), color=INK["ochre"], lw=0.6, ls=":")
    for e in ev:
        if e["class"] in (1, 2, 3, 4, 5, 7) or e["class"] is None:
            col = INK["burgundy"] if e["class"] is None else INK["terracotta"]
            ax2.axvline(e["t_s"], color=col, lw=0.5, alpha=0.6)
    for e in res["rows"]:
        if e["pair"].startswith("sort") and "|sort" in e["pair"]:
            ax2.plot([e["t_s"]], [0.02], "|", color=INK["forest"], ms=8)
    ax2.set_xlabel("title time, s (f = s x 29.97); tick marks: contacts; green ticks at the foot: the sorts' clicks")
    ax2.set_ylabel("speed, m/s")
    ax2.set_xlim(0, T.DURATION)
    ax2.set_ylim(0, max(0.45, float(sp.max()) * 1.05))
    for a in (ax, ax2):
        for s_ in a.spines.values():
            s_.set_color(INK["cream"])
            s_.set_alpha(0.4)
    fig.savefig(path, dpi=110, facecolor=INK["bg"])


def fmt(v, nd=3):
    return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def report(res, path):
    def pf(b):
        return "PASS" if b else "FAIL"
    R = res
    lines = ["# Title v6, preview 1: the bake plot", "",
             "Every line below is computed by preview1_v6.py from the bake (bake_v6.py); nothing is typed in.", "",
             "| Check (spec section 9) | Result | Measured |", "|---|---|---|",
             f"| Rest 7 +- 5 mm short of the record, on its centre line | {pf(R['rest']['pass'])} | "
             f"{R['rest']['short_mm']:.1f} mm short, {R['rest']['off_centre_mm']:+.1f} mm off the line ({R['rest']['status']}) |",
             f"| Roll latch to lip 20-24 s; the budget fits 1080 frames | {pf(R['roll']['pass'])} | roll "
             f"{fmt(R['roll']['roll_s'], 2)} s, lip at {fmt(R['roll']['t_lip'], 2)} s, rest at {fmt(R['roll']['t_rest'], 2)} s, "
             f"slack after rest + 5 s: {fmt(R['roll']['budget'].get('slack_s'), 2)} s |",
             f"| Least speed before the sag >= 0.10 m/s with 15% margin | {pf(R['speed']['pass'])} | "
             f"{R['speed']['v_min']:.3f} m/s at s {R['speed']['at_s']:.2f} m (t {R['speed']['at_t']:.1f} s) |",
             f"| Only the seven designed contacts | {pf(R['contacts']['pass'])} | classes {R['contacts']['classes_seen']}, "
             f"{R['contacts']['n_stray']} stray, ticks in date order: {R['contacts']['tick_order_ok']} |",
             f"| Twelve sorts fall; the ball keeps >= 90% past the row | {pf(R['galley']['pass'])} | "
             f"{R['galley']['fallen']} fallen, speed kept {fmt(R['galley']['speed_kept_past_row'])} |",
             f"| Turns: weights 20-30 left, globe 15-25 right | {pf(R['turns']['pass'])} | weights "
             f"{fmt(R['turns']['weights'] and R['turns']['weights']['turn_deg'], 1)} deg, globe "
             f"{fmt(R['turns']['globe'] and R['turns']['globe']['turn_deg'], 1)} deg |",
             f"| Decompositions within 1 mm on the contact band | {pf(R['decompositions']['pass_'])} | " +
             "; ".join(f"{k}: {v['parts']} parts, surfaces air {v['air_mm']:.2f} / missing {v['missing_mm']:.2f} mm; "
                       f"where the ball stops (swept) air {v['swept_air_mm']:.2f} / missing {v['swept_missing_mm']:.2f} mm"
                       for k, v in R["decompositions"].items() if isinstance(v, dict)) + " |",
             f"| mu_r measured at 30 mm per paper, the fall tuned to it | {pf(R['mu_r']['pass'])} | {R['mu_r']['kind']}; "
             f"fall {R['mu_r']['fall_deg']} deg; felt {R['mu_r']['felt_mu_r']:.4f} |", "",
             "## Reading windows", "", "| Ground | Frames | Seconds | Mean speed | Under 0.2 m/s |", "|---|---|---|---|---|"]
    for w in R["windows"]:
        lines.append(f"| {w['ground']} | f{w['t0'] * T.FPS:.0f}-f{w['t1'] * T.FPS:.0f} | {w['dur_s']:.2f} | "
                     f"{w['v_mean']:.3f} | {w['slow_s']:.2f} s |")
    lines += ["", "## mu_r (30 mm, MuJoCo calibration)", "", "| Surface | Target | Measured (0.12, 0.20, 0.30 m/s) |",
              "|---|---|---|"]
    for k, v in R["mu_r"]["surfaces"].items():
        lines.append(f"| {k} | {v['target']:.5f} | " + ", ".join(f"{x:.5f}" for x in v["measured"].values()) + " |")
    lines += ["", f"Basis: {R['mu_r']['basis']}.", ""]
    if R["contacts"]["stray"]:
        lines += ["## Stray contacts (first 30)", ""] + [f"- f{e['frame']:.0f} {e['pair']} v_n {e['v_n']:.4f}"
                                                         for e in R["contacts"]["stray"]] + [""]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    track, bake, contacts = load()
    res, ev = checks(track, bake, contacts)
    latch = V6 / "latch" / "latch-30mm.json"
    if latch.exists():
        res["latch"] = json.loads(latch.read_text(encoding="utf-8"))["ball_30mm"]
    (OUT / "event-log.json").write_text(json.dumps({"ball_contacts": ev, "row_contacts": res["rows"],
                                                    "classes": T.DESIGNED, "checks": {k: v for k, v in res.items()
                                                                                      if k != "rows"}},
                                                   indent=1, default=float), encoding="utf-8")
    plot(track, bake, ev, res, OUT / "bake-plot.png")
    report(res, OUT / "report.md")
    print(json.dumps({k: (v.get("pass", v.get("pass_")) if isinstance(v, dict) else None) for k, v in res.items()}))


if __name__ == "__main__":
    main()
