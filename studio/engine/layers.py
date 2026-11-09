"""--layers (loom Phase 2b, reports/briefs/modular-engine/architecture.md section 8 Phase 2).

A render with ``--layers`` also writes the film as layers a finishing timeline can move:

- ``<out>/layers/plates/<shot>.<key>.mov``: each shot's clean plate, ProRes 422 HQ at the
  master rate: the shot's own picture (``Pictures.shot``) with nothing drawn over it and no
  transition or dip applied, plus handles. An archival clip's handles are its own source
  frames before its in point and after its out point, as far as the source (or its cached
  span, A26) goes, up to HANDLE_S each side. A still, a tour, a card or a series title extends
  its first and its last frame. Where the next shot dissolves out of this one, the tail
  starts with exactly the frames that dissolve shows. A JSON sidecar beside each plate gives
  the shot id, its record in and out, the plate frames they fall on and its handle frames.
- ``<out>/layers/overlay.mov``: one full-length pass, ProRes 4444 with alpha at the master
  rate: everything ``compose`` draws over the picture (lower thirds, text overlays, burned
  subtitles, the watermark and the provenance mark with its own clock, A16/A42), drawn by the
  same ``render.draw_overlays`` onto a transparent canvas. A dip's black hold and a series
  title that carries its own marks (A40) are transparent, as compose draws nothing there.
  Its alpha is straight (unassociated), as every frame's ``alpha`` field in layers.json says:
  a finishing bridge must set the clip's alpha mode to Straight, or its edges double-darken.
- ``<out>/layers/layers.json``: the sha256 of every file, and the timeline: which plate each
  record frame shows and on which plate frame, and the transitions (dissolve weights, dip
  levels) that rebuild the master's picture: ``frame = overlay over level x blend(from, to, w)``
  (``compose_layers``). Every range is half-open ``[in, out)``; each ``*_out`` field has an
  inclusive ``*_last`` sibling (``*_out - 1``).

Nothing here changes the master: the flag adds a folder after the master is written."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from studio.engine import cadence as CAD
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import titles as TS
from studio.engine.journal import Journal, sha256_file

LAYERS_VERSION = 1
HANDLE_S = 1.0                      # each side of a shot, where its source allows (architecture.md Phase 2)
PLATE_CODEC = {"codec": "prores_ks", "profile": "hq", "profile_id": 3, "pix_fmt": "yuv422p10le",
               "name": "ProRes 422 HQ"}
OVERLAY_CODEC = {"codec": "prores_ks", "profile": "4444", "profile_id": 4, "pix_fmt": "yuva444p10le",
                 "alpha_bits": 16, "alpha": "straight", "name": "ProRes 4444 with alpha"}
# Size estimates for the disk floor, in bits a pixel a frame. A plate is at ProRes 422 HQ's
# nominal rate (220 Mb/s at 1920x1080 and 29.97 fps, Apple's white paper: 3.54) with a
# margin. The overlay is mostly transparent: on the fixture film at 1080p (2026-11-07) it
# measured 0.21 a pixel on average over all its frames (the plates 0.71, on synthetic
# pictures with long flat cards; archival grain sits nearer the nominal rate). Frames carrying a lower third, an overlay or a subtitle are estimated at ProRes
# 4444's nominal rate (330 Mb/s: 5.3) and the rest at 0.5, over twice the measured average.
PLATE_BPP = 4.0
OVERLAY_BPP_BUSY = 5.3
OVERLAY_BPP_QUIET = 0.5
MOV_OVERHEAD_BYTES = 64 * 1024      # a mov's header and index, per file, with room to spare


class LayersRefused(R.Refused):
    """--layers was refused (the disk floor, or a folder that is not an earlier render's layers)."""


# --------------------------------------------------------------------------
# What each plate holds (pure)
# --------------------------------------------------------------------------


def handle_frames(plan: dict, handle_s: float = HANDLE_S) -> int:
    """HANDLE_S at the master rate, in whole frames (24 at 24, 30 at 30000/1001)."""
    return int(round(handle_s * R.fps_of(plan)))


def dissolve_out_frames(plan: dict, i: int) -> int:
    """How many frames after shot i's out point still show its picture: the
    frames of the next shot's dissolve in, by compose's own test."""
    shots = plan["shots"]
    if i + 1 >= len(shots):
        return 0
    nxt = shots[i + 1]
    n = 0
    for f in range(nxt["f0"], nxt["f1"]):
        if R.dissolve_weight_at(plan, f, i + 1) is None:
            break
        n += 1
    return n


def clip_room(s: dict) -> tuple[float, float]:
    """Seconds of an archival clip's source before its in point and after its
    out point that can be read: the reel's own, or its cached span's (A26),
    which keeps SPAN_PAD_S either side. (0, 0) when the source's length is unknown."""
    v = s.get("_video") or {}
    reel = float((v.get("probe") or {}).get("duration_s") or 0.0)
    if reel <= 0:
        return 0.0, 0.0
    start, end = 0.0, reel
    sp = s.get("_span")
    if sp:
        start = float(sp["offset_s"])
        req = sp.get("requested") or [s["in_s"], s["out_s"]]
        end = min(reel, float(req[1]) + float(sp.get("pad_s") or 0.0))
    return max(0.0, float(s["in_s"]) - start), max(0.0, end - float(s["in_s"]) - float(s["_dur"]))


def plate_spec(plan: dict, i: int, handle_s: float = HANDLE_S) -> dict:
    """What shot i's plate holds, decided from the plan alone. ``frames`` =
    head + record frames + tail. ``plate_in`` is the plate frame shown at the
    record in (``record_in``, the shot's first frame in the master) and
    ``plate_out`` the one after its last. The tail starts with the
    ``dissolve_out`` frames the next shot's dissolve shows, then the handle.
    ``head_from``/``tail_from``: ``source`` (an archival clip's own frames
    past its in or out point), ``frozen`` (the first or last frame extended)
    or ``none``. A clip's handles are as long as its source allows; the
    tail's final length is known only once read (a source can end early)."""
    s = plan["shots"][i]
    fps = R.fps_of(plan)
    h = handle_frames(plan, handle_s)
    n = s["f1"] - s["f0"]
    d = dissolve_out_frames(plan, i)
    clip = s["kind"] == "archive_video"
    if clip:
        before, after = clip_room(s)
        content = n + d                                   # frames of its own picture the master shows
        after = max(0.0, after + float(s["_dur"]) - content / fps)     # past the last frame the master shows
        head = min(h, int(math.floor(before * fps + 1e-6)))
        extra = min(max(0, h - d), int(math.floor(after * fps + 1e-6)))
        head_from = "source" if head else "none"
        tail_from = "source" if extra else ("dissolve" if d else "none")
    else:
        head, extra = h, max(0, h - d)
        head_from = "frozen"
        tail_from = "frozen" if extra else ("dissolve" if d else "none")
    tail = d + extra
    return {"shot": s["id"], "kind": s["kind"], "mark": s.get("mark"), "record_in": s["f0"], "record_out": s["f1"],
            "record_last": s["f1"] - 1, "record_frames": n, "head_frames": head, "tail_frames": tail,
            "dissolve_out_frames": d, "plate_in": head, "plate_out": head + n, "plate_last": head + n - 1,
            "frames": head + n + tail, "head_from": head_from, "tail_from": tail_from, "handle_frames": h}


def plate_key(plan: dict, i: int, spec: dict, asset_hash: dict, env_key: dict | None) -> str:
    """The plate's cache key: the shot's segment key (its pictures, ffmpeg,
    the fonts, the engine), the layers' version and code, and its handles."""
    rec = {"segment": R.shot_key(plan, i, asset_hash, env_key), "layers": LAYERS_VERSION, "code": _CODE_HASH,
           "spec": {k: spec[k] for k in ("head_frames", "tail_frames", "dissolve_out_frames", "head_from", "tail_from")},
           "codec": PLATE_CODEC}
    return hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:16]


_CODE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def overlay_busy(plan: dict, f: int) -> bool:
    """A frame whose overlay carries a wide wash or text: a lower third, a text
    overlay or a burned subtitle is up."""
    t = f / plan["fps"]
    return any(x["start"] <= t < x["end"] for k in ("lower_thirds", "overlays", "subtitles") for x in plan.get(k) or [])


def _plates_bytes(plan: dict, specs: list[dict]) -> int:
    px = plan["W"] * plan["H"]
    return int(sum(sp["frames"] for sp in specs) * px * PLATE_BPP / 8 + len(specs) * MOV_OVERHEAD_BYTES)


def _overlay_bytes(plan: dict) -> int:
    px = plan["W"] * plan["H"]
    busy = sum(1 for f in range(plan["frames"]) if overlay_busy(plan, f))
    return int((busy * OVERLAY_BPP_BUSY + (plan["frames"] - busy) * OVERLAY_BPP_QUIET) * px / 8 + MOV_OVERHEAD_BYTES)


def layers_bytes(plan: dict, specs: list[dict]) -> int:
    """The layers' full size before any is written, an upper estimate (see the BPP constants):
    every plate at its own frame count, the whole overlay pass, and the sidecars."""
    return _plates_bytes(plan, specs) + _overlay_bytes(plan) + 256 * 1024 * (1 + len(specs))


PLATE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.[0-9a-f]{16}\.mov(\.json|\.part)?$")


def is_plate_file(name: str) -> bool:
    """A name this pass writes under layers/plates: ``<safe stem>.<16 hex key>.mov``, its
    ``.mov.json`` sidecar or a ``.mov.part`` left by a run that stopped. Only these are ever
    removed as stale; any other file there (a user's own .mov) is left alone."""
    return bool(PLATE_FILE_RE.fullmatch(name))


def plate_write_plan(plan: dict, plates_dir: Path, specs: list[dict], asset_hash: dict,
                     env_key: dict | None) -> dict:
    """Which of ``specs``' plates already sit under ``plates_dir`` by this run's key (a cache
    hit: nothing to render) and which still need rendering, and the bytes any plate file under
    ``plates_dir`` outside this run's keep set would free once write_layers removes it (an
    older key, or a partial file from a run that stopped). Pure: reads the directory's current
    listing but writes nothing, so an estimate and write_layers' own pass always agree."""
    used: set[str] = set()
    names: dict[int, str] = {}
    todo: list[int] = []
    keep: set[str] = set()
    for i, sp in enumerate(specs):
        stem = R.stem_file_name(sp["shot"], used)
        key = plate_key(plan, i, sp, asset_hash, env_key)
        name = f"{stem}.{key}.mov"
        names[i] = name
        keep.update({name, name + ".json"})
        p = plates_dir / name
        if not (p.exists() and p.with_name(name + ".json").exists()):
            todo.append(i)
    stale_bytes = 0
    if plates_dir.exists():
        for old in plates_dir.iterdir():
            if old.name not in keep and is_plate_file(old.name):
                try:
                    stale_bytes += old.stat().st_size
                except OSError:
                    pass
    return {"names": names, "todo": todo, "keep": keep, "stale_bytes": stale_bytes}


def remaining_layers_bytes(plan: dict, plates_dir: Path, specs: list[dict], asset_hash: dict,
                           env_key: dict | None) -> tuple[int, dict]:
    """What ``--layers`` still needs to write: the plates not yet cached under ``plates_dir`` by
    this run's key, plus the overlay (always written in full; nothing caches it), less the bytes
    any stale plate under ``plates_dir`` will free once write_layers removes it, before
    rendering starts. Returns the estimate and the write plan (``plate_write_plan``)."""
    wp = plate_write_plan(plan, plates_dir, specs, asset_hash, env_key)
    todo_specs = [specs[i] for i in wp["todo"]]
    need = (_plates_bytes(plan, todo_specs) + _overlay_bytes(plan) + 256 * 1024 * (1 + len(todo_specs))
            - wp["stale_bytes"])
    return max(0, int(need)), wp


def check_disk(out_dir: Path, need: int, *, min_free_gb: float, disk_usage=shutil.disk_usage) -> dict:
    """Refuse when writing ``need`` bytes would leave the out drive under its floor
    (``drive_floor_gb``: ``min_free_gb``, or D:'s 12 GB when that is higher)."""
    anchor = R._existing(out_dir)
    floor = R.drive_floor_gb(anchor, min_free_gb)
    free = disk_usage(anchor).free
    if free - need < floor * 1024 ** 3:
        raise LayersRefused(f"--layers: the layers need about {need / 1024 ** 3:.2f} GB and the out drive has "
                            f"{free / 1024 ** 3:.2f} GB free; writing them would leave it under the {floor:g} GB floor")
    return {"need_bytes": need, "free_bytes": free, "floor_gb": floor}


def _assert_writable(path: Path, what: str, *, opener=open) -> None:
    """Raise a clear ``LayersRefused`` when ``path`` exists but cannot be opened for writing:
    Windows refuses (WinError 32, a ``PermissionError``) while another program, such as
    DaVinci Resolve, holds it open. Checked before the pass starts, so a locked file is refused
    before any plate or the overlay is rendered, never discovered only after the work is done."""
    if not path.exists():
        return
    try:
        opener(path, "r+b").close()
    except OSError as exc:
        raise LayersRefused(f"--layers: {what} ({path.name}) could not be opened to replace or remove; if it is "
                            f"open in Resolve or another program, close it there and render again ({exc})") from exc


# --------------------------------------------------------------------------
# Encoders and readers
# --------------------------------------------------------------------------


def _rate(plan: dict) -> str:
    return plan.get("fps_rate") or CAD.rate_str(CAD.HOUSE)


def plate_encoder_cmd(plan: dict, out: Path) -> list[str]:
    return [R.ffmpeg(), "-v", "error", "-y", "-filter_threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{plan['W']}x{plan['H']}", "-r", _rate(plan), "-i", "-",
            "-vf", f"scale=out_color_matrix=bt709:out_range=tv,format={PLATE_CODEC['pix_fmt']},"
                   "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
            "-c:v", "prores_ks", "-profile:v", str(PLATE_CODEC["profile_id"]), "-vendor", "apl0", "-threads", "1",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-video_track_timescale", str(R.master_timescale(plan)), "-f", "mov", str(out)]


def overlay_encoder_cmd(plan: dict, out: Path) -> list[str]:
    return [R.ffmpeg(), "-v", "error", "-y", "-filter_threads", "1", "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{plan['W']}x{plan['H']}", "-r", _rate(plan), "-i", "-",
            "-vf", f"scale=out_color_matrix=bt709:out_range=tv,format={OVERLAY_CODEC['pix_fmt']},"
                   "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
            "-c:v", "prores_ks", "-profile:v", str(OVERLAY_CODEC["profile_id"]), "-alpha_bits",
            str(OVERLAY_CODEC["alpha_bits"]), "-vendor", "apl0", "-threads", "1",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-video_track_timescale", str(R.master_timescale(plan)), "-f", "mov", str(out)]


def read_frames(path: Path | str, W: int, H: int, *, alpha: bool = False, start: int = 0, count: int | None = None):
    """Decode a layer (or the master) to 8-bit RGB (or RGBA) arrays, frames
    ``start`` to ``start + count``, in order (bt709, tv range, as written)."""
    ch = 4 if alpha else 3
    vf = f"select=gte(n\\,{start}),scale=in_color_matrix=bt709:in_range=tv,format={'rgba' if alpha else 'rgb24'}"
    cmd = [R.ffmpeg(), "-v", "error", "-threads", "1", "-i", str(path), "-vf", vf, "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24", "-"]
    if count is not None:
        cmd[-1:-1] = ["-frames:v", str(count)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    n = W * H * ch
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                return
            yield np.frombuffer(buf, np.uint8).reshape(H, W, ch)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


class _Encoder:
    def __init__(self, cmd: list[str], part: Path, what: str):
        self.err = tempfile.TemporaryFile()
        self.part, self.what = part, what
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.err)
        self.n = 0

    def write(self, img: Image.Image) -> None:
        try:
            self.proc.stdin.write(img.tobytes())
        except (BrokenPipeError, OSError) as exc:
            self.err.seek(0)
            raise R.EncodeError(f"{self.what} encoder stopped: {self.err.read().decode(errors='replace')[-500:]}") from exc
        self.n += 1

    def finish(self, expect: int) -> None:
        self.proc.stdin.close()
        if self.proc.wait():
            self.err.seek(0)
            raise R.EncodeError(f"{self.what} encoder exited {self.proc.returncode}: "
                                f"{self.err.read().decode(errors='replace')[-500:]}")
        got = R.count_frames(self.part)
        if got != expect:
            raise R.EncodeError(f"{self.what} holds {got} frames, expected {expect}")

    def abort(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        self.err.close()
        R._unlink_quietly(self.part)


# --------------------------------------------------------------------------
# The clean plate (worker side)
# --------------------------------------------------------------------------


def _handle_reader(s: dict, from_s: float, frames: int, fps: float) -> R.VideoReader:
    """A reader of ``frames`` of the clip's source from ``from_s`` seconds after
    its in point (negative: before it), conformed and fitted as the shot's
    own frames are."""
    return R.VideoReader(dict(s, in_s=float(s["in_s"]) + from_s, _dur=frames / fps), 0.0)


def plate_frames(plan: dict, i: int, spec: dict):
    """Yield shot i's plate, frame by frame, as RGB images, and lastly a dict
    with what was read: the tail actually written (a clip's source can end
    before the frames its length promised; the held frames are dropped,
    never shown) and the frames held."""
    s = plan["shots"][i]
    fps = plan["fps"]
    clip = s["kind"] == "archive_video"
    n, d, head = spec["record_frames"], spec["dissolve_out_frames"], spec["head_frames"]
    extra = spec["tail_frames"] - d
    pics = R.Pictures(plan)
    side: list[R.Pictures] = []
    readers: list[R.VideoReader] = []
    got = {"head_frames": head, "tail_frames": d, "held": 0}
    try:
        if head and clip:
            r = _handle_reader(s, -head / fps, head, fps)
            readers.append(r)
            for j in range(head):
                yield pics.fit_video(s, r.frame(j / fps), 0.0)
            if r.held:
                raise R.EncodeError(f"plate {s['id']}: the source ended inside the head handle ({r.held} frames held)")
        elif head:
            first = R.Pictures(plan)
            side.append(first)
            img = first.shot(i, 0.0)                    # the shot's first frame, as compose shows it
            for _ in range(head):
                yield img
        last = None
        for f in range(s["f0"], s["f1"]):              # the record frames: compose's own call, frame for frame
            last = pics.shot(i, f / fps - s["f0"] / fps)
            yield last
        if d:                                           # the next shot's dissolve: as its own segment reads this shot
            dis = R.Pictures(plan)
            side.append(dis)
            for f in range(s["f1"], s["f1"] + d):
                last = dis.shot(i, f / fps - s["f0"] / fps)
                yield last
        if extra and clip:
            r = _handle_reader(s, (n + d) / fps, extra, fps)
            readers.append(r)
            end_tl = float(s["_dur"])
            for j in range(extra):
                fr = r.frame(j / fps)
                if r.held:                              # the source ended: the tail stops at its last real frame
                    got["held"] = r.held
                    break
                got["tail_frames"] += 1
                yield pics.fit_video(s, fr, end_tl)
        elif extra:
            for _ in range(extra):
                got["tail_frames"] += 1
                yield last
        yield got
    finally:
        for r in readers:
            r.close()
        for p in [pics, *side]:
            p.close()


def render_plate(plan: dict, i: int, path: str, spec: dict, sink=None) -> dict:
    """Worker: shot i's clean plate to ``path`` (ProRes 422 HQ) and its sidecar
    ``path.json``. Returns the sidecar. ``sink`` (a queue or any ``.put``able
    object), when given, gets a progress message about once a second so a
    long plate shows up in the journal while it is still being written."""
    t0 = time.perf_counter()
    path = Path(path)
    part = path.with_name(path.name + ".part")
    enc = _Encoder(plate_encoder_cmd(plan, part), part, f"plate {spec['shot']}")
    got = None
    fps = R.fps_of(plan)
    try:
        for k, img in enumerate(plate_frames(plan, i, spec)):
            if isinstance(img, dict):
                got = img
                break
            enc.write(img)
            if sink is not None and k % max(1, round(fps)) == 0:
                sink.put({"shot": spec["shot"], "frame": k, "frames": spec["frames"]})
        head, tail = got["head_frames"], got["tail_frames"]
        frames = head + spec["record_frames"] + tail
        enc.finish(frames)
        os.replace(part, path)
    except BaseException:
        enc.abort()
        raise
    enc.err.close()
    s = plan["shots"][i]
    d = spec["dissolve_out_frames"]
    tail_from = spec["tail_from"]
    if s["kind"] == "archive_video":                    # what the tail turned out to hold, once read
        tail_from = "source" if tail > d else ("dissolve" if d else "none")
    side = dict(spec, file=path.name, tail_frames=tail, frames=frames, plate_out=spec["plate_in"] + spec["record_frames"],
                held_dropped=got["held"], tail_from=tail_from, fps=R.fps_of(plan), fps_rate=_rate(plan),
                codec=PLATE_CODEC["name"], wall_s=round(time.perf_counter() - t0, 3))
    if s["kind"] == "archive_video":
        fps = R.fps_of(plan)
        side["source"] = {"in_s": float(s["in_s"]), "out_s": float(s.get("out_s", s["in_s"] + s["_dur"])),
                          "plate_frame_0_s": round(float(s["in_s"]) - head / fps, 6),
                          "note": "reel seconds; the plate's frame k shows the source at plate_frame_0_s + k / fps"}
    path.with_name(path.name + ".json").write_text(json.dumps(side, indent=2, sort_keys=True), encoding="utf-8")
    return side


# --------------------------------------------------------------------------
# The overlay pass
# --------------------------------------------------------------------------


def overlay_canvas(plan: dict, pics, f: int, i: int, probe: dict | None = None) -> Image.Image:
    """Frame f's overlay: what compose draws over the picture, on a transparent
    canvas (transparent where compose draws nothing)."""
    canvas = Image.new("RGBA", (plan["W"], plan["H"]), (0, 0, 0, 0))
    if not R.overlays_drawn(plan, f, i):
        if probe is not None:
            probe["bare_rgba"] = [(0, 0, 0, 0)] * len(M.glyph_shape_probes(pics.L))
        return canvas
    return R.draw_overlays(canvas, plan, pics, f, i, probe)


def over(fg: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """``fg`` (RGBA, straight alpha) over an RGB ``bg``, as PIL's alpha_composite does it, to RGB uint8."""
    base = Image.fromarray(np.ascontiguousarray(bg[..., :3])).convert("RGBA")
    return np.asarray(Image.alpha_composite(base, Image.fromarray(np.ascontiguousarray(fg))).convert("RGB"))


def label_zone(L: M.Layout) -> tuple[int, int, int, int]:
    """The label's own pixels (A31): x from LABEL_MIN_X to the glyph tile's left, y over the mark zone."""
    gx, _ = M.glyph_origin(L)
    return (int(math.ceil(L.w(M.LABEL_MIN_X))), int(math.floor(M.MARK_ZONE[1] * L.H)),
            gx - max(1, L.px(M.LABEL["halo"])), int(math.ceil(M.MARK_ZONE[3] * L.H)))


def label_ink(rgb_over_black: np.ndarray, L: M.Layout) -> int:
    """The brightest pixel in the label's zone of an overlay laid over black:
    the label's near-white words show there, every other overlay's wash is black."""
    x0, y0, x1, y1 = label_zone(L)
    z = rgb_over_black[y0:y1, x0:x1, :3]
    return int(z.max()) if z.size else 0


LABEL_ON_COVER = 0.5                # a label at least half up and half grown has a word pixel at least half covered
LABEL_OFF_INK = 12                  # no label leaves the zone under this over black (encode ringing included)


def label_on_ink(cls: str | None, label_alpha: float) -> float:
    """The least a shown label's brightest word pixel reaches over black: its
    words' hue at the class's opacity and the label's own, half covered."""
    _, opacity = M.label_type(cls)
    return LABEL_ON_COVER * min(M.PALETTE["mark_text"]) * opacity * label_alpha


def probe_overlay_frame(plan: dict, rgba: np.ndarray, f: int, i: int, bare_rgba) -> dict:
    """The dot's probes on the overlay alone, laid over black: the glyph's shape
    and hue (render.check_mark, over the same black) and the label's presence
    as mark_state says it should be (label_ink). Series titles are checked by
    their own marks (A40) and are skipped here."""
    s = plan["shots"][i]
    if s.get("_title") is not None:
        return {"glyph": "title", "label": "title"}
    black = np.zeros(rgba.shape[:2] + (3,), np.uint8)
    arr = over(rgba, black)
    bare = [tuple(int(v) for v in over(np.array([[px]], np.uint8), np.zeros((1, 1, 3), np.uint8))[0, 0])
            for px in bare_rgba] if bare_rgba is not None else None
    glyph = R.check_mark(plan, arr, f, i, bare)
    st = M.mark_state(f / plan["fps"], plan["marks"])
    L = M.Layout(plan["W"], plan["H"])
    ink = label_ink(arr, L)
    if not R.overlays_drawn(plan, f, i):
        label = "dip" if ink == 0 else "fail"
    elif st and st["label"] and st["label_alpha"] >= 0.5 and st["label_reveal"] >= 0.5:
        label = "on" if ink >= label_on_ink(st["cls"], st["label_alpha"]) else "fail"
    elif not st or not st["label"] or st["label_alpha"] <= 0.0 or st["label_reveal"] <= 0.0:
        label = "off" if ink <= LABEL_OFF_INK else "fail"
    else:
        label = "partial"                                  # surfacing or folding: not judged
    return {"glyph": glyph, "label": label, "ink": ink}


def render_overlay(plan: dict, path: Path, sink=None) -> dict:
    """The full-length overlay pass to ``path`` (ProRes 4444 with alpha), with
    the dot's probes run on every frame's canvas as it is encoded."""
    t0 = time.perf_counter()
    path = Path(path)
    part = path.with_name(path.name + ".part")
    pics = R.Pictures(plan)                                  # fonts and layout only: no picture is read
    enc = _Encoder(overlay_encoder_cmd(plan, part), part, "overlay")
    stats = {"glyph": {}, "label": {}, "fail_frames": [], "transparent_frames": 0, "bare_not_clear": 0}
    try:
        for i, s in enumerate(plan["shots"]):
            for f in range(s["f0"], s["f1"]):
                probe: dict = {}
                canvas = overlay_canvas(plan, pics, f, i, probe)
                arr = np.asarray(canvas)
                if not arr[..., 3].any():
                    stats["transparent_frames"] += 1
                bare = probe.get("bare_rgba")
                if bare and any(px[3] for px in bare):
                    stats["bare_not_clear"] += 1                 # another overlay under the glyph: judged over it
                res = probe_overlay_frame(plan, arr, f, i, bare)
                for k in ("glyph", "label"):
                    stats[k][res[k]] = stats[k].get(res[k], 0) + 1
                if (res["glyph"] in ("fail", "shape") or res["label"] == "fail") and len(stats["fail_frames"]) < 10:
                    stats["fail_frames"].append(f)
                enc.write(canvas)
                if sink is not None and f % max(1, round(plan["fps"])) == 0:
                    sink({"frame": f, "frames": plan["frames"]})
        enc.finish(plan["frames"])
        os.replace(part, path)
    except BaseException:
        enc.abort()
        raise
    finally:
        pics.close()
    enc.err.close()
    stats["frames"] = plan["frames"]
    stats["wall_s"] = round(time.perf_counter() - t0, 3)
    return stats


# --------------------------------------------------------------------------
# The timeline and the recipe that rebuilds the master's picture
# --------------------------------------------------------------------------


def timeline(plan: dict, specs: list[dict]) -> dict:
    """Record frame to plate and plate frame: each shot's run of record frames
    (``record_in`` to ``record_out``) shows its plate from ``plate_in``, one
    plate frame a record frame. Dissolves give, per record frame, the outgoing
    plate's frame and the incoming shot's weight; dips give each frame's
    picture level (0 is the black hold, where the overlay is transparent too)."""
    by = {sp["shot"]: sp for sp in specs}
    runs, dissolves, dips = [], [], []
    shots = plan["shots"]
    for i, s in enumerate(shots):
        sp = by[s["id"]]
        runs.append({"record_in": s["f0"], "record_out": s["f1"], "record_last": s["f1"] - 1,
                     "plate": s["id"], "plate_in": sp["plate_in"]})
        frames = []
        for f in range(s["f0"], s["f1"]):
            w = R.dissolve_weight_at(plan, f, i)
            if w is None:
                break
            prev = by[shots[i - 1]["id"]]
            frames.append({"record": f, "from_plate_frame": prev["plate_in"] + (f - shots[i - 1]["f0"]),
                           "weight": w})
        if frames:
            dissolves.append({"from": shots[i - 1]["id"], "to": s["id"], "record_in": frames[0]["record"],
                              "record_out": frames[-1]["record"] + 1, "record_last": frames[-1]["record"],
                              "frames": frames})
        for f in range(s["f0"], s["f1"]):
            lv = R.picture_level(plan, f, i)
            if lv < 1.0:
                dips.append({"record": f, "level": lv})
    return {"runs": runs, "dissolves": dissolves, "levels": dips,
            "rule": "record frame r of a run shows its plate's frame plate_in + (r - record_in)"}


def compose_layers(plate: np.ndarray, overlay: np.ndarray, *, prev: np.ndarray | None = None,
                   weight: float | None = None, level: float = 1.0) -> np.ndarray:
    """One master frame rebuilt from its layers, compose's arithmetic in its
    order: the outgoing plate blended in (a dissolve), the dip's level, then
    the overlay over it. RGB uint8 plates, an RGBA uint8 overlay."""
    img = Image.fromarray(np.ascontiguousarray(plate[..., :3]))
    if weight is not None and prev is not None:
        img = Image.blend(Image.fromarray(np.ascontiguousarray(prev[..., :3])), img, weight)
    img = R.apply_level(img, level)
    return over(overlay, np.asarray(img))


# --------------------------------------------------------------------------
# The pass, from render()
# --------------------------------------------------------------------------


def check_washes(plan: dict) -> None:
    """compose == plate + overlay only when each lower third's wash is the one planned for its
    span (founder ruling 2026-11-07, render._plan_lower_third_washes): without it compose
    measures the picture under the frame, which the overlay's transparent canvas does not have,
    so the overlay would draw another wash than the master's. Refused, naming the lower thirds."""
    unplanned = [str(lt.get("id", k)) for k, lt in enumerate(plan["lower_thirds"]) if lt.get("wash") is None]
    if unplanned:
        raise LayersRefused(f"--layers: lower third {', '.join(unplanned)} has no planned wash, so the overlay pass "
                            "cannot draw the wash the master's compose measured from its picture")


def _prepare_dir(layers_dir: Path) -> None:
    """An earlier render's layers folder (one holding layers.json, or only
    plates and a partial overlay from a run that stopped) is kept as a cache;
    any other folder of that name is refused and left untouched."""
    if not layers_dir.exists():
        return
    if (layers_dir / "layers.json").is_file():
        return
    ok = {"plates", "overlay.mov", "overlay.mov.part", "layers.json.part", "layers.json.stale"}
    if any(p.name not in ok for p in layers_dir.iterdir()):
        raise LayersRefused(f"--layers: {layers_dir} exists but holds no layers.json, so it is not an earlier "
                            "render's layers; it is left untouched (move or remove it, then render again)")


def write_layers(plan: dict, run_dir: Path, master: Path, journal: Journal, *, asset_hash: dict,
                 env_key: dict | None, workers: int = 1, min_free_gb: float = R.MIN_FREE_GB,
                 disk_usage=shutil.disk_usage) -> Path:
    """``--layers``: every shot's clean plate, the overlay pass and layers.json
    under ``run_dir/layers``. Refused before any file is written when the
    estimate would take the out drive under ``min_free_gb``, or when
    overlay.mov or a stale plate cannot be replaced or removed (WinError 32:
    Resolve or another program has it open). Plates are cached by key like
    segments; a shot's plates under another key are removed."""
    layers_dir = run_dir / "layers"
    plates_dir = layers_dir / "plates"
    overlay_path = layers_dir / "overlay.mov"
    manifest_path = layers_dir / "layers.json"
    stale_manifest = layers_dir / "layers.json.stale"
    check_washes(plan)                                   # render's scout checks it too, before the master
    _prepare_dir(layers_dir)
    specs = [plate_spec(plan, i) for i in range(len(plan["shots"]))]
    need, wp = remaining_layers_bytes(plan, plates_dir, specs, asset_hash, env_key)
    disk = check_disk(run_dir, need, min_free_gb=min_free_gb, disk_usage=disk_usage)
    # Before anything is written or removed: a file this pass must replace or delete, held open by
    # another program (Resolve, most often), is refused clearly now, not discovered mid-pass.
    _assert_writable(overlay_path, "the overlay")
    if plates_dir.exists():
        for old in plates_dir.iterdir():
            if old.name not in wp["keep"] and is_plate_file(old.name):
                _assert_writable(old, "a stale plate")
        for i in wp["todo"]:                             # a plate re-rendered in place (its sidecar was missing)
            _assert_writable(plates_dir / wp["names"][i], "a plate to re-render")
    if manifest_path.exists():            # moved aside the moment the pass starts rewriting it (every pass
        os.replace(manifest_path, stale_manifest)       # rewrites it in full: the overlay is never cached)
    plates_dir.mkdir(parents=True, exist_ok=True)
    todo, sides = [], {}
    for i, sp in enumerate(specs):
        name = wp["names"][i]
        sp["file"] = name
        side = plates_dir / (name + ".json")
        if i not in wp["todo"]:
            try:
                sides[i] = json.loads(side.read_text(encoding="utf-8"))
                continue
            except (ValueError, OSError):
                pass
        todo.append((i, str(plates_dir / name)))
    for old in plates_dir.iterdir():                     # a plate under an old key (or a partial one) is stale
        if old.name not in wp["keep"] and is_plate_file(old.name):
            old.unlink(missing_ok=True)
    journal.decision("assembly", f"--layers: {len(specs)} plates ({len(todo)} to render, {len(specs) - len(todo)} cached) "
                     "and the overlay pass", "loom Phase 2b: a finishing timeline needs the clean picture and the "
                     "graphics apart", unit="layers", evidence=disk)

    def _tick(shot_id):
        def emit(msg):
            journal.event("timing", "assembly", shot_id, lens="frame", frame=msg["frame"], frames=msg["frames"])
        return emit

    n = max(1, min(int(workers), R.MAX_WORKERS, len(todo) or 1))
    if todo and n == 1:
        for i, p in todo:
            for attempt in (0, 1):                       # the same single retry the pool gives a plate
                try:
                    sides[i] = render_plate(plan, i, p, specs[i], sink=R._Direct(_tick(specs[i]["shot"])))
                    break
                except R.EncodeError as e:
                    if attempt:
                        raise
                    journal.retry("assembly", specs[i]["shot"], 1, str(e), fix="re-render the plate once")
    elif todo:
        import multiprocessing as mp
        import queue as queue_mod
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
        ctx = mp.get_context("spawn")
        with ctx.Manager() as manager:
            q = manager.Queue()

            def drain():
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue_mod.Empty:
                        return
                    journal.event("timing", "assembly", msg["shot"], lens="frame", frame=msg["frame"], frames=msg["frames"])

            attempts = {i: 0 for i, _ in todo}
            paths = dict(todo)
            with ProcessPoolExecutor(max_workers=n, mp_context=ctx) as ex:
                futs = {ex.submit(render_plate, plan, i, paths[i], specs[i], q): i for i in paths}
                pending = set(futs)
                try:
                    while pending:
                        done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                        drain()
                        for fut in done:
                            i = futs[fut]
                            try:
                                sides[i] = fut.result()
                            except R.EncodeError as e:
                                if attempts[i] < 1:
                                    attempts[i] += 1
                                    journal.retry("assembly", specs[i]["shot"], attempts[i], str(e),
                                                  fix="re-render the plate once")
                                    nf = ex.submit(render_plate, plan, i, paths[i], specs[i], q)
                                    futs[nf] = i
                                    pending.add(nf)
                                    continue
                                raise
                    drain()
                except BaseException:
                    ex.shutdown(wait=True, cancel_futures=True)
                    raise
    stats = render_overlay(plan, overlay_path,
                           sink=lambda msg: journal.event("timing", "assembly", "overlay", lens="frame", **msg))
    glyph_bad = sum(stats["glyph"].get(k, 0) for k in ("fail", "shape"))
    label_bad = stats["label"].get("fail", 0)
    journal.lint("layers-overlay-mark", glyph_bad == 0 and label_bad == 0, stage="marks", unit="layers",
                 grammar="A16, A42", phase="post-render",
                 evidence={"glyph": stats["glyph"], "label": stats["label"], "fail_frames": stats["fail_frames"],
                           "bare_not_clear": stats["bare_not_clear"],
                           "probe": "the overlay alone over black: the glyph's shape and hue, and the label as mark_state says"})
    if glyph_bad or label_bad:
        raise R.Refused(f"--layers: the overlay's mark probes failed on frames {stats['fail_frames']}")
    plates = []
    files = {}
    for i in range(len(specs)):
        side = sides[i]
        p = plates_dir / side["file"]
        rel = f"plates/{side['file']}"
        files[rel] = sha256_file(p)
        files[rel + ".json"] = sha256_file(p.with_name(p.name + ".json"))
        plates.append(dict(side, file=rel, sha256=files[rel], bytes=p.stat().st_size))
        journal.artifact("assembly", p, unit="layers", role=f"layers/{rel}")
    files["overlay.mov"] = sha256_file(overlay_path)
    journal.artifact("assembly", overlay_path, unit="layers", role="layers/overlay.mov")
    tl = timeline(plan, plates)
    manifest = {
        "version": LAYERS_VERSION, "engine": R.ENGINE_MODEL, "film": plan.get("slug"),
        "width": plan["W"], "height": plan["H"], "fps": R.fps_of(plan), "fps_rate": _rate(plan),
        "timescale": R.master_timescale(plan), "frames": plan["frames"], "handle_s": HANDLE_S,
        "master": {"file": master.name, "sha256": sha256_file(master)},
        "plates": plates,
        "overlay": {"file": "overlay.mov", "sha256": files["overlay.mov"], "bytes": overlay_path.stat().st_size,
                    "frames": plan["frames"], "record_in": 0, "record_out": plan["frames"],
                    "record_last": plan["frames"] - 1, "alpha": OVERLAY_CODEC["alpha"], "codec": OVERLAY_CODEC,
                    "probes": stats},
        "plate_codec": PLATE_CODEC,
        "ranges": "half-open [in, out); every *_out field has an inclusive *_last sibling (*_out - 1)",
        "timeline": tl,
        "compose": "frame r = overlay[r] over level(r) x blend(plate_from[from_plate_frame], plate_to[plate frame], "
                   "weight) (no blend outside a dissolve; level 1 outside a dip), straight alpha, as compose draws it",
        "files": files,
    }
    manifest_part = manifest_path.with_name(manifest_path.name + ".part")
    manifest_part.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(manifest_part, manifest_path)          # atomic: a crash never leaves a half-written manifest
    stale_manifest.unlink(missing_ok=True)            # this pass succeeded; the moved-aside copy is no longer needed
    journal.artifact("assembly", manifest_path, unit="layers", role="layers/layers.json")
    total = sum(pl["bytes"] for pl in plates) + manifest["overlay"]["bytes"]
    journal.decision("assembly", f"--layers: {len(plates)} plates and the overlay written to {layers_dir}",
                     "loom Phase 2b", unit="layers",
                     evidence={"dir": str(layers_dir), "bytes": total, "estimate_bytes": disk["need_bytes"],
                               "plates_bytes": sum(pl["bytes"] for pl in plates),
                               "overlay_bytes": manifest["overlay"]["bytes"]})
    return manifest_path
