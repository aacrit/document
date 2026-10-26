"""GRAMMAR A40, the series titles: ``void document · As It Was``, a pre-rendered master played as it is.

A screenplay shot ``{kind: title_sequence, asset: <master id>, mark: DRAWN}`` sits right after the cold open (the hook)
and before Part 1. Its asset is a master clip in a ledger the film declares (``design/title-sequence``'s delivery:
lossless 1080p24), whose ledger item states what the master already carries:

    {"id": "TS-v1-S-130", "file": "title-v1-S-130.mkv", "licence": "CC BY 2.0", "ai": false,
     "generator": "...", "content_date": "1947-08-17", "content_basis": "...",
     "provenance": "<path to the title's assets-ledger.json>", "record": "S-130",
     "fps": 24, "width": 1920, "height": 1080, "frames": 1368, "burned": true,
     "marks": [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
               {"frame": 1152, "cls": "ARCHIVE", "label": "Archive · 1947"}, {"frame": 1248, "cls": "CARD"}],
     "record_frames": [1156, 1238], "dip": {"centre_frame": 1248, "s": 0.75}, "lockup_frame": 1320}

``burned: true`` means the master carries its own provenance glyph and labels, watermark and lockup, so the engine
draws nothing over it (no double mark); the lints read the pixels to confirm it. ``burned: false`` makes the engine
draw the glyph, the labels and the watermark from ``marks`` (and refuses a master that already shows a glyph).
Pure helpers and plan-time lints; render.py calls them.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from studio.engine import cadence as CAD
from studio.engine import motion as M

KIND = "title_sequence"
SERIES = "void document · As It Was"
SIZE = (1920, 1080)                 # the master is the 1080p24 delivery (GRAMMAR 7.5); the engine scales it for 720p
FPS = 24                            # the title master's own rate (its 1080p24 delivery); the film may master at another
                                    # rate (A44), and then the title is conformed to it by frame repeat, declared
FADE_FRAMES = round(M.LABEL["fade"] * FPS)   # the glyph's 4-frame crossfade at a class change (GRAMMAR 4.1), at 24


def fade_frames(item: dict) -> int:
    """The glyph's crossfade in the title master's own frames (4 at 24, 5 at 30000/1001: A44)."""
    return round(M.LABEL["fade"] * (rate_of(item) or FPS))
HUE_TOL = 2                         # a burned glyph pixel is its class hue within this (the master is lossless RGB)
RECORD_LIMIT = 6.0                  # A7's low-pass mean difference: the record beat is the film's own scan, held whole
LOCKUP_MIN_PX = 2000                # bright type pixels in the lockup band at 1080p: the words and the logomark are there
THEME_ROLE = "main_title"           # the main-title theme cue (score.py), composed for the series titles
STAND_IN = ("motif",)               # until the theme exists, the house motif may stand in (a reviewer item), or silence
PLACE_AFTER = "cold_open"           # the hook
CHAPTER = "chapter"                 # Part 1 and on
# Licences from the least to the most demanding: the master's own licence is at least as demanding as any input's.
_RANK = ((re.compile(r"^public domain$", re.I), 0), (re.compile(r"^cc0( 1\.0)?$", re.I), 1),
         (re.compile(r"^cc[- ]?by[- ]?sa([- ][1-4]\.0)?$", re.I), 3), (re.compile(r"^cc[- ]?by([- ][1-4]\.0)?$", re.I), 2))


def licence_rank(lic: str) -> int | None:
    lic = str(lic or "").strip()
    for rx, k in _RANK:
        if rx.match(lic):
            return k
    return None


def is_title(shot: dict) -> bool:
    return shot.get("kind") == KIND


def is_title_slot(shot: dict) -> bool:
    """A40 placeholder (founder ruling 2026-10-18): a shot holding the title slot with ``title_slot: true``
    until the series title ("The Run") is spliced in later, by ``render --shots``. It is an ordinary shot
    otherwise (a still or a card, most often): no asset, nothing burned, no A7 pose, and none of the other
    A40 checks (provenance, licence, format, marks, lockup, placement, transitions) run for it. Only
    title-theme treats it specially, accepting the main_title cue over a contiguous run of these shots
    exactly as over a title_sequence shot; every other lint still applies to it as the shot it is."""
    return shot.get("title_slot") is True


def _contiguous_runs(idx: list[int]) -> list[list[int]]:
    """``idx``, a sorted list of shot indices, grouped into runs of consecutive indices."""
    runs: list[list[int]] = []
    for i in idx:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


# --------------------------------------------------------------------------
# The master's declared mark timeline
# --------------------------------------------------------------------------


def timeline(item: dict) -> list[dict]:
    """The master's marks, sorted by frame: ``{frame, cls, label, year}``."""
    out = []
    for m in sorted(item.get("marks") or [], key=lambda m: int(m.get("frame", 0))):
        label = str(m.get("label") or "")
        y = re.search(r"(?<!\d)(\d{4})(?!\d)", label)
        out.append({"frame": int(m.get("frame", 0)), "cls": m.get("cls"), "label": label, "year": y.group(1) if y else None})
    return out


def classes(item: dict) -> list[str]:
    return [m["cls"] for m in timeline(item)]


def out_class(item: dict, default: str = "DRAWN") -> str:
    """The class the master ends on (its last mark): what the next shot's glyph crossfades from."""
    tl = timeline(item)
    return tl[-1]["cls"] if tl else default


def rate_of(item: dict) -> float | None:
    """The title master's own frame rate from its ledger item's ``fps`` (24 when it states none; A44: 24 or
    30000/1001), or None when it states another."""
    try:
        return float(CAD.parse_rate(item.get("fps", FPS)))
    except CAD.RateError:
        return None


def _r(item: dict) -> float:
    return rate_of(item) or float(FPS)


def select_master(item: dict, fps: float) -> tuple[dict, str]:
    """A44: the title master to play in a film mastering at ``fps``. A ledger item may declare masters at other rates
    beside its own file: ``masters: {"30000/1001": {"file": ..., "frames": ..., "marks": [...], "record_frames": [...],
    "dip": {...}, "lockup_frame": ...}}``, each stating its own frame counts (they differ by rate) over the item's.
    The master at the film's rate is played 1:1 ("own" when it is the item's file, "alternate" for one of
    ``masters``); when none is, the item's own file is conformed ("conform"). Returns (item to play, how)."""
    alts = item.get("masters") if isinstance(item.get("masters"), dict) else {}
    if rate_of(item) is not None and abs(_r(item) - fps) < 1e-6:
        return item, "own"
    for name, alt in alts.items():
        try:
            r = float(CAD.parse_rate(name))
        except CAD.RateError:
            continue
        if abs(r - fps) < 1e-6 and isinstance(alt, dict) and alt.get("file"):
            # an alternate's frame numbers are its own: it never inherits the item's record_pose (A40 refined)
            out = {k: v for k, v in item.items() if k not in ("masters", "record_pose")}
            out.update(alt, fps=CAD.rate_str(CAD.parse_rate(name)), master_of=item.get("file"))
            if item.get("_path"):
                out["_path"] = str((Path(item["_path"]).parent / alt["file"]).resolve())
            return out, "alternate"
    return item, "conform"


def sub_marks(item: dict, start_s: float) -> list[dict]:
    """The timeline as mark_frame's shots (absolute times), for a master the engine marks itself."""
    return [{"start": start_s + m["frame"] / _r(item), "cls": m["cls"], "label": m["label"], "year": m["year"]} for m in timeline(item)]


def source_frame(k: int, fps: float = FPS, src: float = FPS, n: int | None = None) -> int:
    """The title master's frame on the shot's frame k when the film masters at ``fps`` and the title at ``src`` (A44):
    k itself when they agree, else the frame a repeat or drop conform shows there (cadence.source_index)."""
    return CAD.source_index(k, src, fps, n)


def film_frame(j: int, fps: float = FPS, src: float = FPS) -> int:
    """The shot's frame on which the title master's frame j first shows (A44)."""
    return CAD.output_slot(j, src, fps)


def spans(item: dict, f0: int, f1: int, fps: float = FPS) -> list[tuple[int, int, str, str]]:
    """The title's frames by class: (from_frame, to_frame, cls, label), film frames at the film's master rate ``fps``,
    for the mark track and the share."""
    tl = timeline(item) or [{"frame": 0, "cls": "DRAWN", "label": ""}]
    out = []
    for k, m in enumerate(tl):
        a = f0 + film_frame(m["frame"], fps, _r(item))
        b = f0 + film_frame(tl[k + 1]["frame"], fps, _r(item)) if k + 1 < len(tl) else f1
        a, b = max(f0, min(a, f1)), max(f0, min(b, f1))
        if b > a:
            out.append((a, b, m["cls"], m["label"]))
    return out


def card_spans(item: dict, start_s: float, end_s: float) -> list[tuple[float, float]]:
    """The title's CARD stretches (the lockup), in seconds: the film's watermark stays off there and fades back after."""
    tl = timeline(item)
    out = []
    for k, m in enumerate(tl):
        if m["cls"] != "CARD":
            continue
        b = start_s + tl[k + 1]["frame"] / _r(item) if k + 1 < len(tl) else end_s
        out.append((start_s + m["frame"] / _r(item), b))
    return out


def dip_hold_frames(item: dict) -> list[int]:
    """The master's own dip (ARCHIVE to CARD): the frames of its black hold, master frames."""
    d = item.get("dip")
    if not isinstance(d, dict) or d.get("centre_frame") is None:
        return []
    c, s, r = int(d["centre_frame"]), float(d.get("s", 0.75)), _r(item)
    t0 = c / r - s / 2
    n = int(item.get("frames") or 0)
    return [k for k in range(max(0, int((t0 - 1) * r)), min(n, int((t0 + s + 1) * r)))
            if 0 <= k / r - t0 <= s and M.dip_level(k / r - t0, s, fps=r) <= 0.0]


def expected_class(item: dict, k: int, t: float | None = None) -> tuple[str | None, str | None, float]:
    """(class, outgoing class, crossfade weight) at master frame k (or at ``t`` seconds into the title, when the film
    masters at another rate and the engine draws the marks at its own frame times), as mark_frame draws it."""
    r = _r(item)
    st = M.mark_state(k / r if t is None else t, [{"start": m["frame"] / r, "cls": m["cls"], "label": m["label"]} for m in timeline(item)])
    if st is None:
        return None, None, 1.0
    return st["cls"], st["prev_cls"], st["mix"]


# --------------------------------------------------------------------------
# Pixels
# --------------------------------------------------------------------------


def read_frame(ffmpeg: str, path: str, k: int, size: tuple[int, int] = SIZE, fps: float = FPS) -> np.ndarray:
    """Master frame k (the master at ``fps``) as an HxWx3 uint8 array (RGB, no matrix: the master is RGB)."""
    W, H = size
    r = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{k / fps:.6f}", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    if len(r.stdout) != W * H * 3:
        raise ValueError(f"frame {k} of {path}: {len(r.stdout)} bytes, not {W}x{H} RGB ({r.stderr.decode(errors='replace')[-200:]})")
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3)


class Reader:
    """The master read in order from frame k0, one RGB frame at a time (a title shot renders its frames in order)."""

    def __init__(self, ffmpeg: str, path: str, k0: int, size: tuple[int, int] = SIZE, fps: float = FPS):
        self.W, self.H = size
        self.k = k0
        self.proc = subprocess.Popen([ffmpeg, "-v", "error", "-ss", f"{k0 / fps:.6f}", "-i", str(path), "-map", "0:v:0",
                                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        self.last: np.ndarray | None = None

    def frame(self, k: int) -> np.ndarray:
        n = self.W * self.H * 3
        while self.k <= k:
            buf = self.proc.stdout.read(n)
            if len(buf) < n:
                if self.last is None:
                    raise ValueError(f"the master ended before frame {k}")
                break                       # past the end: the format lint has already refused a short master
            self.last = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
            self.k += 1
        return self.last

    def close(self):
        try:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass


def _probe_expect(W: int, H: int, cls: str, at: tuple[int, int], bare) -> np.ndarray:
    tile, (ox, oy) = M.glyph_tile(W, H, cls)
    px = Image.new("RGBA", (1, 1), tuple(int(v) for v in bare[:3]) + (255,))
    px.alpha_composite(tile.crop((at[0] - ox, at[1] - oy, at[0] - ox + 1, at[1] - oy + 1)))
    return np.array(px.getpixel((0, 0))[:3], dtype=int)


def _centre_expect(W: int, H: int, cls: str) -> np.ndarray:
    """The glyph centre as the class draws it: its hue where the shape is solid there, else (the ring) over black,
    which is what the lockup's CARD sits on."""
    return _probe_expect(W, H, cls, M.glyph_centre(M.Layout(W, H)), (0, 0, 0))


def glyph_shows(arr: np.ndarray, cls: str) -> bool:
    """The frame carries ``cls``'s glyph (A16 refined, A31): the centre (and, for the square, its corner; for the
    ring over the lockup's black, every shape probe) is what the glyph composes there, within HUE_TOL."""
    H, W = arr.shape[:2]
    L = M.Layout(W, H)
    cx, cy = M.glyph_centre(L)
    if int(np.max(np.abs(arr[cy, cx, :3].astype(int) - _centre_expect(W, H, cls)))) > HUE_TOL:
        return False
    shape = M.GLYPH_SHAPE[cls]
    ox, oy = M.glyph_origin(L)
    corner_is_hue = int(np.max(np.abs(arr[oy, ox, :3].astype(int) - np.array(M.MARK_HUE[cls])))) <= HUE_TOL
    if shape == "square":                     # DRAWN's square: its corner is solid, which no other shape's is
        return corner_is_hue
    if shape == "diamond":                    # AI-GENERATED's diamond leaves the box's corner to the picture
        return not corner_is_hue
    if shape == "ring":
        return all(int(np.max(np.abs(arr[y, x, :3].astype(int) - _probe_expect(W, H, cls, (x, y), (0, 0, 0))))) <= HUE_TOL
                   for x, y in M.glyph_shape_probes(L))
    return True


def any_glyph(arr: np.ndarray) -> str | None:
    """The class whose glyph the frame already shows, if any (a master the engine would mark twice)."""
    for cls in ("DRAWN", "AI-GENERATED", "ARCHIVE", "RECONSTRUCTED"):
        if glyph_shows(arr, cls):
            return cls
    return None


def _mark_boxes(W: int, H: int) -> list[tuple[float, float, float, float]]:
    """Where marks are drawn, in pixels: the label's zone and the glyph's box (A31, with the label's shadow), and the
    watermark's box top right (BRAND-KIT 3, with its halo)."""
    pad = 8
    mark = (min(M.MARK_ZONE[0], M.MARK_GLYPH_ZONE[0]) * W - pad, min(M.MARK_ZONE[1], M.MARK_GLYPH_ZONE[1]) * H - pad,
            max(M.MARK_ZONE[2], M.MARK_GLYPH_ZONE[2]) * W + pad, max(M.MARK_ZONE[3], M.MARK_GLYPH_ZONE[3]) * H + pad)
    L = M.Layout(W, H)
    box = L.px(M.WM["box"])
    x1 = W - L.w(M.WM["right"])
    y0 = L.h(M.WM["top"])
    wm = (x1 - box - pad, y0 - pad, x1 + pad, y0 + box + pad)
    return [mark, wm]


def _marks_only(arr: np.ndarray) -> bool:
    """Every lit pixel lies where a mark is drawn (the provenance mark or the watermark): marks alone on black,
    no picture."""
    H, W = arr.shape[:2]
    ys, xs = np.nonzero(arr.max(axis=2))
    if not len(ys):
        return True
    inside = np.zeros(len(xs), dtype=bool)
    for x0, y0, x1, y1 in _mark_boxes(W, H):
        inside |= (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    return bool(inside.all())


def check_frame(arr: np.ndarray, item: dict, k: int, t: float | None = None) -> str:
    """One title frame's mark against the master's timeline: 'burned' (the class glyph is there), 'fade' (inside a
    class change's 4-frame crossfade, the centre between the two), 'dip' (the dip's black hold, every pixel off),
    'dip_glyph' (the black hold with marks alone on it, the glyph, a label or the watermark: a warning), else 'fail'."""
    H, W = arr.shape[:2]
    if k in dip_hold_frames(item):
        if not arr.any():
            return "dip"
        return "dip_glyph" if _marks_only(arr) else "fail"
    cls, prev, mix = expected_class(item, k, t)
    if cls is None:
        return "fail"
    if prev is not None and mix < 1.0:
        L = M.Layout(W, H)
        cx, cy = M.glyph_centre(L)
        a, b = _centre_expect(W, H, prev), _centre_expect(W, H, cls)
        p, d = arr[cy, cx, :3].astype(float), (b - a).astype(float)
        u = float(np.clip(np.dot(p - a, d) / max(float(np.dot(d, d)), 1e-9), 0.0, 1.0))
        return "fade" if float(np.max(np.abs(p - (a + u * d)))) <= 3.0 else "fail"
    return "burned" if glyph_shows(arr, cls) else "fail"


def hold_fit(img: Image.Image, W: int, H: int) -> Image.Image:
    """GRAMMAR 7.2 HOLD (A7): the whole picture, contained, on film black (assemble.py's own fit)."""
    k = min(W / img.width, H / img.height)
    w, h = round(img.width * k), round(img.height * k)
    out = Image.new("RGB", (W, H), M.PALETTE["black"])
    out.paste(img.convert("RGB").resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    return out


def _masked(a: np.ndarray) -> np.ndarray:
    """The picture without the marks: the label and glyph corner (bottom right) and the watermark (top right)."""
    a = a.astype(np.float32).copy()
    H, W = a.shape[:2]
    a[int(0.90 * H):, int(0.55 * W):] = 0
    a[:int(0.15 * H), int(0.85 * W):] = 0
    return a


POSE_ASPECT_TOL = 0.01              # A7 under A41: the pose window's aspect within 1% of the frame's
POSE_HOLD_S = 0.5                   # ... and the resting pose holds at least this long (a one-frame rest is no rest)
POSE_EDGE_PX = 8                    # ... and its outer frame strips (outside the marks) are the scan's, at full size:
POSE_EDGE_LIMIT = 12.0              # mean difference at most this, so a frame overshooting the scan onto black fails


def pose_fit(img: Image.Image, window, W: int, H: int) -> Image.Image:
    """A7 under A41 (founder, 2026-10-17: "A7 compares the tour's last full-frame pose against the matching crop of
    the ledger scan, with nothing but the scan in the frame"): the scan's ``window`` (x0, y0, x1, y1, fractions of
    the scan) filling the frame."""
    x0, y0, x1, y1 = (float(v) for v in window)
    box = (x0 * img.width, y0 * img.height, x1 * img.width, y1 * img.height)
    return img.convert("RGB").resize((W, H), Image.LANCZOS, box=box)


def pose_problem(window, scan_size: tuple[int, int], W: int, H: int) -> str | None:
    """Why a declared record pose is not a full-frame view of the scan alone, or None: the window lies inside the
    scan (nothing but the scan in the frame) and has the frame's aspect (filled, not stretched)."""
    try:
        x0, y0, x1, y1 = (float(v) for v in window)
    except (TypeError, ValueError):
        return "record_pose.window is not four numbers (x0, y0, x1, y1, fractions of the scan)"
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return f"record_pose.window {window} leaves the scan: only the scan may be in the frame"
    aspect = (x1 - x0) * scan_size[0] / ((y1 - y0) * scan_size[1])
    if abs(aspect / (W / H) - 1.0) > POSE_ASPECT_TOL:
        return f"record_pose.window's aspect {aspect:.4f} is not the frame's {W / H:.4f}: the frame is filled, never stretched"
    return None


def record_difference(arr: np.ndarray, record_path: str, window=None) -> float:
    """A7's low-pass mean difference between a master frame and the film's record scan (marks masked): held whole at
    the master's size (0.03 for the masters' own records, about 150 against another film's), or, under A41, its
    declared ``window`` filling the frame."""
    H, W = arr.shape[:2]
    with Image.open(record_path) as im:
        ref = np.asarray(pose_fit(im, window, W, H) if window is not None else hold_fit(im, W, H))

    def lp(x):
        return np.asarray(Image.fromarray(np.clip(x, 0, 255).astype(np.uint8)).resize((96, 54), Image.BOX), dtype=np.float32)

    return float(np.abs(lp(_masked(arr)) - lp(_masked(ref))).mean())


def pose_edge_difference(arr: np.ndarray, record_path: str, window) -> float:
    """A7 under A41, "nothing but the scan in the frame": the mean difference, at full size, between the master frame's
    outer POSE_EDGE_PX strips and the same strips of the scan's window filling the frame, outside the marks' masks. The
    low-pass A7 measure alone lets a frame overshoot the scan's edge onto black by tens of pixels."""
    H, W = arr.shape[:2]
    with Image.open(record_path) as im:
        ref = np.asarray(pose_fit(im, window, W, H)).astype(np.float32)
    keep = np.zeros((H, W), bool)
    e = POSE_EDGE_PX
    keep[:e, :] = keep[-e:, :] = True
    keep[:, :e] = keep[:, -e:] = True
    keep[int(0.90 * H):, int(0.55 * W):] = False            # the masks of _masked: the label and glyph, the watermark
    keep[:int(0.15 * H), int(0.85 * W):] = False
    return float(np.abs(arr.astype(np.float32)[keep] - ref[keep]).mean())


def lockup_pixels(arr: np.ndarray) -> int:
    """Bright pixels in the lockup's band (the middle third of the height): the words and the logomark."""
    H, W = arr.shape[:2]
    band = arr[H // 3: 2 * H // 3, W // 10: 9 * W // 10]
    n = int((band.max(axis=2) >= 150).sum())
    return round(n * (1080 / H) ** 2)


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def provenance(item: dict) -> tuple[dict | None, str | None, str | None]:
    """(the title's assets ledger, its path, the problem) from the master's ``provenance``, read as is or beside the
    ledger that holds the master."""
    ref = item.get("provenance")
    if not isinstance(ref, str) or not ref.strip():
        return None, None, "the master names no provenance (its title assets ledger)"
    p = Path(ref)
    if not p.is_absolute() and item.get("_ledger_file"):
        p = Path(item["_ledger_file"]).parent / p
    if not p.exists():
        return None, str(p), f"provenance ledger not found at {p}"
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p), None
    except Exception as e:
        return None, str(p), f"provenance ledger unreadable: {type(e).__name__}: {e}"


def provenance_items(prov: dict | None) -> list[dict]:
    return list((prov or {}).get("items") or [])


def plain(text) -> str:
    """A ledger's credit as words: the HTML a file page's attribution carries (links, bdi) taken out."""
    import html
    t = re.sub(r"<[^>]+>", "", str(text or ""))
    return " ".join(html.unescape(t).split())


# --------------------------------------------------------------------------
# Plan-time lints (GRAMMAR A40), called by render.build_plan once the timeline is tiled
# --------------------------------------------------------------------------


def _overlaps(a0: float, a1: float, b0: float, b1: float, eps: float = 0.5 / FPS) -> bool:   # half a frame at 24
    return a0 < b1 - eps and a1 > b0 + eps


def plan_lints(lint, journal, play: dict, shots: list[dict], assets: dict, *, lines: list[dict], texts: list[dict],
               cues: list[dict], vl: list[dict], silences: list, fps: float = FPS) -> dict:
    """Every A40 check the plan can decide. ``lint`` is build_plan's; ``silences`` gains the title's span when
    nothing sounds under it (silence is allowed until the main-title theme exists). Returns, per title shot id,
    what the plan and the frames need: {item, burned, record_path, probe}. ``fps`` is the film's master rate (A44): the
    shots' frames are at it, and a title at another rate is conformed to it by frame repeat and declared."""
    from studio.engine import render as R      # the engine's probes and licence rules (render imports this module)
    from studio.engine import score as SC

    out: dict = {}
    idx = [i for i, s in enumerate(shots) if is_title(s)]
    spans_s = [(shots[i]["f0"] / fps, shots[i]["f1"] / fps) for i in idx]
    # A40 placeholder (founder ruling 2026-10-18): a contiguous run of title_slot shots holds the slot until
    # the series title is spliced in, and counts here exactly as a title_sequence shot does; the per-shot
    # checks below (place, transitions, provenance, format, A7 pose, and so on) stay scoped to a real
    # title_sequence (``idx``) and never run for a placeholder.
    slot_runs = _contiguous_runs([i for i, s in enumerate(shots) if is_title_slot(s)])
    slot_spans_s = [(shots[run[0]]["f0"] / fps, shots[run[-1]]["f1"] / fps) for run in slot_runs]
    for c in cues:                             # the theme plays under the series titles (or its placeholder slot), nowhere else
        if c.get("kind", "music") != "music" or c.get("role") != THEME_ROLE:
            continue
        a, b = float(c["start_s"]), float(c["end_s"])
        if not any(t0 - 0.5 / fps <= a and b <= t1 + 0.5 / fps for t0, t1 in spans_s + slot_spans_s):
            lint("title-theme", False, unit=c.get("id"), grammar="A40",
                 evidence={"start_s": a, "end_s": b, "titles": [[round(x, 3) for x in sp] for sp in spans_s],
                           "slots": [[round(x, 3) for x in sp] for sp in slot_spans_s],
                           "fix": "a main_title cue plays under a title_sequence shot, or a contiguous run of "
                                  "title_slot placeholder shots, only, from its first frame"})
    if not idx:
        return out
    lint("title-sequence-once", len(idx) == 1, unit=shots[idx[0]]["id"], grammar="A40",
         evidence={"title_shots": [shots[i]["id"] for i in idx], "fix": None if len(idx) == 1 else "the series titles play once"})
    cold = [i for i, s in enumerate(shots) if s["_part_kind"] == PLACE_AFTER]
    chapters = [i for i, s in enumerate(shots) if s["_part_kind"] == CHAPTER]
    for i in idx:
        s = shots[i]
        item = s.get("_item") or {}
        sid = s["id"]
        t0, t1 = s["f0"] / fps, s["f1"] / fps
        # Placement: after the hook, before Part 1
        want = (cold[-1] + 1) if cold else 0
        place_ok = i == want and (not chapters or i < chapters[0])
        lint("title-sequence-place", place_ok, unit=sid, grammar="A40",
             evidence={"index": i, "expected_index": want, "after": shots[cold[-1]]["id"] if cold else None,
                       "first_chapter_shot": shots[chapters[0]]["id"] if chapters else None,
                       "fix": None if place_ok else "place the series titles right after the cold open's last shot, before Part 1"})
        # Transitions: the master opens and ends on its own black; nothing dissolves into or out of burned marks
        tin = (s.get("transition_in") or {}).get("type", "cut")
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        tout = (nxt.get("transition_in") or {}).get("type", "cut") if nxt else "cut"
        tr_ok = tin == "cut" and tout in ("cut", "dip")
        lint("title-sequence-transitions", tr_ok, unit=sid, grammar="A40, 4.4, 7.3",
             evidence={"in": tin, "out": tout, "next": nxt["id"] if nxt else None,
                       "fix": None if tr_ok else "cut into the series titles (the master opens from black); cut or dip out"})
        # Nothing spoken, drawn or subtitled over it
        over = [v["id"] for v in vl if _overlaps(v["start"], v["start"] + v["dur"], t0, t1)]
        over += [ln["id"] for ln in lines if ln.get("kind") in R.VOICE_KINDS and ln["id"] not in over
                 and t0 - 1e-9 <= float(ln.get("start_s", -1)) < t1]
        over += [t["id"] for t in texts if t.get("kind") in ("lower_third", "overlay")
                 and _overlaps(float(t["start_s"]), float(t["end_s"]), t0, t1)]
        over += [str(c.get("ref")) for c in play.get("subtitle_source", []) if isinstance(c.get("start_s"), (int, float))
                 and isinstance(c.get("end_s"), (int, float)) and _overlaps(float(c["start_s"]), float(c["end_s"]), t0, t1)]
        lint("title-sequence-clear", not over, unit=sid, grammar="A40",
             evidence={"over": over[:20], "fix": None if not over else "nothing is spoken, drawn or subtitled over the series titles"})
        # The audio slot: the main-title theme; until it exists, the house motif or silence
        sounding = [c for c in cues if _overlaps(float(c.get("start_s", 0)), float(c.get("end_s", 0)), t0, t1)]
        roles = {c.get("id"): (SC.cue_role(c) if c.get("kind", "music") == "music" else "ambience") for c in sounding}
        # A29 take (S7): the film's take runs from its first frame to its last, so it spans the slot; it may, only when
        # its rest map declares the A40 handover over the slot (the take rests there and the title carries the room;
        # the mix's take-handover lint measures that it does)
        handover = {c.get("id"): r["id"] for c in sounding if roles[c.get("id")] == "take"
                    for r in [SC.take_handover(c.get("_take"), t0, t1)] if r is not None}
        wrong = [cid for cid, r in roles.items() if r not in (THEME_ROLE,) + STAND_IN and cid not in handover]
        lint("title-audio-slot", not wrong, unit=sid, grammar="A40, A29, A29 take",
             evidence={"cues": roles, "allowed": [THEME_ROLE, *STAND_IN], "take_handover": handover,
                       "fix": None if not wrong else "only the main-title theme (or, until it exists, the house motif) "
                                                     "sounds under the series titles: end the other cues at the cut (a "
                                                     "take declares its rest there: why \"A40 handover\", from the "
                                                     "title's first frame to 8 s after its last)"})
        sounding = [c for c in sounding if c.get("id") not in handover]   # a resting take is not heard in the slot
        theme = [c for c in sounding if roles[c.get("id")] == THEME_ROLE]
        for c in theme:
            a, b = float(c["start_s"]), float(c["end_s"])
            ok = abs(a - t0) <= 0.5 / fps and b <= t1 + 0.5 / fps
            lint("title-theme", ok, unit=c.get("id"), grammar="A40",
                 evidence={"start_s": a, "end_s": b, "title": [round(t0, 3), round(t1, 3)],
                           "fix": None if ok else "the theme starts on the title's first frame and ends by its last"})
        if not theme:
            stand = [cid for cid, r in roles.items() if r in STAND_IN]
            journal.lint("title-theme-pending", True, stage="scout", unit=sid, severity="review", grammar="A40", phase="preflight",
                         evidence={"stand_in": stand or "silence",
                                   "check": "The main-title theme is not placed yet: the series titles play under "
                                            + ("the house motif" if stand else "silence")
                                            + ". Place the music director's main_title cue when it exists."})
            if not sounding:
                silences.append((t0, t1))
                journal.decision("scout", f"{sid}: silence under the series titles", "A40: until the main-title theme "
                                 "exists the slot may be silent; declared intended so A19 does not warn", unit=sid)
        # Provenance: the title's assets ledger, every input open-licensed, sourced and not AI
        prov, prov_path, why = provenance(item)
        problems = [why] if why else []
        pitems = provenance_items(prov)
        if prov is not None and not pitems:
            problems.append("the provenance ledger lists no items")
        for it in pitems:
            if not R.licence_allowed(str(it.get("licence") or ""), play)[0]:
                problems.append(f"{it.get('id')}: licence {it.get('licence')!r} is not allowed")
            if it.get("ai") is not False:
                problems.append(f"{it.get('id')}: ai must be stated false")
            if not (it.get("source_page") or it.get("source_url")):
                problems.append(f"{it.get('id')}: no source page")
            if not (it.get("licence_evidence") or it.get("basis")):
                problems.append(f"{it.get('id')}: no licence evidence or basis")
            if not it.get("sha256"):
                problems.append(f"{it.get('id')}: no sha256 of the file used")
        lint("title-provenance", not problems, unit=sid, grammar="A40, 1.2, 11.1",
             evidence={"provenance": prov_path, "items": len(pitems), "problems": problems[:20],
                       "licences": sorted({str(it.get("licence")) for it in pitems})})
        need = max([licence_rank(it.get("licence")) or 0 for it in pitems] or [0])
        have = licence_rank(item.get("licence"))
        lic_ok = have is not None and have >= need
        lint("title-licence", lic_ok, unit=sid, grammar="A40, 1.2",
             evidence={"licence": item.get("licence"), "rank": have, "inputs_need": need,
                       "attribution": [it.get("id") for it in pitems if (licence_rank(it.get("licence")) or 0) >= 2],
                       "fix": None if lic_ok else "the master's licence is at least as demanding as its inputs' "
                                                  "(CC BY when any input is CC BY)"})
        ai_bits = [] if item.get("ai") is False else ["the master's ai is not stated false"]
        ai_bits += [f"{it.get('id')} is AI" for it in pitems if it.get("ai") is not False]
        if "AI-GENERATED" in classes(item):
            ai_bits.append("the master marks an AI-GENERATED stretch")
        lint("title-no-ai", not ai_bits, unit=sid, grammar="A40, 2.6, A31",
             evidence={"problems": ai_bits, "why": "the series titles hold no AI pixel"})
        # Format: size, frame rate and duration match the delivery, the ledger and the shot
        path = item.get("_path")
        fmt_ok, ev = False, {"file": path}
        if path and Path(path).exists():
            try:
                pr = R.probe_video(Path(path))
                frames = R.count_frames(Path(path))
                n = int(item.get("frames") or 0)
                ev.update(width=pr["width"], height=pr["height"], fps=round(pr["fps"], 4), r_frame_rate=pr["r_frame_rate"],
                          frames=frames, duration_s=round(pr["duration_s"], 4), shot_s=round(s["_dur"], 4), size=list(SIZE),
                          declared={k: item.get(k) for k in ("width", "height", "fps", "frames")})
                r = rate_of(item)                # the played master's own rate (A44: 24 or 30000/1001)
                same = r is not None and abs(r - fps) < 1e-6
                fmt_ok = (r is not None and (pr["width"], pr["height"]) == SIZE and abs(pr["fps"] - r) < 1e-3
                          and (item.get("width"), item.get("height")) == SIZE
                          and n > 0 and frames == n and abs(pr["duration_s"] - n / r) <= 0.5 / r
                          and abs(s["_dur"] - n / r) <= 0.5 / r
                          and abs((s["f1"] - s["f0"]) - n * fps / r) <= (1e-6 if same else 1))
                out[sid] = {"probe": pr, "fps": r,
                            "rate": CAD.rate_str(CAD.parse_rate(item.get("fps", FPS))) if r else None}
                if fmt_ok and not same:
                    # A44 (and A40: the title is played as rendered): no master at the film's rate, so it is conformed
                    pat = CAD.pattern(r, fps, s["f1"] - s["f0"], n)         # never past the master's last frame
                    out[sid]["conform"] = {"shot": sid, "asset": s.get("asset"), "method": "repeat" if fps > r else "drop",
                                           "in_fps": round(r, 3),
                                           "out_rate": CAD.rate_str(CAD.Fraction(fps).limit_denominator(100000)), **pat}
                    journal.decision("conform", f"{sid}: the series titles ({out[sid]['rate']} fps) conformed to the film's "
                                     f"{out[sid]['conform']['out_rate']} by frame {out[sid]['conform']['method']}",
                                     "A40 and A44: the title master is played as rendered, its frames conformed to the "
                                     "film's master rate with no speed change", unit=sid, evidence=out[sid]["conform"])
            except Exception as e:
                ev["error"] = f"{type(e).__name__}: {e}"
        lint("title-format", fmt_ok, unit=sid, grammar="A40, 7.5",
             evidence=dict(ev, fix=None if fmt_ok else "the master is 1920x1080 at the rate its "
                                                       "ledger states (24 or 30000/1001), its frame count the ledger's, and "
                                                       "the shot's dur_s is frames / that rate (A44)"))
        # The record beat: the film's own record, from this film's ledgers, its pixels the film's scan
        rid = item.get("record")
        rec = assets.get(rid) if rid else None
        rec_ok = rec is not None and rec.get("_ledger") != item.get("_ledger")
        tl = timeline(item)
        rframes = [int(x) for x in (item.get("record_frames") or [])]
        rcls = expected_class(item, rframes[0])[0] if rframes else None
        want_cls = ("DRAWN" if R.is_synthetic(rec) else "ARCHIVE") if rec else None
        rec_year = R.year_of(rec) if rec else None
        lab = next((m for m in tl if m["cls"] == rcls), None)
        prov_rec = ((prov or {}).get("records") or {}).get(item.get("record_key") or rid)
        sha_ok = (not (prov_rec and prov_rec.get("sha256") and rec and rec.get("sha256"))) or prov_rec["sha256"] == rec["sha256"]
        year_ok = rcls != "ARCHIVE" or (lab is not None and lab["year"] == rec_year)
        r_ok = rec_ok and bool(rframes) and rcls == want_cls and prov_rec is not None and sha_ok and year_ok
        lint("title-record", r_ok, unit=sid, grammar="A40, A0, 11.1",
             evidence={"record": rid, "in_film_ledger": (rec or {}).get("_ledger"), "record_frames": rframes,
                       "burned_class": rcls, "film_class": want_cls, "label_year": lab["year"] if lab else None,
                       "film_year": rec_year, "in_provenance": prov_rec is not None, "sha256_match": sha_ok,
                       "fix": None if r_ok else "the master's record is an item of this film's own ledgers (not the masters'), "
                                                "in the title's provenance records with the same file, marked as the film marks it"})
        out.setdefault(sid, {}).update(item=item, burned=item.get("burned") is True, record_path=(rec or {}).get("_path"))
        if not (fmt_ok and path):
            continue
        ff = R.ffmpeg()
        n = int(item.get("frames") or 0)
        # The record's pixels: frames of the record beat are the film's scan, held whole (marks masked)
        if rec_ok and rec.get("_path") and rframes:
            # A7 under A41: a master whose record beat tours the scan declares the tour's resting pose; the frames from
            # where it rests to the record beat's end are its window of the scan filling the frame, and nothing else
            pose = item.get("record_pose")
            window, k_from, why, scan_size = None, rframes[0], None, None
            if pose is not None:
                min_hold = int(round(POSE_HOLD_S * _r(item)))
                try:
                    if not isinstance(pose, dict):
                        raise TypeError("record_pose is an object {window, from_frame}")
                    with Image.open(rec["_path"]) as im:
                        scan_size = im.size
                    window = pose.get("window")
                    why = pose_problem(window, scan_size, *SIZE)
                    ff_ = pose.get("from_frame", rframes[0])
                    if isinstance(ff_, bool) or not isinstance(ff_, (int, float)) or float(ff_) != int(ff_):
                        raise ValueError(f"record_pose.from_frame {ff_!r} is not a whole frame number")
                    k_from = int(ff_)
                    if not rframes[0] <= k_from <= rframes[-1]:
                        why = why or f"record_pose.from_frame {k_from} is outside the record beat {rframes[0]}..{rframes[-1]}"
                    elif rframes[-1] - k_from + 1 < min_hold:
                        why = why or (f"record_pose rests {rframes[-1] - k_from + 1} frames: the pose holds at least "
                                      f"{POSE_HOLD_S:g} s ({min_hold} frames) before the record beat ends")
                except (TypeError, ValueError, AttributeError, OSError) as e:
                    why = f"record_pose: {e}"
                lint("title-record-pose", why is None, unit=sid, grammar="A40, A7, A41",
                     evidence={"record": rid, "window": window, "from_frame": k_from, "record_frames": rframes,
                               "scan_size": scan_size, "min_hold_s": POSE_HOLD_S, "problem": why, "fix": None if why is None else
                               "declare the tour's resting pose as a 16:9 window inside the scan, and the frame it rests from"})
            diffs: dict = {}
            edges: dict = {}
            if why is None:
                try:
                    for k in sorted({k_from, rframes[-1], (k_from + rframes[-1]) // 2}):
                        arr = read_frame(ff, path, k, fps=_r(item))
                        diffs[k] = round(record_difference(arr, rec["_path"], window), 3)
                        if window is not None:
                            edges[k] = round(pose_edge_difference(arr, rec["_path"], window), 2)
                except Exception as e:
                    diffs = {"error": f"{type(e).__name__}: {e}"}
            px_ok = (bool(diffs) and "error" not in diffs and max(diffs.values()) <= RECORD_LIMIT
                     and (not edges or max(edges.values()) <= POSE_EDGE_LIMIT))
            lint("title-record-pixels", px_ok, unit=sid, grammar="A40, A7" + (", A41" if window is not None else ""),
                 evidence={"record": rid, "file": rec["_path"], "difference": diffs, "limit": RECORD_LIMIT,
                           **({"edge_difference": edges, "edge_limit": POSE_EDGE_LIMIT, "edge_px": POSE_EDGE_PX} if edges else {}),
                           "measure": ("low-pass mean difference against the scan's declared window filling the frame "
                                       "(the tour's resting pose), marks masked") if window is not None else
                                      "low-pass mean difference against the scan held whole, marks masked"})
        # The marks: burned in and right, or absent and drawn by the engine (never both)
        sample = set()
        for k, m in enumerate(tl):
            a = m["frame"]
            b = tl[k + 1]["frame"] if k + 1 < len(tl) else n
            for f in (a + fade_frames(item) + 1, (a + b) // 2, b - 2):
                if a <= f < b and f < n:
                    sample.add(f)
        holds = dip_hold_frames(item)
        if holds:
            sample -= set(range(min(holds) - fade_frames(item) - 2, max(holds) + fade_frames(item) + 3))
        try:
            frames_ = {k: read_frame(ff, path, k, fps=_r(item)) for k in sorted(sample | set(holds))}
        except Exception as e:
            lint("title-marks", False, unit=sid, grammar="A40, 4, A16, A31", evidence={"error": f"{type(e).__name__}: {e}"})
            continue
        burned = item.get("burned") is True
        got = {k: (check_frame(frames_[k], item, k) if burned else (any_glyph(frames_[k]) or "none")) for k in sorted(sample)}
        if burned:
            bad = {k: v for k, v in got.items() if v != "burned"}
            lint("title-marks", bool(tl) and not bad, unit=sid, grammar="A40, 4, A16, A31",
                 evidence={"burned": True, "timeline": tl, "sampled": got, "bad": bad,
                           "fix": None if tl and not bad else "the master's burned glyph does not match its declared marks"})
            journal.lint("title-burned-review", True, stage="scout", unit=sid, severity="review", grammar="A40, BRAND-KIT 3, 12",
                         phase="preflight",
                         evidence={"check": "The master carries its own glyph, labels, watermark and lockup; the engine draws "
                                            "none of them over it. Confirm they read on the proof."})
        else:
            twice = {k: v for k, v in got.items() if v != "none"}
            lint("title-marks", bool(tl) and not twice, unit=sid, grammar="A40, 4, A16, A31",
                 evidence={"burned": False, "timeline": tl, "already_marked": twice,
                           "fix": None if tl and not twice else ("state the master's marks" if not tl else
                                                                 "the master already shows a glyph: state burned: true")})
        if burned:
            dip = {k: check_frame(frames_[k], item, k) for k in holds}
            bad_dip = {k: v for k, v in dip.items() if v != "dip"}
            # the mark alone on the black hold is a warning; a picture there is no dip at all, and is refused
            lint("title-dip-hold", not bad_dip, unit=sid, grammar="A40, 7.3, A11",
                 severity="block" if "fail" in dip.values() else "warn",
                 evidence={"hold_frames": holds, "found": dip,
                           "fix": None if not bad_dip else "the master's own dip should hold every pixel off on its black "
                                                           "frames (founder ruling 2026-10-10): re-assemble it without the glyph there"})
            if bad_dip:
                journal.lint("title-dip-hold-review", True, stage="scout", unit=sid, severity="review", grammar="A40, A11",
                             phase="preflight", evidence={"check": f"The master's dip shows the glyph on its black hold "
                                                                   f"(frames {sorted(bad_dip)}); the house dip is all black."})
        lf = item.get("lockup_frame")
        if lf is None:
            cards = [m for m in tl if m["cls"] == "CARD"]
            lf = (cards[-1]["frame"] + n) // 2 if cards else None
        try:
            lp = lockup_pixels(read_frame(ff, path, int(lf), fps=_r(item))) if lf is not None else 0
        except Exception:
            lp = 0
        lint("title-lockup", lp >= LOCKUP_MIN_PX, unit=sid, grammar="A40, BRAND-KIT 2",
             evidence={"frame": lf, "bright_px": lp, "min_px": LOCKUP_MIN_PX, "lockup": SERIES,
                       "fix": None if lp >= LOCKUP_MIN_PX else "the master ends on the series lockup; the engine never draws it"})
    return out
