import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

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
                 "loudnorm-linear", "mark-class-valid", "clip-in-out"):
        found = lints(evs, rule)
        assert found, rule
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


def test_card_plate_is_the_small_void_document_plate(plan):
    # CARD and imagery plates differ in size (BRAND-KIT 5: 2.4% vs 3.1% of height).
    L = M.Layout(plan["W"], plan["H"])
    card = M._mark_plate(L, "CARD", "", M.Fonts())
    arch = M._mark_plate(L, "DRAWN", "from PIL test image, test fixture", M.Fonts())
    assert card.height < arch.height
    f_card, f_arch = plan["shots"][0]["f0"] + 5, plan["shots"][2]["f0"] + 30
    x, y = R.mark_probe(plan)
    a = R.render_frame(plan, f_card)
    b = R.render_frame(plan, f_arch)
    bar_h = lambda arr, hue: int(np.sum(np.all(np.abs(arr[:, x].astype(int) - np.array(hue)) <= 2, axis=1)))
    assert bar_h(a, M.MARK_HUE["CARD"]) == card.height
    assert bar_h(b, M.MARK_HUE["DRAWN"]) == arch.height


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
    assert by["S3"]["mark"] == {"class": "DRAWN", "detail": "from PIL test image, test fixture"}
    assert by["S3"]["ledger_id"] == "FX-STILL-A" and by["S3"]["licence"] == "CC0" and by["S3"]["credit"]
    assert by["S3"]["test_fixture"] is True
    assert by["S4"]["licence"] == "CC0" and by["S4"]["transition_in"] == {"type": "dissolve", "s": 0.75}
    assert by["S6"]["mark"]["class"] == "DRAWN" and by["S6"]["test_fixture"] is True
    assert by["S6"]["conform"]["method"] == "drop" and by["S6"]["resampler"]["method"].startswith("lanczos")
    assert by["S1"]["mark"]["class"] == "CARD"
    assert abs(sum(doc["share"].values()) - 1) < 1e-3 and doc["share"]["AI-GENERATED"] == 0
    assert doc["marks"][0]["from_s"] == 0 and doc["marks"][-1]["to_s"] == 24.75
    assert doc["readings"][0]["credit"] == "Read by a computer voice. No recording of Fixture speaker was used."
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
        assert image[wm[0]:wm[1], wm[2]:wm[3]].max() > 120
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
    card = M._mark_plate(L, "CARD", "", M.Fonts())
    x0, y0 = int(round(L.w(M.MARK["x"]))), int(round(L.h(M.MARK["y"])))
    mask = np.ones(arr.shape[:2], bool)
    mask[y0:y0 + card.height, x0:x0 + card.width] = False
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
# Re-review: probe the crossfade, synthetic by generator, loudnorm fallback, long dips
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


def test_loudnorm_dynamic_fallback_is_flagged(tmp_path):
    import soundfile as sf
    t = np.arange(48000 * 6) / 48000
    x = (0.01 * np.sin(2 * np.pi * 300 * t)).astype("float32")      # about -43 dBFS
    x[48000 * 3] = 0.99                                             # one near full-scale click
    sf.write(str(tmp_path / "mix.wav"), x, 48000, subtype="FLOAT")
    loud = R.loudnorm(tmp_path / "mix.wav", tmp_path / "norm.wav")
    assert loud["normalised"] and loud["normalization_type"] == "dynamic" and loud["linear"] is False
    j = J.Journal(film="loud")
    R.loudness_lints(j, loud)
    evs = J.read(j.path)
    flag = lints(evs, "loudnorm-linear")[0]
    assert flag["status"] == "fail" and flag["severity"] == "warn" and "dynamic" in flag["evidence"]["why"]
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
