import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from conftest import HEIGHT, ROOT, WORKERS, make_film

LETTERBOX = np.array(M.PALETTE["letterbox"])


def events(summary):
    return J.read(summary["journal"])


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


# --------------------------------------------------------------------------
# The fixture render as a whole
# --------------------------------------------------------------------------


def test_master_is_24fps_h264_with_every_frame(rendered, plan):
    pr = R.probe_video(Path(rendered["master"]))
    assert (pr["width"], pr["height"]) == R.frame_size(HEIGHT)
    assert abs(pr["fps"] - 24) < 1e-6 and pr["has_audio"]
    assert R.count_frames(Path(rendered["master"])) == plan["frames"] == rendered["frames"] == 594
    assert rendered["workers"] == WORKERS
    tags = subprocess.run([R.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=color_space,color_primaries,color_transfer,pix_fmt", "-of", "json", rendered["master"]],
                          capture_output=True, text=True).stdout
    v = json.loads(tags)["streams"][0]
    assert (v["color_space"], v["color_primaries"], v["color_transfer"], v["pix_fmt"]) == ("bt709", "bt709", "bt709", "yuv420p")


def test_journal_holds_the_run_and_every_unit(rendered):
    evs = events(rendered)
    assert {e["kind"] for e in evs} <= set(J.KINDS)
    lens = [e.get("lens") for e in evs]
    assert "run.start" in lens and lens[-1] == "run.end" and evs[-1]["outcome"] == "ok"
    done = {e["unit"] for e in evs if e.get("lens") == "unit.done" and e["stage"] == "motion"}
    assert done == {f"S{i}" for i in range(1, 10)}
    starts = {e["unit"] for e in evs if e.get("lens") == "unit.start" and e["stage"] == "motion"}
    assert starts == done
    assert [e for e in evs if e.get("lens") == "frame"], "frame progress events for the Lens"
    marks = [e for e in evs if e.get("lens") == "marks"][0]
    assert marks["generated_share"] == 0 and abs(sum(marks["share"].values()) - 1) < 1e-3
    assert not [e for e in evs if e["kind"] == "error"]
    timings = [json.loads(x) for x in Path(J.timings_path()).read_text(encoding="utf-8").splitlines()]
    mine = [t for t in timings if t["run"] == rendered["run"]]
    assert {t["unit_id"] for t in mine if t["stage"] == "motion"} == done
    assert all(t["outcome"] == "ok" for t in mine)
    arts = {e["role"]: e for e in evs if e["kind"] == "artifact"}
    assert arts["master"]["sha256"] and arts["sources"]["sha256"]


def test_a_missing_cue_wav_is_a_warning_and_silence(rendered):
    evs = events(rendered)
    missing = {e["unit"] for e in lints(evs, "audio-present")}
    assert missing == {"C1"}
    assert all(e["severity"] == "warn" for e in lints(evs, "audio-present"))
    loud = lints(evs, "loudness")[0]["evidence"]
    assert loud["normalised"] and abs(loud["output_i"] - R.TARGET_LUFS) <= 1.0


def test_every_lint_t1_enforces_ran_and_passed(rendered):
    evs = events(rendered)
    for rule in ("mark-coverage", "ai-generated-share-zero", "still-first-frame-whole", "still-first-frame-whole-pixels",
                 "clip-aspect", "dissolve-same-class", "conform-logged", "resampler-plain", "master-format",
                 "silent-card-form", "lower-third-format", "no-em-dash", "licence-allowlist", "no-bodies",
                 "still-zoom-limit", "cross-class-dip", "overlay-format", "clip-hold-rendered", "telecine-declared",
                 "loudnorm-linear", "mark-class-valid", "clip-in-out", "still-hold"):
        found = lints(evs, rule)
        assert found, rule
        if rule == "still-first-frame-whole-pixels":
            # the fixture's drawn stills are smooth gradients at their edges: the band cannot see a small crop there
            found = [e for e in found if not (e["status"] == "inconclusive" and e["evidence"]["band_detail"] < R.A7_DETAIL_FLOOR)]
        assert all(e["status"] == "pass" for e in found), (rule, found)
    review = lints(evs, "fill-ok")
    assert {e["unit"]: e["evidence"]["fill_ok"] for e in review} == {"S3": True, "S4": False, "S5": False}
    assert all(e["status"] == "review" for e in review)
    conform = lints(evs, "conform-logged")[0]["evidence"]
    assert conform["method"] == "drop" and conform["filter"] == "fps=24"


# --------------------------------------------------------------------------
# Marks on every frame
# --------------------------------------------------------------------------


def test_mark_plate_on_every_frame_matches_the_shot(plan):
    pics = R.Pictures(plan)
    x, y = R.mark_probe(plan)
    crossfades = dips = 0
    try:
        for f in range(plan["frames"]):
            i = max(k for k, s in enumerate(plan["shots"]) if s["f0"] <= f)
            s = plan["shots"][i]
            arr = np.asarray(R.compose(plan, pics, f, i))
            if R.picture_level(plan, f, i) <= 0.0:          # a dip's black hold: every pixel off
                assert not arr.any(), f
                dips += 1
                continue
            px = arr[y, x].astype(int)
            fading = i > 0 and plan["shots"][i - 1]["mark"] != s["mark"] and f - s["f0"] < 4
            if fading:
                crossfades += 1
                prev = np.array(M.MARK_HUE[plan["shots"][i - 1]["mark"]])
                cur = np.array(M.MARK_HUE[s["mark"]])
                # a true crossfade: the bar pixel lies between the two hues, never the picture showing through
                assert R.between_hues(px, prev, cur), (f, px)
                continue
            assert np.max(np.abs(px - np.array(M.MARK_HUE[s["mark"]]))) <= 2, (f, s["id"], px)
    finally:
        pics.close()
    changes = sum(1 for a, b in zip(plan["shots"], plan["shots"][1:]) if a["mark"] != b["mark"])
    assert changes and crossfades > 0 and dips > 0


def _label_box(plan):
    """The zone right of the glyph where the A16 label is drawn."""
    L = M.Layout(plan["W"], plan["H"])
    gx, gy = M.glyph_origin(L)
    d = M.glyph_px(L)
    return gy - 2, gy + d + L.px(M.LABEL["size"]), gx + d + 1, int(L.w(30))


def test_a16_a_card_carries_the_glyph_alone_and_imagery_its_label_then_the_glyph(plan):
    L = M.Layout(plan["W"], plan["H"])
    x, y = R.mark_probe(plan)
    y0, y1, x0, x1 = _label_box(plan)
    card = R.render_frame(plan, plan["shots"][0]["f0"] + 5)
    assert np.max(np.abs(card[y, x].astype(int) - np.array(M.MARK_HUE["CARD"]))) <= 2
    assert not card[y0:y1, x0:x1].any(), "a CARD has no label: its own words say what it is"
    s3 = next(s for s in plan["shots"] if s["id"] == "S3")
    assert s3["label"] == "Drawn · from PIL test image, test fixture"
    up = R.render_frame(plan, s3["f0"] + 30).astype(int)                       # 1.25 s in: the label is up
    assert up[y0:y1, x0:x1].max() > 150
    st = M.mark_state((s3["f0"] + 30) / 24, plan["marks"])
    assert st["label"] == s3["label"] and st["label_alpha"] > 0.99
    # the G2 plate set its text at 3.1% of height, opaque on a scrim; the label is smaller, translucent and boxless
    assert M.LABEL["size"] < 3.1 and M.LABEL["alpha"] < 1.0


def test_a16_the_label_surfaces_holds_about_3_s_and_is_let_go_to_the_glyph():
    shots = [{"start": 0.0, "cls": "ARCHIVE", "label": "Archive · 1947"}]
    a = [M.label_alpha(f / 24, 0.0) for f in range(0, 24 * 6)]
    assert a[0] == 0.0 and 0.3 < a[2] < 0.95 and a[9] > 0.98                  # up in a few frames, on whisper
    assert all(x > 0.98 for x in a[10:24 * 3])                                  # held about 3 s
    gone = next(f for f in range(24 * 3, len(a)) if a[f] == 0.0)
    assert 3.9 <= gone / 24 <= 4.3 and all(x == 0.0 for x in a[gone:])        # let go, then glyph only
    assert all(b <= c + 1e-9 for b, c in zip(a[24 * 3 + 9:gone], a[24 * 3 + 8:gone - 1]))   # it never comes back up
    L = M.Layout(640, 360)
    img = Image.new("RGB", (640, 360), (255, 255, 255))
    for t in (0.0, 1.0, 5.0, 60.0):                                             # the glyph is on every frame, label or not
        px = M.mark_frame(img, t, shots, M.Fonts()).getpixel(M.glyph_centre(L))[:3]
        assert px == M.MARK_HUE["ARCHIVE"], (t, px)
    y0, y1, x0, x1 = 16, 30, 32, 192
    held = np.asarray(M.mark_frame(img, 1.0, shots, M.Fonts()).convert("RGB")).astype(int)
    after = np.asarray(M.mark_frame(img, 5.0, shots, M.Fonts()).convert("RGB")).astype(int)
    assert (255 - held[y0:y1, x0:x1]).max() > 60 and (255 - after[y0:y1, x0:x1]).max() == 0


def test_a16_the_label_surfaces_at_every_cut_even_with_the_same_words():
    shots = [{"start": 0.0, "cls": "ARCHIVE", "label": "Archive · 1947"},
             {"start": 6.0, "cls": "ARCHIVE", "label": "Archive · 1947"},
             {"start": 9.0, "cls": "ARCHIVE", "label": "Archive · 1948"},
             {"start": 12.0, "cls": "CARD", "label": ""}]
    assert M.label_starts(shots) == [0.0, 6.0, 9.0, None]
    assert M.mark_state(6.5, shots)["label_alpha"] > 0.9 and M.mark_state(12.5, shots)["label_alpha"] == 0.0


def test_a16_refined_an_ai_generated_label_never_fades():
    shots = [{"start": 0.0, "cls": "AI-GENERATED", "label": "AI-generated · context"},
             {"start": 30.0, "cls": "AI-GENERATED", "label": "AI-generated · context"}]
    for t in (0.0, 1 / 24, 4.2, 10.0, 29.9, 30.0, 30.5, 59.0):               # full on each cut frame, never fading
        assert M.mark_state(t, shots)["label_alpha"] == 1.0, t
    assert M.label_alpha(10.0, 0.0, "DRAWN") == 0.0 and M.label_alpha(10.0, 0.0, "AI-GENERATED") > 0.99


def _corner_alpha(W, H, cls):
    tile, (ox, oy) = M.glyph_tile(W, H, cls)
    cx, cy = M.glyph_corner(M.Layout(W, H))
    return tile.getpixel((cx - ox, cy - oy))[3] / 255.0


def _trip_backgrounds(W, H):
    """Every background that could make a dot's or a diamond's corner read as
    the cold blue or amber hue: the hue divided by (1 - corner alpha), a few
    steps around it, plus the hue itself and black, white and grey."""
    out = {(0, 0, 0), (255, 255, 255), (128, 128, 128)}
    for c in M.GLYPH_SHAPE:
        out.add(M.MARK_HUE[c])
        a = _corner_alpha(W, H, c)
        for hue in {M.MARK_HUE[k] for k in M.GLYPH_SHAPE}:
            base = np.array(hue) / max(1.0 - a, 1e-6)
            for d in (-3, -1, 0, 1, 3):
                out.add(tuple(int(v) for v in np.clip(np.round(base + d), 0, 255)))
    return sorted(out)


@pytest.mark.parametrize("height", [360, 720, 1080, 1440, 2160])
def test_a16_the_shape_check_holds_over_any_background(height):
    """Re-review blocker: the corner of a dot or a diamond is the picture under
    an almost clear disc edge (alpha 0.08 at 1080p), so over a background of
    hue / (1 - alpha) it reads as the hue. The check now compares the corner
    with what the class's own glyph composes over the bare pixel."""
    W = round(height * 16 / 9)
    L = M.Layout(W, height)
    plan = {"W": W, "H": height}
    assert M.MARK_HUE["DRAWN"] == M.MARK_HUE["AI-GENERATED"]
    x, y = M.glyph_corner(L)
    cx, cy = M.glyph_centre(L)
    for bg in _trip_backgrounds(W, height):
        img = Image.new("RGBA", (W, height), bg + (255,))
        for drawn in M.GLYPH_SHAPE:
            arr = np.asarray(M.mark_frame(img, 1.0, [{"start": 0.0, "cls": drawn, "label": ""}], M.Fonts()).convert("RGB"))
            assert tuple(arr[cy, cx]) == M.MARK_HUE[drawn], (height, bg, drawn)            # solid hue at the centre
            assert R.glyph_shape_ok(plan, arr, drawn, bg), (height, bg, drawn)             # a correct frame always passes
            for claimed in M.GLYPH_SHAPE:
                if claimed == drawn or M.MARK_HUE[claimed] != M.MARK_HUE[drawn]:
                    continue
                square = {M.GLYPH_SHAPE[claimed], M.GLYPH_SHAPE[drawn]} & {"square"}
                if square and M.GLYPH_SHAPE[claimed] != M.GLYPH_SHAPE[drawn]:
                    # a square for a dot or a diamond (or the reverse) is caught unless the picture is the hue itself
                    if max(abs(int(v) - h) for v, h in zip(bg, M.MARK_HUE[drawn])) > 3:
                        assert not R.glyph_shape_ok(plan, arr, claimed, bg), (height, bg, drawn, claimed)


def test_a16_the_ai_and_drawn_glyphs_differ_at_720p():
    L = M.Layout(1280, 720)
    d = M.glyph_px(L)
    assert d == 6
    ai, dr = (np.asarray(M._glyph(c, d).getchannel("A")) for c in ("AI-GENERATED", "DRAWN"))
    assert dr[0, 0] == 255 and ai[0, 0] == 0 and ai[d // 2, d // 2] == 255 and not np.array_equal(ai, dr)


def test_a16_refined_coverage_refuses_a_drawn_glyph_on_an_ai_generated_shot(plan):
    i = next(k for k, s in enumerate(plan["shots"]) if s["id"] == "S3")       # DRAWN
    f = plan["shots"][i]["f0"] + 30
    probe = {}
    arr = R.render_frame(plan, f, probe=probe)
    assert R.check_mark(plan, arr, f, i, probe["bare_corner"]) == "ok"
    assert R.check_mark(plan, arr, f, i) == "fail"                              # no bare pixel, no judgement: never a pass
    ai = json.loads(json.dumps(plan))
    ai["shots"][i]["mark"] = "AI-GENERATED"                                    # the same cold blue, the wrong shape
    assert R.check_mark(ai, arr, f, i, probe["bare_corner"]) == "shape"


# --------------------------------------------------------------------------
# Stills (A7) and clips (A5, A6, 7.5)
# --------------------------------------------------------------------------


def _image_columns(arr, rows):
    band = arr[rows[0]:rows[1]].astype(int)
    return np.where(np.any(np.abs(band - LETTERBOX).max(axis=2) > 3, axis=0))[0]


def _clip_columns(plan):
    """The test clip's picture columns at 15.2 s (after the dip, before the
    overlay), read on testsrc's full-width colour ramp (88 to 93% of height),
    since the pattern has black areas of its own."""
    H = plan["H"]
    return _image_columns(R.render_frame(plan, int(round(15.2 * 24))), (int(0.88 * H), int(0.93 * H)))


@pytest.mark.parametrize("sid", ["S3", "S4", "S5"])
def test_still_first_frame_is_the_whole_photograph(plan, sid):
    i = [s["id"] for s in plan["shots"]].index(sid)
    s = plan["shots"][i]
    pics = R.Pictures(plan)
    try:
        raw = np.asarray(pics.shot(i, 0.0))
        img = pics.still(s)
        assert R.still_first_frame_whole(plan, pics, i)
    finally:
        pics.close()
    W, H = plan["W"], plan["H"]
    k = min(W / img.width, H / img.height)
    cols = _image_columns(raw, (H // 3, 2 * H // 3))
    assert abs(cols[0] - (W - img.width * k) / 2) <= 1.5 and abs(cols[-1] + 1 - (W + img.width * k) / 2) <= 1.5
    # and the shot's first composed frame is all field outside the photograph's box, overlays aside
    assert s["_cam"]["path"][0] == {"z": 1.0, "x": 0.5, "y": 0.5}


def test_fill_only_with_fill_ok(plan):
    ids = [s["id"] for s in plan["shots"]]
    W, H = plan["W"], plan["H"]
    pics = R.Pictures(plan)
    try:
        s3 = plan["shots"][ids.index("S3")]
        end3 = np.asarray(pics.shot(ids.index("S3"), s3["_dur"] - 1 / 24))
        assert len(_image_columns(end3, (H // 3, 2 * H // 3))) == W           # filled 16:9
        s4 = plan["shots"][ids.index("S4")]
        mid4 = np.asarray(pics.shot(ids.index("S4"), s4["_dur"] / 2))
        cols = _image_columns(mid4, (H // 3, 2 * H // 3))
        assert cols[0] > 10 and cols[-1] < W - 10                                  # stays in its own shape
    finally:
        pics.close()


def test_clip_is_pillarboxed_at_4_3(plan, rendered):
    i = [s["id"] for s in plan["shots"]].index("S6")
    s = plan["shots"][i]
    W, H = plan["W"], plan["H"]
    assert s["_video"]["fit"] == [480, 360]
    cols = _clip_columns(plan)
    assert cols[0] == (W - 480) // 2 and cols[-1] == (W + 480) // 2 - 1
    ev = [e for e in lints(events(rendered), "clip-aspect") if e["unit"] == "S6"][0]["evidence"]
    assert ev["fit"] == [480, 360] and abs(ev["source_dar"] - 4 / 3) < 1e-3


def test_inverse_telecine_restores_the_film_frames(tmp_path):
    import make_media
    src = make_media.telecined(tmp_path / "tc.mp4", seconds=2.0)
    pr = R.probe_video(src)
    conf = R.conform_plan({"telecined": True}, pr)
    assert conf["method"] == "ivtc" and conf["field_order"] == "tff"
    k = 320 * 240 * 3
    r = subprocess.run([R.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", make_media.MOVING.format(s=2.0), "-s", "320x240",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    ref = [np.frombuffer(r.stdout[i:i + k], np.uint8).reshape(240, 320, 3).astype(int) for i in range(0, len(r.stdout) - k + 1, k)]

    def frames(conf):
        shot = {"id": "X", "in_s": 0.0, "_dur": 2.0, "_item": {"_path": str(src)},
                "_video": {"fit": [320, 240], "conform": conf}}
        rd = R.VideoReader(shot, 0.0)
        out = []
        while True:
            b = rd.proc.stdout.read(rd.nbytes)
            if len(b) < rd.nbytes:
                break
            out.append(np.frombuffer(b, np.uint8).reshape(240, 320, 3).astype(int))
        rd.close()
        return out

    ivtc = frames(conf)
    naive = frames(R.conform_plan({"telecined": False}, pr))
    assert 46 <= len(ivtc) <= 48                  # 24 a second, no speed change

    def worst(fs):
        return max(min(float(np.mean(np.abs(f - g))) for g in ref) for f in fs)

    # every restored frame is one of the film's own frames; plain frame drop leaves combed (mixed-field) frames
    assert worst(ivtc) < 3.0
    assert worst(naive) > 10.0


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_cross_class_dissolve_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    shots = play["parts"][1]["shots"]
    s3 = next(s for s in shots if s["id"] == "S3")
    s3["transition_in"] = {"type": "dissolve", "s": 0.5}       # CARD (S2) into DRAWN (S3)
    for s in shots[shots.index(s3):]:
        s["start_s"] -= 0.5
    play["parts"][2]["shots"][0]["start_s"] -= 0.5
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    j = J.Journal(film="refuse")
    with pytest.raises(R.Refused, match="dissolve-same-class"):
        R.render(film, tmp_path / "out", height=HEIGHT, workers=1, min_free_gb=1, journal=j)
    evs = J.read(j.path)
    fail = [e for e in lints(evs, "dissolve-same-class") if e["unit"] == "S3"][0]
    assert fail["status"] == "fail" and fail["evidence"] == {"from": "CARD", "to": "DRAWN"}
    assert [e for e in evs if e["kind"] == "decision" and e["unit"] == "S3"]
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused"
    assert not (tmp_path / "out" / "master.mp4").exists()


class _DU:
    def __init__(self, gb):
        self.free = gb * 1024 ** 3


D_DRIVE = "D:" + chr(92)


def test_preflight_refuses_a_full_disk_and_an_unhealthy_d(tmp_path):
    j = J.Journal(film="pf")
    with pytest.raises(R.Refused, match="under the 10 GB floor"):
        R.preflight(tmp_path, j, disk_usage=lambda p: _DU(9.5))
    assert R.preflight(tmp_path, j, disk_usage=lambda p: _DU(50))["free_gb"] == 50
    with pytest.raises(R.Refused, match="Warning"):
        R.preflight(tmp_path, j, disk_usage=lambda p: _DU(50), drive=D_DRIVE,
                    health=lambda x: {"health": "Warning", "operational": "OK"}, allow_unverified=True)
    ok = R.preflight(tmp_path, j, disk_usage=lambda p: _DU(50), drive=D_DRIVE,
                     health=lambda x: {"health": "Healthy", "operational": "OK"})
    assert ok["volume"]["health"] == "Healthy"
    assert [e["status"] for e in lints(J.read(j.path), "preflight-d-health")] == ["fail", "pass"]


def test_an_unreadable_d_refuses_unless_the_override_is_set(tmp_path, monkeypatch):
    j = J.Journal(film="pf")
    monkeypatch.delenv("DOCUMENT_ALLOW_UNVERIFIED_DISK", raising=False)
    with pytest.raises(R.Refused, match="could not be read"):
        R.preflight(tmp_path, j, disk_usage=lambda p: _DU(50), drive=D_DRIVE, health=lambda x: None)
    monkeypatch.setenv("DOCUMENT_ALLOW_UNVERIFIED_DISK", "1")
    R.preflight(tmp_path, j, disk_usage=lambda p: _DU(50), drive=D_DRIVE, health=lambda x: None)
    humans = [e for e in J.read(j.path) if e["kind"] == "human"]
    assert humans and humans[-1]["override"] == "DOCUMENT_ALLOW_UNVERIFIED_DISK=1"


def test_volume_health_is_read_only_for_d(tmp_path):
    called = []
    j = J.Journal(film="pf")
    R.preflight(tmp_path, j, min_free_gb=0, health=lambda x: called.append(x), drive="C:" + chr(92))
    assert called == []
    assert [e for e in J.read(j.path) if e["kind"] == "human" and e.get("override") == "min_free_gb"]


def test_generated_shots_and_bad_licences_are_refused(tmp_path):
    film = make_film(tmp_path / "film")
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][0]["licence"] = "CC BY-SA 4.0"
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    j = J.Journal(film="lic")
    with pytest.raises(R.Refused, match="licence-allowlist"):
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)


# --------------------------------------------------------------------------
# Resume and the cache
# --------------------------------------------------------------------------


def test_resume_from_a_shot_takes_earlier_shots_from_the_cache(film, rendered):
    out = rendered["out"]
    again = R.render(film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast")
    assert again["rendered"] == [] and len(again["cached"]) == 9
    resumed = R.render(film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", from_shot="S6")
    assert resumed["cached"] == ["S1", "S2", "S3", "S4", "S5"]
    assert resumed["rendered"] == ["S6", "S7", "S8", "S9"]
    evs = events(resumed)
    start = [e for e in evs if e.get("lens") == "run.start"][0]
    assert start["resumed_from"] == "S6"
    skipped = {e["unit"] for e in evs if e.get("lens") == "unit.done" and e.get("status") == "skip"}
    assert skipped == {"S1", "S2", "S3", "S4", "S5"}
    assert R.count_frames(Path(resumed["master"])) == 594


def test_resume_needs_the_earlier_segments(film, tmp_path):
    with pytest.raises(R.Refused, match="no cached segment"):
        R.render(film, tmp_path / "fresh", height=HEIGHT, workers=1, min_free_gb=1, from_shot="S4")
    with pytest.raises(R.Refused, match="no such shot"):
        R.render(film, tmp_path / "fresh", height=HEIGHT, workers=1, min_free_gb=1, from_shot="S99")


def test_cli_refuses_with_exit_code_2(film, tmp_path):
    r = subprocess.run([sys.executable, "-m", "studio.engine.render", str(film), "--out", str(tmp_path / "o"),
                        "--res", "720", "--from", "S99", "--workers", "1"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "refused" in r.stderr


# --------------------------------------------------------------------------
# sources.json
# --------------------------------------------------------------------------


def test_sources_timeline(rendered, plan):
    doc = json.loads(Path(rendered["sources"]).read_text(encoding="utf-8"))
    shots = doc["shots"]
    assert [s["id"] for s in shots] == [f"S{i}" for i in range(1, 10)]
    assert shots[0]["start_s"] == 0 and shots[-1]["end_s"] == doc["duration_s"] == 24.75
    assert all(a["end_s"] == b["start_s"] for a, b in zip(shots, shots[1:]))
    by = {s["id"]: s for s in shots}
    assert by["S3"]["mark"] == {"class": "DRAWN", "detail": "from PIL test image, test fixture",
                                "label": "Drawn · from PIL test image, test fixture"}
    assert by["S3"]["ledger_id"] == "FX-STILL-A" and by["S3"]["licence"] == "CC0" and by["S3"]["credit"]
    assert by["S3"]["test_fixture"] is True
    assert by["S4"]["licence"] == "CC0" and by["S4"]["transition_in"] == {"type": "dissolve", "s": 0.75}
    assert by["S6"]["mark"]["class"] == "DRAWN" and by["S6"]["test_fixture"] is True
    assert by["S6"]["conform"]["method"] == "drop" and by["S6"]["resampler"]["method"].startswith("lanczos")
    assert by["S1"]["mark"]["class"] == "CARD"
    assert abs(sum(doc["share"].values()) - 1) < 1e-3 and doc["share"]["AI-GENERATED"] == 0
    assert doc["marks"][0]["from_s"] == 0 and doc["marks"][-1]["to_s"] == 24.75
    assert doc["readings"][0]["credit"] == "Read by a computer voice. No recording of Fixture speaker was used."
    # The site's balance ("Whose words, and how long") needs each reading's length and whose words they are.
    assert doc["readings"][0]["gender"] == "f"
    assert doc["readings"][0]["dur_s"] == pytest.approx(1.2, abs=0.01)
    heads = [c["heading"] for c in doc["credits"]]
    assert heads[0] == "Shots" and "Readings" in heads


# --------------------------------------------------------------------------
# Overlays and the kit
# --------------------------------------------------------------------------


def test_lower_third_at_its_times_and_watermark_off_on_cards(plan):
    W, H = plan["W"], plan["H"]
    L = M.Layout(W, H)
    pics = R.Pictures(plan)
    try:
        def at(t):
            f = int(round(t * 24))
            i = max(k for k, s in enumerate(plan["shots"]) if s["f0"] <= f)
            return np.asarray(R.compose(plan, pics, f, i)).astype(int)
        lt_box = (int(L.h(80)), int(L.h(92)), int(L.w(4)), int(L.w(30)))
        with_lt, without = at(10.0), at(13.5)          # T1 runs 8.0 to 13.0 over S4 and S5
        # the rule and name are near-white text over the wash
        assert with_lt[lt_box[0]:lt_box[1], lt_box[2]:lt_box[3]].max() > 200
        wm = (int(L.h(5)), int(L.h(11)), int(W - L.w(4) - L.px(6)), int(W - L.w(4)))
        card = at(1.5)
        assert np.max(np.abs(card[wm[0]:wm[1], wm[2]:wm[3]] - np.array(M.PALETTE["black"]))) <= 2
        image = at(16.0)
        # A16: the watermark is quieter (bone at 36%, was 60%), still there over imagery
        assert 60 < image[wm[0]:wm[1], wm[2]:wm[3]].max() < 120
    finally:
        pics.close()
    assert without is not None


def test_subtitles_burn_only_behind_the_flag(film, plan):
    j = J.Journal(film="subs")
    burned = R.build_plan(film, W=plan["W"], H=plan["H"], burn_subtitles=True, journal=j)
    assert plan["subtitles"] == [] and len(burned["subtitles"]) == 4
    f = int(6.0 * 24)
    a, b = R.render_frame(plan, f).astype(int), R.render_frame(burned, f).astype(int)
    H = plan["H"]
    assert np.abs(a[int(0.8 * H):int(0.95 * H)] - b[int(0.8 * H):int(0.95 * H)]).max() > 50
    assert np.array_equal(a[: int(0.5 * H)], b[: int(0.5 * H)])


def test_brand_kit_reexports_the_engine_motion():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kit_motion", ROOT / "design" / "brand-kit" / "motion.py")
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    for name in ("rostrum_move", "lower_third_frame", "mark_plate_frame", "chapter_card_frame", "silent_card_frame",
                 "title_card_frame", "credits_frame", "watermark", "Spring", "PALETTE"):
        assert getattr(kit, name) is getattr(M, name), name
    r = subprocess.run([sys.executable, str(ROOT / "design" / "brand-kit" / "motion.py"), "--table"], capture_output=True, text=True)
    assert r.returncode == 0 and "| `stamp` |" in r.stdout


def test_fixture_commits_no_media():
    """R-08: the fixture's stills, clip and audio are generated at test time."""
    fixture = ROOT / "studio" / "tests" / "fixture"
    tracked = subprocess.run(["git", "ls-files", "--", str(fixture)], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked, "the fixture's text files are tracked"
    assert {Path(f).suffix for f in tracked} <= {".json", ".py"}, tracked
    assert sum((ROOT / f).stat().st_size for f in tracked if (ROOT / f).exists()) <= 1024 * 1024


# --------------------------------------------------------------------------
# Journal order, non-square pixels, low frame rates (verifier round 1)
# --------------------------------------------------------------------------


def test_run_start_is_the_first_event_and_run_end_the_last(rendered):
    evs = events(rendered)
    assert evs[0]["seq"] == 1 and evs[0]["lens"] == "run.start"
    s = evs[0]["settings"]
    assert s["height"] == HEIGHT and s["fps"] == 24 and s["workers"] == WORKERS and s["min_free_gb"] == 1
    assert evs[-1]["lens"] == "run.end" and evs[-1]["seq"] == len(evs)
    assert [e.get("lens") for e in evs].count("run.start") == 1
    plan_ev = [e for e in evs if e.get("lens") == "run.plan"][0]
    assert len(plan_ev["units"]) == 9 and plan_ev["duration_s"] == 24.75


def test_a_refused_run_also_starts_with_run_start(film, tmp_path):
    j = J.Journal(film="refused-order")
    with pytest.raises(R.Refused):
        R.render(film, tmp_path / "o", height=HEIGHT, workers=1, min_free_gb=1, from_shot="S99", journal=j)
    evs = J.read(j.path)
    assert evs[0]["seq"] == 1 and evs[0]["lens"] == "run.start"
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused"


def _film_with_clip(tmp_path, maker, **ledger):
    """The fixture film with S6 pointed at a clip made by ``maker``."""
    import make_media
    film = make_film(tmp_path / "film")
    getattr(make_media, maker)(film / "footage" / "fx-clip.mp4")
    led = json.loads((film / "footage-ledger.json").read_text(encoding="utf-8"))
    item = dict(led["items"][0], id="FX-CLIP", file="fx-clip.mp4", **ledger)
    led["items"].append(item)
    (film / "footage-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    for s in play["parts"][1]["shots"]:
        if s["id"] == "S6":
            s["asset"] = "FX-CLIP"
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def test_ntsc_sar_8_9_clip_is_pillarboxed_at_4_3_not_3_2(tmp_path):
    film = _film_with_clip(tmp_path, "ntsc_dv", telecined=True, width=720, height=480)
    j = J.Journal(film="ntsc")
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    s = next(x for x in plan["shots"] if x["id"] == "S6")
    pr = s["_video"]["probe"]
    assert (pr["width"], pr["height"]) == (720, 480) and abs(pr["sar"] - 8 / 9) < 1e-6
    assert s["_video"]["fit"] == [480, 360]                     # 4:3, never 540x360 (3:2)
    conf = s["_video"]["conform"]
    assert conf["method"] == "ivtc" and conf["field_order"] == "tff"
    cols = _clip_columns(plan)
    assert cols[0] == 80 and cols[-1] == 559
    ev = [e for e in lints(J.read(j.path), "clip-aspect") if e["unit"] == "S6"][0]
    assert ev["status"] == "pass" and ev["evidence"]["storage"] == [720, 480] and abs(ev["evidence"]["sar"] - 0.8889) < 1e-3


def test_ledger_display_aspect_overrides_the_file(tmp_path):
    film = _film_with_clip(tmp_path, "ntsc_dv", telecined=True, display_aspect="16:9")
    j = J.Journal(film="dar")
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    s = next(x for x in plan["shots"] if x["id"] == "S6")
    assert s["_video"]["fit"] == [640, 360]
    assert s["_video"]["probe"]["dar_from"] == "ledger display_aspect"
    assert [e for e in J.read(j.path) if e["kind"] == "decision" and "display aspect" in e["what"]]
    assert R.parse_aspect("4:3") == R.parse_aspect("4/3") == pytest.approx(4 / 3) and R.parse_aspect("1.85") == 1.85


def test_true_10fps_source_is_repeated_to_24_and_journaled(tmp_path):
    film = _film_with_clip(tmp_path, "slow", telecined=False, fps="10")
    j = J.Journal(film="ten")
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    s = next(x for x in plan["shots"] if x["id"] == "S6")
    conf = s["_video"]["conform"]
    assert conf["method"] == "repeat" and conf["filter"] == "fps=24" and conf["in_fps"] == 10
    evs = J.read(j.path)
    assert [e for e in evs if e["kind"] == "decision" and "frame repeat" in e["what"]]
    assert [e for e in lints(evs, "conform-logged") if e["unit"] == "S6"][0]["evidence"]["method"] == "repeat"
    r = R.VideoReader(s, 0.0)
    frames = []
    while True:
        b = r.proc.stdout.read(r.nbytes)
        if len(b) < r.nbytes:
            break
        frames.append(b)
    r.close()
    assert 72 <= len(frames) <= 74                                # 3 s at 24 (the reader reads 2 spare frames)
    assert 29 <= len(set(frames)) <= 31                           # 10 source frames a second, each repeated


# --------------------------------------------------------------------------
# Review round 2: holds, synthetic stills, grammar lints, text, audio, cache
# --------------------------------------------------------------------------


def _edit_play(film, fn):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _plan(film, name="t"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def test_a_synthetic_still_cannot_be_marked_archive(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S3").update(mark="ARCHIVE"))
    with pytest.raises(R.Refused, match=r"mark-class-valid \(S3\)"):
        _plan(film)
    assert R.is_synthetic({"generator": "x"}) and R.is_synthetic({"test_fixture": True}) and not R.is_synthetic({"id": "S-003"})


def test_a_short_clip_holds_under_2s_and_counts_its_held_frames(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S6").update(in_s=2.5, out_s=5.5))     # the stream ends at 4.004 s
    plan, j = _plan(film, "hold")
    s6 = next(s for s in plan["shots"] if s["id"] == "S6")
    assert s6["_video"]["probe"]["duration_from"] == "video stream"
    hold = [e for e in lints(J.read(j.path), "clip-hold") if e["unit"] == "S6"][0]
    assert hold["severity"] == "warn" and 1.4 < hold["evidence"]["hold_s"] < 1.6
    res = R.render_segment(plan, plan["shots"].index(s6), str(tmp_path / "S6.mp4"))
    assert 30 <= res["held_frames"] <= 40                       # about 1.5 s at 24 fps, counted before close()


def test_a_hold_over_2s_is_refused_unless_re_timed(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S6").update(in_s=3.5, out_s=6.5))
    with pytest.raises(R.Refused, match=r"clip-hold \(S6\)"):
        _plan(film)
    led = json.loads((film / "footage-ledger.json").read_text(encoding="utf-8"))
    real = {k: v for k, v in led["items"][0].items() if k not in ("synthetic", "test_fixture", "generator")}
    led["items"].append(dict(real, id="FX-REAL"))
    (film / "footage-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    _edit_play(film, lambda p: _shot(p, "S6").update(asset="FX-REAL", mark="RECONSTRUCTED", alterations=["re-timed"]))
    plan, j = _plan(film)
    hold = [e for e in lints(J.read(j.path), "clip-hold") if e["unit"] == "S6"][0]
    assert hold["status"] == "pass" and hold["evidence"]["retimed"] is True


def test_a_cross_class_dip_under_12_frames_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S3").update(transition_in={"type": "dip", "s": 0.4}))
    with pytest.raises(R.Refused, match=r"cross-class-dip \(S3\)"):
        _plan(film)


@pytest.mark.parametrize("sid,change", [("S3", {"to": {"z": 1.2}}),                     # PUSH ends at 1.12
                                        ("S5", {"preset": "DETAIL", "to": {"z": 1.4}, "from": {"z": 1.4}})])
def test_a_still_zoom_past_its_preset_is_refused(tmp_path, sid, change):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, sid).update(**change))
    with pytest.raises(R.Refused, match=rf"still-zoom-limit \({sid}\)"):
        _plan(film)


def test_an_undrawn_text_kind_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: p["parts"][1]["text"].append({"id": "TX", "kind": "caption", "start_s": 9, "end_s": 10, "lines": ["x"]}))
    with pytest.raises(R.Refused, match=r"kind-supported \(TX\)"):
        _plan(film)


def test_overlay_is_drawn_bottom_right_and_never_over_a_card(plan, tmp_path):
    assert plan["overlays"] == [{"id": "T2", "start": 15.5, "end": 17.25, "text": "29.97 fps, 4 s"}]
    bare = dict(plan, overlays=[])
    f = int(16.5 * 24)
    a, b = R.render_frame(plan, f).astype(int), R.render_frame(bare, f).astype(int)
    W, H = plan["W"], plan["H"]
    diff = np.abs(a - b).max(axis=2)
    ys, xs = np.nonzero(diff > 30)
    assert len(xs) and xs.min() > W * 0.6 and ys.min() > H * 0.8      # bottom right only
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: p["parts"][1]["text"].append(
        {"id": "T9", "kind": "overlay", "start_s": 18.0, "end_s": 19.0, "lines": ["1947"]}))   # over the silent card
    with pytest.raises(R.Refused, match=r"overlay-format \(T9\)"):
        _plan(film)


def test_a_missing_voice_wav_blocks_unless_draft(plan, tmp_path):
    j = J.Journal(film="draft")
    with pytest.raises(R.Refused, match="voice WAVs missing for L1, L2"):
        R.build_mix(plan, tmp_path, j)                           # no audio folder here
    mix, placed = R.build_mix(plan, tmp_path, j, draft=True)
    assert placed["missing"] == ["L1", "L2", "C1"] and float(np.abs(mix).max()) == 0.0
    sev = {e["unit"]: e["severity"] for e in lints(J.read(j.path), "audio-present")}
    assert sev["L1"] == "warn" and sev["C1"] == "warn"


def test_draft_is_journaled_as_a_human_override(film, tmp_path):
    j = J.Journal(film="draft-run")
    with pytest.raises(R.Refused):
        R.render(film, tmp_path / "o", height=HEIGHT, workers=1, min_free_gb=1, from_shot="S99", draft=True, journal=j)
    evs = J.read(j.path)
    assert evs[0]["settings"]["draft"] is True
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--draft"]


def test_telecine_must_be_declared_for_a_29_97_source(tmp_path):
    film = _film_with_clip(tmp_path, "testsrc", telecined=None)
    with pytest.raises(R.Refused, match=r"telecine-declared \(S6\)"):
        _plan(film)


def test_an_unknown_field_order_blocks_inverse_telecine(tmp_path):
    film = _film_with_clip(tmp_path, "testsrc", telecined=True)    # progressive file: no field order to read
    with pytest.raises(R.Refused, match=r"field-order-known \(S6\)"):
        _plan(film)


def test_the_cache_key_holds_ffmpeg_and_the_fonts(plan):
    tk = R.tools_key()
    assert tk["ffmpeg"].startswith("ffmpeg version") and len(tk["fonts"]) == 7 and all(tk["fonts"].values())
    a = R.shot_key(plan, 2, {}, tk)
    b = R.shot_key(plan, 2, {}, dict(tk, ffmpeg="ffmpeg version 0"))
    c = R.shot_key(plan, 2, {}, dict(tk, fonts=dict(tk["fonts"], display="0" * 16)))
    assert len({a, b, c}) == 3


def test_the_master_does_not_depend_on_workers(film, rendered, tmp_path):
    one = R.render(film, tmp_path / "one", height=HEIGHT, workers=1, min_free_gb=1, encode_preset="veryfast")
    assert J.sha256_file(one["master"]) == J.sha256_file(rendered["master"])


def test_decoders_and_encoders_run_single_threaded(plan):
    s6 = next(s for s in plan["shots"] if s["id"] == "S6")
    r = R.VideoReader(s6, 0.0)
    try:
        args = r.proc.args
    finally:
        r.close()
    assert args[args.index("-threads") + 1] == "1" and args[args.index("-filter_threads") + 1] == "1"
    enc = R.encoder_cmd(plan, Path("x.mp4"))
    assert enc[enc.index("-threads") + 1] == "1" and enc[enc.index("-filter_threads") + 1] == "1"


def test_a_failed_segment_leaves_no_partial_file(plan, tmp_path, monkeypatch):
    bad = [R.ffmpeg(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "640x360", "-i", "-",
           "-c:v", "no-such-codec", "-f", "mp4"]
    monkeypatch.setattr(R, "encoder_cmd", lambda plan, out: bad + [str(out)])
    seg = tmp_path / "S1.mp4"
    with pytest.raises(R.EncodeError):
        R.render_segment(plan, 0, str(seg))
    assert not list(tmp_path.iterdir())


def test_ducking_average_matches_a_convolution():
    rng = np.random.default_rng(1)
    x = (rng.random(5000) > 0.7).astype(np.float32)
    for k in (1, 4, 25, 250):
        ref = np.convolve(x, np.ones(k) / k, mode="same") if k > 1 else x
        got = R.moving_average(x, k)
        assert got.shape == x.shape
        assert np.allclose(got[k:-k] if k > 1 else got, ref[k:-k] if k > 1 else ref, atol=1e-5)


def test_segments_mix_and_master_are_artifacts_with_hashes(rendered):
    arts = [e for e in events(rendered) if e["kind"] == "artifact"]
    roles = [e["role"] for e in arts]
    assert roles.count("segment") == 9 and {"mix", "mix-normalised", "master", "sources"} <= set(roles)
    assert all(len(e["sha256"]) == 64 for e in arts)


# --------------------------------------------------------------------------
# Founder rulings 2026-10-10: black is black; voices never overlap
# --------------------------------------------------------------------------


def _at(plan, t):
    f = int(round(t * 24))
    return f, R.render_frame(plan, f).astype(int)


def test_black_under_a_voice_is_all_zero_outside_the_mark(plan):
    s8 = next(s for s in plan["shots"] if s["id"] == "S8" and s["kind"] == "black")
    f, arr = _at(plan, (s8["f0"] + s8["f1"]) / 2 / 24)
    L = M.Layout(plan["W"], plan["H"])
    x0, y0 = M.glyph_origin(L)
    d, ring = M.glyph_px(L), max(1, L.px(M.LABEL["halo"]))
    mask = np.ones(arr.shape[:2], bool)
    mask[y0 - ring:y0 + d + ring, x0 - ring:x0 + d + ring] = False
    assert arr[~mask].any(), "the CARD mark is still drawn"
    assert not arr[mask].any(), "every pixel outside the mark is 0,0,0"


def test_pillarbox_bars_are_exactly_zero(plan):
    W, H = plan["W"], plan["H"]
    for t in (15.2, 13.0):                                         # the 4:3 clip; the portrait still (S5)
        f, arr = _at(plan, t)
        band = arr[int(0.2 * H):int(0.8 * H)]
        if t == 15.2:
            lo, hi = 80, 560
        else:
            cols = _image_columns(arr, (int(0.2 * H), int(0.8 * H)))
            lo, hi = int(cols[0]), int(cols[-1]) + 1
        assert lo > 0 and hi < W and not band[:, :lo].any() and not band[:, hi:].any(), t


@pytest.mark.parametrize("sid", ["S2", "S3", "S6", "S7"])
def test_a_dips_middle_frame_is_all_zero(plan, sid):
    s = next(x for x in plan["shots"] if x["id"] == sid)
    assert s["transition_in"]["type"] == "dip"
    i = plan["shots"].index(s)
    assert R.picture_level(plan, s["f0"], i) == 0.0
    assert not R.render_frame(plan, s["f0"]).any()            # mark plate, watermark and lower third off too


def test_black_is_limited_range_y16_in_the_master(rendered):
    master = rendered["master"]
    tags = json.loads(subprocess.run([R.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                      "stream=color_range,color_space", "-of", "json", master],
                                     capture_output=True, text=True).stdout)["streams"][0]
    assert tags == {"color_range": "tv", "color_space": "bt709"}
    W, H = R.frame_size(HEIGHT)
    raw = subprocess.run([R.ffmpeg(), "-v", "error", "-ss", "21.0", "-i", master, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "yuv420p", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw[: W * H], np.uint8).reshape(H, W)
    u = np.frombuffer(raw[W * H: W * H + W * H // 4], np.uint8)
    body = y[int(0.3 * H):, :]                                  # below the CARD mark
    assert body.min() >= 15 and body.max() <= 17 and abs(float(body.mean()) - 16) < 0.2
    assert abs(float(u.mean()) - 128) < 1.0


def _with_voices(tmp_path):
    """The fixture film plus two narration lines that collide: L3 overlaps L1
    by 1.0 s, L4 overlaps L2 by 0.5 s."""
    from conftest import tone
    film = make_film(tmp_path / "film")
    tone(film / "audio" / "L3.wav", 2.0, 550.0)
    tone(film / "audio" / "L4.wav", 1.0, 660.0)

    def add(p):
        p["parts"][1]["lines"] += [{"id": "L3", "kind": "narration", "start_s": 6.0, "text": "A second test tone.", "sources": []},
                                   {"id": "L4", "kind": "narration", "start_s": 21.0, "text": "A third test tone.", "sources": []}]
        # each new line's caption starts 2 frames before its words, as captions often do
        p["subtitle_source"] += [{"ref": "L3", "start_s": round(6.0 - 2 / 24, 4), "end_s": 7.9, "en": "A second test tone."},
                                 {"ref": "L4", "start_s": round(21.0 - 2 / 24, 4), "end_s": 22.0, "en": "A third test tone."}]
    _edit_play(film, add)
    return film


def test_overlapping_voices_are_refused_with_every_collision(tmp_path):
    film = _with_voices(tmp_path)
    j = J.Journal(film="overlap")
    with pytest.raises(R.Refused, match="voice-overlap"):
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    ev = lints(J.read(j.path), "voice-overlap")[0]
    assert ev["status"] == "fail" and ev["severity"] == "block"
    got = {(c["a"], c["b"]): c for c in ev["evidence"]["collisions"]}
    assert set(got) == {("L1", "L3"), ("L2", "L4")}
    assert got[("L1", "L3")]["overlap_s"] == pytest.approx(1.0, abs=0.01)
    assert got[("L2", "L4")]["overlap_s"] == pytest.approx(0.5, abs=0.01)


def test_voices_closer_than_0_8_s_collide_without_overlapping():
    lines = [{"id": "A", "start": 0.0, "dur": 2.0}, {"id": "B", "start": 2.5, "dur": 1.0}, {"id": "C", "start": 4.3, "dur": 1.0}]
    assert R.voice_collisions(lines) == [{"a": "A", "b": "B", "overlap_s": 0.0, "gap_s": 0.5, "short_by_s": 0.3}]


def test_fit_voices_moves_lines_and_grows_their_shots(tmp_path):
    film = _with_voices(tmp_path)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    j = J.Journal(film="fit")
    fitted = R.fit_voices(play, film, j)
    sh = {s["id"]: s for p in fitted["parts"] for s in p["shots"]}
    ln = {x["id"]: x for p in fitted["parts"] for x in p["lines"]}
    assert ln["L1"]["start_s"] == 5.0                                # before the first insertion: untouched
    assert ln["L3"]["start_s"] == pytest.approx(7.8)                 # L1 ends at 7.0, plus 0.8
    assert sh["S3"]["dur_s"] == pytest.approx(5.8) and sh["S4"]["start_s"] == pytest.approx(9.55)
    assert ln["L2"]["start_s"] == pytest.approx(22.1)                # moved with the timeline
    assert ln["L4"]["start_s"] == pytest.approx(24.1)                # L2 ends 23.3, plus 0.8
    assert sh["S8"]["dur_s"] == pytest.approx(1.5 + 1.3)
    assert R.voice_collisions(R.voice_lines(fitted, film)) == []
    decisions = [e for e in J.read(j.path) if e["kind"] == "decision"]
    assert [d["unit"] for d in decisions] == ["L3", "L4"] and [d["shot"] for d in decisions] == ["S3", "S8"]
    assert play["parts"][1]["lines"][2]["start_s"] == 6.0             # the original is untouched

    # subtitle cues follow their own line by exactly its shift and never stretch
    before = {c["ref"]: (c["start_s"], c["end_s"]) for c in play["subtitle_source"]}
    after = {c["ref"]: (c["start_s"], c["end_s"]) for c in fitted["subtitle_source"]}
    line_shift = {k: ln[k]["start_s"] - x["start_s"] for k, x in
                  ((x["id"], x) for p in play["parts"] for x in p["lines"])}
    assert after["L1"] == before["L1"] == (5.0, 7.5)                 # L1 never moved, so neither does its cue
    for ref, (a0, a1) in after.items():
        b0, b1 = before[ref]
        assert a1 - a0 == pytest.approx(b1 - b0), ref                 # never stretched
        if ref in line_shift:
            assert a0 - b0 == pytest.approx(line_shift[ref]), ref     # moved exactly with its words
    assert after["L3"][0] == pytest.approx(6.0 - 2 / 24 + 1.8, abs=1e-4)  # starts 2 frames before L3, still
    assert after["L4"][0] == pytest.approx(21.0 - 2 / 24 + 3.1, abs=1e-4)
    cues = sorted(after.values())
    assert all(b[0] >= a[1] for a, b in zip(cues, cues[1:])), cues    # no two cues overlap
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=True, journal=j, play=fitted)
    assert plan["frames"] == round((24.75 + 1.8 + 1.3) * 24)
    evs = J.read(j.path)
    assert lints(evs, "voice-overlap")[-1]["status"] == "pass"
    assert lints(evs, "subtitle-overlap")[-1]["status"] == "pass" and lints(evs, "subtitle-overlap")[-1]["severity"] == "block"


def test_a_fit_voices_render_with_burned_subtitles(tmp_path):
    film = _with_voices(tmp_path)
    s = R.render(film, tmp_path / "out", height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast",
                 fit_voices_opt=True, burn_subtitles=True)
    frames = round((24.75 + 1.8 + 1.3) * 24)
    assert s["frames"] == frames and R.count_frames(Path(s["master"])) == frames
    evs = events(s)
    assert evs[-1]["outcome"] == "ok"
    assert lints(evs, "voice-overlap")[0]["status"] == "pass" and lints(evs, "subtitle-overlap")[0]["status"] == "pass"
    assert [e["unit"] for e in evs if e["kind"] == "decision" and "voice-overlap" in e["why"]] == ["L3", "L4"]
    doc = json.loads(Path(s["sources"]).read_text(encoding="utf-8"))
    assert doc["duration_s"] == pytest.approx(frames / 24, abs=1e-3)
    fitted = json.loads((tmp_path / "out" / "screenplay.fitted.json").read_text(encoding="utf-8"))
    assert {c["ref"]: c["start_s"] for c in fitted["subtitle_source"]}["L1"] == 5.0


def test_fit_voices_inside_a_clip_with_no_out_point(tmp_path):
    """A video shot given dur_s but no out_s: fit_voices derives the out point
    the way build_plan does instead of failing on it."""
    from conftest import tone
    film = make_film(tmp_path / "film")
    tone(film / "audio" / "L5.wav", 1.0, 500.0)
    tone(film / "audio" / "L6.wav", 0.5, 600.0)

    def edit(p):
        s6 = _shot(p, "S6")
        s6.pop("out_s")
        s6["dur_s"] = 3.0
        p["parts"][1]["lines"] += [{"id": "L5", "kind": "narration", "start_s": 15.0, "text": "x", "sources": []},
                                   {"id": "L6", "kind": "narration", "start_s": 15.5, "text": "y", "sources": []}]
    _edit_play(film, edit)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fitted = R.fit_voices(play, film, J.Journal(film="noout"))
    s6 = _shot(fitted, "S6")
    assert s6["in_s"] == 0.5 and s6["out_s"] == pytest.approx(0.5 + 3.0 + 1.3)     # L5 ends 16.0, L6 to 16.8


def test_a_render_with_fit_voices_journals_and_saves_the_fitted_screenplay(tmp_path):
    film = _with_voices(tmp_path)
    j = J.Journal(film="fit-run")
    with pytest.raises(R.Refused):                                    # stop after the plan: no such shot
        R.render(film, tmp_path / "o", height=HEIGHT, workers=1, min_free_gb=1, from_shot="S99", fit_voices_opt=True, journal=j)
    evs = J.read(j.path)
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--fit-voices"]
    assert [e for e in evs if e["kind"] == "artifact" and e["role"] == "screenplay-fitted"]
    assert lints(evs, "voice-overlap")[0]["status"] == "pass"
    assert json.loads((tmp_path / "o" / "screenplay.fitted.json").read_text(encoding="utf-8"))["parts"][1]["lines"][2]["start_s"] == 7.8


# --------------------------------------------------------------------------
# Re-review: probe the crossfade, synthetic by generator, linear loudness, long dips
# --------------------------------------------------------------------------


def test_a_crossfade_frame_off_the_hue_line_fails(plan):
    i = next(k for k, s in enumerate(plan["shots"]) if s["id"] == "S3")      # CARD (S2) into DRAWN (S3)
    f = plan["shots"][i]["f0"] + 1
    arr = R.render_frame(plan, f)
    assert R.check_mark(plan, arr, f, i) == "fade"
    x, y = R.mark_probe(plan)
    bad = arr.copy()
    bad[y, x] = (200, 0, 0)
    assert R.check_mark(plan, bad, f, i) == "fail"
    assert R.between_hues((126, 129, 138), (0, 0, 0), (255, 255, 255), tol=3) is False


def test_sources_marks_an_item_with_only_a_generator_as_a_test_fixture(tmp_path):
    film = make_film(tmp_path / "film")
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    for it in led["items"]:
        it.pop("synthetic"), it.pop("test_fixture")
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    plan, j = _plan(film)
    doc = R.sources_doc(plan, j, {})
    assert {s["id"]: s["test_fixture"] for s in doc["shots"] if s["id"] in ("S3", "S4", "S5")} == {"S3": True, "S4": True, "S5": True}


def _wav(path, x):
    import soundfile as sf
    sf.write(str(path), np.asarray(x, dtype="float32"), 48000, subtype="FLOAT")
    return path


def _tone(seconds, amp, hz=300.0):
    t = np.arange(int(48000 * seconds)) / 48000
    return amp * np.sin(2 * np.pi * hz * t)


def test_a_high_lra_mix_comes_out_linear(tmp_path):
    x = _tone(20, 0.04)                                               # 10 s quiet, then 10 s about 17 dB louder
    x[48000 * 10:] *= 7.0
    loud = R.loudnorm(_wav(tmp_path / "mix.wav", x), tmp_path / "norm.wav")
    assert loud["input_lra"] > R.TARGET_LRA                         # the old fixed LRA 11 made loudnorm go dynamic
    assert loud["limiter"] is None and loud["lra_target"] > loud["input_lra"]
    assert loud["normalization_type"] == "linear" and loud["linear"] and not loud["blockers"]
    assert abs(loud["output_i"] - R.TARGET_LUFS) <= 0.5 and loud["output_tp"] <= R.TARGET_TP
    j = J.Journal(film="lra")
    assert R.loudness_lints(j, loud) == []
    evs = J.read(j.path)
    flag = lints(evs, "loudnorm-linear")[0]
    assert flag["status"] == "pass" and flag["severity"] == "block" and flag["phase"] == "preflight"
    assert flag["evidence"]["input_lra"] == loud["input_lra"] and flag["evidence"]["lra_target"] == loud["lra_target"]
    raised = [e for e in evs if e["kind"] == "decision" and "LRA target raised" in e["what"]]
    assert raised and raised[0]["evidence"]["input_lra"] == loud["input_lra"]


def test_a_peaky_well_levelled_mix_passes_with_only_peak_limiting(tmp_path):
    x = _tone(12, 0.172)                                              # about -19 LUFS, so the gain to -18 (A15) is about 1 dB
    x += np.random.default_rng(3).normal(0, 0.01, len(x))            # a little noise, so only lag 0 lines up (the tone repeats every 160)
    for at in (4.0, 8.0):                                             # two 3 ms peaks just over the ceiling after the gain
        i = int(at * 48000)
        x[i:i + 144] += 0.64 * np.sin(np.linspace(0, np.pi, 144))
    loud = R.loudnorm(_wav(tmp_path / "mix.wav", x), tmp_path / "norm.wav")
    assert loud["predicted_tp"] > R.TARGET_TP
    lim = loud["limiter"]
    assert lim and lim["oversample"] == 4 and Path(lim["file"]).exists()
    assert 0.1 < lim["max_reduction_db"] <= R.LIMIT_MAX_DB and lim["over_1db_s"] <= R.LIMIT_OVER_1DB_S
    assert lim["lra_drop"] <= R.LIMIT_LRA_DROP
    assert {round(a["at_s"]) for a in lim["acted"]} == {4, 8}           # it acted at the two peaks and nowhere else
    a0 = lim["attempts"][0]
    assert a0["pre_gain_db"] == lim["pre_gain_db"] == loud["gain_db"] and a0["ceiling_dbtp"] == R.TARGET_TP - R.LIMIT_MARGIN_DB
    assert loud["normalization_type"] == "linear" and loud["output_tp"] <= R.TARGET_TP
    import soundfile as sf
    y, _ = sf.read(str(tmp_path / "norm.wav"))
    assert len(y) == len(x)
    # the limiter's look-ahead delay is compensated: the output lines up with the input sample for sample
    seg = slice(48000, 48000 * 3)                                     # a stretch the limiter never touched
    lags = range(-300, 301)
    corr = [float(np.dot(x[seg], np.roll(y, -lag)[seg])) for lag in lags]
    assert lags[int(np.argmax(corr))] == 0
    scale = 10 ** ((R.TARGET_LUFS - loud["input_i"]) / 20)
    assert np.max(np.abs(y[seg] - x[seg] * scale)) < 0.02             # and is the input times one linear gain
    j = J.Journal(film="peaky")
    assert R.loudness_lints(j, loud) == []
    evs = J.read(j.path)
    dec = [e for e in evs if e["kind"] == "decision" and "true-peak limiter" in e["what"]]
    assert dec and f"{loud['input_tp']:.2f} dBTP" in dec[0]["why"] and dec[0]["evidence"]["attempts"]
    peak = lints(evs, "limiter-peak-only")[0]
    assert peak["status"] == "pass" and peak["severity"] == "block" and len(peak["evidence"]["acted"]) == 2


def test_a_sustained_loud_passage_refuses(tmp_path):
    x = _tone(30, 0.068)                                              # 30 s at -27 LUFS, the last second under dense peaks:
    for at in np.arange(29.0, 30.0, 0.005):                           # at -18 LUFS (A15) a steady louder tone no longer
        i = int(at * 48000)                                           # reaches the ceiling, so the passage is a pulse train
        x[i:i + 48] += 0.6 * np.sin(np.linspace(0, np.pi, 48))
    loud = R.loudnorm(_wav(tmp_path / "mix.wav", x), tmp_path / "norm.wav")
    lim = loud["limiter"]
    assert lim and lim["over_1db_s"] > 0.5 and lim["max_at_s"] >= 29.0
    j = J.Journal(film="sustained")
    refusals = R.loudness_lints(j, loud)
    assert any("compressed the programme" in r for r in refusals)
    peak = lints(J.read(j.path), "limiter-peak-only")[0]
    assert peak["status"] == "fail" and peak["severity"] == "block" and peak["evidence"]["result"] == "refused"
    assert any("1 dB of gain reduction" in o for o in peak["evidence"]["over"])
    assert R.loudness_lints(J.Journal(film="sustained-draft"), loud, draft=True) == []


def test_a_failed_loudness_measurement_raises(tmp_path):
    (tmp_path / "bad.wav").write_bytes(b"not a wav")
    with pytest.raises(R.EncodeError, match="loudness measurement failed"):
        R.loudnorm(tmp_path / "bad.wav", tmp_path / "norm.wav")
    loud = R.loudnorm(_wav(tmp_path / "silent.wav", np.zeros(48000 * 2)), tmp_path / "norm.wav")
    assert loud["normalised"] is False and loud["reason"] == "silent programme"


def test_voice_lines_and_music_are_levelled_before_mixing(plan, film):
    j = J.Journal(film="level")
    mix, placed = R.build_mix(plan, film, j)
    lv = {e["unit"]: e for e in J.read(j.path) if e["kind"] == "decision" and "levelled to" in e["what"]}
    assert set(lv) == {"L1", "L2"}                                    # C1 (ambience) is missing and never levelled
    for ln in placed["lines"]:
        ev = lv[ln["id"]]["evidence"]
        assert ev["target"] == R.DIALOGUE_LUFS and abs(ev["measured_i"] + ev["gain_db"] - R.DIALOGUE_LUFS) < 0.01
        assert ln["level_db"] == ev["gain_db"]
        x = mix[int(ln["at_s"] * 48000): int((ln["at_s"] + ln["dur_s"]) * 48000)]
        assert abs(R._measure(x)["input_i"] - R.DIALOGUE_LUFS) < 0.6


def test_archival_audio_is_never_levelled(plan, film):
    arch = json.loads(json.dumps(plan))
    k = next(n for n, ln in enumerate(arch["lines"]) if ln.get("kind") == "testimony")
    arch["lines"][k]["archival_audio"] = True
    j = J.Journal(film="archival")
    _, placed = R.build_mix(arch, film, j)
    first = next(ln for ln in placed["lines"] if ln["id"] == arch["lines"][k]["id"])
    assert first["kind"] == "archival" and first["level_db"] is None
    assert first["id"] not in {e["unit"] for e in J.read(j.path) if e["kind"] == "decision"}


def test_audio_only_runs_the_preflight_and_the_sound_without_frames(film, tmp_path):
    j = J.Journal(film="audio-only")
    out = tmp_path / "out"
    s = R.render(film, out, height=HEIGHT, workers=1, min_free_gb=1, audio_only=True, journal=j)
    evs = J.read(j.path)
    assert s["frames"] == 0 and Path(s["mix"]).exists() and s["loudness"]["linear"]
    assert not [e for e in evs if e.get("lens") == "frame"] and not (out / "master.mp4").exists()
    assert evs[0]["settings"]["audio_only"] is True and evs[-1]["outcome"] == "ok" and evs[-1]["audio_only"] is True
    assert lints(evs, "loudnorm-linear")[0]["status"] == "pass"
    assert lints(evs, "still-first-frame-whole-pixels")                 # the pre-flight ran in full


def _levelled(x):
    g, _ = R.level_gain(x, R.DIALOGUE_LUFS)
    return x * 10 ** (g / 20)


def _voice(seconds=3.0, amp=0.05):
    return amp * np.sin(2 * np.pi * 220 * np.arange(int(48000 * seconds)) / 48000)


def test_a13_a_peaky_voice_line_is_peak_controlled(tmp_path):
    x = _voice()
    for at in (0.8, 2.1):                                             # two plosive-like peaks over the -4.8 dBTP voice ceiling (A15)
        i = int(at * 48000)
        x[i:i + 96] += 0.25 * np.sin(np.linspace(0, np.pi, 96))
    y, peak = R.voice_peak_control(_levelled(x))
    assert peak and not peak["bad_take"] and peak["tp_before"] > R.VOICE_TP
    assert peak["tp_after"] <= R.VOICE_TP + 0.2 and 0.1 < peak["max_reduction_db"] <= 8.0 and not peak["bad_take"]
    assert len(y) == len(x)
    quiet, quiet_peak = R.voice_peak_control(_levelled(_voice()))   # a steady line under the ceiling is left alone
    assert quiet_peak is None


def _no_a19_verdict(monkeypatch):
    """These A13 lines (a steady buzz, a 0.25 s burst, all zeros) have no
    pause, so A19's voice-clean would refuse them before A13 is reached; the
    tests are about A13, so the cleanup's verdict is set aside."""
    monkeypatch.setattr(R, "_journal_clean", lambda *a, **k: [])


def test_a13_a_single_click_is_peak_control_not_a_bad_take(tmp_path, monkeypatch):
    _no_a19_verdict(monkeypatch)
    x = _voice()
    x[48000] += 1.0                                                   # one click far over the line's own level
    x[48001] -= 1.0
    _, peak = R.voice_peak_control(_levelled(x))
    assert peak["max_reduction_db"] > 8.0                             # cut deep, but only for a few ms
    assert 0 < peak["over_8db_s"] <= R.VOICE_OVER_8DB_MAX_S and not peak["bad_take"]
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L1.wav", x)
    plan, _ = _plan(film)
    j = J.Journal(film="click")
    _, placed = R.build_mix(plan, film, j)
    evs = J.read(j.path)
    lint = [e for e in lints(evs, "voice-peak-control") if e["unit"] == "L1"][0]
    assert lint["status"] == "pass" and lint["severity"] == "block"
    assert {"over_8db_s", "over_3db_s", "over_1db_s"} <= set(lint["evidence"])
    dec = [e for e in evs if e["kind"] == "decision" and e["unit"] == "L1" and "peak-controlled" in e["what"]][0]
    assert "over 8 dB" in dec["what"] and "over 3 dB" in dec["what"] and "over 1 dB" in dec["what"]


def test_a13_a_sustained_10_db_cut_is_a_bad_take(tmp_path):
    x = _voice(3.0)
    for s in np.arange(1.0, 1.3, 0.005):                              # 300 ms of peaks every 5 ms: the limiter holds over 10 dB
        i = int(s * 48000)
        x[i:i + 4] += 1.0 * np.sin(np.linspace(0, np.pi, 4))
    _, peak = R.voice_peak_control(_levelled(x))
    assert peak["over_8db_s"] > R.VOICE_OVER_8DB_MAX_S and peak["max_reduction_db"] >= 10.0
    assert any("over 8 dB for" in b for b in peak["bad_take"])
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L1.wav", x)
    plan, _ = _plan(film)
    j = J.Journal(film="bad-take")
    with pytest.raises(R.Refused, match=r"voice-peak-control \(A13\).*L1 \(.*over 8 dB for"):
        R.build_mix(plan, film, j)
    lint = [e for e in lints(J.read(j.path), "voice-peak-control") if e["unit"] == "L1"][0]
    assert lint["status"] == "fail" and lint["severity"] == "block" and lint["evidence"]["result"] == "refused: re-render the take"
    jd = J.Journal(film="bad-take-draft")
    _, placed = R.build_mix(plan, film, jd, draft=True)               # a draft keeps the take, with a warning
    assert [ln["peak_reduction_db"] for ln in placed["lines"] if ln["id"] == "L1"][0] >= 10.0
    assert [e for e in lints(J.read(jd.path), "voice-peak-control") if e["unit"] == "L1"][0]["severity"] == "warn"


def test_a13_a_line_over_1_db_for_a_quarter_of_it_is_a_bad_take(tmp_path):
    x = _voice(4.0, 0.02)
    for s in np.arange(0, 1.5, 0.02):                                 # mild peaks every 20 ms through the first 1.5 s
        i = int(s * 48000)
        x[i:i + 48] += 0.1 * np.sin(np.linspace(0, np.pi, 48))
    _, peak = R.voice_peak_control(_levelled(x))
    assert peak["over_1db_share"] >= 0.25 and peak["over_8db_s"] == 0
    assert peak["over_3db_share"] <= R.VOICE_OVER_3DB_MAX_SHARE and len(peak["bad_take"]) == 1    # only the 1 dB bound fails
    assert any("over 1 dB for" in b and "limit 20%" in b for b in peak["bad_take"])
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L2.wav", x)
    plan, _ = _plan(film)
    with pytest.raises(R.Refused, match=r"voice-peak-control \(A13\).*L2 \(.*over 1 dB for"):
        R.build_mix(plan, film, J.Journal(film="crushed"))


def test_a13_archival_audio_is_never_peak_controlled(plan, film):
    arch = json.loads(json.dumps(plan))
    for ln in arch["lines"]:
        ln["archival_audio"] = True
    j = J.Journal(film="archival-peaks")
    _, placed = R.build_mix(arch, film, j)
    assert all(ln["peak_reduction_db"] is None and ln["level_db"] is None for ln in placed["lines"])
    assert not lints(J.read(j.path), "voice-peak-control")


def _dynamic(real):
    def fake(src, dst):
        loud = real(src, dst)
        return dict(loud, normalization_type="dynamic", linear=False, blockers=["forced by the test"])
    return fake


def test_a_dynamic_loudness_result_blocks_before_any_frame(tmp_path, monkeypatch):
    film = make_film(tmp_path / "film")
    monkeypatch.setattr(R, "loudnorm", _dynamic(R.loudnorm))
    j = J.Journal(film="dynamic")
    with pytest.raises(R.Refused, match=r"loudness \(pre-flight\).*forced by the test"):
        R.render(film, tmp_path / "out", height=HEIGHT, workers=1, min_free_gb=1, journal=j)
    evs = J.read(j.path)
    assert not [e for e in evs if e.get("lens") == "frame"]
    assert not [e for e in evs if e.get("lens") == "unit.start" and e["stage"] == "motion"]
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused"
    flag = lints(evs, "loudnorm-linear")[0]
    assert flag["status"] == "fail" and flag["severity"] == "block" and flag["phase"] == "preflight"
    assert flag["evidence"]["result"] == "refused" and "input_lra" in flag["evidence"] and "input_tp" in flag["evidence"]


def test_a_dynamic_loudness_result_is_only_a_warning_under_draft(tmp_path):
    loud = R.loudnorm(_wav(tmp_path / "mix.wav", _tone(4, 0.1)), tmp_path / "norm.wav")
    loud = dict(loud, normalization_type="dynamic", linear=False, blockers=["forced by the test"])
    j = J.Journal(film="dynamic-draft")
    assert R.loudness_lints(j, loud, draft=True) == []
    assert R.loudness_lints(J.Journal(film="dynamic-final"), loud)
    evs = J.read(j.path)
    flag = lints(evs, "loudnorm-linear")[0]
    assert flag["status"] == "fail" and flag["severity"] == "warn" and flag["evidence"]["result"] == "dynamic (draft)"
    assert "forced by the test" in flag["evidence"]["why"]
    assert [e for e in evs if e["kind"] == "decision" and "dynamic" in e["what"]]


def test_a_dip_longer_than_a_second_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S3").update(transition_in={"type": "dip", "s": 1.2}))
    with pytest.raises(R.Refused, match=r"dip-length \(S3\)"):
        _plan(film)


# --------------------------------------------------------------------------
# Trailer: false A7 refusal on a dense still; plan checks before any frame
# --------------------------------------------------------------------------


def _dense_still(path, w=3551, h=2037):
    """A photograph-like test image: low-frequency structure with dense
    high-frequency detail on top, the size of the trailer's S21 scan."""
    from PIL import Image
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([60 + 120 * xx / w, 50 + 110 * yy / h, 90 + 60 * np.sin(xx / 300.0) * np.cos(yy / 200.0)], axis=2)
    base[h // 4:h // 2, w // 5:w // 2] += 50
    img = np.clip(base + rng.normal(0, 40, (h, w, 3)), 0, 255).astype(np.uint8)
    Image.fromarray(img).save(path)


def _dense_film(tmp_path):
    film = make_film(tmp_path / "film")
    _dense_still(film / "stills" / "FX-STILL-B.png")             # S4, which enters by a dissolve from S3
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][1].update(width=3551, height=2037)
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    return film


def test_a_dense_still_entering_by_dissolve_passes_a7_on_its_own_layer(tmp_path):
    film = _dense_film(tmp_path)
    j = J.Journal(film="dense")
    plan = R.build_plan(film, W=1920, H=1080, burn_subtitles=False, journal=j)
    i = [s["id"] for s in plan["shots"]].index("S4")
    s4 = plan["shots"][i]
    assert s4["transition_in"]["type"] == "dissolve" and plan["shots"][i - 1]["mark"] == s4["mark"]
    pics = R.Pictures(plan)
    try:
        ev = {}
        assert R.still_first_frame_whole(plan, pics, i, ev), ev          # the old check failed this at 1080p
        own = np.asarray(pics.shot(i, 0.0)).astype(int)
        composed = np.asarray(R.compose(plan, pics, s4["f0"], i)).astype(int)
    finally:
        pics.close()
    assert np.abs(own - composed).mean() > 5                          # the first composited frame is a blend
    assert R.preflight_stills(plan, j) == []


def test_a_still_whose_own_first_frame_is_not_whole_still_refuses(tmp_path, plan):
    i = [s["id"] for s in plan["shots"]].index("S4")
    zoomed = json.loads(json.dumps(plan))
    zoomed["shots"][i]["_cam"]["path"][0] = {"z": 1.25, "x": 0.5, "y": 0.5}
    zoomed["shots"][i]["_cam"]["open_s"] = 1.5
    pics = R.Pictures(zoomed)
    try:
        assert not R.still_first_frame_whole(zoomed, pics, i)
    finally:
        pics.close()
    j = J.Journal(film="zoomed")
    assert R.preflight_stills(zoomed, j) == ["S4"]
    ev = [e for e in lints(J.read(j.path), "still-first-frame-whole-pixels") if e["unit"] == "S4"][0]
    assert ev["status"] == "fail" and ev["phase"] == "preflight"


def _photo_still(path, w=1500, h=2000, contrast=40.0, seed=11):
    """A high-detail test image with a photograph's statistics: 1/f noise in
    each channel, so it has edges and texture at every scale (white noise on a
    gradient averages out under the check's box filter, a photograph does not)."""
    from PIL import Image
    rng = np.random.default_rng(seed)
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
    amp = 1.0 / np.maximum(np.hypot(fx, fy), 1.0 / max(w, h))
    chans = []
    for _ in range(3):
        x = np.fft.irfft2(amp * np.exp(2j * np.pi * rng.random(amp.shape)), s=(h, w))
        chans.append(128 + contrast * (x - x.mean()) / x.std())
    Image.fromarray(np.clip(np.stack(chans, axis=2), 0, 255).astype(np.uint8)).save(path)


def test_a_one_percent_crop_of_a_detailed_still_fails_a7(tmp_path):
    film = make_film(tmp_path / "film")
    _photo_still(film / "stills" / "FX-STILL-B.png")                 # S4, portrait, pillarboxed
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][1].update(width=1500, height=2000)
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    plan = R.build_plan(film, W=1920, H=1080, burn_subtitles=False, journal=J.Journal(film="crop"))
    i = [s["id"] for s in plan["shots"]].index("S4")
    scores = {}
    for z in (1.0, 1.01):
        pl = json.loads(json.dumps(plan))
        pl["shots"][i]["_cam"]["path"][0] = {"z": z, "x": 0.5, "y": 0.5}
        pics = R.Pictures(pl)
        try:
            ev = {}
            scores[z] = (R.still_first_frame_whole(pl, pics, i, ev), ev)
        finally:
            pics.close()
    whole, crop = scores[1.0], scores[1.01]
    assert whole[0] and whole[1]["band_mean_diff"] < R.A7_BAND_LIMIT, whole
    assert not crop[0] and crop[1]["band_mean_diff"] >= R.A7_BAND_LIMIT, crop
    assert crop[1]["low_pass_mean_diff"] < R.A7_FULL_LIMIT          # the whole-picture mean alone passed this 1% crop


def _mounted_still(path, pad=0.15, tone=225):
    """A detailed photograph on a uniform mount: the photograph in the middle,
    a flat border of `pad` of its size on every side."""
    from PIL import Image
    _photo_still(path, w=1200, h=1600)
    with Image.open(path) as im:
        photo = np.asarray(im.convert("RGB"))
    py, px = int(1600 * pad), int(1200 * pad)
    mount = np.full((1600 + 2 * py, 1200 + 2 * px, 3), tone, np.uint8)
    mount[py:py + 1600, px:px + 1200] = photo
    Image.fromarray(mount).save(path)
    return mount.shape[1], mount.shape[0]


def _a7_at(film, sid, z, H=1080):
    plan = R.build_plan(film, W=H * 16 // 9, H=H, burn_subtitles=False, journal=J.Journal(film="a7"))
    i = [s["id"] for s in plan["shots"]].index(sid)
    pl = json.loads(json.dumps(plan))
    pl["shots"][i]["_cam"]["path"][0] = {"z": z, "x": 0.5, "y": 0.5}
    pics = R.Pictures(pl)
    try:
        ev = {}
        return R.still_first_frame_whole(pl, pics, i, ev), ev
    finally:
        pics.close()


def _use_still(film, maker):
    w, h = maker(film / "stills" / "FX-STILL-B.png")
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][1].update(width=w, height=h)
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")


def test_a_mounted_still_is_measured_on_the_photograph_not_the_mount(tmp_path, monkeypatch):
    film = make_film(tmp_path / "film")
    _use_still(film, _mounted_still)
    ok, ev = _a7_at(film, "S4", 1.0)
    assert ok and ev["verdict"] == "whole"
    trim = ev["mount_trim_px"]
    assert all(abs(trim[k] - v) <= 2 for k, v in {"left": 180, "right": 180, "top": 240, "bottom": 240}.items()), trim
    ok, ev = _a7_at(film, "S4", 1.01)
    assert not ok and ev["band_mean_diff"] >= R.A7_BAND_LIMIT, ev
    # without the trim the band lies on the blank mount and the 1% crop passes: what the review found
    monkeypatch.setattr(R, "content_box", lambda img: (0, 0, 0, 0))
    ok, ev = _a7_at(film, "S4", 1.01)
    assert ok and ev["band_mean_diff"] < R.A7_BAND_LIMIT and ev["low_pass_mean_diff"] < R.A7_FULL_LIMIT, ev


def test_a_still_without_detail_at_its_edges_is_inconclusive(tmp_path):
    from PIL import Image
    film = make_film(tmp_path / "film")

    def soft(path):
        yy, xx = np.mgrid[0:1600, 0:1200]
        img = np.stack([80 + 40 * xx / 1200, 70 + 30 * yy / 1600, 90 + 0 * xx], axis=2)    # a smooth wash, no edges
        Image.fromarray(img.astype(np.uint8)).save(path)
        return 1200, 1600

    _use_still(film, soft)
    ok, ev = _a7_at(film, "S4", 1.0)
    assert ok and ev["verdict"] == "inconclusive" and ev["band_detail"] < R.A7_DETAIL_FLOOR
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="soft"))
    j = J.Journal(film="soft-preflight")
    assert R.preflight_stills(plan, j) == []                          # inconclusive never blocks; the geometric lint decides
    s4 = [e for e in lints(J.read(j.path), "still-first-frame-whole-pixels") if e["unit"] == "S4"][0]
    assert s4["status"] == "inconclusive" and s4["evidence"]["verdict"] == "inconclusive"


def _no_frames_rendered(evs, out):
    assert not [e for e in evs if e.get("lens") == "frame"]
    assert not [e for e in evs if e.get("lens") == "unit.start" and e["stage"] == "motion"]
    assert not (out / "segments").exists() or not list((out / "segments").iterdir())
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused" and evs[-1]["stage_failed"] == "scout"


def test_a_plan_violation_refuses_before_any_frame(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _shot(p, "S5").update(preset="PUSH", to={"z": 1.3}))      # z past PUSH's 1.12
    j = J.Journal(film="early")
    with pytest.raises(R.Refused, match=r"still-zoom-limit \(S5\)"):
        R.render(film, tmp_path / "out", height=HEIGHT, workers=1, min_free_gb=1, journal=j)
    evs = J.read(j.path)
    _no_frames_rendered(evs, tmp_path / "out")
    assert all(e.get("phase") == "preflight" for e in evs if e["kind"] == "lint")


def test_the_a7_pixel_check_refuses_in_preflight_with_zero_frames(tmp_path, monkeypatch):
    film = make_film(tmp_path / "film")
    real = R.still_first_frame_whole
    monkeypatch.setattr(R, "still_first_frame_whole",
                        lambda plan, pics, i, detail=None: False if plan["shots"][i]["id"] == "S5" else real(plan, pics, i, detail))
    j = J.Journal(film="early-a7")
    with pytest.raises(R.Refused, match=r"A7 \(pre-flight\): the first frame of S5"):
        R.render(film, tmp_path / "out", height=HEIGHT, workers=1, min_free_gb=1, journal=j)
    _no_frames_rendered(J.read(j.path), tmp_path / "out")


def test_both_phases_are_journaled(rendered):
    evs = events(rendered)
    a7 = lints(evs, "still-first-frame-whole-pixels")
    assert {e["phase"] for e in a7} == {"preflight", "post-render"}
    assert {e["unit"] for e in a7 if e["phase"] == "preflight"} == {"S3", "S4", "S5"}
    stages = [(e["status"], e.get("phase")) for e in evs if e["kind"] == "stage" and e["stage"] == "scout"]
    assert stages[0] == ("start", "preflight") and ("done", "preflight") in stages
    done = next(e for e in evs if e["kind"] == "stage" and e["stage"] == "scout" and e["status"] == "done")
    first_frame = next(k for k, e in enumerate(evs) if e.get("lens") == "frame")
    assert evs.index(done) < first_frame and done["frames_rendered"] == 0


# --------------------------------------------------------------------------
# T1c: colour cast removed (A14), narrator delivery and consistency, A13 follow-ups, A15
# --------------------------------------------------------------------------


def _magenta_film(tmp_path, *, flag=True, mark="RECONSTRUCTED", alterations=(R.NEUTRALISE,)):
    """The fixture film with S6 on a magenta-cast 24 fps clip from a ledger
    item that is not a test pattern (so ARCHIVE and RECONSTRUCTED are open)."""
    film = _film_with_clip(tmp_path, "magenta", telecined=False, fps="24", synthetic=False, test_fixture=False, generator=None,
                           **({"neutralise_cast": True} if flag else {}))
    _edit_play(film, lambda p: _shot(p, "S6").update(mark=mark, alterations=list(alterations), in_s=0.5, out_s=3.5))
    return film


def test_a14_a_magenta_clip_is_neutralised_to_grey_with_its_luma_kept(tmp_path):
    film = _magenta_film(tmp_path)
    plan, j = _plan(film, "magenta")
    i, s = next((k, x) for k, x in enumerate(plan["shots"]) if x["id"] == "S6")
    assert s["_video"]["neutralise_cast"] == {"filter": R.NEUTRALISE_FILTER, "alteration": R.NEUTRALISE}
    assert s["detail"].endswith(R.NEUTRALISE)                         # the mark plate names the alteration
    evs = J.read(j.path)
    assert [e for e in lints(evs, "colour-cast-marked") if e["unit"] == "S6"][0]["status"] == "pass"
    assert [e for e in lints(evs, "alterations-closed") if e["unit"] == "S6"][0]["status"] == "pass"
    assert [e for e in evs if e["kind"] == "decision" and e["unit"] == "S6" and "colour cast neutralised" in e["what"]]
    raw = json.loads(json.dumps(plan))                                # the same clip, not neutralised, for comparison
    raw["shots"][i]["_video"]["neutralise_cast"] = None
    assert R.shot_key(plan, i, {}) != R.shot_key(raw, i, {})          # a cached segment never stands in for the other
    vw, vh = s["_video"]["fit"]
    x0, y0 = (640 - vw) // 2, (360 - vh) // 2
    ys, xs = slice(y0 + 2, y0 + vh - 2), slice(x0 + 2, x0 + vw - 2)
    pics, pics_raw = R.Pictures(plan), R.Pictures(raw)
    try:
        a = np.asarray(pics.shot(i, 1.0)).astype(int)
        b = np.asarray(pics_raw.shot(i, 1.0)).astype(int)
    finally:
        pics.close()
        pics_raw.close()
    before = b[ys, xs]
    assert (before[..., 0] - before[..., 1]).mean() > 15                # the source carries the magenta cast
    grey = a[ys, xs]
    assert np.abs(grey[..., 0] - grey[..., 1]).max() <= 2 and np.abs(grey[..., 1] - grey[..., 2]).max() <= 2
    luma = before @ np.array([0.299, 0.587, 0.114])                   # BT.601 Y, the luma hue=s=0 keeps
    assert np.abs(grey[..., 1] - luma).mean() < 3.0
    assert not a[:, :x0].any() and not a[:, x0 + vw:].any()           # the pillarbox stays RGB 0,0,0 (A11)
    sdoc = R.sources_doc(plan, j, {})
    assert next(x for x in sdoc["shots"] if x["id"] == "S6")["neutralise_cast"]["filter"] == R.NEUTRALISE_FILTER


@pytest.mark.parametrize("flag,mark,alterations", [
    (True, "ARCHIVE", ()),                                            # a neutralised shot is never ARCHIVE
    (True, "RECONSTRUCTED", ("tinted",)),                             # the alteration must be named
    (False, "RECONSTRUCTED", (R.NEUTRALISE,)),                        # a named alteration nothing performs is a false mark
])
def test_a14_the_neutralise_flag_and_the_mark_go_together(tmp_path, flag, mark, alterations):
    film = _magenta_film(tmp_path, flag=flag, mark=mark, alterations=alterations)
    with pytest.raises(R.Refused, match=r"colour-cast-marked \(S6\)"):
        _plan(film)


def test_a14_a_shot_flag_overrides_its_ledger_item():
    item = {"neutralise_cast": True}
    assert R.neutralise_cast({}, item) and not R.neutralise_cast({"neutralise_cast": False}, item)
    assert R.neutralise_cast({"neutralise_cast": True}, {}) and not R.neutralise_cast({}, None)


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))))


def _line(play_or_plan, lid):
    if "parts" in play_or_plan:
        return next(ln for pt in play_or_plan["parts"] for ln in pt.get("lines", []) if ln["id"] == lid)
    return next(ln for ln in play_or_plan["lines"] if ln["id"] == lid)


def test_a14_a_mood_offset_moves_only_the_level_after_levelling(plan, film, tmp_path):
    span = slice(int(5.2 * 48000), int(6.8 * 48000))                 # inside L1 (5.0 to 7.0 s), where nothing else plays
    mixes = {}
    for mood in ("plain", "measured", "warm", "grave", "hushed", "close"):
        p = json.loads(json.dumps(plan))
        _line(p, "L1")["delivery"] = {"mood": mood, "intensity": 2, "pace": "slower", "pause_after_s": 1.5}
        j = J.Journal(film=f"mood-{mood}", directory=tmp_path / mood)
        mix, placed = R.build_mix(p, film, j)
        assert next(ln for ln in placed["lines"] if ln["id"] == "L1")["mood_offset_db"] == R.MOOD_OFFSET_DB[mood]
        dec = [e for e in J.read(j.path) if e["kind"] == "decision" and e["unit"] == "L1" and "delivery" in e["what"]][0]
        assert dec["evidence"]["offset_db"] == R.MOOD_OFFSET_DB[mood] and dec["evidence"]["applies_to"] == "level only"
        mixes[mood] = mix
    for mood, off in R.MOOD_OFFSET_DB.items():
        assert _rms_db(mixes[mood][span]) - _rms_db(mixes["plain"][span]) == pytest.approx(off, abs=0.05)
    assert R.MOOD_OFFSET_DB == {"plain": 0.0, "measured": 0.0, "warm": 0.0, "grave": -0.5, "hushed": -2.0, "close": -1.0}


def test_a14_the_warm_mood_is_plain_and_passes_the_delivery_lint(tmp_path):
    """CoS (2026-10-10): warm joins A14's list at 0 dB; it is judged like a
    plain line (not one of the lower moods) and adds nothing to the baseline."""
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _line(p, "L1").update(delivery={"mood": "warm"}))
    plan, j = _plan(film, "warm")
    nd = [e for e in lints(J.read(j.path), "narrator-delivery") if e["unit"] == "L1"]
    assert nd and nd[0]["status"] == "pass" and nd[0]["evidence"]["offset_db"] == 0.0
    assert "warm" not in R.MOOD_MAY_BE_LOWER and "warm" not in R.BASELINE_MOODS


@pytest.mark.parametrize("lid,delivery", [("L1", {"mood": "angry"}), ("L2", {"mood": "grave"})])   # L2 is a reading
def test_a14_an_unknown_mood_or_a_reading_with_a_delivery_is_refused(tmp_path, lid, delivery):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _line(p, lid).update(delivery=delivery))
    with pytest.raises(R.Refused, match=rf"narrator-delivery \({lid}\)"):
        _plan(film)


def test_a14_a_mood_offset_beyond_2_db_is_refused(tmp_path, monkeypatch, plan, film):
    monkeypatch.setitem(R.MOOD_OFFSET_DB, "hushed", -3.0)
    f2 = make_film(tmp_path / "film")
    _edit_play(f2, lambda p: _line(p, "L1").update(delivery={"mood": "hushed"}))
    with pytest.raises(R.Refused, match=r"narrator-delivery \(L1\)"):
        _plan(f2)
    p = json.loads(json.dumps(plan))                                  # and build_mix refuses it on its own
    _line(p, "L1")["delivery"] = {"mood": "hushed"}
    with pytest.raises(R.Refused, match="narrator-delivery"):
        R.build_mix(p, film, J.Journal(film="mood-3db"))


def test_a13_gain_db_on_a_synthetic_voice_line_is_refused(tmp_path, plan, film):
    f2 = make_film(tmp_path / "film")
    _edit_play(f2, lambda p: _line(p, "L2").update(gain_db=-3))
    with pytest.raises(R.Refused, match=r"voice-gain-db \(L2\)"):
        _plan(f2)
    p = json.loads(json.dumps(plan))
    _line(p, "L1")["gain_db"] = 2.0
    with pytest.raises(R.Refused, match="voice-gain-db"):
        R.build_mix(p, film, J.Journal(film="gain-db"))


def test_a13_only_the_3_db_bound_fails(tmp_path):
    x = _voice(4.0, 0.05)
    for s in np.arange(1.0, 1.36, 0.005):                             # 360 ms of peaks every 5 ms, held 4 to 6 dB down
        i = int(s * 48000)
        x[i:i + 24] += 0.4 * np.sin(np.linspace(0, np.pi, 24))
    _, peak = R.voice_peak_control(_levelled(x))
    assert peak["over_8db_s"] <= R.VOICE_OVER_8DB_MAX_S and peak["over_1db_share"] <= R.VOICE_OVER_1DB_MAX_SHARE
    assert peak["over_3db_share"] > R.VOICE_OVER_3DB_MAX_SHARE
    assert len(peak["bad_take"]) == 1 and "over 3 dB for" in peak["bad_take"][0] and "limit 5%" in peak["bad_take"][0]
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L1.wav", x)
    plan, _ = _plan(film)
    with pytest.raises(R.Refused, match=r"voice-peak-control \(A13\).*L1 \(over 3 dB for"):
        R.build_mix(plan, film, J.Journal(film="three-db"))


def test_a13_a_short_line_is_levelled_and_peak_controlled(tmp_path, monkeypatch):
    _no_a19_verdict(monkeypatch)
    x = _voice(0.25, 0.05)                                            # under one 400 ms gating block
    i = int(0.1 * 48000)
    x[i:i + 96] += 0.25 * np.sin(np.linspace(0, np.pi, 96))
    g, m = R.level_gain(x, R.DIALOGUE_LUFS)
    assert g is not None and m["looped"] == 2                         # measured on the line looped to 0.4 s
    _, peak = R.voice_peak_control(x * 10 ** (g / 20))
    assert peak and peak["measured_looped"] == 2 and peak["tp_after"] <= R.VOICE_TP + 0.2
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L2.wav", x)
    plan, _ = _plan(film)
    j = J.Journal(film="short")
    _, placed = R.build_mix(plan, film, j)
    line = next(ln for ln in placed["lines"] if ln["id"] == "L2")
    assert line["level_db"] is not None and line["peak_reduction_db"] > 0
    evs = J.read(j.path)
    dec = [e for e in evs if e["kind"] == "decision" and e["unit"] == "L2" and "levelled" in e["what"]][0]
    assert dec["evidence"]["measured_looped"] == 2 and "measured looped" in dec["why"]
    assert [e for e in lints(evs, "voice-peak-control") if e["unit"] == "L2"]


def test_a13_a_silent_line_warns_that_it_was_not_levelled(tmp_path, monkeypatch):
    _no_a19_verdict(monkeypatch)
    film = make_film(tmp_path / "film")
    _wav(film / "audio" / "L2.wav", np.zeros(48000))
    plan, _ = _plan(film)
    j = J.Journal(film="silent-line")
    R.build_mix(plan, film, j)
    warn = [e for e in lints(J.read(j.path), "level-measured") if e["unit"] == "L2"][0]
    assert warn["status"] == "fail" and warn["severity"] == "warn"


def test_a15_the_programme_is_minus_18_lufs_and_the_voice_ceiling_follows():
    assert R.TARGET_LUFS == -18.0 and R.TARGET_TP == -1.5
    assert R.VOICE_TP == pytest.approx(R.DIALOGUE_LUFS + (R.TARGET_TP - R.TARGET_LUFS) - R.VOICE_TP_MARGIN)
    assert R.VOICE_TP == pytest.approx(-4.8)


def test_the_post_render_a7_check_journals_each_still_with_its_verdict(rendered):
    post = [e for e in lints(events(rendered), "still-first-frame-whole-pixels") if e["phase"] == "post-render"]
    assert {e["unit"] for e in post} == {"S3", "S4", "S5"}
    for e in post:
        assert e["evidence"]["verdict"] in ("whole", "inconclusive") and "band_detail" in e["evidence"]
        assert e["status"] == ("inconclusive" if e["evidence"]["verdict"] == "inconclusive" else "pass")


def _speech(f0, seconds=3.0, amp=0.1, seed=0):
    """A voiced test line: harmonics to 4 kHz with a slow pitch wobble, cut
    into syllables by short gaps, so it has a pitch, a centroid and a pace."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(48000 * seconds)) / 48000
    inst = f0 * (1 + 0.03 * np.sin(2 * np.pi * 1.3 * t + rng.uniform(0, 6)))
    ph = 2 * np.pi * np.cumsum(inst) / 48000
    x = sum((1.0 / k) * np.sin(k * ph) for k in range(1, int(4000 // f0) + 1))
    gate = (np.sin(2 * np.pi * 2.0 * t) > -0.7).astype(float)
    return amp * x * gate / np.max(np.abs(x))


def test_voice_profile_measures_pitch_centroid_and_pace():
    for f0 in (110.0, 183.0, 240.0):
        p = R.voice_profile(_levelled(_speech(f0)), 7)
        assert p["f0_hz"] == pytest.approx(f0, rel=0.02)
        assert p["f0_p10_hz"] < p["f0_hz"] < p["f0_p90_hz"] and p["f0_range_hz"] > 0
        assert p["voiced_frames"] > 100 and p["speech_s"] == pytest.approx(3.0, abs=0.3)
        assert p["wps"] == pytest.approx(7 / p["speech_s"], rel=0.01)
    lo, hi = (R.voice_profile(_levelled(_speech(f)), 7)["centroid_hz"] for f in (150.0, 250.0))
    assert hi > lo


def _narrator_lines():
    return {f"N{k}": dict(R.voice_profile(_levelled(_speech(f, seed=k)), 7), mood="measured")
            for k, f in enumerate((178.0, 181.0, 183.0, 185.0, 188.0, 182.0))}


def test_narrator_consistency_needs_a_baseline():
    prof = {f"N{k}": dict(R.voice_profile(_levelled(_speech(f)), 7), mood="plain") for k, f in enumerate((180.0, 240.0))}
    res = R.narrator_consistency(prof)
    assert not res["enough"] and {r["verdict"] for r in res["lines"].values()} == {"inconclusive"}


def test_narrator_consistency_blocks_the_mix_and_warns_under_draft(plan, film, tmp_path):
    p = json.loads(json.dumps(plan))
    voices = {"L1": 183.0, "NB": 179.0, "NC": 186.0, "ND": 181.0, "NE": 184.0, "NOFF": 235.0}
    for k, (lid, f0) in enumerate(voices.items()):
        (tmp_path / "audio").mkdir(exist_ok=True)
        wav = _wav(tmp_path / "audio" / f"{lid}.wav", _speech(f0, seed=k))
        if lid == "L1":
            _line(p, "L1")["wav"] = str(wav)
        else:
            p["lines"].append({"id": lid, "kind": "narration", "start_s": 9.0 + k, "text": "one two three four five six seven",
                               "wav": str(wav), "delivery": {"mood": "measured"}, "_part": "ch-1"})
    j = J.Journal(film="narrator")
    with pytest.raises(R.Refused, match=r"narrator-consistency and narrator-drift \(A14\).*NOFF \(f0 \+4"):
        R.build_mix(p, film, j)
    evs = J.read(j.path)
    per = {e["unit"]: e for e in lints(evs, "narrator-consistency") if e["unit"] != "narrator"}
    assert set(per) == set(voices) and per["NOFF"]["status"] == "fail" and per["NOFF"]["severity"] == "block"
    assert all(per[k]["status"] == "pass" for k in voices if k != "NOFF")
    assert {"f0_hz", "f0_range_hz", "centroid_hz", "wps"} <= set(per["L1"]["evidence"]["profile"])
    base = [e for e in evs if e.get("lens") == "narrator-profile"][0]
    assert set(base["lines"]) == set(voices) and base["baseline"]["f0_hz"] > 0
    jd = J.Journal(film="narrator-draft")
    R.build_mix(p, film, jd, draft=True)
    assert [e for e in lints(J.read(jd.path), "narrator-consistency") if e["unit"] == "NOFF"][0]["severity"] == "warn"


# --------------------------------------------------------------------------
# T1c review: private keys, bounded mood exemptions, the narrator's anchor and spread, offsets never positive
# --------------------------------------------------------------------------


def test_a_screenplay_key_starting_with_underscore_is_refused(tmp_path):
    film = _magenta_film(tmp_path, flag=False, mark="ARCHIVE", alterations=())
    _edit_play(film, lambda p: _shot(p, "S6").update(_neutralise=True))          # would grey an ARCHIVE shot
    with pytest.raises(R.Refused, match=r"private-key \(ch-1/S6\)"):
        _plan(film)


def test_a_ledger_key_starting_with_underscore_is_refused(tmp_path):
    film = _magenta_film(tmp_path, flag=False, mark="ARCHIVE", alterations=())
    led = json.loads((film / "footage-ledger.json").read_text(encoding="utf-8"))
    led["items"][-1]["_video"] = {"neutralise_cast": {"filter": "hue=s=0"}}
    (film / "footage-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(R.Refused, match=r"private-key \(ledger footage/FX-CLIP\)"):
        _plan(film)
    assert R.private_keys({"a": [{"b": {"_c": 1}}], "_d": 2}) == ["a.0.b._c", "_d"]


def test_neutralise_is_reset_before_it_is_decided(tmp_path, monkeypatch):
    film = _magenta_film(tmp_path, flag=False, mark="ARCHIVE", alterations=())
    _edit_play(film, lambda p: _shot(p, "S6").update(_neutralise=True))
    monkeypatch.setattr(R, "private_keys", lambda x, path="": [])                # even with the key check gone
    plan, _ = _plan(film)
    s6 = next(x for x in plan["shots"] if x["id"] == "S6")
    assert s6["mark"] == "ARCHIVE" and s6["_neutralise"] is False and s6["_video"]["neutralise_cast"] is None


def test_a_swapped_voice_labelled_hushed_is_refused():
    base = _narrator_lines()                                          # a 183 Hz narrator
    for mood in ("hushed", "grave", "close"):
        swapped = dict(R.voice_profile(_levelled(_speech(95.0, seed=4)), 7), mood=mood)
        x = R.narrator_consistency(dict(base, X=swapped))["lines"]["X"]
        assert x["verdict"] == "off" and any("semitones" in o for o in x["off"]) and x["f0_st"] < -3, (mood, x)
    lower = dict(R.voice_profile(_levelled(_speech(140.0, seed=4)), 7), mood="hushed")   # 4.6 semitones down
    assert R.narrator_consistency(dict(base, X=lower))["lines"]["X"]["verdict"] == "off"


def test_the_baseline_comes_from_plain_and_measured_lines():
    prof = {f"M{k}": {"f0_hz": 183.0 + k, "centroid_hz": 1100.0, "f0_range_hz": 60.0, "wps": 2.4, "mood": "measured"}
            for k in range(4)}
    prof |= {f"G{k}": {"f0_hz": 165.0 + k, "centroid_hz": 1000.0, "f0_range_hz": 60.0, "wps": 2.0, "mood": "grave"}
             for k in range(6)}
    res = R.narrator_consistency(prof)
    assert res["baseline"]["f0_hz"] == pytest.approx(184.5) and res["baseline_from"] == "plain and measured lines"
    few = {k: v for k, v in prof.items() if k != "M0"}                # 3 unmarked lines: the baseline is every line
    assert R.narrator_consistency(few)["baseline_from"].startswith("all lines")


def test_two_voices_sharing_the_narrator_are_refused(plan, film, tmp_path):
    p = json.loads(json.dumps(plan))
    (tmp_path / "audio").mkdir()
    voices = {"L1": 160.0, "NB": 161.0, "NC": 162.0, "ND": 200.0, "NE": 201.0, "NF": 202.0}   # half and half
    for k, (lid, f0) in enumerate(voices.items()):
        wav = _wav(tmp_path / "audio" / f"{lid}.wav", _speech(f0, seed=k))
        if lid == "L1":
            _line(p, "L1").update(wav=str(wav), delivery={"mood": "measured"})
        else:
            p["lines"].append({"id": lid, "kind": "narration", "start_s": 9.0 + k, "text": "one two three four five six seven",
                               "wav": str(wav), "delivery": {"mood": "measured"}, "_part": "ch-1"})
    j = J.Journal(film="two-narrators")
    with pytest.raises(R.Refused, match=r"narrator-consistency and narrator-drift \(A14\).*narrator \(the baseline lines' pitch spreads"):
        R.build_mix(p, film, j)
    whole = [e for e in lints(J.read(j.path), "narrator-consistency") if e["unit"] == "narrator"][0]
    assert whole["status"] == "fail" and whole["evidence"]["spread_st"] > R.NARRATOR_SPREAD_MAX_ST


def test_the_committed_narrator_profile_is_tara():
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    assert prof["voice"] == {"engine": "orpheus", "voice": "tara"} and len(prof["takes"]) == 5
    assert 150 < prof["baseline"]["f0_hz"] < 210 and 500 < prof["baseline"]["centroid_hz"] < 3000


def test_a_positive_mood_offset_is_refused(tmp_path, monkeypatch):
    monkeypatch.setitem(R.MOOD_OFFSET_DB, "plain", 1.0)
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: _line(p, "L1").update(delivery={"mood": "plain"}))
    with pytest.raises(R.Refused, match=r"narrator-delivery \(L1\)"):
        _plan(film)
    assert all(v <= 0 for v in R.MOOD_OFFSET_DB.values() if v != 1.0)


# --------------------------------------------------------------------------
# A14 refined: perceptual narrator bounds (semitones and percent), the stored profile as a drift check
# --------------------------------------------------------------------------


def _p(f0, cen=1100.0, mood="measured"):
    return {"f0_hz": f0, "centroid_hz": cen, "f0_range_hz": 60.0, "wps": 2.4, "mood": mood}


def _with(x):
    base = {f"N{k}": _p(180.0) for k in range(5)}                   # baseline 180 Hz, 1100 Hz
    return R.narrator_consistency(dict(base, X=x))["lines"]["X"]


def _up(st):
    return 180.0 * 2 ** (st / 12)


@pytest.mark.parametrize("st,mood,want", [
    (1.49, "measured", "consistent"), (1.51, "measured", "off"), (1.51, "hushed", "off"),       # never higher, any mood
    (-1.49, "plain", "consistent"), (-1.51, "plain", "off"), (-1.51, "measured", "off"), (-1.51, None, "off"),
    (-2.99, "hushed", "consistent"), (-2.99, "grave", "consistent"), (-2.99, "close", "consistent"),
    (-3.01, "hushed", "off"), (-3.01, "grave", "off"), (-3.01, "close", "off"),
])
def test_narrator_f0_bounds_sit_at_1_5_and_3_semitones(st, mood, want):
    x = _with(_p(_up(st), mood=mood))
    assert x["verdict"] == want, x
    assert x["f0_st"] == pytest.approx(st, abs=0.01)


@pytest.mark.parametrize("pct,mood,want", [
    (24, "measured", "consistent"), (26, "measured", "off"), (26, "grave", "off"),               # never brighter
    (-24, "plain", "consistent"), (-26, "plain", "off"),
    (-39, "grave", "consistent"), (-39, "hushed", "consistent"), (-41, "close", "off"),
])
def test_narrator_centroid_bounds_sit_at_25_and_40_percent(pct, mood, want):
    x = _with(_p(180.0, cen=1100.0 * (1 + pct / 100), mood=mood))
    assert x["verdict"] == want, x
    assert x["centroid_pct"] == pytest.approx(pct, abs=0.01)


def _drift_film(tmp_path, monkeypatch, plan, ref_f0, ref_cen=None):
    """The fixture plan with four plain and measured narrator lines near 183 Hz, and a stored profile."""
    p = json.loads(json.dumps(plan))
    (tmp_path / "audio").mkdir(exist_ok=True)
    profs = {}
    for k, (lid, f0) in enumerate({"L1": 183.0, "NB": 181.0, "NC": 185.0, "ND": 182.0}.items()):
        wav = _wav(tmp_path / "audio" / f"{lid}.wav", _speech(f0, seed=k))
        if lid == "L1":
            _line(p, "L1").update(wav=str(wav), delivery={"mood": "plain"})
        else:
            p["lines"].append({"id": lid, "kind": "narration", "start_s": 9.0 + k, "text": "one two three four five six seven",
                               "wav": str(wav), "delivery": {"mood": "measured"}, "_part": "ch-1"})
    if ref_cen is None:                                               # the films' own centroid, so only f0 drifts
        ref_cen = R.voice_profile(_levelled(_speech(183.0, seed=0)), 7)["centroid_hz"]
    f = tmp_path / "narrator-profile.json"
    f.write_text(json.dumps({"voice": {"engine": "test-tone", "voice": "none"},
                             "baseline": {"f0_hz": ref_f0, "centroid_hz": ref_cen}}), encoding="utf-8")
    monkeypatch.setattr(R, "NARRATOR_PROFILE", f)
    return p


@pytest.mark.parametrize("ref_st,grade", [(0.5, "pass"), (1.5, "warn"), (2.5, "block")])
def test_narrator_drift_in_f0_warns_past_1_and_blocks_past_2_semitones(tmp_path, monkeypatch, plan, film, ref_st, grade):
    p = _drift_film(tmp_path, monkeypatch, plan, ref_f0=183.0 * 2 ** (-ref_st / 12))
    j = J.Journal(film=f"drift-{grade}")
    if grade == "block":
        with pytest.raises(R.Refused, match=r"narrator-drift f0 \+2\.\d+ semitones"):
            R.build_mix(p, film, j)
    else:
        R.build_mix(p, film, j)
    d = [e for e in lints(J.read(j.path), "narrator-drift") if e["unit"] == "narrator-f0"][0]
    assert d["status"] == ("pass" if grade == "pass" else "fail")
    assert d["severity"] == ("warn" if grade == "warn" else "block")     # the blocking bound applies, so a pass is a block lint
    jd = J.Journal(film=f"drift-{grade}-draft")
    R.build_mix(p, film, jd, draft=True)                              # a draft only ever warns
    assert all(e["severity"] == "warn" for e in lints(J.read(jd.path), "narrator-drift"))


@pytest.mark.parametrize("ratio,grade", [(1.10, "pass"), (1.20, "warn"), (1.30, "block")])
def test_a_timbre_only_swap_is_caught_by_centroid_drift(tmp_path, monkeypatch, plan, film, ratio, grade):
    cen = R.voice_profile(_levelled(_speech(183.0, seed=0)), 7)["centroid_hz"]
    p = _drift_film(tmp_path, monkeypatch, plan, ref_f0=183.0, ref_cen=cen / ratio)   # same pitch, brighter film
    j = J.Journal(film=f"timbre-{grade}")
    if grade == "block":
        with pytest.raises(R.Refused, match=r"narrator-drift centroid \+"):
            R.build_mix(p, film, j)
    else:
        R.build_mix(p, film, j)
    d = [e for e in lints(J.read(j.path), "narrator-drift") if e["unit"] == "narrator-centroid"][0]
    assert d["status"] == ("pass" if grade == "pass" else "fail") and d["severity"] == ("warn" if grade == "warn" else "block")


def test_a_narrator_with_no_stored_profile_is_a_review_item(plan, film):
    j = J.Journal(film="no-profile")                                  # the fixture's narrator is a test tone: no profile
    p = json.loads(json.dumps(plan))
    R.build_mix(p, film, j)
    rev = lints(J.read(j.path), "narrator-drift")
    assert len(rev) == 1 and rev[0]["status"] == "review" and rev[0]["evidence"]["check"] == "no reference profile"


def test_a_second_voice_on_the_plain_lines_with_the_narrator_on_the_lower_moods_is_refused():
    lines = {f"P{k}": _p(205.0 + k * 0.5, mood=("plain" if k % 2 else "measured")) for k in range(8)}   # voice X
    for k, mood in enumerate(["hushed", "hushed", "grave", "grave", "grave", "close", "close"]):          # Tara, 176 Hz
        lines[f"L{k}"] = _p(176.0 + (k % 3) * 0.5, mood=mood)
    res = R.narrator_consistency(lines)
    assert all(r["verdict"] == "consistent" for r in res["lines"].values())          # every line alone is within bounds
    assert res["spread_ok"]                                                          # and the baseline lines agree
    assert -3.0 < res["lines"]["L0"]["f0_st"] < -2.4
    assert {m for m, g in res["groups"].items() if not g["ok"]} == {"hushed", "grave", "close", "lower moods pooled"}
    one = R.narrator_consistency({**{f"P{k}": _p(183.0) for k in range(6)}, "H": _p(183.0 * 2 ** (-2.8 / 12), mood="hushed")})
    assert not one["group_off"] and one["lines"]["H"]["verdict"] == "consistent"     # a single line may still drop 3


def test_the_mood_split_refuses_the_mix(plan, film, tmp_path):
    p = json.loads(json.dumps(plan))
    (tmp_path / "audio").mkdir()
    voices = {"L1": (205.0, "plain"), "NB": (206.0, "measured"), "NC": (204.0, "plain"), "ND": (205.5, "measured"),
              "H1": (176.0, "hushed"), "H2": (177.0, "hushed"), "G1": (176.5, "grave"), "G2": (175.5, "grave")}
    for k, (lid, (f0, mood)) in enumerate(voices.items()):
        wav = _wav(tmp_path / "audio" / f"{lid}.wav", _speech(f0, seed=k))
        if lid == "L1":
            _line(p, "L1").update(wav=str(wav), delivery={"mood": mood})
        else:
            p["lines"].append({"id": lid, "kind": "narration", "start_s": 9.0 + k, "text": "one two three four five six seven",
                               "wav": str(wav), "delivery": {"mood": mood}, "_part": "ch-1"})
    j = J.Journal(film="mood-split")
    with pytest.raises(R.Refused, match=r"hushed: median f0 -2\.\d+ semitones"):
        R.build_mix(p, film, j)
    grp = {e["unit"]: e["status"] for e in lints(J.read(j.path), "narrator-consistency") if e["unit"].startswith("narrator:")}
    assert grp == {"narrator:hushed": "fail", "narrator:grave": "fail", "narrator:lower moods pooled": "fail"}


# --------------------------------------------------------------------------
# T1d: a held clip in every segment that shows it; sources checked in pre-flight
# --------------------------------------------------------------------------


def _held_dissolve_film(tmp_path):
    """S6 is a 4 s, 10 fps clip cut from 2.5 to 5.5 s (a 1.5 s hold), and S7 a still that
    dissolves out of it over 1 s: S7's segment starts inside S6's hold, as O2 does in the
    episode (O1, 5.0 s of 10 fps footage to 6.9 s)."""
    film = _film_with_clip(tmp_path, "slow", telecined=False, fps="10")

    def edit(p):
        _shot(p, "S6").update(in_s=2.5, out_s=5.5)
        s7 = _shot(p, "S7")
        for k in ("silent_record", "text"):
            s7.pop(k, None)
        s7.update(kind="archive_still", asset="FX-STILL-A", preset="HOLD", start_s=16.75, dur_s=3.5, mark="DRAWN",
                  transition_in={"type": "dissolve", "s": 1.0})
    _edit_play(film, edit)
    return film


def test_a_dissolve_out_of_a_held_clip_renders_its_last_frame_in_the_next_segment(tmp_path):
    film = _held_dissolve_film(tmp_path)
    plan, _ = _plan(film, "held-dissolve")
    i6 = next(i for i, s in enumerate(plan["shots"]) if s["id"] == "S6")
    s6, s7 = plan["shots"][i6], plan["shots"][i6 + 1]
    assert s6["_video"]["hold_s"] > 1.4 and (s7["f0"] - s6["f0"]) / R.FPS > 4.0 - 2.5   # S7 starts inside the hold
    whole = R.VideoReader(s6, 0.0)                         # one reader from the in point, as a single pass would read it
    try:
        last = [whole.frame(k / R.FPS).tobytes() for k in range(int(round(s6["_dur"] * R.FPS)))][-1]
    finally:
        whole.close()
    late = R.VideoReader(s6, (s7["f0"] - s6["f0"]) / R.FPS)   # a reader that seeks past the stream's last frame
    try:
        assert late.frame((s7["f0"] - s6["f0"]) / R.FPS).tobytes() == last
        assert late.held == 1
    finally:
        late.close()
    res = R.render_segment(plan, i6 + 1, str(tmp_path / "S7.mp4"))
    assert res["held_frames"] == 0 and res["held_by_shot"] == {"S6": 24}      # S6 held through the whole 1 s dissolve


def test_a_held_clip_renders_the_same_bytes_with_one_worker_or_several(tmp_path):
    film = _held_dissolve_film(tmp_path)
    one = R.render(film, tmp_path / "one", height=HEIGHT, workers=1, min_free_gb=1, encode_preset="veryfast")
    many = R.render(film, tmp_path / "many", height=HEIGHT, workers=3, min_free_gb=1, encode_preset="veryfast")
    assert J.sha256_file(one["master"]) == J.sha256_file(many["master"])
    segs = lambda out: {p.name: J.sha256_file(p) for p in (out / "segments").glob("*.mp4")}
    assert segs(tmp_path / "one") == segs(tmp_path / "many")
    for s in (one, many):
        lint = lints(events(s), "clip-hold-rendered")[0]
        held = lint["evidence"]["held_frames"]
        assert lint["status"] == "pass" and set(held) == {"S6"}     # S7 shows S6's hold; it is counted under S6
        assert 34 <= held["S6"] <= 38                                # 1.5 s at 24, summed over S6's and S7's segments


def test_held_frames_are_summed_per_clip_across_segments():
    ids = ["A", "B", "C"]
    results = {0: {"held_frames": 30, "held_by_shot": {"A": 30}}, 1: {"held_frames": 0, "held_by_shot": {"A": 24}},
               2: {"held_frames": 5}}                                # a segment cached before held_by_shot
    assert R.held_totals(results, ids) == {"A": 54, "C": 5}          # 54 frames is 2.25 s: over GRAMMAR 7.1's 2 s


def test_missing_and_undecodable_sources_refuse_in_preflight_all_at_once(tmp_path):
    film = make_film(tmp_path / "film")
    (film / "footage" / "fx-testsrc.mp4").write_bytes(b"\x00" * 4096)     # present, but no frame decodes
    (film / "stills" / "FX-STILL-B.png").unlink()
    (film / "stills" / "FX-STILL-C.png").write_bytes(b"not a png")
    (film / "audio" / "L2.wav").unlink()
    j = J.Journal(film="sources")
    with pytest.raises(R.Refused, match=r"source files missing or unreadable \(pre-flight\)") as e:
        R.render(film, tmp_path / "out", height=HEIGHT, workers=1, min_free_gb=1, journal=j)
    msg = str(e.value)
    for unit, why in (("S6", "no frame decoded"), ("S4", "missing"), ("S5", "not a readable image"), ("L2", "voice WAV missing")):
        assert f"{unit}: " in msg and why in msg
    evs = J.read(j.path)
    _no_frames_rendered(evs, tmp_path / "out")
    lint = lints(evs, "sources-readable")[0]
    assert lint["status"] == "fail" and {p["unit"] for p in lint["evidence"]["problems"]} == {"S4", "S5", "S6", "L2"}
    jd = J.Journal(film="sources-draft")                              # a draft places silence for the WAV, never for a picture
    with pytest.raises(R.Refused) as e:
        R.render(film, tmp_path / "out2", height=HEIGHT, workers=1, min_free_gb=1, draft=True, journal=jd)
    assert "L2" not in str(e.value) and "S6" in str(e.value)


def test_every_source_of_the_fixture_is_checked_and_passes(rendered):
    lint = lints(events(rendered), "sources-readable")[0]
    assert lint["status"] == "pass" and lint["evidence"]["files_checked"] >= 6 and lint["phase"] == "preflight"


def test_until_is_a_check_render_that_never_touches_the_full_master(film, rendered):
    out = rendered["out"]
    files = lambda: {str(p.relative_to(out)): J.sha256_file(p) for p in out.rglob("*") if p.is_file()
                     and "check-" not in str(p.relative_to(out))}
    before = files()
    s = R.render(film, out, height=HEIGHT, workers=2, min_free_gb=1, encode_preset="veryfast", until_s=5.0)
    assert files() == before                                   # master.mp4, sources.json, segments/ and work/ untouched
    assert Path(s["master"]).name == "master.check-5s.mp4" and Path(s["sources"]).name == "sources.check-5s.json"
    assert s["partial"] is True and s["until_s"] == 5.0 and s["rendered"] == ["S1", "S2", "S3"]
    assert (out / "check-5s" / "segments").is_dir()
    pr = R.probe_video(Path(s["master"]))
    assert abs(pr["duration_s"] - s["duration_s"]) < 0.1
    evs = events(s)
    assert evs[-1]["lens"] == "run.end" and evs[-1]["partial"] is True and evs[-1]["until_s"] == 5.0
    roles = {e.get("role") for e in evs if e["kind"] == "artifact"}
    assert "check-master" in roles and "master" not in roles and "segment" not in roles
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--until"]
    j = J.Journal(film="until-resume")
    with pytest.raises(R.Refused):
        R.render(film, out, height=HEIGHT, workers=1, min_free_gb=1, until_s=5.0, from_shot="S99", journal=j)
    assert J.read(j.path)[-1]["resume"]["command"].endswith("--until 5")
    doc = json.loads(Path(s["sources"]).read_text(encoding="utf-8"))
    assert doc["partial"] is True and doc["master"] == "master.check-5s.mp4"
    with pytest.raises(R.Refused, match="--until"):
        R.trim_plan({"shots": [{"f0": 0}]}, 0)


def test_a_truncated_jpeg_or_an_empty_wav_refuses_in_preflight(tmp_path):
    from PIL import Image
    film = make_film(tmp_path / "film")
    jpg = film / "stills" / "FX-STILL-B.jpg"
    Image.new("RGB", (395, 316), (120, 90, 60)).save(jpg, quality=95)
    data = jpg.read_bytes()
    jpg.write_bytes(data[: len(data) // 2])                   # the header and half the scan: verify() alone passes it
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][1]["file"] = "FX-STILL-B.jpg"
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    assert "truncated" in R.opens_as_image(jpg) and R.opens_as_image(film / "stills" / "FX-STILL-A.png") is None
    (film / "audio" / "L2.wav").write_bytes(b"")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    j = J.Journal(film="truncated")
    problems = R.preflight_sources(film, play, j, draft=True)    # a draft forgives a missing WAV, never an unreadable one
    assert {(p["unit"], p["why"].split(":")[0]) for p in problems} == {("S4", "not a readable image"),
                                                                       ("L2", "not a readable WAV")}


def test_an_empty_decode_before_the_clips_end_raises_with_ffmpegs_message(plan, tmp_path, monkeypatch):
    s6 = json.loads(json.dumps(next(s for s in plan["shots"] if s["id"] == "S6")))
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(bytes(4096))
    s6["_item"]["_path"] = str(bad)
    monkeypatch.setattr(R.VideoReader, "tail_frame", lambda self: pytest.fail("a hold was assumed"))
    r = R.VideoReader(s6, 0.5)
    try:
        assert not r.starts_in_hold()
        with pytest.raises(R.EncodeError, match="no frames decoded for S6: .+"):
            r.frame(0.5)
    finally:
        r.close()



def test_narrator_drift_is_inconclusive_when_no_line_has_both_f0_and_centroid(tmp_path, monkeypatch):
    f = tmp_path / "narrator-profile.json"
    f.write_text(json.dumps({"voice": {"engine": "test-tone", "voice": "none"},
                             "baseline": {"f0_hz": 183.0, "centroid_hz": 1100.0}}), encoding="utf-8")
    monkeypatch.setattr(R, "NARRATOR_PROFILE", f)
    j = J.Journal(film="drift-unmeasured")
    profiles = {f"N{k}": {"f0_hz": None, "centroid_hz": 1100.0, "wps": 2.5, "mood": "plain"} for k in range(5)}
    off = R.narrator_consistency_lints(j, profiles, False, {"engine": "test-tone", "voice": "none"})
    d = lints(J.read(j.path), "narrator-drift")
    assert off == [] and len(d) == 1 and d[0]["status"] == "inconclusive" and d[0]["severity"] == "block"
    assert d[0]["evidence"]["check"] == "no line has both f0 and centroid"


# --------------------------------------------------------------------------
# T1e: the founder's revamp (A16 subtle marks, A17 and A18 narration, A19 sound)
# --------------------------------------------------------------------------


def test_a16_a_lower_third_comes_and_goes_and_the_flag_stays_first():
    assert M.lower_third_span(10.0, 20.0) == (10.0, 10.0 + M.LT_MAX_S) and 5.0 < M.LT_MAX_S < 6.0
    assert M.lower_third_span(10.0, 13.0) == (10.0, 13.0)                  # a shorter screenplay span ends it sooner
    img = Image.new("RGB", (640, 360), (40, 40, 40))
    lines = ["Sample speaker", "Role, 1947", "Source title, archive  ·  read by a computer voice"]
    flag = "Account of a sample government, 1948"
    kw = dict(start=0.0, end=12.0, lines=lines, fonts=M.Fonts(), flag=flag)
    up = np.asarray(M.lower_third_frame(img, 2.0, **kw).convert("RGB")).astype(int)
    gone = np.asarray(M.lower_third_frame(img, M.LT_MAX_S + 0.01, **kw).convert("RGB")).astype(int)
    assert up.max() > 150 and np.array_equal(gone, np.asarray(img).astype(int))
    els, top = M.lower_third_layout(M.Layout(640, 360), lines, M.Fonts(), "speaker", flag)
    assert els[0]["kind"] == "flag" and els[0]["size"] >= max(e["size"] for e in els if e["kind"] != "rule")
    assert M.LT["a_flag"] >= max(M.LT["a_name"], M.LT["a_role"], M.LT["a_source"])
    # quieter than the G2 kit: name 4.4% and opaque, wash 0.5, watermark 0.6
    assert M.LT["name"] < 4.4 and M.LT["a_name"] < 1.0 and M.LT["wash"] < 0.5 and M.WM["opacity"] < 0.6


def test_a16_the_lower_third_drawn_by_the_engine_is_clipped_to_its_hold(film, plan):
    lt = plan["lower_thirds"][0]
    assert lt["end"] == min(lt["end_s"], lt["start"] + M.LT_MAX_S)


def _speechlike(seed=0, words=6, word_s=0.35, gap_s=0.6, hiss_db=-60.0):
    """Words (a 140 Hz-plus harmonic stack with a 20 ms rise and a 60 ms
    exponential tail) between gaps, all under white hiss at ``hiss_db``.
    Returns the line and each word's span in samples (rise to end of tail)."""
    rng = np.random.default_rng(seed)
    rate = 48000
    parts, spans, t = [np.zeros(int(0.5 * rate))], [], int(0.5 * rate)
    for w in range(words):
        n = int(word_s * rate)
        tt = np.arange(n) / rate
        sig = sum(np.sin(2 * np.pi * (140 + 20 * w) * h * tt) / h for h in range(1, 12))
        env = np.minimum(1, tt / 0.02) * np.exp(-np.maximum(0, tt - word_s * 0.6) / 0.06)
        parts.append(0.1 * sig * env)
        spans.append((t, t + n))
        t += n
        parts.append(np.zeros(int(gap_s * rate)))
        t += int(gap_s * rate)
    x = np.concatenate(parts)
    return (x + rng.normal(0, 10 ** (hiss_db / 20), len(x))).astype(np.float32), spans


def _db(x):
    return 10 * np.log10(np.mean(np.asarray(x, dtype=float) ** 2) + 1e-30)


def test_a19_a_hissy_synthetic_line_falls_under_minus_80_dbfs_between_words():
    x, spans = _speechlike()
    y, rep = R.clean_voice(x)
    assert rep["cleaned"] and rep["chopped_frames"] == 0
    gain, _ = R.level_gain(y, R.DIALOGUE_LUFS)
    for (a, b), (c, _) in zip(spans, spans[1:]):
        mid = b + (c - b) // 2
        assert _db(x[mid - 4800: mid + 4800]) > -61                           # the hiss was there
        assert _db(y[mid - 4800: mid + 4800]) + gain < -80                     # gone, even after levelling
    assert rep["after"]["floor_dbfs"] + gain < R.CLEAN_FLOOR_MAX_DBFS
    assert rep["before"]["floor_dbfs"] == pytest.approx(-60, abs=1.0) and rep["before"]["snr_db"] > 30


def test_a19_speech_energy_and_word_tails_are_kept_within_half_a_db():
    x, spans = _speechlike(seed=3)
    y, rep = R.clean_voice(x)
    assert abs(rep["speech_change_db"]) <= 0.5
    for a, b in spans:
        assert abs(_db(y[a:b]) - _db(x[a:b])) <= 0.5                           # each word, its 60 ms tail included
        tail = slice(b - int(0.08 * 48000), b)                                  # the last 80 ms: the tail's decay
        assert abs(_db(y[tail]) - _db(x[tail])) <= 1.0


def test_a19_a_take_with_no_clean_pause_is_left_alone():
    t = np.arange(48000 * 2) / 48000
    x = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)               # the fixture's tone: no pause to learn from
    y, rep = R.clean_voice(x)
    assert y is x and rep["cleaned"] is False and "no pause" in rep["why"]


def _hissy(path, seed=0):
    import soundfile as sf
    x, _ = _speechlike(seed=seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, 48000, subtype="FLOAT")
    return x


def test_a19_every_synthetic_line_is_cleaned_and_journaled_and_archival_audio_never(tmp_path):
    film = make_film(tmp_path / "film")
    _hissy(film / "audio" / "L1.wav")                                          # narration, synthetic
    raw = _hissy(film / "audio" / "L2.wav", seed=1)                            # testimony, made archival below
    _edit_play(film, lambda p: next(ln for part in p["parts"] for ln in part.get("lines", []) if ln["id"] == "L2")
               .update(archival_audio=True))
    plan, j = _plan(film, "clean")
    mix, placed = R.build_mix(plan, film, j)
    evs = J.read(j.path)
    by = {ln["id"]: ln for ln in placed["lines"]}
    assert by["L1"]["cleaned"] is True and by["L1"]["floor_after_dbfs"] < by["L1"]["floor_before_dbfs"] - 30
    dec = [e for e in evs if e["kind"] == "decision" and e.get("unit") == "L1" and "cleaned" in e["what"]]
    assert len(dec) == 1 and dec[0]["evidence"]["before"]["snr_db"] and dec[0]["evidence"]["after"]["snr_db"]
    assert dec[0]["evidence"]["floor_after_level_dbfs"] < -80
    vc = [e for e in lints(evs, "voice-clean") if e["unit"] == "L1"]
    assert vc and vc[0]["status"] == "pass"
    # archival audio: not cleaned, not journaled as cleaned, and placed sample for sample
    assert by["L2"]["cleaned"] is None and not [e for e in evs if e.get("unit") == "L2" and "cleaned" in e.get("what", "")]
    at = int(round(by["L2"]["at_s"] * 48000))
    assert np.array_equal(mix[at: at + len(raw)], raw[: len(mix) - at])


def test_a19_ducking_holds_still_under_a_long_bed():
    rate = 48000
    voice = np.zeros(60 * rate, np.float32)
    groups = []
    for g0 in (5.0, 25.0):                                                      # two scenes, 3 lines each, 0.8 s apart
        t = g0
        for _ in range(3):
            for _w in range(5):                                                 # words of 0.3 s with 0.25 s gaps of zero
                voice[int(t * rate): int((t + 0.3) * rate)] = 0.1
                t += 0.55
            t += 0.8 - 0.25
        groups.append((g0, t - 0.8))
    g = R.duck_gain(voice)
    floor = 10 ** (-R.DUCK_DB / 20)
    for a, b in groups:
        inside = g[int((a + R.DUCK_SMOOTH_S / 2) * rate): int((b - R.DUCK_SMOOTH_S / 2) * rate)]   # past the ramps
        assert np.allclose(inside, floor, atol=1e-6), "the bed pumps between words or lines"
        assert g[int((b + 1.0) * rate)] == pytest.approx(1.0) and g[int((a - 0.5) * rate)] == pytest.approx(1.0)
    step = np.abs(np.diff(g.astype(np.float64))).max()
    assert step <= (1 - floor) / (R.DUCK_SMOOTH_S * rate) * 1.01               # a 250 ms ramp, never a jump
    edges = np.flatnonzero(np.abs(np.diff(g.astype(np.float64))) > 1e-9)
    runs = np.split(edges, np.flatnonzero(np.diff(edges) > 1) + 1)
    assert len(runs) == 4                                                       # down and up once per scene, nothing else


def test_a19_a_music_cue_spans_parts_with_fades_at_the_bed_level(tmp_path):
    film = make_film(tmp_path / "film")
    import soundfile as sf
    t = np.arange(48000 * 22) / 48000
    sf.write(str(film / "audio" / "M1.wav"), (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32"), 48000)
    cue = {"id": "M1", "kind": "music", "role": "palette", "source": "test tone", "licence": "CC0", "start_s": 1.0,
           "end_s": 21.0, "fade_in_s": 2.0, "fade_out_s": 3.0, "gain_db": -2.0}
    _edit_play(film, lambda p: p.update(music=[cue]))
    plan, j = _plan(film, "underscore")
    m1 = next(c for c in plan["cues"] if c["id"] == "M1")
    assert m1["_part"] is None and m1["kind"] == "music"
    assert {s["_part"] for s in plan["shots"] if s["f0"] / 24 < 21.0 and s["f1"] / 24 > 1.0} >= {"p-title", "ch-1"}
    _, placed = R.build_mix(plan, film, j)
    pc = next(c for c in placed["cues"] if c["id"] == "M1")
    assert pc["part"] is None and pc["fade_in_s"] == 2.0 and pc["fade_out_s"] == 3.0
    lv = [e for e in J.read(j.path) if e["kind"] == "decision" and e.get("unit") == "M1" and "levelled to" in e["what"]]
    assert lv and lv[0]["evidence"]["target"] == R.MUSIC_LUFS                  # the bed; gain_db is an offset from it
    f = R.cue_fades(np.ones(48000 * 10, np.float32), 10.0, 2.0, 3.0)
    assert f[0] < 1e-3 and f[48000 * 2] == 1.0 and f[48000 * 5] == 1.0 and f[-1] < 1e-3
    assert np.all(np.diff(f[: 48000 * 2]) >= 0) and np.all(np.diff(f[-48000 * 3:]) <= 0)


def test_a19_a_cue_whose_fades_do_not_fit_is_refused(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: p.update(music=[{"id": "M1", "source": "t", "licence": "CC0", "start_s": 1.0, "end_s": 3.0,
                                                "fade_in_s": 2.0, "fade_out_s": 2.0}]))
    with pytest.raises(R.Refused, match=r"cue-span \(M1\)"):
        _plan(film, "bad-fades")


def test_a19_digital_silence_over_4_s_warns_unless_intended():
    rate = 48000
    mix = np.full(20 * rate, 1e-3, np.float32)
    mix[2 * rate: 7 * rate] = 0.0                                               # 5 s of digital zero
    mix[10 * rate: 13 * rate] = 0.0                                             # 3 s: allowed
    runs = R.digital_silence(mix, [])
    assert [(r["from_s"], r["to_s"]) for r in runs] == [(2.0, 7.0)]
    assert R.digital_silence(mix, [(1.5, 7.5)]) == []
    assert R.digital_silence(mix, [(2.0, 4.0)]) == []                           # what is left (3 s) is under the limit


def test_a19_a_shot_or_moment_marked_silence_intended_is_carried_in_the_plan(tmp_path):
    film = make_film(tmp_path / "film")
    _edit_play(film, lambda p: (_shot(p, "S7").update(silence="intended"),
                                p.update(moments=[{"start_s": 1.0, "end_s": 2.0, "silence": "intended"}])))
    plan, _ = _plan(film, "silence")
    s7 = next(s for s in plan["shots"] if s["id"] == "S7")
    assert (s7["f0"] / 24, s7["f1"] / 24) in plan["silences"] and (1.0, 2.0) in plan["silences"]


def test_a17_a18_the_shares_bind_an_event_film_and_the_narration_ceiling_is_gone(plan):
    placed = {"lines": [{"id": "N", "kind": "narration", "at_s": 0.0, "dur_s": plan["duration_s"] * 0.85}]}
    mix = np.full(int(plan["duration_s"] * 48000), 1e-3, np.float32)
    j = J.Journal(film="shares-short")
    assert R.sound_lints(j, plan, mix, placed) == []                            # the fixture is not an event film: warnings
    evs = J.read(j.path)
    assert {e["severity"] for e in lints(evs, "voiceless-floor") + lints(evs, "readings-floor")} == {"warn"}
    assert not [e for e in evs if e["kind"] == "lint" and "narration" in str(e.get("rule"))]   # no narration ceiling lint
    film_plan = dict(plan, runtime_target_s=1200)
    j2 = J.Journal(film="shares-event")
    out = R.sound_lints(j2, film_plan, mix, placed)
    assert any(o.startswith("readings-floor") for o in out) and not any(o.startswith("voiceless-floor") for o in out)
    ok = {"lines": [{"id": "N", "kind": "narration", "at_s": 0.0, "dur_s": plan["duration_s"] * 0.55},
                    {"id": "R", "kind": "reading", "at_s": plan["duration_s"] * 0.55, "dur_s": plan["duration_s"] * 0.32}]}
    assert R.sound_lints(J.Journal(film="shares-ok"), film_plan, mix, ok) == []   # narration 55%: most of the film, allowed
    assert R.sound_lints(J.Journal(film="shares-draft"), film_plan, mix, placed, draft=True) == []



def test_a16_a_lower_thirds_burned_cue_ends_with_the_drawn_span(film, plan, tmp_path):
    f2 = make_film(tmp_path / "film")
    _edit_play(f2, lambda p: next(t for part in p["parts"] for t in part.get("text", []) if t["id"] == "T1").update(end_s=14.0))
    _edit_play(f2, lambda p: next(c for c in p["subtitle_source"] if c["ref"] == "T1").update(end_s=14.0))
    j = J.Journal(film="lt-cue")
    burned = R.build_plan(f2, W=640, H=360, burn_subtitles=True, journal=j)
    lt = next(x for x in burned["lower_thirds"] if x["id"] == "T1")
    cue = next(c for c in burned["subtitles"] if c["ref"] == "T1")
    assert lt["end"] == pytest.approx(8.0 + M.LT_MAX_S) and cue["end"] == lt["end"]


def test_a17_a18_a_short_target_cannot_dodge_the_floors_on_a_long_film(plan):
    placed = {"lines": [{"id": "N", "kind": "narration", "at_s": 0.0, "dur_s": 700.0}]}
    long_film = dict(plan, duration_s=720.0, runtime_target_s=60)            # a 12 min film claiming a 1 min target
    out = R.sound_lints(J.Journal(film="dodge"), long_film, np.full(48000, 1e-3, np.float32), placed)
    assert any(o.startswith("readings-floor") for o in out) and any(o.startswith("voiceless-floor") for o in out)
    no_target = dict(plan, duration_s=720.0, runtime_target_s=None)
    assert R.sound_lints(J.Journal(film="dodge2"), no_target, np.full(48000, 1e-3, np.float32), placed)


def test_a19_a_take_that_stays_noisy_refuses_a_final_render_and_warns_under_draft(tmp_path):
    film = make_film(tmp_path / "film")
    import soundfile as sf
    rng = np.random.default_rng(5)
    x, _ = _speechlike(seed=2)
    x = (x + rng.normal(0, 10 ** (-38 / 20), len(x))).astype(np.float32)      # hiss 38 dB up: no pause clean enough
    sf.write(str(film / "audio" / "L1.wav"), x, 48000, subtype="FLOAT")
    plan, j = _plan(film, "noisy")
    with pytest.raises(R.Refused, match=r"voice-clean and voice-chop \(A19\).*L1"):
        R.build_mix(plan, film, j)
    assert {e["severity"] for e in lints(J.read(j.path), "voice-clean") if e["unit"] == "L1"} == {"block"}
    jd = J.Journal(film="noisy-draft")
    R.build_mix(plan, film, jd, draft=True)
    vc = [e for e in lints(J.read(jd.path), "voice-clean") if e["unit"] == "L1"]
    assert vc and vc[0]["status"] == "fail" and vc[0]["severity"] == "warn"


def test_a19_the_expander_turns_a_breath_down_without_cutting_it():
    """A breath 10 dB over the hiss between two words: an expander keeps it
    (turned down, not gone), the hiss falls by the expander's range."""
    rate = 48000
    x, spans = _speechlike(seed=7, words=2, gap_s=1.2, hiss_db=-66.0)
    a = spans[0][1] + int(0.45 * rate)
    rng = np.random.default_rng(9)
    x[a: a + int(0.25 * rate)] += rng.normal(0, 10 ** (-56 / 20), int(0.25 * rate)).astype(np.float32)   # the breath
    y, rep = R.clean_voice(x)
    br = slice(a + 2400, a + int(0.25 * rate) - 2400)
    assert -40 < _db(y[br]) - _db(x[br]) < -1                                   # kept, quieter
    assert rep["gate"]["kind"] == "downward expander" and 20 <= rep["gate"]["range_db"] <= 30
    assert 0.05 <= rep["gate"]["lookahead_ms"] / 1000 <= 0.08
    assert rep["chopped_audible_share"] <= R.CLEAN_CHOP_MAX_SHARE



def test_a16_refined_an_ai_label_stays_through_a_dissolve(plan):
    """A dissolve joins two shots of one class (GRAMMAR 4.4), so out of an
    AI-GENERATED shot it is into one: the label is full on every frame of it."""
    shots = [{"start": 0.0, "cls": "AI-GENERATED", "label": "AI-generated · context"},
             {"start": 5.0, "cls": "AI-GENERATED", "label": "AI-generated · context"}]
    for f in range(int(4.0 * 24), int(6.5 * 24)):                             # the dissolve's frames on both sides of 5 s
        assert M.mark_state(f / 24, shots)["label_alpha"] == 1.0, f
    assert R.KIND_CLASSES["generated"] == {"AI-GENERATED"}


def test_a16_a_lower_third_cue_that_starts_after_the_drawn_span_is_refused(tmp_path):
    f2 = make_film(tmp_path / "film")
    _edit_play(f2, lambda p: next(c for c in p["subtitle_source"] if c["ref"] == "T1").update(start_s=13.6, end_s=14.5))
    with pytest.raises(R.Refused, match=r"subtitle-lower-third-span \(T1\)"):
        R.build_plan(f2, W=640, H=360, burn_subtitles=True, journal=J.Journal(film="lt-cue-late"))
    R.build_plan(f2, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="lt-cue-tracks"))   # only a burned cue draws


def test_a19_voice_chop_refuses_a_take_with_too_few_pauses_or_an_unsteady_floor():
    rng = np.random.default_rng(11)
    tt = np.arange(48000 * 6) / 48000                                          # 6 s of speech that never pauses: its
    am = 0.05 + 0.95 * np.abs(np.sin(2 * np.pi * 1.7 * tt)) ** 4               # quietest frames are speech 25 dB down
    x = (0.1 * am * sum(np.sin(2 * np.pi * 150 * h * tt) / h for h in range(1, 10))
         + rng.normal(0, 1e-4, len(tt))).astype(np.float32)
    y, rep = R.clean_voice(x)
    assert rep["cleaned"] and rep["pause_share"] < R.CLEAN_PAUSE_MIN_SHARE and not rep["measure_ok"]
    assert rep["measure_why"][0].startswith("the take's floor is within 30 dB of its speech: no pause quiet enough to measure")
    j = J.Journal(film="few-pauses")
    out = R._journal_clean(j, "L9", rep, 0.0)
    assert any("no pause quiet enough to measure" in o for o in out)
    vc = [e for e in lints(J.read(j.path), "voice-chop") if e["unit"] == "L9"][0]
    assert vc["status"] == "fail" and vc["evidence"]["near_floor_frames"] >= 0 and vc["evidence"]["why"]
    x2, spans = _speechlike(seed=5)
    a = spans[0][1] + int(0.05 * 48000)                                        # inside the first pause, after the tail
    x2[a: a + int(0.42 * 48000)] = 0.0                                         # the hiss drops out for 0.42 s: two floors
    _, rep2 = R.clean_voice(x2)
    assert rep2["floor_spread_db"] > R.CLEAN_FLOOR_SPREAD_MAX_DB and any("spread" in w for w in rep2["measure_why"])


def test_a19_voice_clean_reports_the_p90_and_names_its_measure():
    x, _ = _speechlike(seed=6)
    y, rep = R.clean_voice(x)
    j = J.Journal(film="p90")
    R._journal_clean(j, "L8", rep, 3.0)
    ev = [e for e in lints(J.read(j.path), "voice-clean") if e["unit"] == "L8"][0]["evidence"]
    assert "median" in ev["measure"] and "p90" in ev["measure"]
    assert ev["floor_p90_after_level_dbfs"] == pytest.approx(rep["after"]["floor_p90_dbfs"] + 3.0, abs=0.01)


def test_a17_shares_count_voice_kinds_over_their_speech_only(plan):
    placed = {"lines": [
        {"id": "N", "kind": "narration", "line_kind": "narration", "at_s": 0.0, "dur_s": 10.0, "speech_from_s": 1.0, "speech_to_s": 9.0},
        {"id": "R", "kind": "reading", "line_kind": "testimony", "at_s": 10.0, "dur_s": 5.0, "speech_from_s": 10.5, "speech_to_s": 14.5},
        {"id": "X", "kind": "reading", "line_kind": "sfx", "at_s": 15.0, "dur_s": 5.0, "speech_from_s": 15.0, "speech_to_s": 20.0}]}
    sh = R.voice_shares(dict(plan, duration_s=20.0), placed)
    assert sh == {"narration": 0.4, "readings": 0.2, "voiceless": 0.4}


# --------------------------------------------------------------------------
# T1f: the founder's revamp rulings (2026-10-10) and the T1e review advisories
# --------------------------------------------------------------------------


def test_6_1_the_readings_floor_is_20_percent(plan):
    """Founder ruling (2026-10-10): readings carry at least 20% of the runtime, not 30%."""
    assert R.READINGS_FLOOR == 0.20
    d = 1000.0
    event = dict(plan, duration_s=d, runtime_target_s=1200)
    mix = np.full(48000, 1e-3, np.float32)

    def placed(share):
        return {"lines": [{"id": "N", "kind": "narration", "line_kind": "narration", "at_s": 0.0, "dur_s": 500.0,
                           "speech_from_s": 0.0, "speech_to_s": 500.0},
                          {"id": "R", "kind": "reading", "line_kind": "testimony", "at_s": 501.0, "dur_s": d * share,
                           "speech_from_s": 501.0, "speech_to_s": 501.0 + d * share}]}
    assert R.sound_lints(J.Journal(film="floor-21"), event, mix, placed(0.21)) == []          # 21%: passes (it failed at 30%)
    out = R.sound_lints(J.Journal(film="floor-19"), event, mix, placed(0.19))
    assert any(o.startswith("readings-floor") and "'min': 0.2" in o for o in out)


def _still_plan(dur, start=0.0):
    return {"shots": [{"id": "P1", "kind": "archive_still", "start_s": start, "end_s": start + dur},
                      {"id": "M1", "kind": "drawn", "start_s": start + dur, "end_s": start + dur + 25.0}]}


def _spoken(kind, a, b):
    return {"id": f"{kind}-{a}", "kind": "narration" if kind == "narration" else "reading",
            "line_kind": kind, "at_s": a - 0.3, "dur_s": b - a + 0.6, "speech_from_s": a, "speech_to_s": b}


@pytest.mark.parametrize("dur,lines,ok", [
    (10.0, [], True), (10.5, [], False),                                         # A9: 10 s with nothing spoken over it
    (19.9, [("narration", 2.0, 15.0)], True), (20.5, [("narration", 2.0, 15.0)], False),   # A20(a): 20 s under narration
    (14.0, [("narration", 14.2, 18.0)], False),                                  # narration after the cut is not over it
    (29.0, [("testimony", 1.0, 27.0)], True), (31.0, [("testimony", 1.0, 27.0)], False),  # A9: 30 s under a reading
    (25.0, [("sfx", 1.0, 20.0)], False),                                         # only the voice kinds count
    (29.9, [("testimony", -5.0, 0.2)], False),                                   # T1f review: a reading's tail, then 29.7 s silent
    (25.2, [("testimony", -5.0, 0.2)], False),                                   # the tail of a reading plus 25 s of silence
    (19.0, [("narration", 0.0, 3.0), ("narration", 15.0, 19.0)], False),        # narration plus a 12 s pause
    (19.0, [("narration", 0.0, 8.0), ("narration", 8.5, 9.5), ("narration", 9.2, 12.0)], True),  # 7 s silent at the end
    (29.0, [("testimony", 0.5, 10.0), ("narration", 9.0, 19.5)], True),         # overlapping spans merge; 9.5 s silent
    (25.0, [("testimony", -5.0, 0.2), ("narration", 0.5, 24.8)], False),        # T1f review: a reading's 0.2 s tail does not
    (25.0, [("testimony", -5.0, 5.2), ("narration", 5.5, 24.8)], True),         # lift a narrated still to 30 s; 19.8 s unread is fine
    (30.5, [("testimony", 0.0, 30.5)], False),                                   # a hold is at most 30 s, read or not
])
def test_a20a_a_still_holds_by_what_is_spoken_over_it(dur, lines, ok):
    plan = _still_plan(dur)
    placed = {"lines": [_spoken(*ln) for ln in lines]}
    h = R.still_holds(plan, placed)
    assert [x["id"] for x in h] == ["P1"]                                       # archive stills only; a drawn map is not one
    assert h[0]["ok"] is ok, h
    j = J.Journal(film="still-hold")
    out = R.still_hold_lints(j, plan, placed)
    ev = lints(J.read(j.path), "still-hold")[0]
    assert ev["status"] == ("pass" if ok else "fail") and ev["severity"] == "block"
    assert bool(out) is not ok
    assert R.still_hold_lints(J.Journal(film="still-hold-draft"), plan, placed, draft=True) == []   # a warning under --draft


def test_a20a_stills_of_one_asset_are_one_hold_and_a_detail_is_at_most_5_s():
    shots = [{"id": "P1", "kind": "archive_still", "asset": "A", "start_s": 0.0, "end_s": 8.0},
             {"id": "P2", "kind": "archive_still", "asset": "A", "start_s": 8.0, "end_s": 16.0, "transition_in": {"type": "cut"}},
             {"id": "P3", "kind": "archive_still", "asset": "B", "start_s": 16.0, "end_s": 24.0, "transition_in": {"type": "cut"}}]
    h = R.still_holds({"shots": shots}, {"lines": []})
    assert [x["shots"] for x in h] == [["P1", "P2"], ["P3"]]
    assert h[0]["ok"] is False and h[0]["dur_s"] == 16.0 and h[1]["ok"] is True   # 8 + 8 s of one photograph, silent
    dissolved = [dict(shots[0]), dict(shots[1], start_s=7.25, transition_in={"type": "dissolve", "s": 0.75})]
    assert R.still_holds({"shots": dissolved}, {"lines": []})[0]["shots"] == ["P1", "P2"]
    dipped = [dict(shots[0]), dict(shots[1], transition_in={"type": "dip", "s": 0.5})]
    hdip = R.still_holds({"shots": dipped}, {"lines": []})
    assert [x["shots"] for x in hdip] == [["P1", "P2"]] and [x["shots"] for x in hdip[0]["holds"]] == [["P1"], ["P2"]]
    assert hdip[0]["longest_voiceless_s"] == 16.0 and hdip[0]["ok"] is False   # a dip does not reset the 10 s silence
    talk = {"lines": [_spoken("narration", 0.5, 7.5), _spoken("narration", 8.5, 15.5)]}
    assert R.still_holds({"shots": dipped}, talk)[0]["ok"] is True
    narr = {"lines": [_spoken("narration", 0.5, 15.5)]}
    assert R.still_holds({"shots": shots[:2]}, narr)[0]["ok"] is True              # one 16 s hold under narration
    detail = [dict(shots[0]), dict(shots[1], end_s=14.0, preset="DETAIL")]
    hd = R.still_holds({"shots": detail}, narr)[0]
    assert hd["ok"] is False and any("DETAIL P2 6 s" in w for w in hd["why"])
    assert R.still_holds({"shots": [dict(shots[0]), dict(shots[1], end_s=13.0, preset="DETAIL")]}, narr)[0]["ok"] is True


def test_a20a_a_final_render_with_a_silent_still_over_10_s_is_refused(tmp_path):
    film = make_film(tmp_path / "film")

    def stretch(p):                                                            # S5 (no voice over it) runs 11 s, not 3
        shots = [sh for part in p["parts"] for sh in part.get("shots", [])]
        i = next(k for k, sh in enumerate(shots) if sh["id"] == "S5")
        shots[i]["dur_s"] = 11.0
        for sh in shots[i + 1:]:
            sh["start_s"] += 8.0
        for part in p["parts"]:
            for x in part.get("lines", []) + part.get("cues", []) + part.get("text", []):
                if x["start_s"] >= 14.0:
                    x["start_s"] += 8.0
                    if "end_s" in x:
                        x["end_s"] += 8.0
        for c in p["subtitle_source"]:
            if c["start_s"] >= 14.0:
                c["start_s"] += 8.0
                c["end_s"] += 8.0
    _edit_play(film, stretch)
    from studio.engine.render import render
    with pytest.raises(R.Refused, match=r"still-hold \(S5: 11 s with no voice"):
        render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, encode_preset="veryfast", audio_only=True)


def test_a20a_the_still_hold_lint_runs_on_the_fixture_and_passes(plan):
    placed = {"lines": [_spoken("narration", 5.0, 7.0)]}
    holds = R.still_holds(plan, placed)
    assert {h["id"] for h in holds} == {"S3", "S4", "S5"} and all(h["ok"] for h in holds)
    assert next(h for h in holds if h["id"] == "S3")["longest_voiceless_s"] < 4.0          # L1 speaks over S3


def test_a19_a_zero_padded_noisy_take_now_fails_voice_clean():
    """T1e review: the quietest 10% of frames were the digital zero padding a
    take's ends, so a hissy take measured a floor of -300 dBFS and passed.
    The floor is now measured inside the take's live span."""
    rng = np.random.default_rng(5)
    x, _ = _speechlike(seed=2)
    x = (x + rng.normal(0, 10 ** (-38 / 20), len(x))).astype(np.float32)      # hiss 38 dB up: no pause clean enough
    pad = np.zeros(int(1.5 * 48000), np.float32)
    padded = np.concatenate([pad, x, pad])                                     # zero frames: 1.5 + 1.5 of 9.2 s, over 10%
    _, rep = R.clean_voice(padded)
    assert rep["before"]["floor_dbfs"] > -60                                   # the hiss, not the padding (-300 before)
    gain, _ = R.level_gain(padded, R.DIALOGUE_LUFS)
    j = J.Journal(film="zero-padded")
    out = R._journal_clean(j, "LZ", rep, gain)
    vc = [e for e in lints(J.read(j.path), "voice-clean") if e["unit"] == "LZ"][0]
    assert vc["status"] == "fail" and any("voice-clean" in o for o in out)
    # the same take unpadded measures the same floor, within a dB
    _, rep0 = R.clean_voice(x)
    assert rep["before"]["floor_dbfs"] == pytest.approx(rep0["before"]["floor_dbfs"], abs=1.0)


def test_a19_a_clean_take_silent_between_words_still_passes():
    """Digital silence inside the live span (a take that is truly silent in its
    pauses) is still the floor: only the padding at the ends is set aside."""
    x, spans = _speechlike(seed=4, hiss_db=-200.0)                              # no hiss at all
    x = np.concatenate([np.zeros(48000, np.float32), x, np.zeros(48000, np.float32)])
    _, rep = R.clean_voice(x)
    gain, _ = R.level_gain(x, R.DIALOGUE_LUFS)
    assert rep["cleaned"] and rep["after"]["floor_dbfs"] + gain < R.CLEAN_FLOOR_MAX_DBFS
    assert R.live_span(x)[0] == 48000 + 24000                                    # the pad and the take's own lead-in


def test_t1e_review_the_speech_span_is_measured_after_the_placement_gain():
    """A sample at -59 dBFS in the take counts as speech at 0 dB, but a hushed
    line is placed 2 dB down, where the mix hears it at -61: not speech."""
    x = np.zeros(48000, np.float32)
    x[1000:2000] = 0.5
    x[30000:31000] = 10 ** (-59 / 20)                                           # a quiet tail
    assert R.speech_active(x, 0.0)[-1] == 30999
    assert R.speech_active(x, R.MOOD_OFFSET_DB["hushed"])[-1] == 1999


def test_a16_the_shape_check_cannot_be_reached_by_any_picture_at_the_film_resolutions():
    """T1e review: the guarantee, stated exactly. For every resolution the
    engine renders and every pair of classes that share a hue and differ in
    shape, some probe has a channel where no bare value from 0 to 255 brings
    the wrong class's composite within 1 of the drawn class's. So whatever
    the picture under the glyph, a wrong shape fails the lint."""
    for height, (W, H) in R.RESOLUTIONS.items():
        plan = {"W": W, "H": H}
        probes = M.glyph_shape_probes(M.Layout(W, H))
        for drawn in M.GLYPH_SHAPE:
            for claimed in M.GLYPH_SHAPE:
                if M.MARK_HUE[claimed] != M.MARK_HUE[drawn] or M.GLYPH_SHAPE[claimed] == M.GLYPH_SHAPE[drawn]:
                    continue
                guarded = []
                for at in probes:
                    for ch in range(3):
                        reach = []
                        for v in range(256):
                            bare = [0, 0, 0]
                            bare[ch] = v
                            d = abs(int(R.expected_probe(plan, drawn, at, bare)[ch]) - int(R.expected_probe(plan, claimed, at, bare)[ch]))
                            if d <= 1:
                                reach.append(v)
                        if not reach:
                            guarded.append((at, ch))
                assert guarded, (height, drawn, claimed)


def _spread_take(hiss_db, seed=5):
    """A take whose hiss drops out for 0.42 s inside its first pause: its floor frames spread far over 6 dB."""
    x, spans = _speechlike(seed=seed, hiss_db=hiss_db)
    a = spans[0][1] + int(0.05 * 48000)
    x[a: a + int(0.42 * 48000)] = 0.0
    return x


def test_t1f_an_unsteady_floor_takes_the_denoise_only_path_and_passes_when_low():
    x = _spread_take(-100.0)                                                    # spread far over 6 dB, hiss far under -80
    y, rep = R.clean_voice(x)
    y_dn, _ = R.spectral_denoise(x)
    assert rep["path"] == "denoise-only" and np.array_equal(y, y_dn) and rep["gate"] is None
    assert "not one steady floor" in rep["first_pass"]["why"] and rep["first_pass"]["floor_spread_db"] == rep["floor_spread_db"]
    gain, _ = R.level_gain(y, R.DIALOGUE_LUFS)
    j = J.Journal(film="denoise-only-low")
    assert R._journal_clean(j, "LQ", rep, gain) == []
    evs = J.read(j.path)
    dec = [e for e in evs if e["kind"] == "decision" and e.get("unit") == "LQ" and "denoise alone" in e["what"]]
    assert len(dec) == 1 and dec[0]["evidence"]["first_pass"]["floor_spread_db"] > R.CLEAN_FLOOR_SPREAD_MAX_DB
    vc = [e for e in lints(evs, "voice-chop") if e["unit"] == "LQ"][0]
    assert vc["status"] == "pass" and vc["evidence"]["path"] == "denoise-only" and vc["evidence"]["floor_referenced"]["share"] == 0.0
    assert vc["evidence"]["speech_chop_share"] <= R.CLEAN_CHOP_MAX_SHARE
    assert vc["evidence"]["floor_spread_db"] == rep["floor_spread_db"]                      # journaled, not refused
    assert [e for e in lints(evs, "voice-clean") if e["unit"] == "LQ"][0]["status"] == "pass"


def test_t1f_an_unsteady_take_with_audible_hiss_still_refuses_on_voice_clean():
    """The hiss (-60 dBFS) drops to digital zero inside a pause: the floor's
    median is zero, so the median of the floor frames that are not digital
    silence is what voice-clean must hold under -80."""
    x = _spread_take(-60.0)
    y, rep = R.clean_voice(x)
    assert rep["path"] == "denoise-only" and rep["after"]["floor_dbfs"] < -200
    gain, _ = R.level_gain(y, R.DIALOGUE_LUFS)
    j = J.Journal(film="denoise-only-loud")
    out = R._journal_clean(j, "LA", rep, gain)
    vc = [e for e in lints(J.read(j.path), "voice-clean") if e["unit"] == "LA"][0]
    assert vc["status"] == "fail" and vc["evidence"]["floor_heard_after_level_dbfs"] > R.CLEAN_FLOOR_MAX_DBFS
    assert any("voice-clean" in o and "denoise only" in o for o in out)


def test_t1f_a_steady_hiss_take_still_gets_the_expander():
    x, _ = _speechlike(seed=6)                                                  # Tara-like: steady hiss at -60
    y, rep = R.clean_voice(x)
    assert rep["path"] == "expander" and rep["first_pass"] is None and rep["gate"]["kind"] == "downward expander"
    gain, _ = R.level_gain(y, R.DIALOGUE_LUFS)
    j = J.Journal(film="steady")
    assert R._journal_clean(j, "LS", rep, gain) == []
    assert lints(J.read(j.path), "voice-chop")[0]["evidence"]["path"] == "expander"


def test_t1f_an_e_r01_like_take_with_too_few_pauses_is_refused_whatever_its_floor():
    rng = np.random.default_rng(11)
    tt = np.arange(48000 * 6) / 48000
    am = 0.05 + 0.95 * np.abs(np.sin(2 * np.pi * 1.7 * tt)) ** 4
    x = (0.1 * am * sum(np.sin(2 * np.pi * 150 * h * tt) / h for h in range(1, 10))
         + rng.normal(0, 1e-4, len(tt))).astype(np.float32)
    _, rep = R.clean_voice(x)
    assert rep["pause_why"]
    for lift in (0.0, -80.0):                                                       # audible, and pushed far under -80
        j = J.Journal(film=f"few-pauses-{int(-lift)}")
        out = R._journal_clean(j, "LR", rep, lift)
        assert any("no pause quiet enough to measure" in o for o in out)
        assert lints(J.read(j.path), "voice-chop")[0]["status"] == "fail"


def _hiss_in_pauses(burst_db, gaps=6, seed=3):
    """The reviewer's attack.py: a clean take with white hiss filling its pauses after each word's tail."""
    x, spans = _speechlike(seed=seed, hiss_db=-110.0)
    rng = np.random.default_rng(9)
    for i in range(gaps):
        a = spans[i][1] + int(0.12 * 48000)
        b = spans[i + 1][0] if i + 1 < len(spans) else len(x)
        x[a:b] += rng.normal(0, 10 ** (burst_db / 20), b - a).astype(np.float32)
    return x


def _one_quiet_stretch(burst_db, quiet_s, seed=3):
    """The reviewer's attack2.py: white hiss everywhere but one 0.4 to 0.5 s stretch at -92 dBFS (an unsteady floor)."""
    x, spans = _speechlike(seed=seed, hiss_db=-110.0)
    rng = np.random.default_rng(9)
    hiss = rng.normal(0, 10 ** (burst_db / 20), len(x)).astype(np.float32)
    q0 = spans[2][1] + int(0.12 * 48000)
    q1 = q0 + int(quiet_s * 48000)
    hiss[q0:q1] = rng.normal(0, 10 ** (-92 / 20), q1 - q0)
    return x + hiss


def _verdict(x, name):
    y, rep = R.clean_voice(x)
    g, _ = R.level_gain(y, R.DIALOGUE_LUFS)
    j = J.Journal(film=name)
    out = R._journal_clean(j, "LT", rep, g)
    evs = J.read(j.path)
    return rep, out, lints(evs, "voice-clean")[-1], lints(evs, "voice-chop")[-1]


@pytest.mark.parametrize("quiet_s,burst_db", [(0.4, -55), (0.4, -62), (0.5, -55)])
def test_t1f_review_denoise_only_cannot_pass_hiss_in_the_pauses(quiet_s, burst_db):
    """Blocker 1 (attack2.py): one quiet stretch made the floor unsteady, the
    take went denoise-only and passed with its pauses at -53 dBFS levelled."""
    rep, out, vc, _ = _verdict(_one_quiet_stretch(burst_db, quiet_s), f"attack2-{quiet_s}-{-burst_db}")
    assert rep["path"] == "denoise-only"
    assert vc["status"] == "fail" and vc["evidence"]["true_pause_after_level_dbfs"] > R.CLEAN_FLOOR_MAX_DBFS
    assert any("true pauses" in o for o in out)


@pytest.mark.parametrize("burst_db", [-55, -60, -65])
def test_t1f_review_the_expander_cannot_pass_hiss_in_every_pause(burst_db):
    """attack.py: a steady floor of -110 between words that are each followed
    by white hiss. The quietest 10% stayed clean, so voice-clean passed; the
    true pauses hear the hiss. At -55 the hiss is within 30 dB of the speech,
    and only its flatness (white noise) keeps it from counting as speech."""
    rep, out, vc, _ = _verdict(_hiss_in_pauses(burst_db), f"attack-{-burst_db}")
    assert rep["path"] == "expander" and vc["status"] == "fail"
    assert vc["evidence"]["true_pause_after_level_dbfs"] > R.CLEAN_FLOOR_MAX_DBFS


def test_t1f_review_true_pauses_fall_back_to_the_floor_p90_when_there_are_too_few(film):
    import soundfile as sf
    x, _ = sf.read(str(film / "audio" / "L2.wav"), dtype="float32")             # a 1.2 s tone with one 0.2 s pause
    rep, out, vc, _ = _verdict(x, "few-true-pauses")
    assert rep["true_pause_frames"] < R.CLEAN_TRUE_PAUSE_MIN and vc["evidence"]["true_pause_fallback_p90"] is True
    assert vc["status"] == "pass" and out == []


def test_t1f_review_voice_chop_is_speech_referenced_on_both_paths():
    x, _ = _speechlike(seed=6)
    _, rep = R.clean_voice(x)
    assert rep["path"] == "expander" and rep["speech_chop_share"] <= R.CLEAN_CHOP_MAX_SHARE
    old_only = dict(rep, chopped_audible_share=0.05, chopped_audible=99)          # the floor-referenced share: journal only
    j = J.Journal(film="chop-old")
    assert not [o for o in R._journal_clean(j, "LO", old_only, 0.0) if "voice-chop" in o]
    ch = lints(J.read(j.path), "voice-chop")[0]
    assert ch["status"] == "pass" and ch["evidence"]["floor_referenced"]["share"] == 0.05
    for path in ("expander", "denoise-only"):
        bad = dict(rep, path=path, speech_chop_share=0.03, near_speech_cut=9, near_speech_frames=300,
                   first_pass=rep.get("first_pass") or {"why": "test"})
        j2 = J.Journal(film=f"chop-{path}")
        out = R._journal_clean(j2, "LC", bad, 0.0)
        assert any("within 30 dB of the speech cut over 3 dB" in o for o in out), path
        assert lints(J.read(j2.path), "voice-chop")[0]["status"] == "fail"
