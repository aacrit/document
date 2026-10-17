"""The Run: the contact event list, from a 1 kHz contact log (stdlib only).

The simulation samples every active contact once a millisecond as {t_s, pair, v_n, f_n}: the pair is the two geom
names sorted and joined by "|", v_n the normal approach speed (m/s, positive closing), f_n the normal force (N).
A contact *event* is the onset of a pair: the first sample of a pair that was not in contact in the previous
millisecond. Its impulse is the normal force integrated over the contact's first IMPULSE_MS milliseconds (or until it
separates), N s. Events slower than V_MIN are rolling contact or resting, not sounds, and are kept out of the list.
Each event is one JSONL line: {"t_s", "frame", "pair", "v_n", "impulse"}. The sound and the score sync to this list.
"""

from __future__ import annotations

import json
from pathlib import Path

DT = 0.001
IMPULSE_MS = 5
V_MIN = 0.005
FPS = 24


def events(samples, v_min: float = V_MIN, impulse_ms: int = IMPULSE_MS, t_offset: float = 0.0) -> list[dict]:
    """Onsets from a time-ordered list of samples (dicts with t_s, pair, v_n, f_n)."""
    by_t: dict[int, dict[str, dict]] = {}
    for s in samples:
        by_t.setdefault(round(s["t_s"] / DT), {})[s["pair"]] = s
    ticks = sorted(by_t)
    out, open_ = [], {}
    prev: set[str] = set()
    for k in ticks:
        cur = by_t[k]
        now = set(cur)
        if k - 1 not in by_t:
            prev = set()
        for pair in sorted(now - prev):
            open_[pair] = {"t_s": round(k * DT + t_offset, 4), "pair": pair, "v_n": round(cur[pair]["v_n"], 5),
                           "impulse": 0.0, "_left": impulse_ms}
        for pair in list(open_):
            ev = open_[pair]
            if pair in cur and ev["_left"] > 0:
                ev["impulse"] += cur[pair]["f_n"] * DT
                ev["_left"] -= 1
            if pair not in cur or ev["_left"] <= 0:
                out.append(ev)
                del open_[pair]
        prev = now
    out += list(open_.values())
    res = []
    for ev in sorted(out, key=lambda e: (e["t_s"], e["pair"])):
        if ev["v_n"] < v_min:
            continue
        res.append({"t_s": ev["t_s"], "frame": round(ev["t_s"] * FPS, 2), "pair": ev["pair"], "v_n": ev["v_n"],
                    "impulse": round(ev["impulse"], 7)})
    return res


def write_jsonl(rows, path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def read_jsonl(path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
