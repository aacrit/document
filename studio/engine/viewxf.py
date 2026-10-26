"""A7 like for like (GRAMMAR A40, 2026-10-26): a title's record scan seen through the camera's declared view transform.

A title master rendered in Blender is the record printed on a page, lit, exposed and passed through a view transform
(The Run: Cycles through AgX). AgX's tone curve lifts black ink to grey once white paper sits at the scan's white, so
a perfect page through AgX reads 7.9 against its own scan (A7's limit is 6.0) while the same frames through sRGB
Standard read 2.9 to 3.9. A title item that declares its ``view_transform`` has A7 pass the SCAN through the same
transform first, deterministically (no ML), and then compare: the record is still the film's own scan, held whole.

    "view_transform": {"name": "AgX", "look": "None", "exposure": 2.97,
                       "basis": "the stops from the scan's linear values to the master's scene-linear at the pose"}

or just ``"view_transform": "AgX"`` (look None, exposure 0). The chain, as Blender forms the master's pixels: the scan
(sRGB, 8 bit) decoded to linear Rec.709 by the sRGB curve (as Blender reads an sRGB texture), resampled in linear to
the frame (held whole on black, or the A41 window filling it), scaled by 2 ** exposure (Blender's view exposure, in
stops, together with the light on the page), then the view transform to the sRGB display, rounded to 8 bit.

Two backends, pinned:
- ``ocio``: exact. Blender 4.4.3's own OpenColorIO config (``config.ocio`` and ``AgX_Base_sRGB.cube`` at the sha256s
  pinned below) through PyOpenColorIO, run in Blender's bundled Python (PyOpenColorIO 2.4.1); used when that install
  is found (``DOCUMENT_BLENDER_DIR``, else the house path) and its files match the pins.
- ``published``: everywhere else (CI). AgX as published by Troy Sobotka, in the default-contrast curve fitted by
  Benjamin Wrensch ("Minimal AgX Implementation", 2023: the inset matrix, log2 from -12.47393 to +4.026069 stops, the
  6th-order sigmoid, the outset matrix), and Standard as the sRGB curve. Close to Blender's AgX on a neutral page, not
  identical; the lint's evidence names the backend it used.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

NAMES = ("AgX", "Standard")
EXPOSURE_MAX = 16.0                 # stops either way: a declaration past this is a typo, not a camera

BLENDER_DIR = "D:/document-media/tools/blender-4.4.3-windows-x64"
BLENDER_VERSION = "4.4"
PINS = {                            # Blender 4.4.3's colour management, as The Run was rendered through it
    "config.ocio": "5915e3a94f199d819dc15c8c7a6ffc501094f1cc81117387221bdb1889a704b2",
    "luts/AgX_Base_sRGB.cube": "02f4d185608daa67fda01a1a48529bbc1533c8afdc826cde5c78f2eb5bb1b839",
}

# The published AgX (Sobotka; Wrensch's fit). Rows act on linear Rec.709 column vectors.
AGX_INSET = np.array([[0.842479062253094, 0.0784335999999992, 0.0792237451477643],
                      [0.0423282422610123, 0.878468636469772, 0.0791661274605434],
                      [0.0423756549057051, 0.0784336, 0.879142973793104]])
AGX_OUTSET = np.array([[1.19687900512017, -0.0980208811401368, -0.0990297440797205],
                       [-0.0528968517574562, 1.15190312990417, -0.0989611768448433],
                       [-0.0529716355144438, -0.0980434501171241, 1.15107367264116]])
AGX_MIN_EV, AGX_MAX_EV = -12.47393, 4.026069


def parse(decl) -> tuple[dict | None, str | None]:
    """(the spec {name, look, exposure}, None), (None, None) when nothing is declared, or (None, the problem)."""
    if decl is None:
        return None, None
    if isinstance(decl, str):
        decl = {"name": decl}
    if not isinstance(decl, dict):
        return None, "view_transform is a name (\"AgX\") or an object {name, look, exposure}"
    name = decl.get("name")
    if name not in NAMES:
        return None, f"view_transform.name {name!r} is not one of {', '.join(NAMES)}"
    look = decl.get("look", "None")
    if not isinstance(look, str) or not look.strip():
        return None, "view_transform.look is a look's name, or \"None\""
    ev = decl.get("exposure", 0.0)
    if isinstance(ev, bool) or not isinstance(ev, (int, float)) or not math.isfinite(float(ev)) \
            or abs(float(ev)) > EXPOSURE_MAX:
        return None, f"view_transform.exposure {ev!r} is not a number of stops within {EXPOSURE_MAX:g} either way"
    return {"name": name, "look": look.strip(), "exposure": float(ev)}, None


# --------------------------------------------------------------------------
# The pure parts
# --------------------------------------------------------------------------


def srgb_to_linear(v: np.ndarray) -> np.ndarray:
    """The sRGB curve (IEC 61966-2-1), as Blender decodes an sRGB texture: code values 0..1 to linear."""
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v: np.ndarray) -> np.ndarray:
    v = np.clip(np.asarray(v, dtype=np.float64), 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055)


def agx_published(lin: np.ndarray) -> np.ndarray:
    """Linear Rec.709 (H, W, 3) to sRGB display code values 0..1 through the published AgX (default contrast)."""
    x = np.asarray(lin, dtype=np.float64) @ AGX_INSET.T
    x = np.log2(np.maximum(x, 1e-10))
    x = (np.clip(x, AGX_MIN_EV, AGX_MAX_EV) - AGX_MIN_EV) / (AGX_MAX_EV - AGX_MIN_EV)
    x2 = x * x
    x4 = x2 * x2
    y = 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232
    return np.clip(y @ AGX_OUTSET.T, 0.0, 1.0)


def published(lin: np.ndarray, spec: dict) -> np.ndarray:
    if spec["look"] != "None":
        raise ValueError(f"view_transform.look {spec['look']!r} needs Blender's own config (the ocio backend); "
                         "the published curve has no looks")
    return agx_published(lin) if spec["name"] == "AgX" else linear_to_srgb(lin)


def to_linear_frame(img: Image.Image, window, W: int, H: int) -> np.ndarray:
    """The scan as linear Rec.709 at the frame's size: its ``window`` filling the frame (A41), or held whole on black
    (7.2 HOLD), resampled in linear as the renderer's camera samples the page."""
    lin = srgb_to_linear(np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0).astype(np.float32)
    if window is not None:
        x0, y0, x1, y1 = (float(v) for v in window)
        box, size, at = (x0 * img.width, y0 * img.height, x1 * img.width, y1 * img.height), (W, H), (0, 0)
    else:
        k = min(W / img.width, H / img.height)
        box, size = None, (round(img.width * k), round(img.height * k))
        at = ((W - size[0]) // 2, (H - size[1]) // 2)
    out = np.zeros((H, W, 3), np.float32)
    for c in range(3):
        ch = Image.fromarray(np.ascontiguousarray(lin[:, :, c])).resize(size, Image.LANCZOS, box=box)   # mode F
        out[at[1]:at[1] + size[1], at[0]:at[0] + size[0], c] = np.asarray(ch)
    return np.maximum(out, 0.0)


def display(lin: np.ndarray, spec: dict, backend: str | None = None) -> tuple[np.ndarray, str]:
    """(8-bit sRGB display frame, the backend used) of a linear frame through the declared exposure and transform."""
    x = np.asarray(lin, dtype=np.float32) * np.float32(2.0 ** spec["exposure"])
    backend = backend or ("ocio" if blender_ocio() else "published")
    y = ocio_apply(x, spec) if backend == "ocio" else published(x, spec)
    return np.clip(np.round(y * 255.0), 0, 255).astype(np.uint8), backend


# --------------------------------------------------------------------------
# The exact backend: Blender's own config through its bundled PyOpenColorIO
# --------------------------------------------------------------------------


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


@functools.lru_cache(maxsize=4)
def _pinned(root: str) -> dict | None:
    base = Path(root) / BLENDER_VERSION
    py = base / "python" / "bin" / ("python.exe" if os.name == "nt" else "python3.11")
    cm = base / "datafiles" / "colormanagement"
    if not py.exists() or not all((cm / k).exists() for k in PINS):
        return None
    if any(_sha(cm / k) != v for k, v in PINS.items()):
        return None
    return {"python": str(py), "config": str(cm / "config.ocio")}


def blender_ocio() -> dict | None:
    """Blender 4.4.3's Python and its pinned colour config, or None (then the published curve)."""
    return _pinned(os.environ.get("DOCUMENT_BLENDER_DIR") or BLENDER_DIR)


_OCIO_SCRIPT = r"""
import sys, numpy as np, PyOpenColorIO as OCIO
src, dst, cfg_path, view, look = sys.argv[1:6]
cfg = OCIO.Config.CreateFromFile(cfg_path)
dvt = OCIO.DisplayViewTransform(src="Linear Rec.709", display="sRGB", view=view)
pipe = OCIO.LegacyViewingPipeline()
pipe.setDisplayViewTransform(dvt)
if look != "None":
    pipe.setLooksOverrideEnabled(True)
    pipe.setLooksOverride(look)
cpu = pipe.getProcessor(cfg).getDefaultCPUProcessor()
a = np.ascontiguousarray(np.load(src).astype(np.float32))
cpu.applyRGB(a)
np.save(dst, a)
"""


def ocio_apply(lin: np.ndarray, spec: dict) -> np.ndarray:
    b = blender_ocio()
    if b is None:
        raise RuntimeError("Blender 4.4.3's pinned colour config is not available")
    with tempfile.TemporaryDirectory() as d:
        src, dst, script = Path(d) / "in.npy", Path(d) / "out.npy", Path(d) / "vx.py"
        np.save(src, np.ascontiguousarray(lin, dtype=np.float32))
        script.write_text(_OCIO_SCRIPT, encoding="utf-8")
        p = subprocess.run([b["python"], "-I", str(script), str(src), str(dst), b["config"], spec["name"], spec["look"]],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise RuntimeError(f"OpenColorIO failed: {p.stderr.strip()[-400:]}")
        return np.load(dst).astype(np.float64)


@functools.lru_cache(maxsize=8)
def _reference(path: str, mtime: float, window, W: int, H: int, spec_json: str, backend: str | None):
    spec = json.loads(spec_json)
    with Image.open(path) as im:
        lin = to_linear_frame(im, window, W, H)
    return display(lin, spec, backend)


def reference(record_path: str, window, W: int, H: int, spec: dict, backend: str | None = None):
    """(the scan as the declared camera shows it, at the frame's size, as uint8 RGB; the backend used)."""
    win = tuple(float(v) for v in window) if window is not None else None
    backend = backend or ("ocio" if blender_ocio() else "published")
    arr, used = _reference(str(record_path), os.path.getmtime(record_path), win, W, H,
                           json.dumps(spec, sort_keys=True), backend)
    return arr, used
