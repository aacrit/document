"""No denoiser of any kind in any render of The Run (founder, 2026-10-18: no AI pixels). Every render path and profile
in design/title-sequence/blender/run/ is read: nothing may set a Cycles denoiser on, the scene settings must set it off,
and every master item the assembly writes declares `denoise: false` and its `renderer` (WG-2's lint)."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
LOG = Path("D:/document-media/title-sequence/run/render-log.jsonl")
KEYS = {"use_denoising", "use_preview_denoising", "use_viewport_denoising"}


def _assignments():
    for p in sorted(RUN.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    for el in (t.elts if isinstance(t, ast.Tuple) else [t]):
                        if isinstance(el, ast.Attribute) and el.attr in KEYS:
                            yield p.name, el.attr, node.value


def test_nothing_turns_a_denoiser_on():
    for name, key, value in _assignments():
        assert not (isinstance(value, ast.Constant) and value.value is True), f"{name} sets {key} = True"


def test_the_render_settings_turn_both_denoisers_off():
    src = (RUN / "run_scene.py").read_text(encoding="utf-8")
    body = src[src.index("def render_settings"):]
    body = body[:body.index("\ndef ", 1)]
    assert "cy.use_denoising = False" in body and "cy.use_preview_denoising = False" in body
    for p in RUN.glob("*.py"):
        s = p.read_text(encoding="utf-8")
        assert not re.search(r"denoiser\s*=\s*['\"](OPENIMAGEDENOISE|OPTIX)", s), p.name


def test_every_master_item_declares_no_denoise_and_its_renderer():
    src = (RUN / "assemble_take.py").read_text(encoding="utf-8")
    assert src.count('"denoise": False') >= 2 and src.count('"renderer"') >= 2
    take = (RUN / "run_take.py").read_text(encoding="utf-8")
    assert '"denoise": bool(sc.cycles.use_denoising)' in take and "no denoiser (founder ruling)" in take


def test_builds_since_the_ruling_were_not_denoised():
    if not LOG.exists():
        return
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        e = json.loads(ln)
        info = e.get("info") or {}
        if e.get("event") == "built" and "denoise" in info:
            assert info["denoise"] is False, e
