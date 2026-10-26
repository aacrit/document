"""A7 like for like (GRAMMAR A40, 2026-10-26): a title's record scan seen through the master's own view transform.

A title master rendered in Blender is the record printed on a page, lit, exposed and passed through a view transform
(The Run: Cycles through AgX). AgX's tone curve lifts black ink to grey once white paper sits at the scan's white, so
a perfect page through AgX reads 7.9 against its own scan (A7's limit is 6.0) while the same frames through sRGB
Standard read 2.9 to 3.9. A title item that declares its ``view_transform`` has A7 pass the SCAN through the same
transform first, deterministically (no ML), and then compare: the record is still the film's own scan, held whole.

The ledger item names the render's view sidecar, and the sidecar names the master:

    "view_transform": {"name": "AgX", "look": "None", "sidecar": "the-run-v5c-S-130-2997-sound.view.json"}

The sidecar (``SIDECAR_SCHEMA``) is written by the render chain after the render, beside the master, and bound to it
by the master's sha256 (The Run: design/title-sequence/blender/run/view_settings_v5c.py, called from tail_v5c.py):

    {"schema": "document.view/1", "renderer": "Blender 4.4.3",
     "master": "<the master's file name>", "master_sha256": "<sha256 of that file>",
     "view_transform": "AgX", "look": "None",
     "display_device": "sRGB", "gamma": 1.0, "use_curve_mapping": false,    # as recorded, or else listed in:
     "defaults_assumed": ["display_device", "gamma", "use_curve_mapping"], "defaults_basis": "<why each is the default>",
     "exposure": [<the view exposure at master frame 0>, <frame 1>, ...]   # or one number for every frame
    }

What it holds is what is true of the render: ``exposure`` is the view exposure as keyed in the render's input (its
--expo file, per frame), read back from Blender on the frames where the render recorded it, in stops, and nothing
else (no light on the page, no fit); ``view_transform`` and ``look`` are what the scene script sets (scene_v5c.py
settings()), read back where recorded; display, gamma and curve mapping are the recorded values, or Blender's defaults
only where the sidecar lists them in ``defaults_assumed`` with a ``defaults_basis`` (both echoed into the lint's
evidence); a key neither recorded nor listed is refused. The ledger may restate ``exposure``; it must then equal the
sidecar's on every frame A7 samples. A sidecar for another master or file, or whose transform or look differ from the
declaration, is refused. The sha256 binding guards against mistakes (a sidecar from another render, a re-encoded
master), not forgery: anyone who can write the master can write its sidecar. The guard against gaming the exposure
is the structure floor: the transformed scan must keep its structure (half the plain scan's low-pass spread inside
the record, and ``STRUCTURE_MIN`` levels), so no exposure can wash the record out to pass.

The chain, as Blender forms the master's pixels: the scan (sRGB, 8 bit) decoded to linear Rec.709 by the sRGB curve
(as Blender reads an sRGB texture), resampled in linear to the frame (held whole on black, or the A41 window filling
it), scaled by 2 ** exposure, then the view transform to the sRGB display, rounded to 8 bit.

Two backends, pinned:
- ``ocio``: exact. Blender 4.4.3's own OpenColorIO config (``config.ocio`` and ``AgX_Base_sRGB.cube`` at the sha256s
  pinned below) through PyOpenColorIO, run in Blender's bundled Python (PyOpenColorIO 2.4.1); used when that install
  is found (``DOCUMENT_BLENDER_DIR``, else the house path) and its files match the pins. ``python -m
  studio.engine.viewxf --self-check`` checks it against pinned values.
- ``published``: AgX as published by Troy Sobotka, in the default-contrast curve fitted by Benjamin Wrensch ("Minimal
  AgX Implementation", 2023), and Standard as the sRGB curve. Not Blender's curve (up to about 14 levels apart in
  the shadows), so the lint fails closed on it: a declared view passes A7 only on the exact backend, except under the
  test-only switch ``DOCUMENT_A7_PUBLISHED_OK=1`` that the test fixtures set.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

NAMES = ("AgX", "Standard")
EXPOSURE_MAX = 6.0                  # stops either way: past this the camera is not exposing a page
SIDECAR_SCHEMA = "document.view/1"
TEST_SWITCH = "DOCUMENT_A7_PUBLISHED_OK"     # test-only: lets the published curve stand in for the exact backend
STRUCTURE_FLOOR = 0.5               # the transformed scan keeps at least half the plain scan's low-pass p95-p5 spread
STRUCTURE_MIN = 16.0                # ... and at least this many 8-bit levels of it, whatever the plain scan's (The Run's
                                    # three records keep 32 (C20-METAR-0851), 56 (S-16928) and 99 (S-130): 2x and more)
DISPLAY_DEFAULTS = {"display_device": "sRGB", "gamma": 1.0, "use_curve_mapping": False}   # what this check reproduces

BLENDER_DIR = "D:/document-media/tools/blender-4.4.3-windows-x64"
BLENDER_VERSION = "4.4"
PINS = {                            # Blender 4.4.3's colour management, as The Run was rendered through it
    "config.ocio": "5915e3a94f199d819dc15c8c7a6ffc501094f1cc81117387221bdb1889a704b2",
    "luts/AgX_Base_sRGB.cube": "02f4d185608daa67fda01a1a48529bbc1533c8afdc826cde5c78f2eb5bb1b839",
}
# The exact backend on a neutral ramp of linear values (Blender 4.4.3, sRGB display, look None, exposure 0), 8 bit
SELF_CHECK_RAMP = [0.0, 0.0005, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.18, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
SELF_CHECK_WANT = {"AgX": [0, 0, 3, 9, 18, 32, 58, 87, 118, 170, 197, 217, 233, 245, 255, 255],
                   "Standard": [0, 2, 7, 16, 25, 39, 63, 89, 118, 188, 255, 255, 255, 255, 255, 255]}

# The published AgX (Sobotka; Wrensch's fit). Rows act on linear Rec.709 column vectors.
AGX_INSET = np.array([[0.842479062253094, 0.0784335999999992, 0.0792237451477643],
                      [0.0423282422610123, 0.878468636469772, 0.0791661274605434],
                      [0.0423756549057051, 0.0784336, 0.879142973793104]])
AGX_OUTSET = np.array([[1.19687900512017, -0.0980208811401368, -0.0990297440797205],
                       [-0.0528968517574562, 1.15190312990417, -0.0989611768448433],
                       [-0.0529716355144438, -0.0980434501171241, 1.15107367264116]])
AGX_MIN_EV, AGX_MAX_EV = -12.47393, 4.026069


def _ev_ok(ev) -> bool:
    return not isinstance(ev, bool) and isinstance(ev, (int, float)) and math.isfinite(float(ev)) \
        and abs(float(ev)) <= EXPOSURE_MAX


def parse(decl) -> tuple[dict | None, str | None]:
    """(the declaration {name, look, sidecar, exposure or None}, None), (None, None) when nothing is declared, or
    (None, the problem)."""
    if decl is None:
        return None, None
    if not isinstance(decl, dict):
        return None, "view_transform is an object {name, look, sidecar}: the render's sidecar binds it to the master"
    name = decl.get("name")
    if name not in NAMES:
        return None, f"view_transform.name {name!r} is not one of {', '.join(NAMES)}"
    look = decl.get("look", "None")
    if not isinstance(look, str) or not look.strip():
        return None, "view_transform.look is a look's name, or \"None\""
    sc = decl.get("sidecar")
    if not isinstance(sc, str) or not sc.strip():
        return None, "view_transform.sidecar names the render's view sidecar (schema document.view/1) beside the master"
    ev = decl.get("exposure")
    if ev is not None and not _ev_ok(ev):
        return None, f"view_transform.exposure {ev!r} is not a number of stops within {EXPOSURE_MAX:g} either way"
    return {"name": name, "look": look.strip(), "sidecar": sc.strip(), "exposure": None if ev is None else float(ev)}, None


@functools.lru_cache(maxsize=16)
def _file_sha(path: str, size: int, mtime: float) -> str:
    return _sha(Path(path))


def sidecar(decl: dict, master_path: str, n_frames: int) -> tuple[dict | None, str | None]:
    """(the render's sidecar, None) when it binds ``decl`` to the master at ``master_path``, else (None, why)."""
    mp = Path(master_path)
    p = Path(decl["sidecar"])
    p = p if p.is_absolute() else mp.parent / p
    try:
        sc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"view sidecar {p} unreadable: {type(e).__name__}: {e}"
    if not isinstance(sc, dict) or sc.get("schema") != SIDECAR_SCHEMA:
        return None, f"view sidecar {p} is not schema {SIDECAR_SCHEMA}"
    if sc.get("master") != mp.name:
        return None, f"view sidecar names master {sc.get('master')!r}, not the played {mp.name!r}"
    st = mp.stat()
    if sc.get("master_sha256") != _file_sha(str(mp), st.st_size, st.st_mtime):
        return None, "view sidecar's master_sha256 is not the played master's: the declaration is not this render's"
    for k, want in (("view_transform", decl["name"]), ("look", decl["look"])):
        if sc.get(k) != want:
            return None, f"the render's {k} is {sc.get(k)!r}, the ledger declares {want!r}"
    assumed = sc.get("defaults_assumed") or []
    basis = sc.get("defaults_basis")
    if not isinstance(assumed, list) or any(k not in DISPLAY_DEFAULTS for k in assumed) \
            or (assumed and not (isinstance(basis, str) and basis.strip())):
        return None, ("view sidecar's defaults_assumed lists only display_device, gamma or use_curve_mapping, with a "
                      "defaults_basis saying why each is the default")
    missing = [k for k in DISPLAY_DEFAULTS if k not in sc and k not in assumed]
    if missing:
        return None, f"the render did not record its display, gamma or curve mapping ({', '.join(missing)})"
    got = {k: sc.get(k, DISPLAY_DEFAULTS[k]) if k in assumed else sc[k] for k in DISPLAY_DEFAULTS}
    if got != DISPLAY_DEFAULTS:
        return None, f"the render's display, gamma or curve mapping {got} is not one this check reproduces {DISPLAY_DEFAULTS}"
    ev = sc.get("exposure")
    evs = ev if isinstance(ev, list) else None
    if evs is not None and len(evs) < n_frames:
        return None, f"view sidecar's exposure has {len(evs)} frames; the master has {n_frames}"
    if not all(_ev_ok(x) for x in (evs if evs is not None else [ev])):
        return None, f"view sidecar's exposure is not stops within {EXPOSURE_MAX:g} either way on every frame"
    return {**sc, "_path": str(p)}, None


def exposure_at(sc: dict, k: int) -> float:
    ev = sc["exposure"]
    return float(ev[k] if isinstance(ev, list) else ev)


def exact_required() -> bool:
    """True unless the test-only switch is set inside a pytest run (PYTEST_CURRENT_TEST): never in a real plan."""
    return not (os.environ.get(TEST_SWITCH) == "1" and os.environ.get("PYTEST_CURRENT_TEST"))


def spread(arr: np.ndarray, box=None) -> float:
    """The low-pass (96 x 54, as A7) p95 - p5 of the mean channel, inside ``box`` (x0, y0, x1, y1 in fractions)."""
    lp = np.asarray(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize((96, 54), Image.BOX),
                    dtype=np.float32).mean(axis=2)
    if box is not None:
        x0, y0, x1, y1 = box
        lp = lp[int(round(y0 * 54)):max(int(round(y1 * 54)), int(round(y0 * 54)) + 1),
                int(round(x0 * 96)):max(int(round(x1 * 96)), int(round(x0 * 96)) + 1)]
    p5, p95 = np.percentile(lp, [5, 95])
    return float(p95 - p5)


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


def self_check() -> int:
    """The exact backend reproduces Blender 4.4.3's AgX and Standard on the pinned ramp (a local check, not a test)."""
    b = blender_ocio()
    if b is None:
        print("viewxf self-check: Blender 4.4.3's pinned colour config was not found; the exact backend is unavailable")
        return 2
    lin = np.repeat(np.array(SELF_CHECK_RAMP, np.float32)[None, :, None], 3, axis=2)
    bad = 0
    for name, want in SELF_CHECK_WANT.items():
        got = display(lin, {"name": name, "look": "None", "exposure": 0.0}, "ocio")[0][0, :, 0].tolist()
        ok = got == want
        bad += not ok
        print(f"viewxf self-check {name}: {'ok' if ok else 'MISMATCH'} {got}" + ("" if ok else f" want {want}"))
    print(f"viewxf self-check: {b['config']}")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-check"]:
        raise SystemExit(self_check())
    raise SystemExit("usage: python -m studio.engine.viewxf --self-check")
