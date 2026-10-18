"""Cinematography ticket #3: grid-overlay contact sheets, a PIL preview tool
with no render and no ffmpeg encode. Hermetic: a small synthetic film with
one located person (human source) and one still declared ``whole``, built
from the shared fixture (``conftest.make_film``) in a private temp copy so
nothing here touches the shared ``film`` session fixture or writes into the
film folder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from conftest import make_film
from studio.engine import levels as LV
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import sheets as SH


def _film_with_subjects(tmp_path: Path) -> Path:
    film = make_film(tmp_path / "film")
    ledger_path = film / "stills-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for item in ledger["items"]:
        if item["id"] == "FX-STILL-A":          # S3, preset PUSH: a located, human-sourced person
            item["people"] = [{"x": 0.30, "y": 0.10, "w": 0.25, "h": 0.55, "name": "Test Subject",
                               "facing": "camera", "source": "human"}]
        elif item["id"] == "FX-STILL-C":         # S5, HOLD under a fill exception: nothing to single out
            item["whole"] = True
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    return film


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_sheets_exist_for_every_still(tmp_path):
    film = _film_with_subjects(tmp_path)
    r = SH.build_sheets(film, out_dir=tmp_path / "out")
    assert r["sheets"], "no sheet was written"
    paths = [Path(m["path"]) for m in r["sheets"]]
    assert all(p.is_file() and p.stat().st_size > 0 for p in paths)
    index = json.loads(r["index"].read_text(encoding="utf-8"))
    assert index["sheets"] == r["sheets"]
    assert index["plan_sha"] == r["plan_sha"]
    # every still shot in the fixture (S3, S4, S5) is on some sheet
    shot_ids = {sid for m in r["sheets"] for sid in m["shots"]}
    assert {"S3", "S4", "S5"} <= shot_ids


def test_no_writes_into_the_film_folder(tmp_path):
    film = _film_with_subjects(tmp_path)
    before = _snapshot(film)
    SH.build_sheets(film, out_dir=tmp_path / "out")
    after = _snapshot(film)
    assert before == after


def test_skip_sound_lints_drops_music_cues_in_memory_only(tmp_path):
    film = _film_with_subjects(tmp_path)
    raw_before = (film / "screenplay.json").read_bytes()
    r = SH.build_sheets(film, out_dir=tmp_path / "out", skip_sound_lints=True)
    assert r["sheets"]
    assert (film / "screenplay.json").read_bytes() == raw_before   # never written


def test_cell_geometry_matches_the_camera_window(tmp_path):
    """A cell is exactly the camera's window at that stop's time: the same
    ``fit_still`` pixels as the public camera resolver (``overlays.framing_at``)
    gives the renderer, at the cell's own resolution."""
    film = _film_with_subjects(tmp_path)
    import studio.engine.journal as J
    from studio.engine import render as R
    j = J.Journal(film="cine3-geom", directory=tmp_path / "journal")
    plan = SH.plan_stills(film, j)
    s = next(x for x in plan["shots"] if x["id"] == "S3")
    cam = s["_cam"]
    dur = float(s["_dur"])
    still = SH._StillImage(s)
    L = M.Layout(320, 180)
    for t in SH.stop_times(cam, dur):
        pic, src, dst, f = SH.camera_crop(still, cam, t, dur, L)
        want_f = OV.framing_at(cam, t, dur)
        want_pic = M.fit_still(still.img, L, z=want_f["z"], cx=want_f["x"], cy=want_f["y"], clamp=cam["clamp"])
        assert f == want_f
        assert pic.convert("RGB").tobytes() == want_pic.convert("RGB").tobytes()
        # src/dst are the same window still_view gives directly, against the original (un-prescaled) size
        want_src, want_dst = M.still_view(still.size, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        assert src == want_src and dst == want_dst
        # the rendered cell is the crop over a caption strip: its top rows are this exact picture
        cell = SH.render_cell(still, s, t, dur, L.W, L.H)
        assert cell.size == (L.W, L.H + SH.LABEL_H)


def test_overlays_use_the_house_zones_from_motion_py():
    assert SH.ZONES["MARK"] == tuple(M.MARK_ZONE)
    assert SH.ZONES["GLYPH"] == tuple(M.MARK_GLYPH_ZONE)
    lt, sub, wm = SH.ZONES["LT"], SH.ZONES["SUB"], SH.ZONES["WM"]
    # LT starts at motion.LT's own x and ends at its own bottom (fractions of the frame)
    assert abs(lt[0] - M.LT["x"] / 100.0) < 1e-9
    assert abs(lt[3] - M.LT["bottom"] / 100.0) < 1e-9
    assert abs(sub[3] - M.SUB["bottom"] / 100.0) < 1e-9
    assert abs((wm[2] - wm[0]) * (16 / 9) - (wm[3] - wm[1])) < 1e-6   # the watermark box is square (16:9 frame)
    for frac in (lt, sub, wm, SH.ZONES["MARK"], SH.ZONES["GLYPH"]):
        assert 0.0 <= frac[0] < frac[2] <= 1.0 and 0.0 <= frac[1] < frac[3] <= 1.0


def test_deterministic_same_plan_same_bytes(tmp_path):
    film = _film_with_subjects(tmp_path)
    r1 = SH.build_sheets(film, out_dir=tmp_path / "out1")
    r2 = SH.build_sheets(film, out_dir=tmp_path / "out2")
    assert len(r1["sheets"]) == len(r2["sheets"]) and r1["sheets"]
    for m1, m2 in zip(sorted(r1["sheets"], key=lambda m: (m["chapter"], m["page"])),
                      sorted(r2["sheets"], key=lambda m: (m["chapter"], m["page"]))):
        b1, b2 = Path(m1["path"]).read_bytes(), Path(m2["path"]).read_bytes()
        assert b1 == b2, m1["path"]


def test_scale_class_thresholds():
    assert SH.scale_class(0.9) == "whole"
    assert SH.scale_class(0.8) == "whole"
    assert SH.scale_class(0.6) == "field"
    assert SH.scale_class(0.4) == "detail"
    assert SH.scale_class(0.1) == "detail"


def test_compose_verdict_bands():
    assert SH.compose_verdict(None) == "n/a"
    assert SH.compose_verdict((0.30, 0.30, 0.44, 0.44)) == "golden"     # centre near 0.37, 0.37
    assert SH.compose_verdict((0.45, 0.45, 0.55, 0.55)) == "centred"
    assert SH.compose_verdict((0.0, 0.0, 0.05, 0.05)) == "off"


def test_whole_still_has_no_subject(tmp_path):
    film = _film_with_subjects(tmp_path)
    import studio.engine.journal as J
    j = J.Journal(film="cine3-whole", directory=tmp_path / "journal")
    plan = SH.plan_stills(film, j)
    s5 = next(x for x in plan["shots"] if x["id"] == "S5")
    assert s5["_item"].get("whole") is True
    box, source, name = SH.subject_box(s5["_cam"])
    assert box is None and source is None and name is None


def test_a46_levels_overlay_is_never_written(tmp_path):
    """Merged-tree regression (review of 2e50428, BLOCK 1): since #11,
    build_plan writes ``<ledger>.levels.json`` beside the ledger by default,
    even for a DRAWN (ineligible) still, held and measured there for
    grade-jump. This tool threads ``write_overlays=False`` through so it
    never does, on top of the generic no-write snapshot above."""
    film = _film_with_subjects(tmp_path)
    SH.build_sheets(film, out_dir=tmp_path / "out")
    assert not list(film.glob("*.levels.json"))


def test_still_image_applies_the_a46_black_floor(tmp_path):
    """#11's floor applies to a sheet's cells in the same order as the
    render (``render.Pictures.still``): on the full scan, before the
    pre-scale."""
    img = Image.new("RGB", (40, 40), (60, 60, 60))     # a flat, milky-grey scan: well above the floor's p2 threshold
    path = tmp_path / "milky.png"
    img.save(path)
    m = LV.measure(Image.open(path))
    fp = LV.floor_params(m)
    assert fp is not None, "the fixture scan should be eligible for the floor"
    levels = {"applied": True, **fp}
    s = {"_item": {"_path": str(path)}, "_cam": {"fit_scale": 1.0, "z_max": 1.0}, "_levels": levels}
    still = SH._StillImage(s)
    got = np.asarray(still.img)
    raw = np.asarray(Image.open(path).convert("RGB"))
    assert not np.array_equal(got, raw)
    want = np.asarray(LV.apply(Image.open(path).convert("RGB"), levels))
    assert np.array_equal(got, want)


def test_still_image_with_no_levels_record_is_unchanged(tmp_path):
    img = Image.new("RGB", (10, 10), (128, 64, 32))
    path = tmp_path / "plain.png"
    img.save(path)
    s = {"_item": {"_path": str(path)}, "_cam": {"fit_scale": 1.0, "z_max": 1.0}}
    still = SH._StillImage(s)
    assert np.array_equal(np.asarray(still.img), np.asarray(img.convert("RGB")))
