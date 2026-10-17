"""A40, the series titles (void document · As It Was): a pre-rendered master played as it is, right after the cold
open and before Part 1, its own marks burned in and checked on its pixels, its provenance declared and free of AI,
its format matched, its record beat this film's own record; the main-title theme's slot under it. Small synthetic
masters (4 s of 1080p24 FFV1) stand in for the 57 s ones."""

from __future__ import annotations

import json
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


def make_master(path, record_png, *, burned=True, glyph_on_hold=True, n=N):
    """A short master in the real ones' shape: the machine (DRAWN), a cut to the record held whole (ARCHIVE), a dip
    and the lockup (CARD), the marks burned in as assemble.py burns them (or none)."""
    W, H = TS.SIZE
    fonts = M.Fonts()
    machine, rec, lock = _machine(W, H), TS.hold_fit(Image.open(record_png), W, H), _lockup(W, H)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    item = {"marks": TL, "dip": DIP, "frames": n}
    holds = TS.dip_hold_frames(item)
    shots = [{"start": m["frame"] / 24, "cls": m["cls"], "label": m.get("label", "")} for m in TL]
    t0 = DIP["centre_frame"] / 24 - DIP["s"] / 2
    p = subprocess.Popen([R.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "24",
                          "-i", "-", "-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "bgr0", str(path)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / 24
        pic = machine if k < 36 else rec if k < 60 else lock
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


def test_a40_the_key_keeps_its_no_ai_line_and_shows_the_titles_classes(tmp_path, masters):
    plan, j = plan_of(titled_film(tmp_path, masters))
    assert "AI-GENERATED" not in plan["key_classes"]
    assert {"DRAWN", "ARCHIVE", "CARD"} <= set(plan["key_classes"])
    lay = M.mark_key_layout(M.Layout(1920, 1080), M.Fonts(), plan["key_classes"])
    assert M.KEY_NO_AI in M.mark_key_drawn_text(lay)
    assert lints(j, "title-no-ai")[0]["evidence"]["key_line"] == M.KEY_NO_AI


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
