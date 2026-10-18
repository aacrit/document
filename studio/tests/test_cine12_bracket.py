"""Cinematography ticket #12 (GRAMMAR A50, BRAND-KIT 14e): a DETAIL stop inside a fill_exception shot, bracketed
by the whole picture at both ends (founder ruling 3, 2026-10-17: "One DETAIL stop within 3x, bracketed by the
whole picture at both ends"). Hermetic: synthetic sizes and ledgers, the fixture film for the plan-level checks."""

from __future__ import annotations

import json
import math
import random
import shutil

import pytest

from studio.engine import bracket as BR
from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import render as R
from studio.engine import tour as T
from conftest import make_film

W, H = 1920, 1080
HZ = 24.0
TEXT = {"name": "subject", "x": 0.3, "y": 0.2, "w": 0.25, "h": 0.2, "kind": "text", "source": "auto",
        "confidence": 0.9}
EXC = "a small scan, the only copy"


def shot_of(item, dur, **kw):
    return dict({"id": "X", "kind": "archive_still", "_dur": float(dur), "_item": item, "fill_exception": EXC}, **kw)


def frames(cam, dur, hz=HZ):
    return [(k / hz, OV.framing_at(cam, k / hz, dur)) for k in range(int(math.floor(dur * hz)) + 1)]


def windows(cam, size, dur, hz=HZ):
    L = M.Layout(W, H)
    out = []
    for t, f in frames(cam, dur, hz):
        src, dst = M.still_view(size, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        out.append((t, f, src, dst))
    return out


def runs(zs, eps=1e-9):
    """The direction changes of a sequence: [+1, -1] is one push in and one pull out."""
    out = []
    for a, b in zip(zs, zs[1:]):
        d = 1 if b > a + eps else (-1 if b < a - eps else 0)
        if d and (not out or out[-1] != d):
            out.append(d)
    return out


# --------------------------------------------------------------------------
# The shape: whole, one push, hold, one pull, whole
# --------------------------------------------------------------------------


def test_the_bracket_opens_and_ends_whole_with_one_push_and_one_pull():
    size = (420, 560)
    cam = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0), size, W, H)
    assert cam["bracket"] is not None and cam["opens_whole"] and cam["clamp"] == "native"
    fs = frames(cam, 40.0)
    assert fs[0][1] == {"z": 1.0, "x": 0.5, "y": 0.5}
    assert fs[-1][1]["z"] == pytest.approx(1.0) and fs[-1][1]["x"] == pytest.approx(0.5)
    zs = [f["z"] for _, f in fs]
    assert runs(zs) == [1, -1]                                   # one push in, one pull out, no other reversal
    xs, ys = [f["x"] for _, f in fs], [f["y"] for _, f in fs]
    assert len(runs(xs)) <= 2 and len(runs(ys)) <= 2             # the centre goes to the detail once and back once
    tm = cam["bracket"]["timing"]
    assert tm["open_s"] >= M.BRACKET["open_s"] - 1e-6 and tm["end_s"] >= M.BRACKET["end_s"] - 1e-6
    assert tm["hold_s"] >= M.BRACKET["read_default_s"] - 1e-6     # text with no line count: 3 s
    # the whole at the start is held, never moved before the settle; the whole at the end is the picture itself
    assert all(f["z"] <= M.TOUR["whole_creep_max"] + 1e-9 for t, f in fs if t <= tm["open_s"])
    assert all(f == {"z": 1.0, "x": 0.5, "y": 0.5} or f["z"] == pytest.approx(1.0)
               for t, f in fs if t >= tm["whole_again_s"])
    # every frame is inside the picture's own pillarboxed shape: never a pixel beyond the source
    for _, f, src, dst in windows(cam, size, 40.0):
        assert src[0] >= -0.5 and src[1] >= -0.5 and src[2] <= size[0] + 0.5 and src[3] <= size[1] + 0.5
        assert dst[2] - dst[0] < W                               # pillarboxed on every frame
    # the detail holds the region whole
    b = cam["bracket"]
    win = BR.window(b["segments"][2]["b"], size, W, H)
    assert BR.inside(T.roi_box(TEXT), win, 1e-4)


def test_the_moves_keep_the_house_speed_guides():
    """A49's 7-second rule and 5%/s cruise (#4's pan-speed-px and zoom-speed) on every rendered frame."""
    size = (420, 560)
    cam = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0), size, W, H)
    ws = windows(cam, size, 40.0)
    for (ta, fa, a, _), (tb, fb, b, _) in zip(ws, ws[1:]):
        ww, wh = a[2] - a[0], a[3] - a[1]
        pan = max(abs((b[0] + b[2]) - (a[0] + a[2])) / 2 / ww, abs((b[1] + b[3]) - (a[1] + a[3])) / 2 / wh)
        assert pan / (tb - ta) <= 1 / M.BRACKET["cross_s"] + 1e-3
        zr = abs(math.log((a[2] - a[0]) / (b[2] - b[0]))) / (tb - ta)
        assert math.exp(zr) - 1 <= M.BRACKET["zoom_cruise"] + 1e-3


def test_text_with_a_line_count_holds_at_reading_pace():
    size = (420, 560)
    page = dict(TEXT, lines=8)
    cam = R.still_camera(shot_of({"people": False, "roi": [page]}, 60.0), size, W, H)
    assert cam["bracket"]["timing"]["hold_s"] >= 8 * M.BRACKET["read_line_s"] - 1e-6
    assert BR.hold_min(page, "text") == pytest.approx(10.0)
    assert BR.hold_min(TEXT, "text") == pytest.approx(3.0)
    assert BR.hold_min({"kind": "object"}, "object") == pytest.approx(1.5)
    bad, _ = T.item_schema({"roi": [dict(TEXT, lines=0)]})
    assert bad and "lines" in bad[0]
    _, unknown = T.item_schema({"roi": [page]})
    assert not unknown


# --------------------------------------------------------------------------
# The caps: 3x on the master, the face at 1.3 of the whole
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(420, 560), (539, 400), (300, 420), (611, 420)])
def test_the_detail_never_passes_the_softness_cap_on_the_master(size):
    tiny = {"name": "subject", "x": 0.45, "y": 0.45, "w": 0.05, "h": 0.05, "kind": "object", "source": "auto",
            "confidence": 0.9}
    cam = R.still_camera(shot_of({"people": False, "roi": [tiny]}, 50.0), size, 640, 360)
    zc = BR.zcap(size, 3.0)
    if cam.get("bracket") is None:
        assert zc < M.BRACKET["min_detail_z"] and "no room" in cam["bracket_why"]
        return
    assert cam["z_max"] <= zc + 1e-9
    deepest = max(f["z"] for _, f in frames(cam, 50.0, 8.0))
    assert BR.master_scale(size) * deepest <= 3.0 + 1e-6            # judged on the 1080p master, not the delivery


def test_a_face_is_never_pushed_past_1_3_of_the_whole():
    size = (420, 560)
    face = {"name": "subject", "x": 0.4, "y": 0.2, "w": 0.1, "h": 0.1, "kind": "face", "source": "auto",
            "confidence": 0.9}
    cam = R.still_camera(shot_of({"people": [], "roi": [face]}, 40.0), size, W, H)
    assert cam["bracket"] is not None
    assert max(f["z"] for _, f in frames(cam, 40.0)) <= M.CINE["face_zmax"] + 1e-9
    assert cam["bracket"]["detail"]["face_capped"]
    # a located person framed by an object detail caps it too
    obj = dict(face, kind="object")
    item = {"people": [{"x": 0.38, "y": 0.18, "w": 0.15, "h": 0.2, "name": "a man"}], "roi": [obj]}
    cam = R.still_camera(shot_of(item, 40.0), size, W, H)
    assert max(f["z"] for _, f in frames(cam, 40.0)) <= M.CINE["face_zmax"] + 1e-9


def test_a_written_stop_past_the_caps_is_refused_as_written():
    size = (420, 560)
    zc = BR.zcap(size, 3.0)
    cam = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0,
                                 camera=[{"x": 0.4, "y": 0.3, "z": zc + 0.2}]), size, W, H)
    assert cam.get("bracket") is None and any("softness cap" in p for p in cam["problems"])
    two = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0,
                                 camera=[{"roi": "subject"}, {"x": 0.4, "y": 0.6, "z": 1.3}]), size, W, H)
    assert two.get("bracket") is None and any("one DETAIL stop" in p for p in two["problems"])
    ok = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0,
                                camera=[{"roi": "whole"}, {"x": 0.4, "y": 0.3, "z": 1.4}, {"roi": "whole"}]),
                        size, W, H)
    assert ok["bracket"]["detail"]["authored"] and ok["bracket"]["detail"]["z"] == pytest.approx(1.4)
    person = {"people": [{"x": 0.35, "y": 0.25, "w": 0.1, "h": 0.1, "name": "a man"}]}
    face = R.still_camera(shot_of(person, 40.0, camera=[{"x": 0.4, "y": 0.3, "z": 1.5}]), size, W, H)
    assert any("face cap" in p for p in face["problems"])


# --------------------------------------------------------------------------
# Falling back to whole + creep, and the long hold's one breath
# --------------------------------------------------------------------------


def test_a_shot_too_short_for_the_bracket_keeps_whole_and_creep():
    size = (420, 560)
    cam = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 8.0), size, W, H)
    assert cam.get("bracket") is None and cam["bracket_why"].startswith("too short")
    assert cam["path"][-1]["z"] == pytest.approx(min(M.TOUR["whole_creep_max"], 1 + M.TOUR["creep_scale_per_s"] * 8))
    assert not cam["problems"]
    # no subject, the ledger's own whole, no_zoom: whole + creep, each saying why
    assert "no subject" in R.still_camera(shot_of({"people": False}, 40.0), size, W, H)["bracket_why"]
    whole = R.still_camera(shot_of({"people": False, "whole": True, "roi": [dict(TEXT, source="human")]}, 40.0),
                           size, W, H)
    assert "declares the still whole" in whole["bracket_why"]
    nz = R.still_camera(shot_of({"people": False, "roi": [TEXT]}, 40.0, no_zoom=True), size, W, H)
    assert "no_zoom" in nz["bracket_why"]
    near = dict(TEXT, x=0.02, y=0.02, w=0.96, h=0.96)
    assert "nearly the whole" in R.still_camera(shot_of({"people": False, "roi": [near]}, 40.0), size, W,
                                                H)["bracket_why"]


@pytest.mark.parametrize("dur", [42.0, 48.0, 54.0])
def test_a_long_whole_hold_is_one_breath(dur):
    """Spec 5.3: over 42 to 54 s the creep is one breath, 0.1 to 0.15%/s, one direction, eased at both ends."""
    size = (539, 400)
    cam = R.still_camera(shot_of({"people": False}, dur), size, W, H)
    assert cam.get("bracket") is None
    zs = [f["z"] for _, f in frames(cam, dur)]
    assert runs(zs) == [1]                                           # one way, start to end
    assert zs[-1] == pytest.approx(M.TOUR["whole_creep_max"])
    mean = math.log(zs[-1]) / dur
    assert 0.001 <= math.exp(mean) - 1 <= 0.0015 + 1e-9
    rates = [math.log(b / a) * HZ for a, b in zip(zs, zs[1:])]
    assert max(rates) <= 0.0015 + 1e-4                                # the cruise, never a 1.5%/s push
    assert rates[0] < max(rates) / 4 and rates[-1] < max(rates) / 4    # eased at both ends (the rostrum curve)


# --------------------------------------------------------------------------
# Arrival before the word
# --------------------------------------------------------------------------


def _words(text, t, every=0.4, measured=True):
    out = []
    for i, w in enumerate(text.split()):
        out.append({"w": w, "n": T.norm_word(w), "i": i, "t": t + i * every, "e": t + (i + 1) * every,
                    "line": "L1", "kind": "narration", "m": measured})
    return out


def test_the_detail_arrives_before_the_subject_at_word_with_the_a43_lead():
    size = (420, 560)
    words = _words("the report counts the dead and the burned houses in every village", 20.0)
    shot = shot_of({"people": False, "roi": [TEXT]}, 45.0, subject_at="burned houses")
    cam = R.still_camera(shot, size, W, H, words=words)
    tm = cam["bracket"]["timing"]
    onset = next(w["t"] for w in words if w["n"] == "burned")
    assert tm["arrive_s"] == pytest.approx(onset - M.CINE["anchor_lead_s"], abs=1e-3)
    assert tm["anchor"]["at"] == "burned houses" and tm["anchor"]["measured"]
    name_end = next(w["e"] for w in words if w["n"] == "houses")
    assert tm["arrive_s"] + tm["hold_s"] >= name_end - 1e-6          # held through the words
    # the detail is reached on time: the frame at arrival is at its depth
    f = OV.framing_at(cam, tm["arrive_s"], 45.0)
    assert f["z"] == pytest.approx(cam["bracket"]["segments"][1]["b"]["z"], rel=1e-9)
    # a cue too early for the whole and the push keeps whole + creep, saying why
    early = R.still_camera(shot, size, W, H, words=_words("burned houses and more words here", 1.0))
    assert early.get("bracket") is None and "no time around the cue" in early["bracket_why"]
    # the region subject_at names, when the ledger names no subject
    place = {"name": "text-1", "x": 0.1, "y": 0.6, "w": 0.3, "h": 0.2, "kind": "text", "cue": "burned houses"}
    by_cue = R.still_camera(shot_of({"people": False, "roi": [place]}, 45.0, subject_at="burned houses"), size, W,
                            H, words=words)
    assert by_cue["bracket"]["detail"]["src"] == "subject_at" and by_cue["bracket"]["detail"]["name"] == "text-1"


# --------------------------------------------------------------------------
# Truth on every frame: people and must_show, the cap, the picture's own pixels (a property test)
# --------------------------------------------------------------------------


def test_people_and_must_show_are_whole_at_some_point_for_random_small_pictures():
    rng = random.Random(12)
    made = 0
    for _ in range(60):
        iw, ih = rng.randint(250, 640), rng.randint(250, 640)
        size = (iw, ih)
        if T.upscale(size, W, H, 1.0) <= 3.0:
            continue                                                     # it would fill: no exception
        def box():
            w, h = rng.uniform(0.05, 0.5), rng.uniform(0.05, 0.5)
            return {"x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w, "h": h}
        people = [dict(box(), name=f"p{k}") for k in range(rng.randint(0, 3))]
        subj = dict(box(), name="subject", kind=rng.choice(["text", "object", "place", "face"]), source="auto",
                    confidence=0.9)
        ms = dict(box(), name="caption", kind="text", must_show=True)
        item = {"people": people, "roi": [subj, ms]}
        dur = rng.uniform(5.0, 60.0)
        shot = shot_of(item, dur)
        cam = R.still_camera(shot, size, W, H)
        wins = windows(cam, size, dur, 8.0)
        src = [w for _, _, w, _ in wins]
        assert T.people_check(src, T.people_of(item), size)["ok"]
        assert not T.must_show(src, item, size)
        for _, f, s, d in wins:
            assert s[0] >= -0.5 and s[1] >= -0.5 and s[2] <= iw + 0.5 and s[3] <= ih + 0.5
            if cam.get("bracket") is not None:
                assert BR.master_scale(size) * f["z"] <= 3.0 + 1e-6
        if cam.get("bracket") is not None:
            made += 1
            assert wins[0][1] == {"z": 1.0, "x": 0.5, "y": 0.5}
            assert wins[-1][1]["z"] == pytest.approx(1.0)
            assert runs([f["z"] for _, f, _, _ in wins]) == [1, -1]
    assert made >= 3                                                     # the property ran on real brackets


def test_steering_moves_the_detail_off_a_text_zone_when_it_can():
    size = (420, 560)
    caption = {"name": "caption", "x": 0.3, "y": 0.42, "w": 0.2, "h": 0.05, "kind": "text", "must_show": True}
    subj = {"name": "subject", "x": 0.25, "y": 0.3, "w": 0.3, "h": 0.17, "kind": "object", "source": "auto",
            "confidence": 0.9}
    item = {"people": False, "roi": [subj, caption]}
    zone = M.ZONES["SUB"] if "SUB" in M.ZONES else (0.1, 0.8, 0.9, 0.95)
    plain = R.still_camera(shot_of(item, 40.0), size, W, H)
    steered = R.still_camera(shot_of(item, 40.0), size, W, H, avoid=[(T.roi_box(caption), zone)])
    def ov(c):
        win = BR.window(c["bracket"]["segments"][1]["b"], size, W, H)
        return BR.overlap(win, [(T.roi_box(caption), zone)], size, W, H), win
    o_plain, _ = ov(plain)
    o_steer, win = ov(steered)
    assert o_steer <= o_plain + 1e-9
    assert BR.inside(T.roi_box(subj), win, 1e-4)                        # never at the cost of the detail's own region


# --------------------------------------------------------------------------
# In the plan: lints, journal, Sources
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("cine12") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _plan(film, name="cine12"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def lints(evs, rule, unit):
    return [e["status"] for e in evs if e["kind"] == "lint" and e.get("rule") == rule and e.get("unit") == unit]


def test_the_plan_journals_why_a_short_exception_keeps_whole_and_creep(film):
    plan, j = _plan(film)
    evs = J.read(j.path)
    s5 = next(s for s in plan["shots"] if s["id"] == "S5")
    assert s5["_cam"].get("bracket") is None
    assert any(e["kind"] == "decision" and e.get("unit") == "S5" and "whole + creep" in e.get("what", "")
               for e in evs)
    assert lints(evs, "still-first-frame-whole", "S5") == ["pass"]


def test_a_written_path_on_an_exception_shot_is_refused_when_it_cannot_be_drawn(film):
    _edit(film, lambda p: _shot(p, "S5").update(camera=[{"x": 0.5, "y": 0.5, "z": 1.2}, {"x": 0.4, "y": 0.4, "z": 1.3}],
                                                 preset=None))
    with pytest.raises(R.Refused, match="tour-path"):
        _plan(film, "cine12-two")
    _edit(film, lambda p: _shot(p, "S5").update(camera=[{"x": 0.5, "y": 0.4, "z": 1.2}]))
    with pytest.raises(R.Refused, match="tour-path"):                    # 3 s cannot hold the bracket's settles
        _plan(film, "cine12-short")


def _long_s5(play, extra=30.0):
    """S5 held 33 s: every later shot and line moves on by the same."""
    s5 = _shot(play, "S5")
    t5 = float(s5["start_s"])
    s5["dur_s"] = float(s5["dur_s"]) + extra
    for p in play["parts"]:
        for s in p["shots"]:
            if s is not s5 and float(s.get("start_s", 0)) > t5:
                s["start_s"] = float(s["start_s"]) + extra
        for ln in p.get("lines") or []:
            if float(ln.get("start_s", 0)) > t5:
                ln["start_s"] = float(ln["start_s"]) + extra


def test_the_plan_draws_the_bracket_lints_it_and_sources_say_so(film):
    _edit(film, _long_s5)
    sub = {"name": "subject", "x": 0.3, "y": 0.3, "w": 0.3, "h": 0.2, "kind": "object", "source": "human"}
    # a taller synthetic portrait (the fill would still pass 3x: 4.8x), so the cap leaves room for a push past 1.25
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 700), (90, 80, 70))
    ImageDraw.Draw(img).rectangle((120, 210, 240, 350), fill=(200, 190, 170))
    img.save(film / "stills" / "FX-STILL-C.png")
    _edit(film, lambda d: next(i for i in d["items"] if i["id"] == "FX-STILL-C").update(roi=[sub], width=400,
                                                                                         height=700),
          name="stills-ledger.json")
    plan, j = _plan(film, "cine12-long")
    evs = J.read(j.path)
    s5 = next(s for s in plan["shots"] if s["id"] == "S5")
    assert s5["_cam"]["bracket"] is not None
    for rule in ("tour-softness", "tour-people", "still-zoom-limit", "still-first-frame-whole"):
        assert lints(evs, rule, "S5") == ["pass"], rule
    assert any(e["kind"] == "decision" and e.get("unit") == "S5" and "inside the whole" in e.get("what", "")
               for e in evs)
    doc = R.sources_doc(plan, j, {})
    row = next(x for x in doc["shots"] if x["id"] == "S5")
    assert row["fill_detail"] in ("detail", "field") and row["fill_exception"]
    assert row["fill_detail"] == s5["_cam"]["bracket"]["detail"]["scale"]
    other = next(x for x in doc["shots"] if x["id"] == "S4")
    assert other["fill_detail"] is False


def test_a_push_under_1_25_would_not_read_and_keeps_whole_and_creep():
    """Reviewer, 2026-10-17 (founder to confirm): a stop showing more than 64% of the picture is no move."""
    assert M.BRACKET["min_detail_z"] == M.BRACKET_MIN_Z == 1.25
    size = (611, 404)                                                  # Partition O4: the cap allows z 1.122
    tiny = dict(TEXT, x=0.45, y=0.45, w=0.05, h=0.05)
    cam = R.still_camera(shot_of({"people": False, "roi": [tiny]}, 50.0), size, W, H)
    assert cam.get("bracket") is None and "push under 1.25 would not read" in cam["bracket_why"]
    big = dict(TEXT, x=0.1, y=0.1, w=0.7, h=0.7)                       # framing it needs z 1.14: too shallow
    cam = R.still_camera(shot_of({"people": False, "roi": [big]}, 50.0), (420, 560), W, H)
    assert cam.get("bracket") is None and "would not read" in cam["bracket_why"]
    wrote = R.still_camera(shot_of({"people": False}, 50.0, camera=[{"x": 0.5, "y": 0.4, "z": 1.2}]), (420, 560), W, H)
    assert any("too shallow" in p for p in wrote["problems"])


@pytest.mark.parametrize("size,w", [((420, 560), 0.25), ((420, 560), 0.6), ((578, 800), 0.2), ((416, 672), 0.3),
                                    ((530, 742), 0.5), ((539, 408), 0.2)])
def test_the_record_names_a_detail_only_when_the_deepest_frame_shows_40_percent_or_less(size, w):
    sub = dict(TEXT, x=0.5 - w / 2, y=0.4 - w / 2, w=w, h=w, kind="object")
    cam = R.still_camera(shot_of({"people": False, "roi": [sub]}, 50.0), size, W, H)
    if cam.get("bracket") is None:
        assert BR.sources_scale(cam) is False
        return
    shown = min((s[2] - s[0]) * (s[3] - s[1]) / (size[0] * size[1]) for _, _, s, _ in windows(cam, size, 50.0, 8.0))
    scale = BR.sources_scale(cam)
    assert scale == ("detail" if shown <= M.CINE["detail_share"] + 1e-6 else "field")
    assert (BR.copy_phrase(cam) == "to one detail") == (scale == "detail")
    assert shown <= 1 / M.BRACKET_MIN_Z ** 2 + 1e-6                     # every bracket shows 64% or less at its deepest
    assert BR.sources_scale({"fill_exception": None}) is None
