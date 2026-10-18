"""A41 TOUR (founder, 2026-10-17): every still fills 16:9 on every frame and
the camera tours it along a path of stops timed to the narration. Pure
geometry on tiny synthetic sizes first, then the plan-time lints on the
fixture film (no frame is rendered)."""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import render as R
from studio.engine import tour as T
from conftest import make_film

W, H = 640, 360
A = W / H
PORTRAIT, WIDE, LANDSCAPE43 = (1200, 1600), (3200, 1000), (1600, 1200)
ROOT = Path(__file__).resolve().parents[2]


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


def cam_for(shot, size, **kw):
    shot = dict({"id": "X", "kind": "archive_still", "_dur": 8.0, "_item": {"people": False}}, **shot)
    return R.still_camera(shot, size, W, H, **kw)


def frames(cam, dur, hz=24.0):
    n = int(math.floor(dur * hz))
    return [OV.framing_at(cam, k / hz, dur) for k in range(n + 1)]


def fills(size, f, clamp="image"):
    src, dst = M.still_view(size, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp=clamp)
    inside = src[0] >= -0.5 and src[1] >= -0.5 and src[2] <= size[0] + 0.5 and src[3] <= size[1] + 0.5
    return dst == (0.0, 0.0, float(W), float(H)) and inside


# --------------------------------------------------------------------------
# The path: stops at their times, never below the fill, creep on holds
# --------------------------------------------------------------------------

def test_stops_are_hit_at_their_times():
    path = [{"t": 0.0, "x": 0.5, "y": 0.2, "z": 1.0}, {"t": 3.0, "x": 0.3, "y": 0.6, "z": 1.4},
            {"t": 6.0, "x": 0.7, "y": 0.5, "z": 1.1}]
    cam = cam_for({"camera": path, "_dur": 6.0}, LANDSCAPE43)
    assert cam["preset"] == "TOUR" and cam["macro"] == "PATH" and not cam["problems"]
    for st in path:
        want = T.to_frame(T.settle(st, LANDSCAPE43, A), LANDSCAPE43, W, H)
        got = OV.framing_at(cam, st["t"], 6.0)
        assert got == pytest.approx(want, abs=1e-9), st


def test_a_still_never_goes_below_the_fill_on_any_frame():
    for size in (PORTRAIT, WIDE, LANDSCAPE43, (1920, 1080)):
        for shot in ({}, {"preset": "HOLD"}, {"preset": "PULL"}, {"preset": "DRIFT", "direction": "rl"},
                     {"preset": "TILT"}, {"preset": "FILL", "focus": [0.2, 0.9]}, {"preset": "DETAIL", "region": {"x": 0.9, "y": 0.1}},
                     {"camera": [{"t": 0, "x": 0, "y": 0, "z": 1}, {"t": 4, "x": 1, "y": 1, "z": 1.5}]}):
            cam = cam_for(dict(shot, _dur=8.0), size)
            assert cam["clamp"] == "image" and cam["opens_whole"] is False
            for f in frames(cam, 8.0):
                assert fills(size, f), (size, shot, f)
            assert cam["tour"]["z_min"] >= 1.0 - 1e-12


def test_a_stop_below_the_fill_is_refused_as_written():
    cam = cam_for({"camera": [{"t": 0, "z": 0.8}]}, LANDSCAPE43)
    assert any("below the fill" in p for p in cam["problems"])
    assert all(fills(LANDSCAPE43, f) for f in frames(cam, 8.0))     # and it is still drawn at the fill


def test_a_long_hold_keeps_creeping_and_a_short_one_may_rest():
    cam = cam_for({"preset": "HOLD", "_dur": 6.0}, (1920, 1080))
    fs = frames(cam, 6.0)
    assert all(a != b for a, b in zip(fs[1:-1], fs[2:-1]))           # no frozen frame
    assert fs[-1]["z"] / fs[0]["z"] == pytest.approx(1 + M.TOUR["creep_scale_per_s"] * 6.0, rel=1e-6)
    tl = T.build([{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5}], 1.2, (1920, 1080), A, 2.0)
    assert [g["kind"] for g in tl["segments"]] == ["creep"]              # A54: a still's own edges always creep
    tl = T.build([{"t": 0.0, "z": 1.3, "x": 0.3, "y": 0.5}, {"t": 2.0, "z": 1.3, "x": 0.5, "y": 0.5, "hold": 1.2},
                  {"t": 4.0, "z": 1.3, "x": 0.7, "y": 0.5}], 6.0, LANDSCAPE43, A, 2.0)
    assert [g["kind"] for g in tl["segments"]][:2] == ["move", "hold"]  # a short hold between legs may rest
    # a stop held in the middle of a path creeps too, then the next move starts from where it crept to
    tl = T.build([{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "hold": 3.0}, {"t": 5.0, "z": 1.3, "x": 0.3, "y": 0.5}],
                 5.0, LANDSCAPE43, A, 2.0)
    assert [g["kind"] for g in tl["segments"]] == ["creep", "move"]
    assert tl["segments"][1]["a"] == tl["segments"][0]["b"]


def test_creep_at_the_cap_drifts_instead_and_no_zoom_never_scales():
    size = (1200, 900)                                              # 4:3: room to drift vertically at the fill
    p = T.settle({"z": 1.0, "x": 0.5, "y": 0.5}, size, A)
    q, how = T.creep(p, 4.0, size, A, zmax=1.0)
    assert how == "drift" and q["z"] == 1.0 and q["y"] != p["y"]
    q, how = T.creep(p, 4.0, size, A, zmax=2.0, no_zoom=True)
    assert how == "drift" and q["z"] == 1.0


# --------------------------------------------------------------------------
# Macros and the default tour
# --------------------------------------------------------------------------

@pytest.mark.parametrize("preset", ["HOLD", "PUSH", "PULL", "DRIFT", "TILT", "DETAIL"])
def test_each_macro_reproduces_its_old_preset_endpoints(preset):
    frm, to = R.PRESETS[preset]
    st = T.macro_stops(preset, {}, 6.0)
    for got, want in zip((st[0], st[-1]), (frm, to)):
        assert got["z"] == pytest.approx(want["z"])
        assert got["x"] == pytest.approx(want.get("x", 0.5)) and got["y"] == pytest.approx(want.get("y", 0.5))
    assert st[0]["t"] == 0.0 and st[-1]["t"] == 6.0


def test_macros_keep_direction_region_from_to_and_focus():
    d = T.macro_stops("DRIFT", {"direction": "rl"}, 5.0)
    assert d[0]["x"] == pytest.approx(2 / 3) and d[-1]["x"] == pytest.approx(1 / 3)
    t = T.macro_stops("TILT", {"direction": "up"}, 5.0)
    assert t[0]["y"] == 1.0 and t[-1]["y"] == 0.0
    det = T.macro_stops("DETAIL", {"region": {"x": 0.2, "y": 0.7}}, 4.0)
    assert det[0]["x"] == det[-1]["x"] == 0.2 and det[0]["z"] == 1.3
    p = T.macro_stops("PUSH", {"to": {"z": 1.2, "x": 0.4}}, 4.0)
    assert p[-1]["z"] == 1.2 and p[-1]["x"] == 0.4
    f = T.macro_stops("FILL", {"focus": [0.3, 0.2]}, 4.0)
    assert f[0] == pytest.approx(dict(f[0], z=1.0, x=0.3, y=0.2))


def test_the_default_tour_tilts_a_portrait_and_pans_a_wide_picture():
    # A47 retired the geometric tilt: the default pass sweeps from the end furthest from the subject to it, so a
    # portrait whose subject sits low tilts top to bottom, and a wide picture whose subject sits right pans left to
    # right; with no subject it holds the whole, upper-weighted (test_cine2_subject.py)
    low = {"name": "subject", "x": 0.3, "y": 0.8, "w": 0.4, "h": 0.15, "kind": "place"}
    cam = cam_for({"_dur": 16.0, "_item": {"people": False, "roi": [low]}}, PORTRAIT)   # time for the whole sweep
    assert cam["macro"] == "DEFAULT"
    a, b = OV.framing_at(cam, 0.0, 16.0), OV.framing_at(cam, 16.0, 16.0)
    assert a["y"] < b["y"]                                            # top to bottom, toward the subject
    src0, _ = M.still_view(PORTRAIT, M.Layout(W, H), z=a["z"], cx=a["x"], cy=a["y"], clamp="image")
    assert src0[1] == pytest.approx(0, abs=0.5)                       # opens at the far end (the top) ...
    assert src0[2] - src0[0] == pytest.approx(PORTRAIT[0], abs=0.5)   # ... at the fill: the full width
    right = {"name": "subject", "x": 0.85, "y": 0.3, "w": 0.1, "h": 0.3, "kind": "place"}
    cam = cam_for({"_dur": 8.0, "_item": {"people": False, "roi": [right]}}, WIDE)
    a, b = OV.framing_at(cam, 0.0, 8.0), OV.framing_at(cam, 8.0, 8.0)
    assert a["x"] < b["x"]                                            # left to right, toward the subject
    cam = cam_for({"_dur": 8.0}, (1920, 1080))                       # the frame's own shape: the fill, creeping
    assert [g["kind"] for g in cam["tour"]["segments"]] == ["creep"]


def test_the_default_tour_shows_the_whole_picture():
    # (2089, 1186) is 0.9% narrower than 16:9: the fill alone hides a 11 px strip, so the pass still tilts (Partition S-029)
    assert T.long_axis((2089, 1186), A) == "y" and T.long_axis((1920, 1080), A) is None
    for size in (PORTRAIT, WIDE, LANDSCAPE43, (2089, 1186), (3388, 1905)):
        tl = T.build(T.default_stops(size, A, 8.0), 8.0, size, A, 2.0)
        assert T.covered(T.windows_of(tl), T.whole_box(size, A), size)      # (3388, 1905): 1.3 px hidden, counted shown


# --------------------------------------------------------------------------
# Anchors: at a narration word
# --------------------------------------------------------------------------

LINE = {"id": "N1", "kind": "narration", "start": 10.0, "dur": 4.0, "text": "The road to Bengal ran past the mill."}


def test_at_anchors_a_stop_to_a_word_index_or_a_cue():
    words = T.shot_words([LINE], 9.0, 17.0)
    t_bengal = next(w["t"] for w in words if w["n"] == "bengal")
    assert T.anchor_time(3, words) == pytest.approx(t_bengal)
    assert T.anchor_time("Bengal", words) == pytest.approx(t_bengal)
    assert T.anchor_time("the mill", words) == pytest.approx(next(w["t"] for w in words[6:] if w["n"] == "the"))
    assert T.anchor_time("Calcutta", words) is None and T.anchor_time(40, words) is None
    path = [{"t": 0, "z": 1}, {"at": "Bengal", "x": 0.3, "y": 0.6, "z": 1.3}]
    cam = cam_for({"camera": path, "_dur": 8.0, "start_s": 9.0}, LANDSCAPE43, words=words)
    st = cam["tour"]["stops"][1]
    assert st["t"] == pytest.approx(t_bengal - 9.0)
    assert OV.framing_at(cam, st["t"], 8.0) == pytest.approx(T.to_frame(st, LANDSCAPE43, W, H))
    bad = cam_for({"camera": [{"t": 0}, {"at": "Calcutta"}], "_dur": 8.0, "start_s": 9.0}, LANDSCAPE43, words=words)
    assert any(p.startswith("anchor:") for p in bad["problems"])


def test_the_tour_resolver_visits_each_region_when_it_is_named():
    roi = [{"name": "the mill", "x": 0.6, "y": 0.5, "w": 0.2, "h": 0.2},
           {"name": "road", "cue": "Bengal", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3},
           {"name": "sky", "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.2}]
    words = T.shot_words([LINE], 9.0, 17.0)
    st = T.tour_stops(roi, words, 9.0, 8.0, LANDSCAPE43, A, 2.0)
    assert [s.get("roi") for s in st] == [None, "road", "the mill"]          # sky is never named
    t_bengal = next(w["t"] for w in words if w["n"] == "bengal") - 9.0
    assert st[0]["t"] == 0.0 and st[1]["t"] == pytest.approx(t_bengal)
    w = T.window(LANDSCAPE43, A, st[2]["z"], st[2]["x"], st[2]["y"])
    assert w[0] <= 0.6 * 1600 and w[2] >= 0.8 * 1600                       # the region is whole in frame
    assert T.tour_stops(roi, [], 9.0, 8.0, LANDSCAPE43, A, 2.0) is None      # nothing named: the default tour


def test_the_js_tour_helper_agrees_with_the_engine():
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is needed for the tour helper (the builders run on it)")
    item = {"roi": [{"name": "the mill", "x": 0.6, "y": 0.5, "w": 0.2, "h": 0.2},
                    {"name": "road", "cue": "Bengal", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}]}
    words = T.shot_words([LINE], 9.0, 17.0)
    js = ("import { tour } from " + json.dumps((ROOT / "studio" / "tour.mjs").as_uri()) + ";"
          f"const item = {json.dumps(item)};"
          f"const words = {json.dumps([{'w': w['w'], 't': w['t']} for w in words])};"
          f"console.log(JSON.stringify([tour(item, {{narration: {json.dumps(LINE['text'])}}}),"
          " tour(item, {words, start_s: 9}), tour(item), tour(item, {narration: 'nothing here'}),"
          " tour(item, {words, start_s: 9, dur_s: 3.0})]));")
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout
    by_cue, timed, bare, none, short = json.loads(out)
    # a region named too late to reach is left out, in both
    py_short = T.tour_stops(item["roi"], words, 9.0, 3.0, LANDSCAPE43, A, 2.0)
    assert [s.get("roi") for s in short] == [s.get("roi") for s in py_short] == [None, "road"]
    assert by_cue == [{"t": 0, "z": 1, "x": 0.5, "y": 0.5}, {"at": "Bengal", "roi": "road"}, {"at": "the mill", "roi": "the mill"}]
    assert bare == "tour" and none is None
    py = T.tour_stops(item["roi"], words, 9.0, 8.0, LANDSCAPE43, A, 2.0)
    roi = {r["name"]: r for r in item["roi"]}
    for path in (by_cue, timed):
        stops, probs = T.parse_path(path, 8.0, words, 9.0, roi, LANDSCAPE43, A, 2.0)
        assert not probs
        assert [(round(s["t"], 2), round(s["x"], 4), round(s["y"], 4), round(s["z"], 4)) for s in stops] == \
               [(round(s["t"], 2), round(s["x"], 4), round(s["y"], 4), round(s["z"], 4)) for s in py]


# --------------------------------------------------------------------------
# Guards, pure
# --------------------------------------------------------------------------

def test_a_thin_box_between_sample_lines_is_judged_exactly():
    size = (3200, 1000)                                                     # a panorama: the fill is 1778 px wide
    hold = T.build(T.macro_stops("HOLD", {}, 6.0), 6.0, size, A, 2.0)
    wins = T.windows_of(hold)
    x0 = min(w[0] for w in wins) / 3200
    x1 = max(w[2] for w in wins) / 3200
    assert 0.2 < x0 < 0.25 and 0.75 < x1 < 0.82
    line = (0.0, 0.515, 1.0, 0.528)                                         # a row of people across the whole width
    assert not T.covered(wins, line, size) and not T.seen(wins, line, size)
    people = {"boxes": [{"name": "the row", "box": line}], "unlocated": 0, "known": True}
    assert not T.people_check(wins, people, size)["ok"]
    assert T.coverage(wins, size) == pytest.approx((x1 - x0), abs=0.01)
    assert T.covered(wins, (0.3, 0.515, 0.7, 0.528), size)


@pytest.mark.parametrize("words,nobody", [(False, True), ([], True), ("none", True), ("None visible", True),
                                          ("none resolvable", True), ("no one named; three refugees", False),
                                          ("nobody identifiable; a guard at left", False),
                                          ("empty street but for a policeman", False), ("none named", False)])
def test_only_a_closed_set_of_words_means_nobody(words, nobody):
    assert (T.people_of({"people": words})["unlocated"] == 0) is nobody


def test_a_720p_delivery_frames_exactly_as_the_1080p_master():
    size = (1400, 980)                                    # at 1.6x on the master a DETAIL (1.3) stops at 1.167
    shot = {"id": "X", "kind": "archive_still", "_dur": 6.0, "_item": {"people": False}, "preset": "DETAIL",
            "_fill_max_upscale": 1.6}
    a = R.still_camera(dict(shot), size, 1280, 720)
    b = R.still_camera(dict(shot), size, 1920, 1080)
    assert a["capped"] and b["capped"] and a["tour"]["z_max"] == pytest.approx(b["tour"]["z_max"])
    for t in (0.0, 1.3, 3.0, 6.0):
        assert T.at(a["tour"], t) == pytest.approx(T.at(b["tour"], t))


def test_a_still_softness_cap_is_3x_unless_the_film_states_one():
    """Founder, 2026-10-17: "fill the frame, soft is acceptable up to 3x"."""
    assert R.STILL_MAX_UPSCALE == 3.0 and R.FILL_MAX_UPSCALE == 1.6           # a clip's FILL keeps 1.6
    size = (800, 600)                                                       # 2.4x to fill the 1080p master
    shot = {"id": "X", "kind": "archive_still", "_dur": 6.0, "_item": {"people": False}, "preset": "HOLD"}
    cam = R.still_camera(dict(shot), size, 1920, 1080)
    assert cam["preset"] == "TOUR" and cam["zcap"] == pytest.approx(3.0 * 800 / 1920)
    assert cam["zcap"] >= 1.0                                               # it fills: no exception needed
    assert R.still_camera(dict(shot, _fill_max_upscale=1.6), size, 1920, 1080)["zcap"] < 1.0


def test_a_still_held_whole_creeps_inside_its_own_shape():
    """Founder, 2026-10-17: a still under fill_exception is never frozen: whole on its first frame, then a gentle
    push inside its pillarboxed shape, no further than whole_creep_max."""
    size = (300, 420)
    shot = {"id": "X", "kind": "archive_still", "_dur": 8.0, "_item": {"people": False},
            "fill_exception": "a small scan, held whole"}
    cam = R.still_camera(shot, size, W, H)
    assert cam["opens_whole"] and cam["clamp"] == "native"
    fs = frames(cam, 8.0)
    assert fs[0] == {"z": 1.0, "x": 0.5, "y": 0.5}
    assert all(b["z"] > a["z"] for a, b in zip(fs[1:-1], fs[2:-1]))        # moving on every frame
    assert fs[-1]["z"] == pytest.approx(min(M.TOUR["whole_creep_max"], 1 + M.TOUR["creep_scale_per_s"] * 8.0))
    assert max(f["z"] for f in fs) <= M.TOUR["whole_creep_max"] + 1e-9
    for f in fs:                                                            # inside the picture's own fitted shape
        src, dst = M.still_view(size, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp="native")
        assert src[0] >= -0.5 and src[2] <= 300.5 and src[1] >= -0.5 and src[3] <= 420.5
        assert dst[2] - dst[0] < W                                           # pillarboxed
    long = R.still_camera(dict(shot, _dur=20.0), size, W, H)
    assert long["z_max"] == pytest.approx(M.TOUR["whole_creep_max"])


def test_a_stop_at_zero_or_negative_zoom_is_refused_not_a_crash():
    for z in (0.0, -1.0):
        cam = cam_for({"camera": [{"t": 0, "z": z}, {"t": 4, "z": 1.2}]}, LANDSCAPE43)
        assert any("below the fill" in p for p in cam["problems"])
        assert all(fills(LANDSCAPE43, f) for f in frames(cam, 8.0))


def test_find_under_a41_opens_at_the_fill_not_the_whole_sheet():
    size = (1600, 1200)
    shot = {"id": "M", "kind": "archive_still", "_dur": 6.0, "_item": {"people": False}, "preset": "FIND",
            "fill_ok": False}
    cam = R.still_camera(shot, size, W, H)
    zf = max(W / (1600 * min(W / 1600, H / 1200)), H / (1200 * min(W / 1600, H / 1200)))
    assert cam["preset"] == "FIND" and cam["clamp"] == "image" and cam["opens_whole"] is False
    assert cam["path"][0]["z"] == pytest.approx(zf)
    assert all(fills(size, OV.framing_at(cam, k / 4, 6.0)) for k in range(25))
    held = R.still_camera(dict(shot, fill_exception="a small sheet, held whole"), size, W, H)
    assert held["opens_whole"] and held["path"][0] == {"z": 1.0, "x": 0.5, "y": 0.5}


def test_people_check_over_the_path():
    size = LANDSCAPE43
    top = {"boxes": [{"name": "a", "box": (0.45, 0.02, 0.55, 0.10)}], "unlocated": 0, "known": True}
    push = T.build(T.macro_stops("PUSH", {}, 6.0), 6.0, size, A, 2.0)
    assert not T.people_check(T.windows_of(push), top, size)["ok"]          # 4:3 at the fill: the top 12.5% is never shown
    tilt = T.build(T.macro_stops("TILT", {"direction": "up"}, 6.0), 6.0, size, A, 2.0)
    assert T.people_check(T.windows_of(tilt), top, size)["ok"]               # a tilt that ends on her shows her
    tall = {"boxes": [{"name": "standing", "box": (0.4, 0.0, 0.6, 1.0)}], "unlocated": 0, "known": True}
    assert T.people_check(T.windows_of(tilt), tall, size)["ok"]              # too tall for any frame: every part shown
    assert not T.people_check(T.windows_of(push), tall, size)["ok"]
    unknown = T.people_of({}, kind="archive_still")
    assert unknown["unlocated"] == 1 and not unknown["known"]
    hold = T.build(T.macro_stops("HOLD", {}, 6.0), 6.0, size, A, 2.0)
    assert not T.people_check(T.windows_of(hold), unknown, size)["ok"]        # the top and bottom are never shown
    cover = T.build(T.covering_stops(size, A, 6.0), 6.0, size, A, 2.0)
    assert T.people_check(T.windows_of(cover), unknown, size)["ok"]
    assert T.people_of({"people": "none visible"})["unlocated"] == 0
    assert T.people_of({"people": [{"name": "X"}]})["unlocated"] == 1
    assert T.people_of({}, kind="drawn")["unlocated"] == 0


def test_speed_guides_warn_on_a_fast_pan_or_zoom():
    size = WIDE
    slow = T.build(T.default_stops(size, A, 20.0), 20.0, size, A, 2.0)
    fast = T.build(T.default_stops(size, A, 2.0), 2.0, size, A, 2.0)
    zoom = T.build([{"t": 0, "z": 1.0}, {"t": 1.0, "z": 1.5}], 1.0, LANDSCAPE43, A, 2.0)

    def sampled(tl):
        return [(t, T.window(tl["size"], A, f["z"], f["x"], f["y"])) for t, f in T.samples(tl, 24.0)]
    assert T.speed_report(sampled(slow))["ok"]
    r = T.speed_report(sampled(fast))
    assert not r["ok"] and r["pan_per_s"] > M.TOUR["pan_guide_per_s"]
    z = T.speed_report(sampled(zoom))
    assert not z["ok"] and z["zoom_per_s"] > M.TOUR["zoom_guide_per_s"]


def test_a_reversal_across_a_cut_is_named_and_a_landed_stop_is_not():
    assert T.reversal((0.2, 0.0, 0.0), (-0.2, 0.0, 0.0)) == ["pan x"]
    assert T.reversal((0.2, 0.0, 0.1), (0.2, 0.0, -0.1)) == ["zoom"]
    assert T.reversal((0.2, 0.0, 0.0), (0.0, 0.0, -0.01)) == []             # the cut lands on a stop (a creep)


def test_must_show_lists_a_region_the_path_never_shows():
    item = {"roi": [{"name": "caption", "x": 0.0, "y": 0.9, "w": 1.0, "h": 0.1, "must_show": True},
                    {"name": "sign", "x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1}], "must_show": ["sign"]}
    hold = T.build(T.macro_stops("HOLD", {}, 6.0), 6.0, LANDSCAPE43, A, 2.0)
    assert T.must_show(T.windows_of(hold), item, LANDSCAPE43) == ["caption"]


# --------------------------------------------------------------------------
# The plan: lints on the fixture film (no frame rendered)
# --------------------------------------------------------------------------

def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _item(film, aid, fn):
    _edit(film, lambda d: fn(next(i for i in d["items"] if i["id"] == aid)), name="stills-ledger.json")


def _plan(film, name="a41"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=W, H=H, burn_subtitles=False, journal=j), j


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("a41") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


ROI_A = [{"name": "the shapes", "x": 0.2, "y": 0.2, "w": 0.65, "h": 0.6}]   # an authored subject: no covering pass


def test_the_fixture_tours_its_landscape_still_and_holds_the_small_ones_whole(film):
    plan, j = _plan(film, "a41-base")
    by = {s["id"]: s for s in plan["shots"]}
    assert by["S3"]["_cam"]["preset"] == "TOUR" and by["S3"]["_cam"]["macro"] == "PUSH"
    assert by["S3"]["_cam"]["covering"]                     # a PUSH alone shows 80% of a 10:7 picture: it tours it all
    assert by["S5"]["_cam"]["fill_exception"] and by["S5"]["_cam"]["opens_whole"]
    evs = J.read(j.path)
    for rule in ("tour-path", "tour-anchor", "tour-fills", "tour-softness", "tour-people"):
        assert [e["status"] for e in lints(evs, rule) if e["unit"] == "S3"] == ["pass"], rule
    assert [e["status"] for e in lints(evs, "still-first-frame-whole") if e["unit"] == "S5"] == ["pass"]
    assert not [e for e in lints(evs, "still-first-frame-whole") if e["unit"] == "S3"]
    assert any(e["kind"] == "decision" and e.get("unit") == "S5" and "fill_exception" in e.get("what", "")
               for e in evs)


def test_a_person_never_in_frame_over_the_path_refuses(film):
    _item(film, "FX-STILL-A", lambda i: i.update(people=[{"name": "edge", "x": 0.0, "y": 0.0, "w": 0.08, "h": 0.08}]))
    # a preset that misses her becomes a covering pass (journaled); an authored path that misses her is refused
    plan, _ = _plan(film, "a41-people-macro")
    assert next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]["covering"]
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[{"t": 0, "x": 0.5, "y": 0.5, "z": 1.2}]))
    with pytest.raises(R.Refused, match=r"tour-people \(S3\)"):
        _plan(film, "a41-people")
    # a path that passes over her clears it
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[{"t": 0, "x": 0.0, "y": 0.0, "z": 1.1},
                                                                      {"t": 4.0, "x": 0.5, "y": 0.5, "z": 1.0}]))
    plan, j = _plan(film, "a41-people-ok")
    assert [e["status"] for e in lints(J.read(j.path), "tour-people") if e["unit"] == "S3"] == ["pass"]


def test_an_unlocated_person_tours_a_hold_rather_than_crop_them_out(film):
    _item(film, "FX-STILL-A", lambda i: i.update(people=True))
    _edit(film, lambda p: _shot(p, "S3").update(preset="HOLD"))
    plan, j = _plan(film, "a41-cover")
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    assert cam["covering"] and cam["macro"] == "HOLD"
    evs = J.read(j.path)
    assert [e["status"] for e in lints(evs, "tour-people") if e["unit"] == "S3"] == ["pass"]
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "covering" in e.get("what", "") for e in evs)


def test_the_softness_cap_refuses_without_a_stated_exception(film):
    _edit(film, lambda p: _shot(p, "S5").pop("fill_exception"))             # 300x420: the fill alone is 2.13x
    with pytest.raises(R.Refused, match=r"tour-softness \(S5\)"):
        _plan(film, "a41-soft")
    _edit(film, lambda p: _shot(p, "S5").update(fill_exception="a small scan; the founder's 1.6x would be passed"))
    _plan(film, "a41-soft-ok")
    # an exception on a picture that can fill the 1080p master is refused: every still fills
    from PIL import Image
    Image.new("RGB", (2000, 1400), (90, 80, 70)).save(film / "stills" / "FX-STILL-A.png")
    _item(film, "FX-STILL-A", lambda i: i.update(width=2000, height=1400))
    _edit(film, lambda p: _shot(p, "S3").update(fill_exception="a reason in words"))
    with pytest.raises(R.Refused, match=r"tour-fill-exception \(S3\)"):
        _plan(film, "a41-exc-needless")
    _edit(film, lambda p: _shot(p, "S5").update(fill_exception="no"))           # one word is not a reason
    with pytest.raises(R.Refused, match=r"tour-fill-exception \(S5\)"):
        _plan(film, "a41-exc-word")
    _edit(film, lambda p: _shot(p, "S5").update(fill_exception="a small scan"))
    _edit(film, lambda p: _shot(p, "S3").update(fill_exception=None))
    # an authored stop past the cap is refused, never softened quietly (2000 px wide: 1.6x is z 5 at 360p)
    _edit(film, lambda p: _shot(p, "S3").update(fill_exception=None, preset=None, camera=[{"t": 0, "z": 1.0}, {"t": 4, "z": 6.0}]))
    with pytest.raises(R.Refused, match=r"tour-softness \(S3\)"):
        _plan(film, "a41-deep")


def test_a_macro_past_the_cap_stops_at_it(film):
    _item(film, "FX-STILL-A", lambda i: i.update(roi=ROI_A))
    _edit(film, lambda p: p.update(settings={"fill_max_upscale": 1.6}))      # the film states the old cap
    _edit(film, lambda p: _shot(p, "S3").update(preset="DETAIL"))           # 1.3 x 1.28 = 1.66x on the master: past 1.6
    plan, j = _plan(film, "a41-macro-cap")
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    assert cam["capped"] and T.upscale((1500, 1050), 1920, 1080, cam["tour"]["z_max"]) <= 1.6 + 1e-6
    partial = [e for e in lints(J.read(j.path), "tour-partial") if e["unit"] == "S3"]
    assert partial and partial[0]["severity"] == "review"                    # authored (roi): a reviewer item, no pass


def test_speed_and_reversal_are_warnings_never_refusals(film):
    def edit(p):
        _shot(p, "S3").update(preset=None, dur_s=3.25, camera=[{"t": 0, "x": 0.0, "y": 0.0, "z": 1.2},
                                                               {"t": 0.8, "x": 1.0, "y": 1.0, "z": 1.2},
                                                               {"t": 3.25, "x": 0.0, "y": 0.0, "z": 1.2}])
        s4 = _shot(p, "S4")
        s4.update(asset="FX-STILL-A", preset=None, transition_in={"type": "cut"}, start_s=7.75, dur_s=4.0,
                  fill_ok=None, repeat_reason="the same landscape, a second look the fixture intends",
                  camera=[{"t": 0, "x": 0.0, "y": 0.5, "z": 1.2}, {"t": 0.5, "x": 1.0, "y": 0.5, "z": 1.2}])
        s4.pop("fill_exception")
    _edit(film, edit)
    plan, j = _plan(film, "a41-speed")                                        # warnings only: the plan is made
    evs = J.read(j.path)
    sp = [e for e in lints(evs, "tour-speed") if e["unit"] == "S3"]
    assert sp and sp[0]["status"] == "fail" and sp[0]["severity"] == "warn"
    rv = [e for e in lints(evs, "tour-continuity") if e["unit"] == "S4"]
    assert rv and rv[0]["status"] == "fail" and rv[0]["severity"] == "warn" and "pan x" in rv[0]["evidence"]["reversed"]


def test_a_reversal_across_a_cut_warns(film):
    _item(film, "FX-STILL-A", lambda i: i.update(roi=ROI_A))                 # authored: the DRIFTs stay DRIFTs
    def two(p):
        s3 = _shot(p, "S3")
        s3.update(preset="DRIFT", dur_s=3.25, fill_ok=None)
        s4 = _shot(p, "S4")
        s4.update(asset="FX-STILL-A", preset="DRIFT", direction="rl", transition_in={"type": "cut"}, start_s=7.75,
                  dur_s=4.0, fill_ok=None, repeat_reason="the same landscape, a second look the fixture intends")
        s4.pop("fill_exception")
    _edit(film, two)
    plan, j = _plan(film, "a41-reverse")
    rv = [e for e in lints(J.read(j.path), "tour-continuity") if e["unit"] == "S4"]
    assert rv and rv[0]["status"] == "fail" and rv[0]["severity"] == "warn" and "pan x" in rv[0]["evidence"]["reversed"]


def test_tour_on_a_clip_with_burned_captions_is_refused(film):
    def burn(d):
        d["items"][0]["speakers_on_screen"] = [{"name": "A", "in_s": 0.0, "out_s": 9.0}]
    _edit(film, burn, name="footage-ledger.json")
    _edit(film, lambda p: _shot(p, "S6").update(camera="tour"))
    with pytest.raises(R.Refused, match=r"tour-burned-captions \(S6\)"):
        _plan(film, "a41-clip")


def test_ml_upscaling_still_forces_reconstructed(film):
    _item(film, "FX-STILL-A", lambda i: i.update(ml_upscaled=True))
    with pytest.raises(R.Refused, match=r"tour-ml-upscale \(S3\)"):
        _plan(film, "a41-ml")
    _item(film, "FX-STILL-A", lambda i: i.update(ml_upscaled=False))
    _item(film, "FX-STILL-C", lambda i: i.update(upscaler="Real-ESRGAN x4"))   # S5, held whole under its exception
    with pytest.raises(R.Refused, match=r"tour-ml-upscale \(S5\)"):
        _plan(film, "a41-ml-whole")
    _item(film, "FX-STILL-C", lambda i: i.update(upscaler=None))
    _edit(film, lambda d: d["items"][0].update(ml_upscaled=True), name="footage-ledger.json")   # a clip too
    with pytest.raises(R.Refused, match=r"tour-ml-upscale \(S6\)"):
        _plan(film, "a41-ml-clip")


def test_a_path_on_a_clip_is_refused_with_or_without_a_preset(film):
    _edit(film, lambda p: _shot(p, "S6").update(camera="tour"))               # no burned captions: still a later ticket
    with pytest.raises(R.Refused, match=r"tour-video \(S6\)"):
        _plan(film, "a41-clip-tour")
    _edit(film, lambda p: _shot(p, "S6").update(camera=[{"t": 0, "z": 1.2}], preset="FILL"))   # never silently ignored
    with pytest.raises(R.Refused, match=r"tour-video \(S6\)"):
        _plan(film, "a41-clip-both")


def test_a_hold_that_shows_part_of_the_picture_tours_it_unless_authored(film):
    _edit(film, lambda p: _shot(p, "S3").update(preset="HOLD"))               # people: false; 10:7 at the fill shows 80%
    plan, j = _plan(film, "a41-hold-cover")
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    # A47: the HOLD becomes the default pass, which ends on the subject; nobody is in the picture and the ledger
    # names no subject, so the subject is the whole picture. Its fill shows 80% of it, under WHOLE_HOLD_MIN_SHOWN
    # (founder ruling, option (c)): one sweep end to end shows it all, then a drift
    assert cam["covering"] and cam["cover"] == "subject" and cam["subject"]["src"] == "whole"
    assert cam["subject"]["whole_mode"] == "sweep" and not T.reversals(cam["tour"])
    assert T.covered([w for _, w in R.still_windows(cam, {"_dur": 4.0}, (1500, 1050), W, H)], (0, 0, 1, 1), (1500, 1050))
    evs = J.read(j.path)
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "ending on the subject" in e.get("what", "")
               for e in evs)
    assert not [e for e in lints(evs, "tour-partial") if e["unit"] == "S3"]
    # a person the ledger has not located still needs the whole picture: the pass covers it (A7)
    _item(film, "FX-STILL-A", lambda i: i.update(people=True))
    plan, j = _plan(film, "a41-hold-cover-whole")
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    assert T.covered([w for _, w in R.still_windows(cam, {"_dur": 4.0}, (1500, 1050), W, H)], (0, 0, 1, 1), (1500, 1050))
    assert not [e for e in lints(J.read(j.path), "tour-partial") if e["unit"] == "S3"]
    _item(film, "FX-STILL-A", lambda i: i.update(people=False))
    _item(film, "FX-STILL-A", lambda i: i.update(must_show=["the shapes"], roi=ROI_A))
    plan, j = _plan(film, "a41-hold-authored")
    assert not next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]["covering"]
    assert [e["severity"] for e in lints(J.read(j.path), "tour-partial") if e["unit"] == "S3"] == ["review"]


def test_an_unspoken_anchor_refuses(film):
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[{"t": 0}, {"at": "Calcutta", "z": 1.2}]))
    with pytest.raises(R.Refused, match=r"tour-anchor \(S3\)"):
        _plan(film, "a41-anchor")
    # L1 ("A test tone stands in for the narrator.") starts at 5.0, inside S3 (4.5 to 8.5): "narrator" anchors
    _edit(film, lambda p: _shot(p, "S3").update(camera=[{"t": 0}, {"at": "narrator", "z": 1.2}]))
    plan, _ = _plan(film, "a41-anchor-ok")
    st = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]["tour"]["stops"][1]
    assert 0.5 < st["t"] < 4.0 and st["at"] == "narrator"


def test_a_covering_pass_starts_far_from_the_focus_and_keeps_one_speed():
    size = PORTRAIT                                                         # tilts: the fill window travels in y
    st = T.covering_stops(size, A, 9.0, focus=[0.5, 0.6])
    assert st[0]["y"] == 0.0 and st[1]["y"] == 1.0 and st[2]["y"] == 0.6    # far end, near end, back to the focus
    ys = [T.settle(x, size, A)["y"] for x in st]
    sweep, back = abs(ys[1] - ys[0]), abs(ys[2] - ys[1])
    assert st[1]["t"] == pytest.approx(9.0 * sweep / (sweep + back))         # time shared by distance: one speed
    tl = T.build(st, 9.0, size, A, 2.0)
    assert T.covered(T.windows_of(tl), (0, 0, 1, 1), size)
    end = T.covering_stops(size, A, 9.0, focus=[0.5, 1.0])                  # the focus is the near end: two stops
    assert len(end) == 2 and end[-1]["t"] == 9.0


def test_a_picture_a_few_pixels_off_16_9_creeps_and_a_slow_pass_creeps_too():
    size = (1920, 1078)                                       # the fill hides 3.4 px: under 0.5% of the side
    assert T.long_axis(size, A) is None
    cam = cam_for({"_dur": 8.0}, size)
    assert [g["kind"] for g in cam["tour"]["segments"]] == ["creep"]
    wins = [w for _, w in R.still_windows(cam, {"_dur": 8.0}, size, W, H)]
    assert T.people_check(wins, T.people_of({}), size)["whole_shown"]     # the hidden strip counts as shown
    big = (2089, 1186)                                        # 11 px hidden, over 0.5%: the pass, with creep layered
    assert T.long_axis(big, A) == "y"
    st = T.default_stops(big, A, 8.0, zmax=3.0)                # in to the middle and out again: ends at the fill
    assert len(st) == 3 and st[1]["z"] == pytest.approx(1 + M.TOUR["creep_scale_per_s"] * 4.0)
    assert st[0]["z"] == st[-1]["z"] == 1.0
    tl = T.build(st, 8.0, big, A, 3.0)
    assert T.covered(T.windows_of(tl), (0, 0, 1, 1), big)
    fs = [T.at(tl, k / 24) for k in range(8 * 24 + 1)]
    assert all(a != b for a, b in zip(fs[1:-1], fs[2:-1]))      # moving on every frame
    assert len(T.default_stops(PORTRAIT, A, 8.0, zmax=3.0)) == 2   # a pass faster than the creep needs none


def test_a_non_finite_stop_is_refused_not_a_crash():
    for bad in ({"t": 0, "x": float("inf")}, {"t": 0, "z": float("nan")}, {"t": float("inf")},
                {"t": 0, "hold": float("nan")}):
        cam = cam_for({"camera": [bad, {"t": 4, "z": 1.1}]}, LANDSCAPE43)
        assert any("finite" in p or "hold" in p for p in cam["problems"]), bad
        assert all(fills(LANDSCAPE43, f) for f in frames(cam, 8.0))
