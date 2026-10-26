"""The Run v5c final: mastered at 29.97 (founder ruling 2026-10-25), the final_hq profile, no denoiser anywhere in the
scene or the job, and the shot's camera opens wide, never cuts, and ends on the record's pose."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import channel_v5c as C  # noqa: E402

TITLE = json.loads((RUN.parent / "title.json").read_text(encoding="utf-8"))
BAKE = Path("D:/document-media/title-sequence/run/sim/v5c/run-bake.json")


def test_titles_master_at_2997_and_final_hq_is_declared():
    assert TITLE["master_fps"] == "30000/1001"
    p = TITLE["render"]["final_hq"]
    assert p["res"] == [2560, 1440] and p["samples"] <= 1024 and p["noise_threshold"] >= 0.01
    assert p["use_denoising"] is False and p["fps"] == "30000/1001"
    src = (RUN / "render_whole.py").read_text(encoding="utf-8")
    assert '"--fps"' in src and '"--profile"' in src and 'default="final_hq"' in src


def test_the_v5c_scene_and_job_never_denoise():
    s = (RUN / "scene_v5c.py").read_text(encoding="utf-8")
    assert "cy.use_denoising = False" in s and "cy.use_preview_denoising = False" in s
    j = (RUN / "final_v5c.py").read_text(encoding="utf-8")
    assert 'prof.get("use_denoising", False) is False' in j and '"denoise": False' in j


def test_the_shot_is_one_continuous_move_ending_on_the_record():
    if not BAKE.exists():
        return
    import shot_v5c as SH
    bake = json.loads(BAKE.read_text(encoding="utf-8"))
    rest = json.loads((BAKE.parent / "run-timing.json").read_text(encoding="utf-8"))["rest_sim_s"]
    fr = SH.shot(bake, 30000 / 1001, rest)
    E = np.array([f["eye"] for f in fr])
    step = np.linalg.norm(np.diff(E, axis=0), axis=1)
    assert step.max() < 0.08                              # no cut: the eye never jumps between frames
    assert C.RUNTIME["min"] <= len(fr) / (30000 / 1001) <= C.RUNTIME["max"]
    eye, tgt = SH.record_pose()
    assert np.allclose(fr[-1]["eye"], eye) and fr[-1]["end"] == 1.0
    held = [f for f in fr if f["end"] >= 0.999]
    assert len(held) / (30000 / 1001) >= 0.5
    assert abs(fr[0]["eye"][2] - C.OPEN["height"]) < 1e-9
