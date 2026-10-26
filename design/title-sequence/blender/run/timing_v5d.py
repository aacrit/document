"""The Run v5d: the run's event list and contact onsets, corrected, from the unchanged v5c bake (CPU only, seconds).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/timing_v5d.py

Two defects in the v5c sim's written events (the bake itself, the marble's poses, is right and is reused unchanged):

1. sim_v5c's track took any x past the lip (2.43) for the felt well without checking y, and turn 1 reaches x 2.70.
   So 104 frames of turn 1 (239-342) got s = LENGTH + ..., and events_from_track wrote a false "step 1 (the leaf)" at
   7.946 s, a false "onto felt" from 7.96 to 11.4 s (the Foley laid a felt bed through turn 1), and, because the step
   search found that false crossing first, no event at all for the real step 1 at 15.85 s. Here the track's s and u
   are recomputed from the bake's own poses with channel_v5c.arc_s (past the lip only inside the well), and the
   events are re-derived by sim_v5c's own events_from_track.
2. run-timing.json's title_t / frame_24 and run-contact-events.jsonl's t_s still carry T_RELEASE = 0.5 s from bake
   time (it is 0.0 since 65daeda: title t = sim t). Here title_t = t, the onsets are on the raw sim clock, and each
   carries its 29.97 frame.

Writes D:/document-media/title-sequence/run/sim/v5d/{run-timing.json, run-contact-events.jsonl} (the v5c files are
left as the bake wrote them) with the sha256 of each source.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import eventlog as E  # noqa: E402

SIM_V5C = Path("D:/document-media/title-sequence/run/sim/v5c")
SIM_V5D = Path("D:/document-media/title-sequence/run/sim/v5d")
FPS = 30000 / 1001


def corrected_track(bake):
    """The bake's track ([t, s, u, speed, z] at 240 Hz) with s and u recomputed from the poses written beside it."""
    poses, track = bake["poses"]["marble"], bake["track"]
    if len(poses) != len(track):
        raise ValueError(f"the bake's poses ({len(poses)}) and track ({len(track)}) are not one sampling")
    out = []
    for p, r in zip(poses, track):
        if abs(p[0] - r[0]) > 1e-4:
            raise ValueError(f"pose t {p[0]} is not track t {r[0]}")
        s, u = C.arc_s(p[1], p[2])
        out.append([r[0], s, u if np.isfinite(u) else None, r[3], r[4]])
    return out


def events(track, t_rest):
    """sim_v5c's own event extraction on the corrected track (title time = sim time: T_RELEASE is 0)."""
    import sim_v5c as S                                   # mujoco is imported there; only its pure function is used
    if C.T_RELEASE != 0.0:
        raise ValueError("title t = sim t is assumed (channel_v5c.T_RELEASE 0)")
    ev = S.events_from_track(track, t_rest)
    for e in ev:
        e.pop("frame_24", None)
        e["frame_2997"] = round(e["t"] * FPS, 2)
    return ev


def corrected_contacts(contacts, release_s):
    """Contact onsets back on the raw sim clock (t_s minus the bake-time release offset), each with its 29.97 frame;
    the stale 24 fps 'frame' field is dropped."""
    out = []
    for c in contacts:
        t = round(c["t_s"] - release_s, 4)
        if t < 0:
            continue
        d = {k: v for k, v in c.items() if k != "frame"}
        d.update({"t_s": t, "frame_2997": round(t * FPS, 2)})
        out.append(d)
    return out


def corrected_timing(rep, bake):
    rest = rep["rest_sim_s"]
    tr = corrected_track(bake)
    out = {k: v for k, v in rep.items() if k != "events"}
    out.update({"what": rep["what"] + " -- events re-derived for v5d (timing_v5d.py): corrected arc length in turn 1, "
                                      "title t = sim t",
                "release_title_s": 0.0, "rest_title_s": rest, "title_total_s": round(rest + C.RUNTIME["arrive"], 3),
                "events": events(tr, rest),
                "corrections": ["s past the lip only inside the well (channel_v5c.arc_s): the false step 1 at 7.946 s "
                                "and the false felt 7.96-11.4 s are gone, the real step 1 is found",
                                f"the stale release offset ({rep['release_title_s']} s) removed: title_t = t"]})
    return out


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    rep = json.loads((SIM_V5C / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((SIM_V5C / "run-bake.json").read_text(encoding="utf-8"))
    contacts = E.read_jsonl(SIM_V5C / "run-contact-events.jsonl")
    t = corrected_timing(rep, bake)
    t["sources"] = {n: sha256(SIM_V5C / n) for n in ("run-timing.json", "run-bake.json", "run-contact-events.jsonl")}
    SIM_V5D.mkdir(parents=True, exist_ok=True)
    (SIM_V5D / "run-timing.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    E.write_jsonl(corrected_contacts(contacts, rep["release_title_s"]), SIM_V5D / "run-contact-events.jsonl")
    for e in t["events"]:
        print(f"{e['t']:7.3f} s  f {e['frame_2997']:7.1f}  {e['event']}")


if __name__ == "__main__":
    main()
