"""R12, fill and sound polish (founder notes on The Next Village pilot):
A34 FILL, A35 image-repeat, A36 archival sound edges, A37 the duck's pre-roll,
A38 the narrator voicing EQ and A39 pacing as guidance. Each in both
directions: what passes and what is refused (or, for A39, guided)."""

import json
import math

import numpy as np
import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import render as R
from studio.engine import score as SC
from conftest import make_film

RATE = 48000


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _plan(film, name="r12"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("r12") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    import shutil
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


# --------------------------------------------------------------------------
# A34: FILL
# --------------------------------------------------------------------------

def test_a34_a_4_3_hd_picture_opens_whole_then_fills_inside_itself():
    cam = R.fill_camera({"id": "x", "_dur": 12.0}, (1440, 1080), 1920, 1080)
    f = cam["fill"]
    assert cam["path"][0] == {"z": 1.0, "x": 0.5, "y": 0.5}                    # A7: the whole original first
    assert f["full"] and f["z_end"] == pytest.approx(4 / 3, abs=1e-4) and f["end_upscale"] == pytest.approx(4 / 3, abs=1e-4)
    assert f["end_inside_picture"] and cam["z_rel_max"] == pytest.approx(1.0)  # 7.2's z = 1: the largest 16:9 window
    assert (cam["open_s"], cam["move_s"]) == (M.FILL["open_s"], M.FILL["move_s"])
    assert OV.framing_at(cam, 1.0, 12.0) == cam["path"][0]                        # still whole inside the open
    mid = OV.framing_at(cam, 2.5 + 3.0, 12.0)["z"]
    assert 1.0 < mid < 4 / 3                                                      # moving, on the rostrum curve
    for t in (8.5, 10.0, 12.0):                                                   # then it holds the fill
        assert OV.framing_at(cam, t, 12.0)["z"] == pytest.approx(4 / 3)
    src, dst = M.still_view((1440, 1080), M.Layout(1920, 1080), z=f["z_end"], clamp="image")
    assert dst == (0.0, 0.0, 1920.0, 1080.0) and src[0] >= -1e-3 * 1440 and src[2] <= 1440 * (1 + 1e-3)   # a crop of it


def test_a34_the_upscale_limit_stops_short_and_a_low_resolution_reel_stays_whole():
    sd = R.fill_camera({"id": "x", "_dur": 12.0}, (640, 480), 1920, 1080)       # its plain fit is already 2.25x
    assert sd["path"] == [{"z": 1.0, "x": 0.5, "y": 0.5}] and not sd["fill"]["full"] and sd["fill"]["z_end"] == 1.0
    assert sd["fill"]["end_inside_picture"]                                      # whole, on the field: nothing invented
    allowed = R.fill_camera({"id": "x", "_dur": 12.0}, (640, 480), 1920, 1080, max_upscale=3.0)
    assert allowed["fill"]["full"] and allowed["fill"]["end_upscale"] == pytest.approx(3.0, abs=1e-3)
    sq = R.fill_camera({"id": "x", "_dur": 12.0}, (1000, 1000), 1920, 1080)      # a square scan: 1.08x fit, 1.92x to fill
    assert not sq["fill"]["full"] and sq["fill"]["end_upscale"] == pytest.approx(R.FILL_MAX_UPSCALE, abs=1e-3)
    assert sq["fill"]["end_inside_picture"]                                      # crops top and bottom, shows all its width
    big = R.fill_camera({"id": "x", "_dur": 12.0}, (3000, 4000), 1920, 1080)     # a large portrait scan fills at 0.64x
    assert big["fill"]["full"] and big["fill"]["end_upscale"] < 1.0


def test_a34_focus_frames_the_end_and_is_checked_against_the_safe_area():
    c = R.fill_camera({"id": "x", "_dur": 12.0, "focus": [0.3, 0.4]}, (1440, 1080), 1920, 1080)
    assert c["fill"]["focus_from"] == "declared" and c["path"][-1]["y"] < 0.5 and R.fill_safe(c["fill"])
    low = R.fill_camera({"id": "x", "_dur": 12.0, "focus": [0.5, 0.97]}, (1440, 1080), 1920, 1080)
    assert low["fill"]["focus_in_frame"][1] > R.FILL_SAFE[3] and not R.fill_safe(low["fill"])   # under the lower thirds
    for bad in ([1.2, 0.5], [0.5], "centre", [True, 0.5]):
        with pytest.raises(R.Refused, match="focus must be"):
            R.fill_camera({"id": "x", "_dur": 12.0, "focus": bad}, (1440, 1080), 1920, 1080)


def test_a34_fill_is_the_default_only_for_a_long_narrow_archive_picture():
    def pre(aspect, still=False, **shot):
        return R.shot_preset(dict({"kind": "archive_still" if still else "archive_video", "_dur": 8.0}, **shot), aspect, still=still)
    assert pre(4 / 3) == R.FILL and pre(1.0, still=True) == R.FILL and pre(0.7, still=True) == R.FILL
    assert pre(16 / 9) is None and pre(16 / 9, still=True) == "HOLD"          # nothing to fill
    assert pre(4 / 3, _dur=6.0) is None                                        # 6 s or less: plays as it is
    assert pre(4 / 3, fill_ok=False) is None and pre(4 / 3, preset="HOLD") == "HOLD" and pre(1.0, still=True, preset="push") == "PUSH"
    assert R.shot_preset({"kind": "drawn", "_dur": 9.0}, 1.0, still=True) == "HOLD"   # a drawn map is not archive
    named = {"in_s": 0.0, "out_s": 10.0, "_item": {"speakers_on_screen": [{"name": "A", "in_s": 2.0, "out_s": 6.0}]}}
    shot = dict({"kind": "archive_video", "_dur": 10.0}, **named)
    assert R.shot_preset(shot, 4 / 3, still=False) is None and "burns speakers' names" in shot["_preset_from"]


def test_a34_a_clip_fills_after_opening_whole_in_the_render(film):
    _edit(film, lambda p: _shot(p, "S6").update(preset="FILL"))
    plan, j = _plan(film, "fill-clip")
    i = next(k for k, s in enumerate(plan["shots"]) if s["id"] == "S6")
    s6 = plan["shots"][i]
    assert s6["_cam"]["preset"] == R.FILL and s6["_video"]["decode"] == [640, 480]   # decoded for its end framing
    evs = J.read(j.path)
    for rule in ("fill-declared", "fill-opens-whole", "fill-inside-picture", "fill-burned-names"):
        assert [e["status"] for e in lints(evs, rule) if e["unit"] == "S6"] == ["pass"], rule
    assert [e["severity"] for e in lints(evs, "fill-ok") if e["unit"] == "S6"] == ["review"]
    pics = R.Pictures(plan)
    try:
        first = np.asarray(pics.shot(i, 0.0))
        last = np.asarray(pics.shot(i, s6["_dur"] - 1 / 24))
    finally:
        pics.close()
    field = np.array(M.PALETTE["letterbox"])
    assert np.abs(first[:, :70].astype(int) - field).max() <= 2                  # pillarboxed: the whole 4:3 frame
    assert np.abs(last[:, :70].astype(int) - field).max() > 30                   # filled: picture to the frame's edge
    doc = R.sources_doc(plan, j, {})
    assert next(s for s in doc["shots"] if s["id"] == "S6")["fill"]["full"] is True


def test_a34_a_clip_takes_fill_or_hold_and_a_fill_never_says_fill_ok_false(film):
    _edit(film, lambda p: _shot(p, "S6").update(preset="PUSH"))
    with pytest.raises(R.Refused, match=r"video-preset \(S6\)"):
        _plan(film, "fill-push")
    _edit(film, lambda p: _shot(p, "S6").update(preset="FILL", fill_ok=False))
    with pytest.raises(R.Refused, match=r"fill-declared \(S6\)"):
        _plan(film, "fill-false")
    _edit(film, lambda p: _shot(p, "S6").update(preset="HOLD", fill_ok=None))
    plan, _ = _plan(film, "fill-hold")
    assert "_cam" not in next(s for s in plan["shots"] if s["id"] == "S6")    # plays as it is, pillarboxed


def test_a34_a_still_fills_stops_short_at_the_limit_and_the_film_may_raise_it(film):
    _edit(film, lambda p: _shot(p, "S5").update(preset="FILL"))                  # FX-STILL-C, a 300x420 portrait
    plan, j = _plan(film, "fill-still")
    cam = next(s for s in plan["shots"] if s["id"] == "S5")["_cam"]
    assert not cam["fill"]["full"] and cam["fill"]["end_upscale"] == pytest.approx(1.6, abs=1e-3)
    evs = J.read(j.path)
    up = next(e for e in lints(evs, "fill-upscale") if e["unit"] == "S5")
    assert up["status"] == "fail" and up["severity"] == "warn" and "stops at" in up["evidence"]["why"]
    assert [e["severity"] for e in lints(evs, "fill-review") if e["unit"] == "S5"] == ["review"]
    assert [e["status"] for e in lints(evs, "still-first-frame-whole") if e["unit"] == "S5"] == ["pass"]
    _edit(film, lambda p: p.update(settings={"fill_max_upscale": 3.0}))
    plan, _ = _plan(film, "fill-still-3")
    assert next(s for s in plan["shots"] if s["id"] == "S5")["_cam"]["fill"]["full"]
    _edit(film, lambda p: p.update(settings={"fill_max_upscale": 4.0}))
    with pytest.raises(R.Refused, match="film-settings"):
        _plan(film, "fill-still-4")


# --------------------------------------------------------------------------
# A35: image-repeat
# --------------------------------------------------------------------------

def _stills(*spec):
    out = []
    for k, (asset, part, tr) in enumerate(spec):
        out.append({"id": f"P{k}", "kind": "archive_still", "asset": asset, "_part": part,
                    "transition_in": {"type": tr}})
    return out


def test_a35_one_showing_is_shots_in_a_row_and_a_dip_or_another_shot_starts_another():
    shots = _stills(("A", "c1", "cut"), ("A", "c1", "cut"), ("A", "c1", "dissolve"), ("B", "c1", "cut"),
                    ("A", "c2", "cut"), ("A", "c2", "dip"))
    ap = R.image_appearances(shots)
    assert [(a["asset"], a["shots"]) for a in ap] == [("A", ["P0", "P1", "P2"]), ("B", ["P3"]), ("A", ["P4"]), ("A", ["P5"])]
    assert [a["needs_reason"] for a in ap] == [False, False, False, True]      # P5: twice in c2, three times in the film
    clip = [{"id": "V1", "kind": "archive_video", "asset": "R", "_part": "c1"}, {"id": "V2", "kind": "archive_video",
                                                                                "asset": "R", "_part": "c1"}]
    assert R.image_appearances(clip) == []                                     # a reel's shots are A33's (clip-repeat)


def test_a35_a_third_showing_in_the_film_needs_a_reason_even_in_a_new_part():
    shots = _stills(("A", "c1", "cut"), ("B", "c1", "cut"), ("A", "c2", "cut"), ("B", "c2", "cut"), ("A", "c3", "cut"))
    ap = R.image_appearances(shots)
    assert [a["needs_reason"] for a in ap] == [False, False, False, False, True]
    assert ap[-1]["n_film"] == 3 and ap[-1]["n_part"] == 1


def test_a35_a_repeat_in_a_part_is_refused_unless_the_story_says_why(film):
    _edit(film, lambda p: _shot(p, "S5").update(asset="FX-STILL-A"))            # S3 already shows it in ch-1
    with pytest.raises(R.Refused, match=r"image-repeat \(S5\)"):
        _plan(film, "repeat")
    _edit(film, lambda p: _shot(p, "S5").update(repeat_reason="ok"))           # a word is not a reason
    with pytest.raises(R.Refused, match=r"image-repeat \(S5\)"):
        _plan(film, "repeat-word")
    why = "the goddess returns at the close, as the story's frame"
    _edit(film, lambda p: _shot(p, "S5").update(repeat_reason=why))
    plan, j = _plan(film, "repeat-why")
    evs = J.read(j.path)
    got = [e for e in lints(evs, "image-repeat") if e["unit"] == "S5"]
    assert {e["severity"] for e in got} == {"block", "review"} and all(e["status"] in ("pass", "review") for e in got)
    assert any(e["kind"] == "decision" and e.get("unit") == "S5" and why in e["why"] for e in evs)


def test_a35_the_fixture_shows_each_image_once():
    film_shots = json.loads((R.Path(__file__).resolve().parent / "fixture" / "screenplay.json").read_text(encoding="utf-8"))
    shots = [dict(s, _part=p["id"]) for p in film_shots["parts"] for s in p["shots"]]
    assert not any(a["needs_reason"] for a in R.image_appearances(shots))


# --------------------------------------------------------------------------
# A36: archival sound edges
# --------------------------------------------------------------------------

def _noise(seconds, dbfs=-40.0, seed=1):
    return (np.random.default_rng(seed).standard_normal(int(seconds * RATE)) * 10 ** (dbfs / 20)).astype(np.float32)


def _seg(sid, t_in, dur, *, asset="R", src_in=10.0, runs=(), pad=R.EDGE_PAD_S, reel_s=60.0):
    x0 = max(0.0, src_in - pad)
    x = _noise(min(reel_s, src_in + dur + pad) - x0, seed=len(sid))
    return {"id": sid, "kind": "span", "asset": asset, "src_in": src_in, "src_out": src_in + dur, "t_in": t_in,
            "t_out": t_in + dur, "x": x, "x0": x0, "x_end": x0 + len(x) / RATE, "runs": list(runs), "head": None, "tail": None}


def _steps(segs):
    parts = []
    for g in segs:
        y, h, _ = R.segment_audio(g)
        parts.append((int(round((g["t_in"] - h / RATE) * RATE)), y, 0.0, g["id"]))
    return {(s["segment"], s["edge"]): s["step_db"] for s in R.edge_steps(parts, segs)}


def test_a36_the_edge_fade_steps_gently_and_a_20_ms_cut_does_not():
    n = int(0.6 * RATE)
    g = R.edge_gain(n, rising=False)
    assert g[0] == pytest.approx(1.0, abs=1e-3) and 20 * math.log10(g[-1]) == pytest.approx(-R.EDGE_DEPTH_DB, abs=0.5)
    assert np.all(np.diff(g) <= 0)
    seg = _seg("s", 5.0, 3.0)
    seg["head"] = {"ext": 0.6, "fade": 0.6, "inside": 0.0}
    seg["tail"] = {"ext": 0.6, "fade": 0.6, "inside": 0.0}
    gentle = _steps([seg])
    assert max(gentle.values()) <= R.EDGE_STEP_MAX_DB
    seg["head"] = {"ext": 0.0, "fade": 0.02, "inside": 0.02}
    seg["tail"] = {"ext": 0.0, "fade": 0.02, "inside": 0.02}                   # A26's old 20 ms cut
    hard = _steps([seg])
    assert min(hard.values()) > R.EDGE_STEP_MAX_DB + 10


def test_a36_edges_carry_the_reel_past_the_cut_longer_into_silence_and_stop_short_of_speech():
    plan = {"lines": [], "cues": []}
    lone = _seg("a", 10.0, 3.0)
    R.plan_edges([lone], plan, R.Path("."))
    assert lone["tail"]["ext"] == R.EDGE_LONG_S and lone["tail"]["silence"]    # silence follows: the long fade
    assert lone["head"]["ext"] == pytest.approx(R.EDGE_PAD_S - 0.1, abs=0.11) or lone["head"]["ext"] == R.EDGE_LONG_S
    busy = {"lines": [], "cues": [{"start_s": 0.0, "end_s": 30.0}]}            # a bed under it: the house fade
    s2 = _seg("b", 10.0, 3.0)
    R.plan_edges([s2], busy, R.Path("."))
    assert s2["tail"]["ext"] == R.EDGE_FADE_S and s2["head"]["ext"] == R.EDGE_FADE_S
    talk = _seg("c", 10.0, 3.0, runs=[(12.0, 12.75), (13.25, 14.0)])          # the reel speaks 0.25 s after the out point
    R.plan_edges([talk], busy, R.Path("."))
    t = talk["tail"]                                                           # up to the next word's onset, less 40 ms
    assert t["ext"] == pytest.approx(0.25 - R.EDGE_GUARD_BEFORE_S, abs=1e-3) and t["limited_by"] == "the reel speaks or ends"
    assert t["fade"] == pytest.approx(R.EDGE_MIN_S) and t["inside"] == pytest.approx(R.EDGE_MIN_S - t["ext"])
    assert 13.0 - t["inside"] >= 12.75 + R.EDGE_GUARD_AFTER_S - 1e-9            # it starts after the last word's decay
    assert max(_steps([talk]).values()) <= R.EDGE_STEP_MAX_DB


def test_a36_another_sound_bounds_the_tail_and_one_reel_in_step_is_joined():
    plan = {"lines": [], "cues": [{"start_s": 0.0, "end_s": 60.0}]}
    a, b = _seg("a", 10.0, 3.0, src_in=10.0), _seg("b", 14.0, 3.0, src_in=14.0)    # same reel, 1 s apart in both clocks
    R.plan_edges([a, b], plan, R.Path("."))
    assert a["tail"]["joined"] == "b" and b["head"]["joined"] == "a" and a["tail"]["ext"] == pytest.approx(1.0)
    y, h, core = R.segment_audio(a)
    assert len(y) == pytest.approx((3.0 + R.EDGE_FADE_S + 1.0) * RATE, abs=2) and abs(y[-1]) > 0   # plays through the gap
    c, d = _seg("c", 10.0, 3.0, src_in=10.0), _seg("d", 13.3, 3.0, asset="Q", src_in=40.0)   # another reel 0.3 s after
    R.plan_edges([c, d], plan, R.Path("."))
    assert c["tail"]["ext"] == pytest.approx(0.3) and c["tail"]["limited_by"] == "another sound is placed"
    assert c["tail"]["fade"] == pytest.approx(R.EDGE_MIN_S) and d["head"]["ext"] == pytest.approx(0.3)   # a crossfade


def _noisy_reel(dest, seconds=8.0):
    """FX-REEL with a noise floor (about -45 dBFS) under its phrases, the shape of an optical track."""
    from make_media import _run
    words = "gte(t,1.15)*lt(t,2.25)+gte(t,3.2)*lt(t,4.0)"
    _run(["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24:duration={seconds}",
          "-f", "lavfi", "-i", f"aevalsrc='0.01*(random(0)*2-1)+0.35*sin(2*PI*440*t)*({words})':s=48000:d={seconds}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", "48", "-pix_fmt", "yuv420p",
          "-c:a", "pcm_s16le", "-shortest", str(dest)])


def _with_reel(film):
    """The fixture with a noisy reel playing its own sound on S6 (2 s, a clip shot) and nothing else changed."""
    _noisy_reel(film / "footage" / "fx-noisy.mkv")
    _edit(film, lambda d: d["items"].append({
        "id": "FX-NOISY", "file": "fx-noisy.mkv", "title": "Synthetic reel with a noise floor, test fixture", "date": "2026",
        "archive": "studio test fixture", "archive_short": "test fixture", "licence": "CC0", "synthetic": True,
        "test_fixture": True, "data_source": "ffmpeg testsrc2 and aevalsrc, test fixture", "telecined": False,
        "people": False, "shows_bodies": False}), "footage-ledger.json")
    _edit(film, lambda p: _shot(p, "S6").update(asset="FX-NOISY", in_s=4.5, out_s=7.5, native_fps=24))


def test_a36_a_clip_playing_its_own_sound_eases_in_and_out(film):
    _with_reel(film)
    plan, j = _plan(film, "edge-own")
    mix, placed = R.build_mix(plan, film, j)
    evs = J.read(j.path)
    edges = lints(evs, "archival-sound-edge")
    assert {e["unit"] for e in edges} == {"S6:head", "S6:tail"} and all(e["status"] == "pass" for e in edges)
    s6 = next(s for s in plan["shots"] if s["id"] == "S6")
    t_out = s6["f1"] / R.FPS
    tail = mix[int((t_out + 0.05) * RATE): int((t_out + 0.15) * RATE)]
    assert np.sqrt(np.mean(tail ** 2)) > 10 ** (-60 / 20)                     # the reel's floor carries on past the cut
    assert all(e["evidence"]["step_db"] <= R.EDGE_STEP_MAX_DB for e in edges)


def test_a36_a_hard_cut_of_the_noise_floor_is_refused(film, monkeypatch):
    _with_reel(film)
    plan, j = _plan(film, "edge-hard")
    for k in ("EDGE_FADE_S", "EDGE_LONG_S", "EDGE_MIN_S"):                    # the pre-R12 edge: A26's 20 ms fade only
        monkeypatch.setattr(R, k, 0.0)
    with pytest.raises(R.Refused, match=r"archival-sound-edge \(A36\)"):
        R.build_mix(plan, film, j)
    plan, j = _plan(film, "edge-hard-draft")
    R.build_mix(plan, film, j, draft=True)                                     # a warning under --draft
    edges = lints(J.read(j.path), "archival-sound-edge")
    assert any(e["status"] == "fail" and e["severity"] == "warn" for e in edges)


# --------------------------------------------------------------------------
# A37: the duck's pre-roll
# --------------------------------------------------------------------------

def test_a37_the_duck_eases_down_over_a_second_and_is_at_depth_on_the_onset():
    voice = np.zeros(10 * RATE, np.float32)
    voice[5 * RATE: 7 * RATE] = 0.1
    g = R.duck_gain(voice)
    floor = 10 ** (-R.DUCK_DB / 20)
    assert g[5 * RATE] == pytest.approx(floor, abs=1e-6)                       # full depth on the onset
    assert g[int((5 - SC.DUCK_ATTACK_S - 0.01) * RATE)] == pytest.approx(1.0)
    db = 20 * np.log10(g[int(3.5 * RATE): 5 * RATE].astype(np.float64))
    k = RATE // 10
    assert (db[:-k] - db[k:]).max() <= SC.DUCK_ATTACK_MAX_DB                    # at most 2 dB in any 100 ms going down
    assert (db[:-k] - db[k:]).max() == pytest.approx(R.DUCK_DB * math.sin(math.pi * 0.1 / SC.DUCK_ATTACK_S / 2) * 2 / 2, abs=0.1)
    # the release is unchanged: back up within the 250 ms ramp after the voice
    assert g[int((7 + R.DUCK_SMOOTH_S) * RATE)] == pytest.approx(1.0)


def test_a37_duck_slope_passes_the_eased_attack_and_refuses_the_old_one():
    active = np.zeros(2000, bool)
    active[800:1200] = True                                                    # 4 s of voice on the 10 ms grid
    new = SC.duck_from_activity(active, [], 1.2)
    ok = next(c for c in SC.score_checks([], dict(SC.STANDARD), duration_s=20.0, duck_grid=new) if c["rule"] == "duck-slope")
    assert ok["ok"] and ok["evidence"]["attack_db_per_100ms"] <= SC.DUCK_ATTACK_MAX_DB
    k = 25
    env = np.clip(np.convolve(active.astype(float), np.ones(k) / k, mode="same"), 0, 1)
    old = (1.0 - env * (1.0 - 10 ** (-SC.DUCK_DB / 20))).astype(np.float32)   # the pre-R12 centred 250 ms ramp
    bad = next(c for c in SC.score_checks([], dict(SC.STANDARD), duration_s=20.0, duck_grid=old) if c["rule"] == "duck-slope")
    assert not bad["ok"] and bad["evidence"]["attack_db_per_100ms"] > 2 * SC.DUCK_ATTACK_MAX_DB
    assert "duck-slope" in SC.RULES


# --------------------------------------------------------------------------
# A38: the narrator voicing EQ
# --------------------------------------------------------------------------

def test_a38_the_house_eq_is_on_by_default_and_a_film_may_declare_its_own_inside_bounds():
    eq, how, probs = SC.narrator_eq_setting({})
    assert eq == SC.NARRATOR_EQ_HOUSE and how == "house (default)" and not probs
    assert SC.narrator_eq_setting({"narrator_eq": "off"})[0] is None
    own = {"low": {"type": "bell", "hz": 180.0, "gain_db": 2.0, "q": 1.0},
           "high": {"type": "high_shelf", "hz": 7000.0, "gain_db": -1.5, "slope": 1.0}}
    assert SC.narrator_eq_setting({"narrator_eq": own}) == (own, "film", [])
    for bad in ({"low": dict(own["low"], gain_db=4.0)}, {"high": dict(own["high"], gain_db=1.0)},
                {"low": dict(own["low"], hz=40.0)}, {"mid": own["low"]}, "loud", {"low": dict(own["low"], type="shelf")}):
        assert SC.narrator_eq_setting({"narrator_eq": bad})[2], bad
    house = SC.NARRATOR_EQ_HOUSE
    assert SC.eq_db_at(200, house) == pytest.approx(2.5, abs=0.01)             # warmth where Tara's chest is
    assert SC.eq_db_at(500, house) < 0.5 and abs(SC.eq_db_at(1000, house)) < 0.15   # the low-mids and the middle left alone
    assert abs(SC.eq_db_at(3000, house)) < 0.2 and SC.eq_db_at(4000, house) > -0.5  # her presence band kept
    assert -2.5 <= SC.eq_db_at(8000, house) <= -1.5 and SC.eq_db_at(12000, house) >= -2.5   # the treble eased


def test_a38_the_eq_keeps_the_line_at_its_loudness_and_measures_as_declared():
    rng = np.random.default_rng(3)
    white = rng.standard_normal(4 * RATE)
    pink = np.fft.irfft(np.fft.rfft(white) / np.sqrt(np.maximum(np.fft.rfftfreq(len(white), 1 / RATE), 20.0)))
    x = (pink / np.abs(pink).max() * 0.3).astype(np.float32)
    y, rec = SC.apply_voice_eq(x, SC.NARRATOR_EQ_HOUSE)
    assert SC.integrated_lufs(y) == pytest.approx(SC.integrated_lufs(x), abs=0.05)
    assert all(c["error_db"] is not None and c["error_db"] <= SC.NARRATOR_EQ_TOL_DB for c in rec["response"])
    low = next(c for c in rec["response"] if c["band"] == "low")
    assert low["measured_db"] == pytest.approx(2.5, abs=0.3)


def test_a38_only_the_narration_is_eqd_and_the_lint_holds_the_declared_eq(film, monkeypatch):
    plan, j = _plan(film, "eq-house")
    _, placed = R.build_mix(plan, film, j)
    ev = lints(J.read(j.path), "narrator-eq")[0]
    assert ev["status"] == "pass" and ev["evidence"]["declared"] == "house (default)" and ev["evidence"]["lines"] == 1
    assert ev["evidence"]["narrator_eq"] == SC.NARRATOR_EQ_HOUSE
    _edit(film, lambda p: p.update(narrator_eq="off"))
    plan_off, j_off = _plan(film, "eq-off")
    _, placed_off = R.build_mix(plan_off, film, j_off)
    assert lints(J.read(j_off.path), "narrator-eq")[0]["evidence"]["narrator_eq"] is None
    reading = {x["id"]: x for x in placed["lines"]}["L2"]
    assert reading == {x["id"]: x for x in placed_off["lines"]}["L2"]          # the reader is never EQ'd
    _edit(film, lambda p: p.update(narrator_eq={"low": {"type": "bell", "hz": 200.0, "gain_db": 5.0, "q": 1.0}}))
    with pytest.raises(R.Refused, match="narrator-eq-declared"):
        _plan(film, "eq-bad")
    _edit(film, lambda p: p.pop("narrator_eq"))
    plan, j = _plan(film, "eq-swapped")
    real = SC.apply_voice_eq
    monkeypatch.setattr(SC, "apply_voice_eq", lambda x, eq: real(x, dict(eq, high=dict(eq["high"], gain_db=-1.0))))
    with pytest.raises(R.Refused, match=r"narrator-eq \(A38\)"):
        R.build_mix(plan, film, j)


# --------------------------------------------------------------------------
# A39: pacing is guidance
# --------------------------------------------------------------------------

def test_a39_the_pacing_limits_are_advisory_and_the_truth_limits_still_bind(film):
    plan, _ = _plan(film, "a39-plan")
    assert R.PACING_ADVISORY == ("still-hold", "dip-budget", "voiceless-floor")
    placed = {"lines": [{"id": "N", "kind": "narration", "at_s": 0.0, "dur_s": 700.0}]}
    long_film = dict(plan, duration_s=720.0, runtime_target_s=1200)
    j = J.Journal(film="a39")
    out = R.sound_lints(j, long_film, np.full(48000, 1e-3, np.float32), placed)
    assert out and all(o.startswith("readings-floor") for o in out)           # whose words are heard still binds
    evs = J.read(j.path)
    assert lints(evs, "voiceless-floor")[0]["severity"] == "warn"
    assert [e["evidence"]["rule"] for e in lints(evs, "pacing-guide")] == ["voiceless-floor"]


def test_a36_a_speech_bound_edge_is_a_reviewer_item_and_any_other_step_is_refused():
    seg = _seg("s", 5.0, 3.0, runs=[(9.0, 9.9), (10.25, 12.9)])                # the reel speaks either side of the cut
    seg["tail"] = {"ext": 0.0, "fade": 0.6, "inside": 0.6, "limited_by": "wanted", "wanted": 0.6}
    seg["head"] = {"ext": 0.03, "fade": 0.08, "inside": 0.05, "limited_by": "the reel speaks or ends", "wanted": 0.6}
    y, h, _ = R.segment_audio(seg)
    parts = [(int(round((seg["t_in"] - h / RATE) * RATE)), y, 0.0, "s")]
    j = J.Journal(film="edge-bound")
    assert R.archival_edge_lints(j, parts, [seg]) == []
    evs = [e for e in lints(J.read(j.path), "archival-sound-edge") if e["unit"] == "s:head"]
    assert {(e["status"], e["severity"]) for e in evs} == {("fail", "warn"), ("review", "review")}
    seg["head"] = dict(seg["head"], limited_by="another sound is placed")      # room was there: the edit is at fault
    j2 = J.Journal(film="edge-placed")
    assert any("s head steps" in o for o in R.archival_edge_lints(j2, parts, [seg]))
