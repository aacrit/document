"""A40, the series titles (void document · As It Was): a pre-rendered master played as it is, right after the cold
open and before Part 1, its own marks burned in and checked on its pixels, its provenance declared and free of AI,
its format matched, its record beat this film's own record; the main-title theme's slot under it. Small synthetic
masters (4 s of 1080p24 FFV1) stand in for the 57 s ones."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import make_film, tone
from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import score as SC
from studio.engine import titles as TS
from studio.engine import viewxf as VX

N = 96                                  # 4 s
COLD_S = 2.0
TITLE_S = N / TS.FPS
SHIFT = COLD_S + TITLE_S
TL = [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
      {"frame": 36, "cls": "ARCHIVE", "label": "Archive · 1947"},
      {"frame": 60, "cls": "CARD"}]
DIP = {"centre_frame": 60, "s": 0.75}


def _machine(W, H):
    y, x = np.mgrid[0:H, 0:W]
    a = np.stack([40 + 60 * x / W, 30 + 40 * y / H, 20 + 30 * (x + y) / (W + H)], axis=2)
    return Image.fromarray(a.astype(np.uint8))


def _lockup(W, H):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(img).text((W / 2, H / 2), TS.SERIES, font=M._font(M.Fonts().display, 60), fill=M.PALETTE["bone"], anchor="mm")
    return img


def make_master(path, record_png, *, burned=True, glyph_on_hold=True, n=N, pose=None, rec_pic=None):
    """A short master in the real ones' shape: the machine (DRAWN), a cut to the record held whole (ARCHIVE), a dip
    and the lockup (CARD), the marks burned in as assemble.py burns them (or none). ``pose`` (window, from_frame): the
    record beat tours to that window of the scan filling the frame and rests there from from_frame (A7 under A41).
    ``rec_pic``: the record beat's picture as given (a camera's view of the page) instead of the scan held whole."""
    W, H = TS.SIZE
    fonts = M.Fonts()
    machine, lock = _machine(W, H), _lockup(W, H)
    rec = rec_pic if rec_pic is not None else TS.hold_fit(Image.open(record_png), W, H)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    toured = TS.pose_fit(Image.open(record_png), pose[0], W, H) if pose is not None else None
    item = {"marks": TL, "dip": DIP, "frames": n}
    holds = TS.dip_hold_frames(item)
    shots = [{"start": m["frame"] / 24, "cls": m["cls"], "label": m.get("label", "")} for m in TL]
    t0 = DIP["centre_frame"] / 24 - DIP["s"] / 2
    p = subprocess.Popen([R.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "24",
                          "-i", "-", "-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "bgr0", str(path)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / 24
        pic = machine if k < 36 else rec if k < 60 else lock
        if pose is not None and pose[1] <= k < 60:
            pic = toured
        if t0 <= t < t0 + DIP["s"]:
            pic = Image.blend(black, pic, M.dip_level(t - t0, DIP["s"]))
        if burned and (glyph_on_hold or k not in holds):
            pic = M.mark_frame(pic, t, shots, fonts).convert("RGB")
        p.stdin.write(np.asarray(pic.convert("RGB")).tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return path


@pytest.fixture(scope="session")
def masters(tmp_path_factory, film):
    d = tmp_path_factory.mktemp("masters")
    rec = film / "stills" / "FX-STILL-B.png"
    return {"dir": d,
            "burned": make_master(d / "burned.mkv", rec),
            "clean_dip": make_master(d / "clean-dip.mkv", rec, glyph_on_hold=False),
            "bare": make_master(d / "bare.mkv", rec, burned=False)}


def _sha(p):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def titled_film(tmp_path, masters, *, master="burned", item=None, prov_items=None, records=None, shot=None, edit=None):
    """The fixture film with a cold open and the series titles before its title card; everything after them moves
    on by SHIFT. ``item``, ``prov_items``, ``records`` and ``shot`` override the defaults; ``edit(play)`` runs last."""
    film = make_film(tmp_path / "film")
    stills = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    items = stills if isinstance(stills, list) else stills["items"]
    rec_file = film / "stills" / "FX-STILL-B.png"
    items.append({"id": "FX-REC", "file": "FX-STILL-B.png", "title": "A stand-in record of 17 August 1947", "date": "1947-08-17",
                  "archive": "fixture archive", "archive_short": "fixture", "licence": "Public domain", "basis": "test",
                  "credit": "fixture", "sha256": _sha(rec_file), "shows_bodies": False, "graphic_medical": False,
                  "named_patient": False, "shows_violence": False})
    (film / "stills-ledger.json").write_text(json.dumps(stills), encoding="utf-8")
    prov = {"ledger": "title-sequence assets", "rule": "no AI pixels",
            "records": records if records is not None else {"FX-REC": {"sha256": _sha(rec_file), "cls": "ARCHIVE"}},
            "items": prov_items if prov_items is not None else [
                {"id": "T-01", "title": "A clay tablet", "licence": "CC0", "ai": False, "source_page": "https://example.org/t01",
                 "licence_evidence": "read 2026-10-16", "sha256": "0" * 64, "holder": "A museum"},
                {"id": "T-13", "title": "A tabulator", "licence": "CC BY 2.0", "ai": False, "credit": "A photographer",
                 "source_page": "https://example.org/t13", "basis": "CC BY 2.0 on the file page", "sha256": "1" * 64}]}
    (film / "title-assets.json").write_text(json.dumps(prov), encoding="utf-8")
    src = masters[master]
    it = {"id": "TS-test", "file": src.name, "title": f"{TS.SERIES}, series titles (test)", "version": "v1",
          "creator": "void document studio", "archive_short": "void document studio", "source_short": "period records",
          "date": "2026-10-17", "content_date": "1947-08-17", "content_basis": "the latest record shown, FX-REC",
          "generator": "a test master", "licence": "CC BY 2.0", "basis": "the studio's own work from its provenance",
          "credit": "void document studio", "ai": False, "provenance": "title-assets.json", "record": "FX-REC",
          "fps": 24, "width": 1920, "height": 1080, "frames": N, "burned": master != "bare", "marks": TL,
          "record_frames": [40, 50], "dip": DIP, "lockup_frame": 84,
          "shows_bodies": False, "graphic_medical": False, "named_patient": False, "shows_violence": False}
    it.update(item or {})
    (film / "masters-ledger.json").write_text(json.dumps({"items": [it]}), encoding="utf-8")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    play["ledgers"]["titles"] = {"path": "masters-ledger.json", "media": str(masters["dir"])}

    def move(x):
        for k in ("start_s", "end_s"):
            if isinstance(x.get(k), (int, float)):
                x[k] = round(x[k] + SHIFT, 4)

    for part in play["parts"]:
        for coll in ("shots", "lines", "cues", "text"):
            for x in part.get(coll, []):
                move(x)
    for x in play.get("subtitle_source", []) + play.get("music", []) + play.get("moments", []):
        move(x)
    # A55 (voice-over-black): L2 shifted along with S8 (still inside it); move it onto S5 (an archive_still, never
    # black) so a render here doesn't refuse for voice-over-black instead of whatever this helper's own tests check.
    next(ln for part in play["parts"] for ln in part.get("lines", []) if ln["id"] == "L2")["start_s"] = round(12.5 + SHIFT, 4)
    play["runtime_target_s"] = play["runtime_target_s"] + SHIFT
    ts = {"id": "TS1", "kind": "title_sequence", "start_s": COLD_S, "dur_s": TITLE_S, "asset": "TS-test", "mark": "DRAWN",
          "transition_in": {"type": "cut"}, "why": "The series titles, after the hook."}
    ts.update(shot or {})
    play["parts"][:0] = [
        {"id": "cold", "kind": "cold_open", "title": "Cold open", "shots": [
            {"id": "CO1", "kind": "black", "start_s": 0.0, "dur_s": COLD_S, "mark": "CARD", "transition_in": {"type": "cut"},
             "silence": "intended", "why": "The hook, in this test a breath of black."}]},
        {"id": "series", "kind": "series_title", "title": TS.SERIES, "shots": [ts]}]
    if edit:
        edit(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def plan_of(film, W=640, H=360):
    j = J.Journal(film="a40")
    try:
        return R.build_plan(film, W=W, H=H, burn_subtitles=False, journal=j), j
    except R.Refused as e:
        return e, j


def lints(j, rule):
    return [e for e in J.read(j.path) if e.get("kind") == "lint" and e.get("rule") == rule]


def passed(j, rule):
    got = lints(j, rule)
    return bool(got) and all(e.get("status") == "pass" for e in got)


def failed(j, rule):
    return any(e.get("status") == "fail" for e in lints(j, rule))


RULES = ("title-sequence-once", "title-sequence-place", "title-sequence-transitions", "title-sequence-clear",
         "title-audio-slot", "title-provenance", "title-licence", "title-no-ai", "title-format", "title-record",
         "title-record-pixels", "title-marks", "title-lockup")


# --------------------------------------------------------------------------
# The good case
# --------------------------------------------------------------------------


def test_a40_a_burned_master_after_the_cold_open_passes_every_lint(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters))
    assert not isinstance(plan, Exception), plan
    for rule in RULES:
        assert passed(j, rule), (rule, lints(j, rule))
    s = next(x for x in plan["shots"] if x["id"] == "TS1")
    assert s["f1"] - s["f0"] == N and s["_title"]["burned"] is True
    # the master's own dip shows the glyph on its black hold, as the real masters do: a warning and a reviewer item
    assert any(e["status"] == "fail" and e["severity"] == "warn" for e in lints(j, "title-dip-hold"))
    assert lints(j, "title-dip-hold-review")
    # no theme yet: silence is allowed, declared intended, and the reviewer is told
    assert (COLD_S, COLD_S + TITLE_S) in plan["silences"]
    assert lints(j, "title-theme-pending")[0]["evidence"]["stand_in"] == "silence"


def test_a40_a_clean_dip_needs_no_warning(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, master="clean_dip"))
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-dip-hold") and not lints(j, "title-dip-hold-review")


def test_a40_the_titles_hold_no_ai_and_the_plan_draws_no_key(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters))
    assert "key_classes" not in plan                         # A56: the mark key card is retired from films
    assert lints(j, "title-no-ai")[0]["status"] == "pass"


def test_a40_the_plan_marks_hand_the_next_shot_the_class_the_master_ends_on(tmp_path, masters):
    plan, _ = plan_of(titled_film(tmp_path, masters))
    i = [s["id"] for s in plan["shots"]].index("TS1")
    assert plan["marks"][i]["cls"] == "CARD" and plan["marks"][i]["label"] == ""
    # its lockup is a CARD span: the film's watermark is off there
    assert any(abs(a - (COLD_S + 60 / 24)) < 1e-6 and abs(b - SHIFT) < 1e-6 for a, b in plan["card_spans"])


# --------------------------------------------------------------------------
# Each lint, the other way
# --------------------------------------------------------------------------


def test_a40_the_titles_go_right_after_the_cold_open(tmp_path, masters):
    def late(play):                         # the title part moved after the film's title card
        series = play["parts"].pop(1)
        play["parts"].insert(2, series)
        title_part = play["parts"][1]
        for s in title_part["shots"]:
            s["start_s"] = round(s["start_s"] - TITLE_S, 4)
        series["shots"][0]["start_s"] = round(title_part["shots"][-1]["start_s"] + title_part["shots"][-1]["dur_s"], 4)
    plan, j = plan_of(titled_film(tmp_path, masters, edit=late))
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-place")


def test_a40_nothing_dissolves_into_the_titles(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, shot={"transition_in": {"type": "dip", "s": 0.5}}))
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-transitions")


def test_a40_no_voice_or_lower_third_over_the_titles(tmp_path, masters):
    def voice(play):
        play["parts"][1]["lines"] = [{"id": "LX", "kind": "narration", "start_s": COLD_S + 1.0, "text": "Over the titles."}]
        play["parts"][1]["text"] = [{"id": "TX", "kind": "lower_third", "start_s": COLD_S, "end_s": COLD_S + 2,
                                     "lines": ["A place", "1947"]}]
    film = titled_film(tmp_path, masters, edit=voice)
    tone(film / "audio" / "LX.wav", 1.0)
    plan, j = plan_of(film)
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-clear")
    assert {"LX", "TX"} <= set(next(e for e in lints(j, "title-sequence-clear") if e["status"] == "fail")["evidence"]["over"])


def test_a40_the_audio_slot_takes_the_theme_or_the_motif_and_nothing_else(tmp_path, masters):
    def bed(play):
        play["music"] = [{"id": "B1", "kind": "music", "start_s": 0.5, "end_s": COLD_S + 2.0, "wav": "score/b1.wav"}]
    plan, j = plan_of(titled_film(tmp_path / "a", masters, edit=bed))
    assert isinstance(plan, R.Refused) and failed(j, "title-audio-slot")

    def motif(play):
        play["music"] = [{"id": "M1", "kind": "music", "role": "house_motif", "start_s": COLD_S, "end_s": SHIFT, "wav": "m.wav"}]
    plan, j = plan_of(titled_film(tmp_path / "b", masters, edit=motif))
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-audio-slot") and lints(j, "title-theme-pending")[0]["evidence"]["stand_in"] == ["M1"]
    assert (COLD_S, SHIFT) not in plan["silences"]

    def theme(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S, "end_s": SHIFT, "wav": "mt.wav"}]
    plan, j = plan_of(titled_film(tmp_path / "c", masters, edit=theme))
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-theme") and not lints(j, "title-theme-pending")

    def theme_late(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S + 1, "end_s": SHIFT, "wav": "mt.wav"}]
    plan, j = plan_of(titled_film(tmp_path / "d", masters, edit=theme_late))
    assert isinstance(plan, R.Refused) and failed(j, "title-theme")

    def theme_elsewhere(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": SHIFT + 5, "end_s": SHIFT + 8, "wav": "mt.wav"}]
    plan, j = plan_of(titled_film(tmp_path / "e", masters, edit=theme_elsewhere))
    assert isinstance(plan, R.Refused) and failed(j, "title-theme")


def test_a40_the_main_title_role_is_featured_and_recurs_by_design():
    c = {"kind": "music", "role": "main_title"}
    assert SC.cue_role(c) == "main_title" and SC.role_problem(c) is None
    assert "main_title" in SC.FEATURED and "main_title" in SC.BRAND and "main_title" not in SC.UNDERSCORE
    assert SC.role_problem({"kind": "music", "role": "main_title", "score_role": "bed"}) is not None


def test_a40_provenance_must_be_declared_open_and_sourced(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path / "a", masters, item={"provenance": "missing.json"}))
    assert isinstance(plan, R.Refused) and failed(j, "title-provenance")
    bad = [{"id": "T-99", "title": "x", "licence": "CC BY-NC 4.0", "ai": False, "source_page": "https://e.org", "basis": "b",
            "sha256": "2" * 64}]
    plan, j = plan_of(titled_film(tmp_path / "b", masters, prov_items=bad))
    assert isinstance(plan, R.Refused) and failed(j, "title-provenance")
    unsourced = [{"id": "T-98", "title": "x", "licence": "CC0", "ai": False}]
    plan, j = plan_of(titled_film(tmp_path / "c", masters, prov_items=unsourced))
    ev = next(e for e in lints(j, "title-provenance") if e["status"] == "fail")["evidence"]
    assert any("source page" in p for p in ev["problems"]) and any("sha256" in p for p in ev["problems"])


def test_a40_the_masters_licence_is_as_demanding_as_its_inputs(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, item={"licence": "CC0"}))
    assert isinstance(plan, R.Refused) and failed(j, "title-licence")
    assert TS.licence_rank("Public domain") < TS.licence_rank("CC0") < TS.licence_rank("CC BY 2.0") < TS.licence_rank("CC BY-SA 4.0")


def test_a40_no_ai_anywhere_in_the_titles(tmp_path, masters):
    ai = [{"id": "T-50", "title": "a texture", "licence": "CC0", "ai": True, "source_page": "local", "basis": "b",
           "sha256": "3" * 64}]
    plan, j = plan_of(titled_film(tmp_path / "a", masters, prov_items=ai))
    assert isinstance(plan, R.Refused) and failed(j, "title-no-ai")
    plan, j = plan_of(titled_film(tmp_path / "b", masters, item={"ai": None}))
    assert isinstance(plan, R.Refused) and failed(j, "title-no-ai")
    plan, j = plan_of(titled_film(tmp_path / "c", masters, shot={"mark": "AI-GENERATED"}))
    assert isinstance(plan, R.Refused) and failed(j, "mark-class-valid")


@pytest.mark.parametrize("over", [{"frames": N - 1}, {"fps": 25}, {"width": 1280}])
def test_a40_size_rate_and_length_must_match_the_ledger(tmp_path, masters, over):
    plan, j = plan_of(titled_film(tmp_path, masters, item=over))
    assert isinstance(plan, R.Refused) and failed(j, "title-format")


def test_a40_the_shot_runs_the_masters_length(tmp_path, masters):
    def longer(play):
        play["parts"][1]["shots"][0]["dur_s"] = TITLE_S + 1.0
        for part in play["parts"][2:]:
            for s in part["shots"]:
                s["start_s"] = round(s["start_s"] + 1.0, 4)
    plan, j = plan_of(titled_film(tmp_path, masters, edit=longer))
    assert isinstance(plan, R.Refused) and failed(j, "title-format")


def test_a40_the_record_is_this_films_own(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path / "a", masters, item={"record": "S-999"}))
    assert isinstance(plan, R.Refused) and failed(j, "title-record")
    plan, j = plan_of(titled_film(tmp_path / "b", masters, records={}))           # not in the title's own records
    assert isinstance(plan, R.Refused) and failed(j, "title-record")
    plan, j = plan_of(titled_film(tmp_path / "c", masters, records={"FX-REC": {"sha256": "f" * 64}}))   # another file
    assert isinstance(plan, R.Refused) and failed(j, "title-record")
    marks = [dict(m) for m in TL]
    marks[1]["label"] = "Archive · 1946"                                           # the label's year is not the record's
    plan, j = plan_of(titled_film(tmp_path / "d", masters, item={"marks": marks}))
    assert isinstance(plan, R.Refused) and failed(j, "title-record")


def test_a40_the_record_beats_pixels_are_the_films_scan(tmp_path, masters):
    # the record names another still of the film (drawn, as the fixture's stills are): its pixels do not match
    marks = [TL[0], dict(TL[1], cls="DRAWN", label="Drawn · 2026"), TL[2]]
    film = titled_film(tmp_path, masters, item={"record": "FX-STILL-A", "marks": marks}, records={"FX-STILL-A": {}})
    plan, j = plan_of(film)
    assert passed(j, "title-record"), lints(j, "title-record")
    assert isinstance(plan, R.Refused) and failed(j, "title-record-pixels")


def test_a40_burned_marks_must_match_the_declared_timeline(tmp_path, masters):
    wrong = [dict(TL[0], cls="ARCHIVE", label="Archive · 1947"), TL[1], TL[2]]
    plan, j = plan_of(titled_film(tmp_path, masters, item={"marks": wrong}))
    assert isinstance(plan, R.Refused) and failed(j, "title-marks")


def test_a40_a_burned_master_is_never_marked_again(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, item={"burned": False}))
    assert isinstance(plan, R.Refused) and failed(j, "title-marks")
    assert next(e for e in lints(j, "title-marks") if e["status"] == "fail")["evidence"]["already_marked"]


def test_a40_a_master_without_its_lockup_is_refused(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, item={"lockup_frame": 20}))     # a machine frame: no lockup there
    assert isinstance(plan, R.Refused) and failed(j, "title-lockup")


def test_a40_the_master_is_dated_by_its_content_for_a0(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, item={"content_date": "2030"}))
    assert isinstance(plan, R.Refused)
    assert any(e["status"] == "fail" and e.get("unit") == "TS1" for e in lints(j, "as-of"))


# --------------------------------------------------------------------------
# Frames: played as they are; ours only where the master has none
# --------------------------------------------------------------------------


def test_a40_a_burned_master_plays_as_it_is(tmp_path, masters):
    plan, _ = plan_of(titled_film(tmp_path, masters), W=1920, H=1080)
    s = next(x for x in plan["shots"] if x["id"] == "TS1")
    ff = R.ffmpeg()
    pics = R.Pictures(plan)
    try:
        for k in (0, 20, 45, 84):
            got = R.render_frame(plan, s["f0"] + k, pics)
            want = TS.read_frame(ff, str(masters["burned"]), k)
            assert np.array_equal(got, want), k                       # not a pixel drawn over it: no double mark
            assert TS.check_frame(pics.title_native, s["_item"], k) in ("burned", "fade")
    finally:
        pics.close()


def test_a40_a_bare_master_gets_our_marks_from_its_timeline(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters, master="bare"))
    assert not isinstance(plan, Exception), plan
    assert passed(j, "title-marks")
    s = next(x for x in plan["shots"] if x["id"] == "TS1")
    pics = R.Pictures(plan)
    try:
        for k, cls in ((10, "DRAWN"), (45, "ARCHIVE"), (84, "CARD")):
            arr = R.render_frame(plan, s["f0"] + k, pics)
            assert TS.check_frame(arr, s["_item"], k) == "burned" and TS.glyph_shows(arr, cls), k
        hold = TS.dip_hold_frames(s["_item"])[0]
        assert not R.render_frame(plan, s["f0"] + hold, pics).any()   # its own dip's black hold stays black
    finally:
        pics.close()


def test_a40_the_frame_check_tells_a_square_from_a_diamond_and_finds_a_missing_glyph(masters):
    item = {"marks": TL, "dip": DIP, "frames": N}
    a = TS.read_frame(R.ffmpeg(), str(masters["burned"]), 10)
    assert TS.check_frame(a, item, 10) == "burned"
    assert TS.check_frame(a, dict(item, marks=[dict(TL[0], cls="AI-GENERATED")] + TL[1:]), 10) == "fail"
    bare = TS.read_frame(R.ffmpeg(), str(masters["bare"]), 10)
    assert TS.check_frame(bare, item, 10) == "fail" and TS.any_glyph(bare) is None


def test_a40_sources_and_credits_show_the_titles(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters))
    doc = R.sources_doc(plan, j, {})
    s = next(x for x in doc["shots"] if x["id"] == "TS1")
    assert s["kind"] == "title_sequence" and s["title_sequence"]["record"] == "FX-REC"
    assert [p["id"] for p in s["title_sequence"]["provenance"]] == ["T-01", "T-13"]
    a, b = COLD_S, SHIFT
    pieces = [(round(m["from_s"], 3), m["class"]) for m in doc["marks"] if a - 1e-6 <= m["from_s"] < b - 1e-6]
    assert [c for _, c in pieces][:3] == ["DRAWN", "ARCHIVE", "CARD"]
    assert abs(sum(doc["share"].values()) - 1.0) < 1e-3
    series = dict(plan["credits"])["Series titles"]
    assert series[0].startswith(TS.SERIES) and any("CC BY 2.0" in ln and "A tabulator" in ln for ln in series)


def test_a40_a_render_with_the_titles_passes_mark_coverage(tmp_path, masters):
    def longer_credits(play):              # the Series titles block lengthens the roll (credits-roll)
        play["parts"][-1]["shots"][-1]["dur_s"] += 6.0
        play["runtime_target_s"] += 6.0
    film = titled_film(tmp_path, masters, edit=longer_credits)
    out = tmp_path / "out"
    summary = R.render(film, out, height=360, workers=2, min_free_gb=1, encode_preset="veryfast")
    ev = next(e for e in J.read(summary["journal"]) if e.get("kind") == "lint" and e.get("rule") == "mark-coverage")
    assert ev["status"] == "pass", ev["evidence"]
    assert ev["evidence"]["title_burned"] > 0
    doc = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert any(sh["kind"] == "title_sequence" for sh in doc["shots"])


def test_a40_the_titles_record_is_a_showing_for_a35():
    shots = [{"id": "TS1", "kind": "title_sequence", "asset": "TS-test", "_item": {"record": "R"}, "_part": "series"},
             {"id": "A", "kind": "archive_still", "asset": "R", "_part": "p1", "transition_in": {"type": "cut"}},
             {"id": "B", "kind": "archive_still", "asset": "X", "_part": "p2", "transition_in": {"type": "cut"}},
             {"id": "C", "kind": "archive_still", "asset": "R", "_part": "p2", "transition_in": {"type": "dip", "s": 0.5}}]
    aps = {ap["shots"][0]: ap for ap in R.image_appearances(shots)}
    assert aps["TS1"]["n_film"] == 1 and not aps["A"]["needs_reason"]          # the film's own showing is its second
    assert aps["C"]["n_film"] == 3 and aps["C"]["needs_reason"]                # a third needs its repeat_reason
    assert not any(ap["needs_reason"] for ap in R.image_appearances([s for s in shots if s["id"] != "TS1"]))


def test_a40_marks_alone_on_the_dip_hold_warn_and_a_picture_there_does_not_pass():
    item = {"marks": TL, "dip": DIP, "frames": N}
    k = TS.dip_hold_frames(item)[0]
    black = np.zeros((1080, 1920, 3), np.uint8)
    assert TS.check_frame(black, item, k) == "dip"
    wm = np.asarray(M.watermark(Image.fromarray(black), 10.0, start=0.0).convert("RGB"))     # the watermark's last frames
    assert wm.any() and TS.check_frame(wm, item, k) == "dip_glyph"
    pic = black.copy()
    pic[500:520, 900:960] = 200                                                             # picture on the hold
    assert TS.check_frame(pic, item, k) == "fail"


# --------------------------------------------------------------------------
# A7 under A41 (founder, 2026-10-17): the record beat may tour the scan; its resting pose is the scan's declared 16:9
# window filling the frame, and A7 compares those frames with that crop, nothing but the scan in the frame
# --------------------------------------------------------------------------

def _scan(tmp_path, w=1600, h=1200):
    y, x = np.mgrid[0:h, 0:w]
    a = np.stack([(x * 255 // w), (y * 255 // h), ((x // 40 + y // 40) % 2) * 200], axis=2).astype(np.uint8)
    p = tmp_path / "scan.png"
    Image.fromarray(a).save(p)
    return p


def test_a7_under_a41_the_resting_pose_matches_its_window(tmp_path):
    p = _scan(tmp_path)
    W, H = TS.SIZE
    win = (0.1, 0.2, 0.9, 0.2 + 0.8 * 1600 / 1200 * 9 / 16)            # 16:9 in the scan's pixels
    assert TS.pose_problem(win, (1600, 1200), W, H) is None
    with Image.open(p) as im:
        frame = np.asarray(TS.pose_fit(im, win, W, H))
        whole = np.asarray(TS.hold_fit(im, W, H))
    assert TS.record_difference(frame, str(p), win) < 1.0                # the toured pose is the scan's crop
    assert TS.record_difference(whole, str(p), win) > TS.RECORD_LIMIT    # a pillarboxed hold is not that pose
    assert TS.record_difference(whole, str(p)) < 1.0                     # without a pose, A7 as written still holds


def test_a7_under_a41_the_pose_is_the_scan_alone_and_unstretched():
    W, H = TS.SIZE
    assert "leaves the scan" in TS.pose_problem((-0.05, 0.0, 0.9, 0.6), (1600, 1200), W, H)
    assert "aspect" in TS.pose_problem((0.0, 0.0, 1.0, 1.0), (1600, 1200), W, H)
    assert "four numbers" in TS.pose_problem(None, (1600, 1200), W, H)


WIN_B = [0.0, 0.0, 1.0, round(395 / 316 * 9 / 16, 6)]     # a 16:9 window of FX-STILL-B (395 x 316 px)


def _pose_problem(j):
    return lints(j, "title-record-pose")[-1]["evidence"]["problem"]


def test_a7_under_a41_a_declared_pose_is_checked_in_the_plan(tmp_path, masters):
    # the fixture's record is not 16:9, so its whole sheet as a window would be stretched to fill the frame
    plan, j = plan_of(titled_film(tmp_path / "a", masters, item={"record_pose": {"window": [0.0, 0.0, 1.0, 1.0],
                                                                                "from_frame": 40}}))
    assert isinstance(plan, R.Refused) and "aspect" in _pose_problem(j)
    for k, (ff_, says) in enumerate(((5, "outside the record beat"), (51, "outside the record beat"),
                                     (50, "holds at least"), (40.5, "whole frame"), (None, "whole frame"))):
        plan, j = plan_of(titled_film(tmp_path / f"b{k}", masters, item={"record_pose": {"window": WIN_B, "from_frame": ff_}}))
        assert isinstance(plan, R.Refused) and says in _pose_problem(j), (ff_, _pose_problem(j))
    plan, j = plan_of(titled_film(tmp_path / "c", masters, item={"record_pose": [0, 0, 1, 1]}))      # malformed: no crash
    assert isinstance(plan, R.Refused) and "object" in _pose_problem(j)


def test_a7_under_a41_a_toured_master_resting_on_its_window_passes(tmp_path, masters, film):
    rec = film / "stills" / "FX-STILL-B.png"
    toured = dict(masters, toured=make_master(masters["dir"] / "toured.mkv", rec, pose=(WIN_B, 38)))
    # the pose rests from f38 so it holds its 0.5 s (POSE_HOLD_S) before the dip begins (f51)
    plan, j = plan_of(titled_film(tmp_path / "a", toured, master="toured",
                                  item={"record_frames": [38, 50], "record_pose": {"window": WIN_B, "from_frame": 38}}))
    assert passed(j, "title-record-pose"), [x["evidence"] for x in lints(j, "title-record-pose")]
    assert passed(j, "title-record-pixels"), [x["evidence"] for x in lints(j, "title-record-pixels")]
    ev = lints(j, "title-record-pixels")[-1]["evidence"]
    assert "resting pose" in ev["measure"] and max(ev["edge_difference"].values()) <= TS.POSE_EDGE_LIMIT
    # the same master declared as held whole (no pose) fails A7 as written
    plan, j = plan_of(titled_film(tmp_path / "b", toured, master="toured", item={"record_frames": [38, 50]}))
    assert isinstance(plan, R.Refused) and failed(j, "title-record-pixels")


def test_a7_under_a41_an_alternate_rate_master_never_inherits_the_pose():
    item = {"file": "a.mkv", "fps": 24, "record_frames": [40, 50], "record_pose": {"window": WIN_B, "from_frame": 40},
            "masters": {"30000/1001": {"file": "b.mkv", "frames": 120, "record_frames": [50, 62]}}}
    alt, how = TS.select_master(item, 30000 / 1001)
    assert how == "alternate" and "record_pose" not in alt
    item["masters"]["30000/1001"]["record_pose"] = {"window": WIN_B, "from_frame": 50}
    assert TS.select_master(item, 30000 / 1001)[0]["record_pose"]["from_frame"] == 50


def test_a7_under_a41_an_overshoot_onto_black_fails_the_edge_check(tmp_path):
    p = _scan(tmp_path)
    W, H = TS.SIZE
    win = (0.1, 0.2, 0.9, 0.2 + 0.8 * 1600 / 1200 * 9 / 16)
    with Image.open(p) as im:
        frame = np.asarray(TS.pose_fit(im, win, W, H)).copy()
    assert TS.pose_edge_difference(frame, str(p), win) < 1.0
    frame[:, :40] = 0                                                  # 40 px of black at the left: past the scan
    assert TS.pose_edge_difference(frame, str(p), win) > TS.POSE_EDGE_LIMIT


def test_a40_a_shots_span_across_the_titles_is_the_full_render_byte_for_byte(tmp_path, masters):
    """render --shots (#61's review): a span that ends inside the series titles (the cold open's last shot through
    TS1) and one that starts there (TS1 through the first shot after it) render the same segments as the full
    film, byte for byte: the titles' own frames (a master played as it is) and their edges included."""
    def longer_credits(play):              # the Series titles block lengthens the roll (credits-roll)
        play["parts"][-1]["shots"][-1]["dur_s"] += 6.0
        play["runtime_target_s"] += 6.0
    film = titled_film(tmp_path, masters, edit=longer_credits)
    out = tmp_path / "out"
    R.render(film, out, height=360, workers=2, min_free_gb=1, encode_preset="veryfast")
    full = {p.name.split(".")[0]: J.sha256_file(p) for p in (out / "segments").glob("*.mp4")}
    ids = [s["id"] for s in R.build_plan(film, W=640, H=360, burn_subtitles=False,
                                         journal=J.Journal(film="a40-shots", directory=tmp_path / "j"),
                                         write_overlays=False)["shots"]]
    after = ids[ids.index("TS1") + 1]
    for a, b in (("CO1", "TS1"), ("TS1", after)):
        s = R.render(film, out, height=360, workers=2, min_free_gb=1, encode_preset="veryfast", shots=f"{a}..{b}")
        assert s["partial"] is True and s["rendered"] == ids[ids.index(a):ids.index(b) + 1]
        mine = {p.name.split(".")[0]: J.sha256_file(p) for p in (out / f"shots-{a}-{b}" / "segments").glob("*.mp4")}
        assert set(mine) == set(s["rendered"]), (a, b, sorted(mine))
        assert all(mine[k] == full[k] for k in mine), (a, b)


# --------------------------------------------------------------------------
# A40 like for like (coordinator, founder-delegated, 2026-10-26): a master rendered through a view transform (The Run:
# Cycles through AgX) declares it, and A7 passes the SCAN through that same transform before comparing. AgX lifts
# black ink to grey once white paper sits at the scan's white, so a perfect page through AgX fails A7 as written.
# The tests force the published curve (no Blender here, as on CI): the ocio backend is the exact one where Blender
# 4.4.3's pinned config is found.
# --------------------------------------------------------------------------


@pytest.fixture
def no_blender(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_BLENDER_DIR", str(tmp_path / "no-blender"))
    assert VX.blender_ocio() is None


def _page(w, h, shift=0.0):
    """A page as linear albedo, drawn at any size from the same geometry: paper 0.86, eight lines of ink at 0.012."""
    y, x = np.mgrid[0:h, 0:w] / np.array([h, w], dtype=float)[:, None, None]
    a = np.full((h, w), 0.86)
    for r in range(8):
        y0 = 0.12 + r * 0.1
        a[(y >= y0) & (y < y0 + 0.035) & (x > 0.1 + shift) & (x < 0.62 + 0.15 * (r * 7 % 3) + shift)] = 0.012
    return np.repeat(a[..., None], 3, axis=2)


def _scan_of(page, path):
    Image.fromarray(np.round(VX.linear_to_srgb(page) * 255).astype(np.uint8)).save(path)
    return str(path)


AGX = {"name": "AgX", "look": "None", "exposure": 2.5}     # puts the page's paper (241) at its scan's white (239)


def _camera(page, view=AGX):
    """The renderer's view of the page: its linear albedo at the frame's own size, exposed, through AgX. Drawn from
    the page itself, not from the scan the engine reads."""
    return np.round(VX.agx_published(page * 2 ** view["exposure"]) * 255).astype(np.uint8)


def test_a7_like_for_like_a_page_through_agx_passes_against_its_scan_once_declared(tmp_path, no_blender):
    W, H = TS.SIZE
    scan = _scan_of(_page(1600, 900), tmp_path / "scan.png")
    frame = _camera(_page(W, H))
    assert TS.record_difference(frame, scan) > TS.RECORD_LIMIT              # A7 as written: AgX's lift reads as a fault
    assert TS.record_difference(frame, scan, None, AGX) < 1.0               # like for like: the scan through AgX
    assert TS.reference_frame(scan, W, H, None, AGX)[1] == "published"


def test_a7_like_for_like_still_fails_when_the_record_differs(tmp_path, no_blender):
    W, H = TS.SIZE
    frame = _camera(_page(W, H))
    moved = _scan_of(_page(1600, 900, shift=0.08), tmp_path / "moved.png")          # the same page, its text altered
    assert TS.record_difference(frame, moved, None, AGX) > TS.RECORD_LIMIT
    other = str(_scan(tmp_path))                                                     # another scan altogether
    assert TS.record_difference(frame, other, None, AGX) > TS.RECORD_LIMIT


def test_a7_like_for_like_keeps_the_edge_strip_check(tmp_path, no_blender):
    W, H = TS.SIZE
    page = _page(1600, 1200)
    scan = _scan_of(page, tmp_path / "scan.png")
    win = (0.0, 0.0, 1.0, 1600 / 1200 * 9 / 16)
    with Image.open(scan) as im:
        lin = VX.to_linear_frame(im, win, W, H)
    frame = np.round(VX.agx_published(lin * 2 ** AGX["exposure"]) * 255).astype(np.uint8)
    assert TS.pose_edge_difference(frame, scan, win, AGX) < 1.0
    assert TS.record_difference(frame, scan, win, AGX) < 1.0
    frame[:, :40] = 0                                                                # 40 px past the scan onto black
    assert TS.pose_edge_difference(frame, scan, win, AGX) > TS.POSE_EDGE_LIMIT


def test_a7_like_for_like_an_undeclared_item_is_a7_as_before(tmp_path):
    p = _scan(tmp_path)
    W, H = TS.SIZE
    win = (0.1, 0.2, 0.9, 0.2 + 0.8 * 1600 / 1200 * 9 / 16)
    with Image.open(p) as im:
        held, posed = np.asarray(TS.hold_fit(im, W, H)), np.asarray(TS.pose_fit(im, win, W, H))
    assert VX.parse(None) == (None, None)
    for w, want in ((None, held), (win, posed)):
        ref, backend = TS.reference_frame(str(p), W, H, w)
        assert backend is None and np.array_equal(ref, want)                         # the scan as it always was


def test_a7_like_for_like_a_declaration_is_checked():
    assert VX.parse("AgX") == ({"name": "AgX", "look": "None", "exposure": 0.0}, None)
    assert VX.parse({"name": "AgX", "exposure": 3.75})[0]["exposure"] == 3.75
    for bad, says in (({"name": "Filmic"}, "not one of"), (7, "a name"), ({"name": "AgX", "exposure": "3"}, "stops"),
                      ({"name": "AgX", "exposure": float("nan")}, "stops"), ({"name": "AgX", "exposure": 40}, "stops"),
                      ({"name": "AgX", "look": ""}, "look")):
        spec, why = VX.parse(bad)
        assert spec is None and says in why, (bad, why)
    with pytest.raises(ValueError, match="Blender's own config"):
        VX.published(np.zeros((1, 1, 3)), {"name": "AgX", "look": "Punchy", "exposure": 0.0})


def test_a7_like_for_like_the_published_curves(no_blender):
    v = np.array([0.0, 0.002, 0.02, 0.18, 1.0, 4.0, 16.0])
    lin = np.repeat(v[None, :, None], 3, axis=2)
    agx = VX.display(lin, {"name": "AgX", "look": "None", "exposure": 0.0})[0][0, :, 0]
    std = VX.display(lin, {"name": "Standard", "look": "None", "exposure": 0.0})[0][0, :, 0]
    assert np.all(np.diff(agx.astype(int)) > 0) and agx[0] <= 1 and agx[-1] >= 250  # monotone, black to near white
    assert agx[3] == 127                                                              # mid grey, Wrensch's fit
    assert std.tolist() == [0, 7, 39, 118, 255, 255, 255]                             # the sRGB curve, clipped


def test_a7_like_for_like_the_exact_backend_is_pinned(tmp_path, monkeypatch):
    root = tmp_path / "blender"
    cm = root / VX.BLENDER_VERSION / "datafiles" / "colormanagement"
    (cm / "luts").mkdir(parents=True)
    (root / VX.BLENDER_VERSION / "python" / "bin").mkdir(parents=True)
    (root / VX.BLENDER_VERSION / "python" / "bin" / ("python.exe" if os.name == "nt" else "python3.11")).write_text("")
    for k in VX.PINS:
        (cm / k).write_text("not Blender 4.4.3's colour management", encoding="utf-8")
    monkeypatch.setenv("DOCUMENT_BLENDER_DIR", str(root))
    assert VX.blender_ocio() is None                    # a config that is not the pinned one is never used


def test_a7_like_for_like_in_the_plan(tmp_path, masters, film, no_blender):
    rec = film / "stills" / "FX-STILL-B.png"
    with Image.open(rec) as im:
        W, H = TS.SIZE
        pic = Image.fromarray(np.round(VX.agx_published(VX.to_linear_frame(im, None, W, H) * 2 ** AGX["exposure"])
                                       * 255).astype(np.uint8))
    m = dict(masters, agx=make_master(masters["dir"] / "agx.mkv", rec, rec_pic=pic))
    plan, j = plan_of(titled_film(tmp_path / "a", m, master="agx", item={"view_transform": AGX}))
    assert passed(j, "title-record-pixels"), [x["evidence"] for x in lints(j, "title-record-pixels")]
    ev = lints(j, "title-record-pixels")[-1]["evidence"]
    assert ev["view_transform"] == AGX and ev["view_backend"] == "published" and "through the master's declared" in ev["measure"]
    plan, j = plan_of(titled_film(tmp_path / "b", m, master="agx"))                  # undeclared: A7 as written
    assert isinstance(plan, R.Refused) and failed(j, "title-record-pixels")
    assert "view_transform" not in lints(j, "title-record-pixels")[-1]["evidence"]
    plan, j = plan_of(titled_film(tmp_path / "c", m, master="agx", item={"view_transform": {"name": "Filmic"}}))
    assert isinstance(plan, R.Refused) and failed(j, "title-record-pixels")
    assert "not one of" in lints(j, "title-record-pixels")[-1]["evidence"]["difference"]["error"]
    plan, j = plan_of(titled_film(tmp_path / "d", masters, item={"view_transform": AGX}))   # a plain master declared AgX
    assert isinstance(plan, R.Refused) and failed(j, "title-record-pixels")


# --------------------------------------------------------------------------
# A40 lockup card (coordinator, founder-delegated, 2026-10-26, implementing the 2026-10-18 ruling: The Run is one
# physics-only shot with no fades; the series lockup is a separate CARD shot after it, on a hard cut). title-lockup
# is met by the master's own lockup or by the series-title part ending on the house lockup card.
# --------------------------------------------------------------------------

NO_LOCKUP = {"lockup_frame": 20}               # a machine frame: this master carries no lockup of its own
HOLD = {"id": "TS1r", "kind": "archive_still", "asset": "FX-REC", "preset": "DRIFT", "fill_ok": False,
        "fill_exception": "a small test scan: the fill would pass 1.6x at 360p", "dur_s": 1.0, "mark": "ARCHIVE",
        "transition_in": {"type": "cut"}, "why": "The title's record held whole after its resting pose.",
        "repeat_reason": "The title's own record, held whole again so it can be read before the slot ends."}
CARD = {"id": "TS1b", "kind": "card", "card": "title", "text": [TS.SERIES], "dur_s": 1.0, "mark": "CARD",
        "transition_in": {"type": "cut"}, "why": "The series lockup, on a hard cut after the title."}


def with_shots(after=(), next_part=()):
    """An edit for titled_film: shots appended to the series-title part after TS1 (``after``) or put first in the next
    part (``next_part``), everything after them moved on by their length."""
    def edit(play):
        add = [dict(s) for s in list(after) + list(next_part)]
        t = COLD_S + TITLE_S
        extra = sum(s["dur_s"] for s in add)

        def move(x):
            for k in ("start_s", "end_s"):
                if isinstance(x.get(k), (int, float)) and x[k] >= t - 1e-6:
                    x[k] = round(x[k] + extra, 4)
        for part in play["parts"][2:]:
            for coll in ("shots", "lines", "cues", "text"):
                for x in part.get(coll, []):
                    move(x)
        for x in play.get("subtitle_source", []) + play.get("music", []) + play.get("moments", []):
            move(x)
        play["runtime_target_s"] += extra
        for s in add:
            s["start_s"] = round(t, 4)
            t += s["dur_s"]
        play["parts"][1]["shots"] += add[:len(after)]
        play["parts"][2]["shots"][:0] = add[len(after):]
    return edit


def _lockup_lint(j):
    got = lints(j, "title-lockup")
    assert got, [(e.get("rule"), e.get("unit")) for e in J.read(j.path) if e.get("kind") == "lint" and e.get("status") == "fail"]
    return got[-1]


def test_a40_lockup_card_after_the_title_and_its_record_hold_meets_the_lockup(tmp_path, masters):
    for k, after in enumerate(((HOLD, CARD), (CARD,))):
        plan, j = plan_of(titled_film(tmp_path / f"a{k}", masters, item=NO_LOCKUP, edit=with_shots(after)))
        ev = _lockup_lint(j)
        assert ev["status"] == "pass" and ev["evidence"]["lockup_card"] == "TS1b", ev
        assert ev["evidence"]["in_master"] is False and ev["evidence"]["card_problem"] is None


def test_a40_lockup_missing_or_misplaced_is_refused(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path / "a", masters, item=NO_LOCKUP, edit=with_shots((HOLD,))))
    assert isinstance(plan, R.Refused) and failed(j, "title-lockup")
    assert "a archive_still" in _lockup_lint(j)["evidence"]["card_problem"]               # the part ends on the hold
    plan, j = plan_of(titled_film(tmp_path / "b", masters, item=NO_LOCKUP))
    assert isinstance(plan, R.Refused) and "no lockup card" in _lockup_lint(j)["evidence"]["card_problem"]
    plan, j = plan_of(titled_film(tmp_path / "c", masters, item=NO_LOCKUP, edit=with_shots(next_part=(CARD,))))
    assert isinstance(plan, R.Refused) and "outside the series-title part" in _lockup_lint(j)["evidence"]["card_problem"]
    plan, j = plan_of(titled_film(tmp_path / "d", masters, item=NO_LOCKUP,
                                  edit=with_shots(({"id": "TS1x", "kind": "black", "dur_s": 1.0, "mark": "CARD", "silence": "intended",
                                                    "transition_in": {"type": "cut"}, "why": "A breath."}, CARD))))   # not a record hold
    assert isinstance(plan, R.Refused) and "only holds of the title's record" in _lockup_lint(j)["evidence"]["card_problem"]


def test_a40_lockup_card_must_be_the_house_lockup(tmp_path, masters):
    for k, (card, says) in enumerate(((dict(CARD, text=["void document"]), "not the series lockup"),
                                      ({k_: v for k_, v in CARD.items() if k_ != "card"}, "not a title card"),
                                      (dict(CARD, transition_in={"type": "dip", "s": 0.5}), "not joined by a cut"))):
        plan, j = plan_of(titled_film(tmp_path / f"a{k}", masters, item=NO_LOCKUP, edit=with_shots((HOLD, card))))
        assert isinstance(plan, R.Refused) and failed(j, "title-lockup"), card
        assert says in _lockup_lint(j)["evidence"]["card_problem"], (card, _lockup_lint(j)["evidence"])


def test_a40_lockup_card_is_pure_and_the_master_lockup_still_counts(tmp_path, masters):
    def S(id_, kind, part, **kw):
        return dict({"id": id_, "kind": kind, "_part": part, "_part_kind": "series_title", "_first_in_part": False}, **kw)
    shots = [S("TS1", "title_sequence", "series"), S("TS1r", "drawn", "series", asset="R"),
             S("TS1b", "card", "series", card="title", text=["  void document ·  As It Was "])]
    assert TS.lockup_card(shots, 0, {"record": "R"}, R.card_kind) == ("TS1b", None)     # spacing is not wording
    plan, j = plan_of(titled_film(tmp_path, masters))                                     # the fixture's own lockup
    assert _lockup_lint(j)["status"] == "pass" and _lockup_lint(j)["evidence"]["in_master"] is True


# --------------------------------------------------------------------------
# A40 title slot: a placeholder (title_slot: true) holds the slot until the series title is spliced in
# (founder ruling 2026-10-18: "the title is standalone, spliced via render --shots; a film never waits for
# its title"). title-theme accepts the main_title cue over a contiguous run of these shots exactly as over
# a title_sequence; none of A40's other per-shot checks run for a placeholder (it has no asset, no A7 pose).
# --------------------------------------------------------------------------


def slot_film(tmp_path, *, ids=("TS1", "TS1b"), title_slot=True, extra_before=0.0, edit=None):
    """The fixture film with the cold open followed by placeholder shot(s) standing in for the series
    titles, instead of a real title_sequence. Together the placeholders span exactly ``TITLE_S``, so the
    rest of the film shifts by the total (``COLD_S + extra_before + TITLE_S``) regardless of how many
    placeholder shots make up the run. ``extra_before`` inserts one ordinary card between the cold open and
    the slot run (a misplaced-run fixture: the slot then sits one shot late). ``edit(play)`` runs last, as
    in ``titled_film``."""
    film = make_film(tmp_path / "film")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    total_shift = round(COLD_S + extra_before + TITLE_S, 4)

    def move(x):
        for k in ("start_s", "end_s"):
            if isinstance(x.get(k), (int, float)):
                x[k] = round(x[k] + total_shift, 4)
    for part in play["parts"]:
        for coll in ("shots", "lines", "cues", "text"):
            for x in part.get(coll, []):
                move(x)
    for x in play.get("subtitle_source", []) + play.get("music", []) + play.get("moments", []):
        move(x)
    play["runtime_target_s"] = play["runtime_target_s"] + total_shift
    slot_start = round(COLD_S + extra_before, 4)
    slot_dur = TITLE_S / len(ids)
    slots = []
    for k, sid in enumerate(ids):
        s = {"id": sid, "kind": "card", "start_s": round(slot_start + k * slot_dur, 4), "dur_s": slot_dur, "mark": "CARD",
             "text": ["The Run"], "transition_in": {"type": "cut"},
             "why": "The series titles' slot, held by a placeholder until the title is spliced in."}
        if title_slot:
            s["title_slot"] = True
        slots.append(s)
    series_shots = slots
    if extra_before:
        series_shots = [{"id": "X1", "kind": "card", "start_s": COLD_S, "dur_s": extra_before, "mark": "CARD",
                          "text": ["Not the slot"], "transition_in": {"type": "cut"},
                          "why": "An ordinary card before the slot (a misplaced-run fixture)."}] + slots
    play["parts"][:0] = [
        {"id": "cold", "kind": "cold_open", "title": "Cold open", "shots": [
            {"id": "CO1", "kind": "black", "start_s": 0.0, "dur_s": COLD_S, "mark": "CARD", "transition_in": {"type": "cut"},
             "silence": "intended", "why": "The hook, in this test a breath of black."}]},
        {"id": "series", "kind": "series_title", "title": TS.SERIES, "shots": series_shots}]
    if edit:
        edit(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def test_a40_title_slot_a_contiguous_run_of_placeholders_takes_the_main_title_theme(tmp_path):
    def theme(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S, "end_s": SHIFT, "wav": "mt.wav"}]
    film = slot_film(tmp_path, edit=theme)
    plan, j = plan_of(film)
    assert not isinstance(plan, Exception), plan
    # the slot run is accepted (no title-theme refusal); there is no title_sequence shot to emit a pass entry for
    assert not failed(j, "title-theme")
    # the run counts once, in the right place, each shot an allowed kind: all three now fire real pass entries
    assert passed(j, "title-sequence-once") and passed(j, "title-sequence-place") and passed(j, "title-slot-kind")
    # title-sequence-clear runs over the run too, but only ever as a warning for a placeholder
    assert lints(j, "title-sequence-clear") and all(e["severity"] == "warn" for e in lints(j, "title-sequence-clear"))
    # none of A40's other per-shot checks (transitions, provenance, format, A7 pose, and so on) are raised for
    # a placeholder: there is no title_sequence shot, so none of these ever run (once/place/kind/clear do, and
    # are checked above instead)
    for rule in RULES:
        if rule in ("title-sequence-once", "title-sequence-place", "title-sequence-clear"):
            continue
        assert not lints(j, rule), (rule, lints(j, rule))


def test_a40_title_slot_a_single_placeholder_also_takes_the_theme(tmp_path):
    def theme(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S, "end_s": SHIFT, "wav": "mt.wav"}]
    film = slot_film(tmp_path, ids=("TS1",), edit=theme)
    plan, j = plan_of(film)
    assert not isinstance(plan, Exception), plan
    assert not failed(j, "title-theme")
    assert passed(j, "title-sequence-once") and passed(j, "title-sequence-place") and passed(j, "title-slot-kind")


def test_a40_title_theme_over_a_non_slot_still_still_refuses(tmp_path):
    """The same shots, the same cue, but without ``title_slot: true``: a plain still is not the slot, so the
    theme over it refuses exactly as it would over any other non-title shot."""
    def theme(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S, "end_s": SHIFT, "wav": "mt.wav"}]
    film = slot_film(tmp_path, title_slot=False, edit=theme)
    plan, j = plan_of(film)
    assert isinstance(plan, R.Refused) and failed(j, "title-theme")


def test_a40_title_theme_over_a_slot_run_must_start_on_its_first_frame(tmp_path):
    """The cue is contained in the run but starts a second late: title-theme holds a slot run to the same
    bound as a title_sequence shot (the per-shot check at titles.py:565), not mere containment."""
    def theme_late(play):
        play["music"] = [{"id": "MT", "kind": "music", "role": "main_title", "start_s": COLD_S + 1.0, "end_s": SHIFT, "wav": "mt.wav"}]
    plan, j = plan_of(slot_film(tmp_path, edit=theme_late))
    assert isinstance(plan, R.Refused) and failed(j, "title-theme")


def test_a40_title_slot_run_not_right_after_the_cold_open_is_misplaced(tmp_path):
    """An ordinary card sits between the cold open and the slot: one run, correctly formed, in the wrong
    place. title-sequence-once still passes (there is only one run); title-sequence-place refuses it."""
    plan, j = plan_of(slot_film(tmp_path, extra_before=1.0))
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-place")
    assert passed(j, "title-sequence-once")


def test_a40_title_slot_two_separate_runs_refuses_once(tmp_path):
    """TS1 and TS1b are split by an ordinary card: two runs, not one, even though each is otherwise fine."""
    def split(play):
        series = next(p for p in play["parts"] if p["id"] == "series")
        ts1, ts1b = series["shots"]
        mid_dur = 1.0
        ts1["dur_s"] = round(ts1["dur_s"] - mid_dur, 4)
        mid = {"id": "MID", "kind": "card", "start_s": round(ts1["start_s"] + ts1["dur_s"], 4), "dur_s": mid_dur,
               "mark": "CARD", "text": ["Not the slot"], "transition_in": {"type": "cut"}, "why": "Splits the run."}
        ts1b["start_s"] = round(mid["start_s"] + mid_dur, 4)
        series["shots"] = [ts1, mid, ts1b]
    plan, j = plan_of(slot_film(tmp_path, edit=split))
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-once")
    ev = next(e for e in lints(j, "title-sequence-once") if e["status"] == "fail")
    assert len(ev["evidence"]["slot_runs"]) == 2


def test_a40_title_slot_a_real_title_plus_a_slot_both_refuses_once(tmp_path, masters):
    """A real title_sequence and a title_slot placeholder never coexist, wherever the placeholder sits."""
    def add_slot(play):
        s1 = next(sh for part in play["parts"] for sh in part.get("shots", []) if sh["id"] == "S1")
        s1["title_slot"] = True
    plan, j = plan_of(titled_film(tmp_path, masters, edit=add_slot))
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-once")
    ev = next(e for e in lints(j, "title-sequence-once") if e["status"] == "fail")
    assert ev["evidence"]["title_shots"] == ["TS1"] and ev["evidence"]["slot_runs"] == [["S1"]]


def test_a40_title_slot_on_a_chapter_black_shot_is_misplaced(tmp_path):
    """A title_slot flag on an ordinary chapter shot (S8, a black shot deep in the fixture film, not right
    after any cold open): black is an allowed kind, so only its place is wrong."""
    film = make_film(tmp_path / "film")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    s8 = next(sh for part in play["parts"] for sh in part.get("shots", []) if sh["id"] == "S8")
    assert s8["kind"] == "black"
    s8["title_slot"] = True
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    plan, j = plan_of(film)
    assert isinstance(plan, R.Refused) and failed(j, "title-sequence-place")
    assert passed(j, "title-slot-kind") and passed(j, "title-sequence-once")


def test_a40_title_slot_kind_refuses_a_clip_or_a_video():
    """Only a still, a card or black may wear the slot: title-slot-kind refuses a video shot flagged
    title_slot. Called directly against plan_lints with a synthetic shot, independent of the rest of a
    plan (an archive_video shot needs more setup than this check cares about)."""
    calls = []

    def lint(rule, ok, **kw):
        calls.append((rule, ok, kw))

    class StubJournal:
        def lint(self, *a, **k):
            pass

        def decision(self, *a, **k):
            pass
    shots = [{"id": "V1", "kind": "archive_video", "title_slot": True, "f0": 0, "f1": 48, "_part_kind": "series_title"}]
    TS.plan_lints(lint, StubJournal(), {"parts": []}, shots, {}, lines=[], texts=[], cues=[], vl=[], silences=[], fps=24.0)
    assert any(rule == "title-slot-kind" and not ok for rule, ok, kw in calls)


def test_a40_title_slot_placeholder_still_obeys_every_other_lint(tmp_path):
    """A placeholder is an ordinary shot otherwise: voice over it still fails A55 voice-over-black, which is
    checked at render time (voice_over_black_lints runs after build_plan, inside render()), not at plan time."""
    def voice(play):
        play["parts"][1]["lines"] = [{"id": "LX", "kind": "narration", "start_s": COLD_S + 0.2, "text": "Over the slot."}]
    film = slot_film(tmp_path, edit=voice)
    tone(film / "audio" / "LX.wav", 1.0)
    j = J.Journal(film="a40-slot-voice")
    with pytest.raises(R.Refused, match="voice-over-black"):
        R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, encode_preset="veryfast", journal=j)


def test_a40_title_slot_is_title_slot_and_contiguous_runs_helpers():
    assert TS.is_title_slot({"title_slot": True}) and not TS.is_title_slot({"title_slot": "true"})
    assert not TS.is_title_slot({})
    assert TS._contiguous_runs([2, 3, 4, 7, 8, 11]) == [[2, 3, 4], [7, 8], [11]]
    assert TS._contiguous_runs([]) == []
