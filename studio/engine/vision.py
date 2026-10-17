"""A45: automatic subject finding (founder ruling 2, 2026-10-17), the I/O side.

    python -m studio.engine.vision <film dir> [--write] [--json <report>]

measure -> cache -> rulebook -> overlay:

- **Measure.** MediaPipe on CPU (``mediapipe`` Tasks API: ObjectDetector for
  people, FaceDetector, PoseLandmarker for facing), the models pinned by
  sha256 in ``studio/vision-models.json`` and kept outside git; plus a
  pure-numpy spectral-residual saliency (``saliency_box``). The local
  Qwen2.5-VL is not used: measured on 10 Real World stills at temperature 0
  with a fixed seed it was cheap (about 3 GPU seconds a still) but not
  byte-identical across two runs (5 of 10 answers moved a box by a pixel or
  changed a region), so A45 runs MediaPipe and saliency only.
- **Cache.** Every measurement goes into the ledger's sidecar
  (``<ledger stem>.vision.json`` next to it: film data, never in git) keyed
  by (image sha256, model key). The rulebook's fields are recorded beside it
  per item with (image sha256, model key, ``RULEBOOK_VERSION``) for review.
  The file is written with sorted keys, so a rerun is byte-identical, and a
  render never re-infers: the planner re-applies the pure, cheap rulebook to
  the cached measurement, so an edit to the item's own words is never stale.
- **Rulebook.** ``studio.engine.rulebook`` (pure) turns measurements and the
  item's own words into the auto fields. No model writes framing.
- **Overlay.** The human ledger is never rewritten. The planner merges the
  rulebook's fields into each still's item (``rulebook.overlay``): a field
  the human wrote wins, and the human's own people words keep their count.

At plan time (``plan_overlay``) a missing sidecar entry is measured on the CPU
when MediaPipe and its pinned models are present, else the still goes without
auto fields (the A41 default and guards apply); either way it is journaled
and nothing is refused. ``DOCUMENT_VISION=off`` skips measuring at plan time
(the test suite sets it); cached entries are still used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from studio.engine import rulebook as RB

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "studio" / "vision-models.json"
SIDECAR_VERSION = 1
PERSON_SCORE_MIN = 0.25          # detections under this are not recorded at all
TILE = 640                       # object detector tiles (source px), so 8 px rooftop figures are seen at all
TILE_OVERLAP = 0.25
NMS_IOU = 0.5
NEST_SHARE = 0.5               # a box half inside a stronger one is the same figure
EDGE_PX = 2
ROUND = 4                        # every measured number is rounded: float noise never reaches the cache


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_dir(man: dict | None = None) -> Path:
    man = man or manifest()
    return Path(os.environ.get("DOCUMENT_VISION_MODELS") or man["model_dir"])


def cpu_model_key(man: dict | None = None) -> str:
    """The pinned CPU stack as one string: package and each model's hash."""
    mp_ = (man or manifest())["mediapipe"]
    return "mp:" + mp_["package"].split("==")[-1] + ":" + ":".join(
        mp_[k]["sha256"][:12] for k in ("object", "face", "pose")) + "+sr1"


def r(v: float) -> float:
    return round(float(v), ROUND)


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------


def load_rgb(path) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return im.convert("RGB")


# --------------------------------------------------------------------------
# Saliency (pure numpy, spectral residual: Hou and Zhang 2007)
# --------------------------------------------------------------------------


def _box_blur(a: np.ndarray, k: int) -> np.ndarray:
    pad = k // 2
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def saliency_map(img: Image.Image, width: int = 128) -> np.ndarray:
    """The spectral-residual saliency of a picture, ``width`` wide, 0 to 1."""
    h = max(8, round(img.height * width / img.width))
    g = np.asarray(img.convert("L").resize((width, h), Image.Resampling.BOX), dtype=np.float64) / 255.0
    f = np.fft.fft2(g)
    amp = np.log(np.abs(f) + 1e-9)
    ph = np.angle(f)
    res = amp - _box_blur(amp, 3)
    s = np.abs(np.fft.ifft2(np.exp(res + 1j * ph))) ** 2
    for _ in range(3):
        s = _box_blur(s, 5)
    s -= s.min()
    return s / s.max() if s.max() > 0 else s


def saliency_box(img: Image.Image) -> dict:
    """The most salient region as a box in picture fractions, with how
    concentrated the saliency is in it (``concentration``: share of the
    saliency mass inside minus the share of the area, 0 to 1). A picture whose
    saliency is spread evenly scores near 0, so the rulebook holds it whole."""
    s = saliency_map(img)
    h, w = s.shape
    thr = s.mean() * 3.0
    mask = s >= thr
    if not mask.any():
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "concentration": 0.0}
    ys, xs = np.nonzero(mask)
    # the box around the mass-weighted core: the 10th to 90th percentile of the salient pixels on each axis
    wts = s[ys, xs]
    def q(v, p):
        o = np.argsort(v, kind="stable")
        cw = np.cumsum(wts[o]) / wts.sum()
        return float(v[o][min(len(v) - 1, int(np.searchsorted(cw, p)))])
    x0, x1 = q(xs, 0.1), q(xs, 0.9) + 1
    y0, y1 = q(ys, 0.1), q(ys, 0.9) + 1
    inside = s[int(y0):int(y1), int(x0):int(x1)].sum() / s.sum()
    area = (x1 - x0) * (y1 - y0) / (w * h)
    return {"x": r(x0 / w), "y": r(y0 / h), "w": r((x1 - x0) / w), "h": r((y1 - y0) / h),
            "concentration": r(max(0.0, min(1.0, inside - area)))}


# --------------------------------------------------------------------------
# MediaPipe (CPU)
# --------------------------------------------------------------------------


class MissingModel(RuntimeError):
    pass


def _checked(man: dict, key: str) -> str:
    m = man["mediapipe"][key]
    p = model_dir(man) / m["file"]
    if not p.exists():
        raise MissingModel(f"{m['file']} is not in {p.parent} (fetch {m['url']})")
    got = sha256_file(p)
    if got != m["sha256"]:
        raise MissingModel(f"{m['file']} sha256 {got[:12]} is not the pinned {m['sha256'][:12]}")
    return str(p)


class CPU:
    """The pinned MediaPipe detectors, made once per run."""

    def __init__(self, man: dict | None = None):
        man = man or manifest()
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python import vision as V
        except Exception as e:                       # noqa: BLE001 - any import failure is "not installed here"
            raise MissingModel(f"mediapipe is not importable here ({e.__class__.__name__}: {e})") from e
        want = man["mediapipe"]["package"].split("==")[-1]
        if mp.__version__ != want:
            raise MissingModel(f"mediapipe {mp.__version__} is not the pinned {want}")
        self.mp = mp
        cpu = BaseOptions.Delegate.CPU
        self.obj = V.ObjectDetector.create_from_options(V.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=_checked(man, "object"), delegate=cpu),
            score_threshold=PERSON_SCORE_MIN, max_results=50, category_allowlist=["person"]))
        self.face = V.FaceDetector.create_from_options(V.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=_checked(man, "face"), delegate=cpu),
            min_detection_confidence=0.5))
        self.pose = V.PoseLandmarker.create_from_options(V.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_checked(man, "pose"), delegate=cpu), num_poses=1,
            min_pose_detection_confidence=0.5))
        self.key = cpu_model_key(man)

    def _mp(self, arr: np.ndarray):
        return self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(arr))

    def people(self, arr: np.ndarray) -> list[dict]:
        """Person boxes in source pixels: the whole picture, then overlapping
        tiles at native resolution (small figures), merged by NMS."""
        H, W = arr.shape[:2]
        dets = []
        tiles = [(0, 0, W, H)]
        step = int(TILE * (1 - TILE_OVERLAP))
        if max(W, H) > TILE * 1.25:
            for y in range(0, max(1, H - TILE) + step, step):
                for x in range(0, max(1, W - TILE) + step, step):
                    x0, y0 = min(x, max(0, W - TILE)), min(y, max(0, H - TILE))
                    t = (x0, y0, min(W, x0 + TILE), min(H, y0 + TILE))
                    if t not in tiles:
                        tiles.append(t)
        for k, (x0, y0, x1, y1) in enumerate(tiles):
            res = self.obj.detect(self._mp(arr[y0:y1, x0:x1]))
            for d in res.detections:
                b = d.bounding_box
                sc = max(c.score for c in d.categories if c.category_name == "person")
                bx, by, bw, bh = x0 + b.origin_x, y0 + b.origin_y, b.width, b.height
                # a tile's figure that touches the tile's inner edge is a part of someone: the whole picture or
                # the neighbouring tile sees all of them
                if k and ((x0 > 0 and bx <= x0 + EDGE_PX) or (y0 > 0 and by <= y0 + EDGE_PX)
                          or (x1 < W and bx + bw >= x1 - EDGE_PX) or (y1 < H and by + bh >= y1 - EDGE_PX)):
                    continue
                dets.append((float(sc), bx, by, bw, bh))
        return nms(dets)

    def faces(self, arr: np.ndarray) -> list[dict]:
        res = self.face.detect(self._mp(arr))
        out = []
        for d in res.detections:
            b = d.bounding_box
            kp = [(k.x, k.y) for k in (d.keypoints or [])]
            out.append({"score": r(d.categories[0].score), "px": [b.origin_x, b.origin_y, b.width, b.height],
                        "kp": [[r(x), r(y)] for x, y in kp]})
        return sorted(out, key=lambda f: (-f["score"], f["px"]))

    def facing(self, arr: np.ndarray, px) -> dict | None:
        """Pose on one person's crop: the landmarks the rulebook reads for facing."""
        H, W = arr.shape[:2]
        x, y, w, h = px
        mx, my = w * 0.15, h * 0.1
        x0, y0 = max(0, int(x - mx)), max(0, int(y - my))
        x1, y1 = min(W, int(x + w + mx)), min(H, int(y + h + my))
        if x1 - x0 < 24 or y1 - y0 < 48:
            return None
        res = self.pose.detect(self._mp(arr[y0:y1, x0:x1]))
        if not res.pose_landmarks:
            return None
        lm = res.pose_landmarks[0]
        pick = {"nose": 0, "l_ear": 7, "r_ear": 8, "l_sh": 11, "r_sh": 12}
        return {k: [r(lm[i].x), r(lm[i].z), r(getattr(lm[i], "visibility", 0.0) or 0.0)] for k, i in pick.items()}

    def measure(self, img: Image.Image) -> dict:
        arr = np.asarray(img)
        H, W = arr.shape[:2]
        people = self.people(arr)
        for p in people:
            p["pose"] = self.facing(arr, p["px"]) if p["score"] >= 0.4 else None
        faces = self.faces(arr)
        sal = saliency_box(img)
        to_f = lambda px: {"x": r(px[0] / W), "y": r(px[1] / H), "w": r(px[2] / W), "h": r(px[3] / H)}
        return {"size": [W, H], "model": self.key,
                "people": [dict(to_f(p["px"]), score=p["score"], pose=p["pose"]) for p in people],
                "faces": [dict(to_f(f["px"]), score=f["score"], kp=f["kp"]) for f in faces],
                "saliency": sal}


def nms(dets: list[tuple]) -> list[dict]:
    """Non-maximum suppression, deterministic: by score, then position."""
    dets = sorted(dets, key=lambda d: (-round(d[0], 6), d[1], d[2], d[3], d[4]))
    kept: list[tuple] = []
    for d in dets:
        if all(iou(d[1:], k[1:]) < NMS_IOU and not inside(d[1:], k[1:], NEST_SHARE)
               and not inside(k[1:], d[1:], NEST_SHARE) for k in kept):
            kept.append(d)
    return [{"score": r(s), "px": [int(x), int(y), int(w), int(h)]} for s, x, y, w, h in kept]


def iou(a, b) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax1, bx1) - max(a[0], b[0])), max(0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0.0


def inside(a, b, share: float = 0.8) -> bool:
    """Most of box a lies inside box b (a tile's half-figure inside the whole one)."""
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax1, bx1) - max(a[0], b[0])), max(0, min(ay1, by1) - max(a[1], b[1]))
    return a[2] * a[3] > 0 and iw * ih / (a[2] * a[3]) >= share


# --------------------------------------------------------------------------
# Sidecar cache
# --------------------------------------------------------------------------


def sidecar_path(ledger_file) -> Path:
    p = Path(ledger_file)
    return p.with_name(p.stem + ".vision.json")


def read_sidecar(path: Path) -> dict:
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("version") == SIDECAR_VERSION and isinstance(d.get("measure"), dict):
                d.setdefault("items", {})
                return d
        except ValueError:
            pass
    return {"version": SIDECAR_VERSION, "measure": {}, "items": {}}


def dump_sidecar(d: dict) -> str:
    """Sorted keys and fixed separators: the same cache is the same bytes."""
    d = dict(d, _note=("A45 vision cache: measurements keyed by '<image sha256>|<model key>', and the rulebook's "
                       "fields per item for review. Film data, never in git. Regenerate with "
                       "python -m studio.engine.vision <film dir> --write."))
    return json.dumps(d, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_sidecar(path: Path, d: dict) -> bool:
    """Write the cache when its bytes change. Returns whether it wrote."""
    text = dump_sidecar(d)
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)
    return True


def still_items(play: dict, assets: dict) -> list[dict]:
    """The ledger items the screenplay shows as archive stills, once each, in
    screenplay order."""
    seen, out = set(), []
    for part in play.get("parts", []):
        for s in part.get("shots", []):
            if s.get("kind") == "archive_still" and s.get("asset") in assets and s["asset"] not in seen:
                it = assets[s["asset"]]
                if it.get("_path") and Path(it["_path"]).exists():
                    seen.add(s["asset"])
                    out.append(it)
    return out


def human_item(item: dict) -> dict:
    return {k: v for k, v in item.items() if not str(k).startswith("_")}


class Measurer:
    """Measures on demand, through the sidecar cache. The CPU stack is made on
    the first miss; when MediaPipe or a pinned model is missing it is never
    made and ``why`` says so (the still then goes without boxes, held whole)."""

    def __init__(self, allow: bool = True):
        self.man = manifest()
        self.key = cpu_model_key(self.man)
        self.allow = allow
        self.cpu: CPU | None = None
        self.why: str | None = None if allow else "measuring is off here (DOCUMENT_VISION=off)"
        self.measured: list[str] = []

    def get(self, cache: dict, sha: str, path) -> dict | None:
        k = f"{sha}|{self.key}"
        if k in cache["measure"]:
            return cache["measure"][k]
        if self.why:
            return None
        if self.cpu is None:
            try:
                self.cpu = CPU(self.man)
            except MissingModel as e:
                self.why = str(e)
                return None
        m = self.cpu.measure(load_rgb(path))
        cache["measure"][k] = m
        self.measured.append(sha)
        return m


def apply(items: list[dict], meas: Measurer, caches: dict) -> list[dict]:
    """Measure (through the cache) and run the rulebook on each item. Returns
    one record per item: {id, sha256, measured, fields, why, merged, used}."""
    out = []
    for it in items:
        sc = caches.setdefault(it["_ledger_file"], read_sidecar(sidecar_path(it["_ledger_file"])))
        sha = sha256_file(it["_path"])
        m = meas.get(sc, sha, it["_path"])
        res = RB.fields(human_item(it), m, meas.key)
        merged, used = RB.overlay(it, res["fields"])
        sc["items"][it["id"]] = {"sha256": sha, "model": meas.key if m is not None else None,
                                 "rulebook": RB.RULEBOOK_VERSION, "fields": res["fields"], "why": res["why"]}
        out.append({"id": it["id"], "sha256": sha, "measured": m is not None, "fields": res["fields"],
                    "why": res["why"], "merged": merged, "used": used})
    return out


def summary(rec: dict) -> dict:
    """One still's verdict, for the journal and the report."""
    mg = rec["merged"]
    roi = [r for r in mg.get("roi") or [] if isinstance(r, dict)] if isinstance(mg.get("roi"), list) else []
    sub = next((r for r in roi if r.get("name") == "subject"), None)
    pe = mg.get("people")
    plist = pe if isinstance(pe, list) else []
    located_n = sum(1 for p in plist if isinstance(p, dict) and "x" in p)
    unloc = sum(1 for p in plist if not (isinstance(p, dict) and "x" in p))
    sub_out = None
    if sub is not None:
        sub_out = {k: sub[k] for k in ("kind", "x", "y", "w", "h", "confidence", "facing", "source") if k in sub}
    return {"id": rec["id"], "class": mg.get("class"), "people_located": located_n,
            "people_unlocated": unloc if isinstance(pe, list) else None, "people_ledger": None if isinstance(pe, list)
            else pe, "subject": sub_out, "whole": mg.get("whole") is True, "compose": mg.get("compose"),
            "caption_names": mg.get("caption_names"), "from_rulebook": rec["used"], "measured": rec["measured"]}


# --------------------------------------------------------------------------
# Plan time
# --------------------------------------------------------------------------


def measuring_allowed() -> bool:
    return os.environ.get("DOCUMENT_VISION", "").strip().lower() not in ("off", "0", "no", "false")


def plan_overlay(stills: list[dict], journal=None) -> dict:
    """At plan time: every archive still's item gets the rulebook's fields
    under the human's (``rulebook.overlay``). A miss in the cache is measured
    on the CPU and cached, unless measuring is off (``DOCUMENT_VISION=off``)
    or MediaPipe or a pinned model is missing here: then the still goes
    without boxes and is held whole, journaled, never refused (founder
    ruling 2: degrade, never block). Returns {stills, measured, degraded}."""
    meas = Measurer(measuring_allowed())
    caches: dict = {}
    by_item: dict = {}
    for s in stills:
        it = s.get("_item") or {}
        if s.get("kind") != "archive_still" or not it.get("_path") or not it.get("_ledger_file") or not it.get("id"):
            continue
        by_item.setdefault(it["id"], []).append(s)
    if not by_item:
        return {"stills": [], "measured": 0, "degraded": None}
    recs = apply([shots[0]["_item"] for shots in by_item.values()], meas, caches)
    for rec in recs:
        for s in by_item[rec["id"]]:
            priv = {k: v for k, v in s["_item"].items() if str(k).startswith("_")}
            s["_item"] = dict(rec["merged"], **priv)
            s["_vision"] = summary(rec)
    wrote = []
    if meas.measured:
        for lf, sc in caches.items():
            if write_sidecar(sidecar_path(lf), sc):
                wrote.append(str(sidecar_path(lf)))
    unmeasured = [r["id"] for r in recs if not r["measured"]]
    if journal is not None:
        journal.decision("motion", f"A45: {len(recs)} still(s) through rulebook {RB.RULEBOOK_VERSION}"
                         + (f", {len(meas.measured)} measured now" if meas.measured else ""),
                         "founder ruling 2: automatic, deterministic subject finding; the human ledger's fields win",
                         evidence={"model": meas.key, "rulebook": RB.RULEBOOK_VERSION, "cache_written": wrote,
                                   "stills": [summary(r) for r in recs]})
        if unmeasured:
            journal.decision("motion", f"A45: {len(unmeasured)} still(s) not measured: held whole",
                             "founder ruling 2: degrade, never block; the A41 default and guards apply",
                             evidence={"why": meas.why, "stills": unmeasured,
                                       "fix": "python -m studio.engine.vision <film dir> --write where MediaPipe and "
                                              "the pinned models are present"})
    return {"stills": [summary(r) for r in recs], "measured": len(meas.measured),
            "degraded": {"why": meas.why, "stills": unmeasured} if unmeasured else None}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def run(film: Path, write: bool) -> dict:
    from studio.engine import render as R
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    items = still_items(play, R.load_ledgers(film, play))
    meas = Measurer(True)
    caches: dict = {}
    recs = apply(items, meas, caches)
    wrote = []
    if write:
        for lf, sc in caches.items():
            if write_sidecar(sidecar_path(lf), sc):
                wrote.append(str(sidecar_path(lf)))
    return {"film": str(film), "model": meas.key, "rulebook": RB.RULEBOOK_VERSION, "measured_now": len(meas.measured),
            "degraded": meas.why, "written": wrote, "stills": [summary(r) for r in recs],
            "sidecars": {str(sidecar_path(lf)): hashlib.sha256(dump_sidecar(sc).encode()).hexdigest()
                         for lf, sc in caches.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.vision",
                                 description="A45: measure, cache and run the rulebook on a film's archive stills.")
    ap.add_argument("film", type=Path)
    ap.add_argument("--write", action="store_true", help="write the sidecar cache next to each stills ledger")
    ap.add_argument("--json", type=Path, help="write the report here as JSON")
    a = ap.parse_args(argv)
    rep = run(a.film.resolve(), a.write)
    for s in rep["stills"]:
        sub = s["subject"]
        what = "whole" if s["whole"] else (f"subject {sub['kind']}" if sub else "-")
        print(f"{s['id']:<38} {str(s['class']):<9} people {s['people_located']}+{s['people_unlocated']}u "
              f"{what:<16} names {s['caption_names']}")
    print(f"model {rep['model']}, rulebook {rep['rulebook']}, measured now {rep['measured_now']}"
          + (f", degraded: {rep['degraded']}" if rep["degraded"] else "")
          + (f", wrote {', '.join(rep['written'])}" if rep["written"] else ", nothing written"))
    for k, v in rep["sidecars"].items():
        print(f"sidecar {k} sha256 {v}")
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
