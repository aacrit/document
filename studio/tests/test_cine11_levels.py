"""Cinematography ticket 11, GRAMMAR A46 (founder ruling 4, 2026-10-17: "Black
floor: AUTOMATED ... every still over the threshold (p2 > 24). White, gamma and
hue stay untouched. Log each applied floor in the ledger as non-material ...
opt out per still with `levels: none` and a stated reason. `grade-jump` stays
guidance."). Small synthetic images only; nothing is rendered or encoded."""

import colorsys
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import journal as J
from studio.engine import levels as LV
from studio.engine import render as R
from conftest import make_film


def grey_image(counts: dict[int, int], width: int = 100) -> Image.Image:
    """A grey image with exactly ``counts[v]`` pixels at level v (rows filled in order)."""
    vals = np.concatenate([np.full(n, v, np.uint8) for v, n in sorted(counts.items())])
    assert vals.size % width == 0
    a = vals.reshape(-1, width)
    return Image.fromarray(np.stack([a, a, a], axis=-1), "RGB")


def milky(w: int = 240, h: int = 160, black: int = 48, tint=(1.0, 0.86, 0.66), seed: int = 0) -> Image.Image:
    """A sepia scan with a grey floor: a tone ramp from ``black`` to paper white, tinted, with grain."""
    rng = np.random.default_rng(seed)
    y = np.linspace(black, 235, w)[None, :].repeat(h, 0) + rng.normal(0, 2.0, (h, w))
    rgb = np.stack([np.clip(y * t + (1 - t) * 8, 0, 255) for t in tint], axis=-1)
    return Image.fromarray(np.rint(rgb).astype(np.uint8), "RGB")


def hue_deg(rgb) -> float:
    r, g, b = (c / 255.0 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


def hue_delta(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


# --------------------------------------------------------------------------
# The measure and the threshold
# --------------------------------------------------------------------------


def test_luma_is_rec709_in_integers_and_a_grey_is_its_own_level():
    a = np.array([[[v, v, v] for v in range(256)]], np.uint8)
    assert (LV.luma_u8(a)[0] == np.arange(256)).all()
    assert LV.luma_u8(np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], np.uint8)).tolist() == [[54, 182, 19]]


@pytest.mark.parametrize("p2,floored", [(24, False), (25, True)])
def test_the_threshold_p2_24_is_untouched_and_25_is_floored(p2, floored):
    img = grey_image({12: 5, p2: 15, 200: 980})          # p0.5 = 12 (rank 5), p2 = rank 20
    m = LV.measure(img)
    assert (m["p0_5"], m["p2"]) == (12, p2)
    fp = LV.floor_params(m)
    assert (fp is not None) is floored
    if floored:
        assert fp == {"black_in": 12, "black_out": 10, "white": 255, "gain": round(245 / 243, 4)}


def test_a_floor_never_lifts_a_black():
    """p2 over 24 with p0.5 already at or under 10 (a few true blacks, a border) is left as held."""
    m = LV.measure(grey_image({4: 5, 34: 15, 200: 980}))
    assert m["p2"] == 34 and m["p0_5"] == 4 and LV.floor_params(m) is None
    rec = LV.decide({"kind": "archive_still", "mark": "ARCHIVE"}, {}, m, None)
    assert rec["applied"] is False and "already at or under 10" in rec["why"]


# --------------------------------------------------------------------------
# The map: endpoints, linear, hue and sepia kept
# --------------------------------------------------------------------------


def test_the_map_sends_p0_5_to_10_keeps_white_and_moves_midtones_on_a_straight_line():
    p = {"black_in": 40, "black_out": 10, "white": 255}
    t = LV.lut(p)
    assert t[40] == 10 and t[255] == 255 and t[0] == 0
    for c in range(40, 256):                                 # every level sits on the line, rounded half up
        assert t[c] == math.floor(10 + (c - 40) * 245 / 215 + 0.5)
    d = np.diff(t[40:])
    assert d.min() >= 1 and d.max() <= 2                     # monotone, no gamma bend: steps of the gain 1.14
    mids = [t[c] - c for c in (80, 128, 176)]                # the shift falls linearly toward white
    assert mids[0] < mids[1] < mids[2] <= 0
    assert abs((mids[1] - mids[0]) - (mids[2] - mids[1])) <= 1
    img = grey_image({40: 5, 128: 15, 255: 980})
    out = np.asarray(LV.apply(img, {"applied": True, **p}))
    assert set(np.unique(out[..., 0])) == {10, t[128], 255}
    assert LV.measure(Image.fromarray(out))["p0_5"] == 10


def test_hue_and_sepia_are_preserved_within_one_degree():
    img = milky(black=48)
    m = LV.measure(img)
    fp = LV.floor_params(m)
    assert m["p2"] > LV.P2_MAX and fp is not None
    out = LV.apply(img, {"applied": True, **fp})
    a, b = np.asarray(img).astype(float), np.asarray(out).astype(float)
    # the sepia patch (a mid-tone block) and the paper (the light end) keep their hue angle
    for x0, x1 in ((90, 130), (200, 236)):
        ha, hb = hue_deg(a[:, x0:x1].reshape(-1, 3).mean(0)), hue_deg(b[:, x0:x1].reshape(-1, 3).mean(0))
        assert hue_delta(ha, hb) <= 1.0, (x0, ha, hb)
    # and so does each sepia colour on its own, through the 8-bit table
    t = LV.lut(fp)
    for rgb in ((150, 110, 70), (112, 92, 60), (200, 170, 128), (240, 228, 200)):
        assert hue_delta(hue_deg(rgb), hue_deg([t[c] for c in rgb])) <= 1.0, rgb
    assert LV.measure(out)["p2"] < m["p2"]


def test_per_channel_black_points_would_shift_the_hue_so_one_map_is_shared():
    """The control: a sepia print's floor is itself tinted (warm paper base), so a black point per channel
    would neutralise it, a grade; the one shared map keeps the hue."""
    y = np.linspace(0, 190, 240)[None, :].repeat(160, 0)
    arr = np.rint(np.stack([y + 50, y + 35, y + 20], -1)).astype(np.uint8)     # a warm floor (50, 35, 20)
    img = Image.fromarray(arr, "RGB")
    q = [int(np.percentile(arr[..., k], 0.5)) for k in range(3)]
    per = np.stack([np.asarray(LV.lut({"black_in": q[k], "black_out": 10, "white": 255}))[arr[..., k]] for k in range(3)], -1)
    mid = arr[:, 100:140].reshape(-1, 3).mean(0)
    assert hue_delta(hue_deg(mid), hue_deg(per[:, 100:140].reshape(-1, 3).mean(0))) > 1.0
    fp = LV.floor_params(LV.measure(img))
    assert fp is not None
    shared = np.asarray(LV.apply(img, {"applied": True, **fp}))
    assert hue_delta(hue_deg(mid), hue_deg(shared[:, 100:140].reshape(-1, 3).mean(0))) <= 1.0


def test_determinism_same_bytes_twice():
    img = milky(black=60, seed=3)
    p = {"applied": True, **LV.floor_params(LV.measure(img))}
    assert LV.apply(img, p).tobytes() == LV.apply(milky(black=60, seed=3), p).tobytes()
    assert LV.measure(img) == LV.measure(milky(black=60, seed=3))
    assert LV.apply(img, None) is img and LV.apply(img, {"applied": False}) is img


def sepia_shadows(seed: int = 4) -> np.ndarray:
    """A sepia print whose shadows are warm: a dark brown (60, 40, 22) under a ramp to paper, with grain."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, 300)[None, :].repeat(200, 0)
    base = np.array([60, 40, 22.0]) + y[..., None] * np.array([180, 175, 160.0])
    return np.rint(np.clip(base + rng.normal(0, 1.5, (200, 300, 1)), 0, 255)).astype(np.uint8)


def test_the_black_point_reads_the_darkest_channel_so_sepia_shadows_do_not_clip():
    arr = sepia_shadows()
    img = Image.fromarray(arr, "RGB")
    m = LV.measure(img)
    fp = LV.floor_params(m)
    assert fp is not None and fp["black_in"] == m["min0_5"] < m["p0_5"]
    out = np.asarray(LV.apply(img, {"applied": True, **fp}))
    newly = ((out == 0) & (arr > 0)).any(-1).mean()
    assert newly <= 0.005, newly                               # at most 0.5% of pixels newly clipped in any channel
    keep = (out > 0).all(-1) & (out < 255).all(-1) & ((arr.max(-1).astype(int) - arr.min(-1)) >= 12)
    ha = np.array([hue_deg(px) for px in arr[keep][::23]])
    hb = np.array([hue_deg(px) for px in out[keep][::23]])
    assert max(hue_delta(a, b) for a, b in zip(ha, hb)) <= 3.0  # unclipped pixels keep their hue (8-bit rounding)
    # the control: a black point read from luma clips the blue of the shadows and turns them
    lum = np.asarray(LV.apply(img, {"applied": True, "black_in": m["p0_5"], "black_out": 10, "white": 255}))
    assert ((lum == 0) & (arr > 0)).any(-1).mean() > 0.05


@pytest.mark.parametrize("black,floored", [(73, True), (74, False)])
def test_a_pale_scan_past_the_gain_cap_is_shown_as_held(black, floored):
    img = grey_image({black: 5, black + 5: 15, 240: 980})
    m = LV.measure(img)
    assert m["min0_5"] == black
    fp = LV.floor_params(m)
    assert (fp is not None) is floored
    rec = LV.decide({"kind": "archive_still", "mark": "ARCHIVE"}, {}, m, None)
    if floored:
        assert fp["gain"] <= LV.LEVELS_MAX_GAIN and rec["applied"]
    else:
        assert LV.gain(black) > LV.LEVELS_MAX_GAIN and rec["applied"] is False and rec["pale"] is True
        assert rec["why"].startswith("pale scan, left as held")


def test_the_copy_claims_exactly_what_the_map_does():
    """Every claim in the record's WHAT and the Sources page's copy, paired with the math (like the privacy page)."""
    web = (Path(R.__file__).resolve().parents[2] / "web" / "src" / "film-data.ts").read_text(encoding="utf-8")
    page = web.split("export const BLACK_FLOOR_COPY =", 1)[1].split('"')[1]
    claims = ("grey floor taken down to near black", "one straight-line level", "the same on every colour",
              "raises contrast and colour strength by the same small factor", "the white point kept")
    for text in (LV.WHAT, page):
        for c in claims:
            assert c in text, (c, text)
        for word in ("hue", "untouched", "flat", "unchanged", "gamma"):
            assert word not in text.lower(), (word, text)
    assert "flat" not in LV.MATERIALITY
    arr = sepia_shadows(seed=9)
    img = Image.fromarray(arr, "RGB")
    fp = LV.floor_params(LV.measure(img))
    t = LV.lut(fp)
    out = np.asarray(LV.apply(img, {"applied": True, **fp}))
    # near black: the black point goes to 10; the white point kept: 255 stays 255
    assert t[fp["black_in"]] == 10 and t[255] == 255
    # one straight-line level: a single slope, rounding aside
    c = np.arange(fp["black_in"], 256)
    assert np.abs(np.array(t)[c] - (10 + (c - fp["black_in"]) * fp["gain"])).max() <= 0.5 + 1e-9
    # the same on every colour: one table for R, G and B
    assert all((out[..., k] == np.array(t)[arr[..., k]]).all() for k in range(3))
    # contrast and colour strength rise by the same small factor: every difference between channels times k
    ok = (out > 0).all(-1)
    d_in = arr[ok].astype(int)[:, 0] - arr[ok].astype(int)[:, 2]
    d_out = out[ok].astype(int)[:, 0] - out[ok].astype(int)[:, 2]
    assert np.abs(d_out - fp["gain"] * d_in).max() <= 1.0
    assert 1.0 < fp["gain"] <= LV.LEVELS_MAX_GAIN


def test_the_overlay_write_is_atomic(tmp_path, monkeypatch):
    led = tmp_path / "stills-ledger.json"
    led.write_text("{}", encoding="utf-8")
    entry = {"FX": {"version": LV.VERSION, "applied": False}}
    assert LV.write_overlays({str(led): entry}) == [str(tmp_path / "stills-ledger.levels.json")]
    before = (tmp_path / "stills-ledger.levels.json").read_bytes()
    assert b"\r\n" not in before    # LF only: byte-identical whatever OS wrote it (Windows text mode would CRLF it)
    assert LV.write_overlays({str(led): entry}) == []          # unchanged content is not rewritten

    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(LV.os, "replace", boom)
    assert LV.write_overlays({str(led): {"FX": {"version": LV.VERSION, "applied": True}}}) == []
    assert (tmp_path / "stills-ledger.levels.json").read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))


# --------------------------------------------------------------------------
# Who gets it: opt-out, the excluded classes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind,mark", [("archive_video", "ARCHIVE"), ("card", "CARD"), ("black", "CARD"),
                                       ("drawn", "DRAWN"), ("title_sequence", "DRAWN"), ("generated", "AI-GENERATED"),
                                       ("archive_still", "DRAWN"), ("archive_still", "AI-GENERATED")])
def test_never_on_clips_cards_drawn_ai_or_the_titles(kind, mark):
    ok, why = LV.eligible({"kind": kind, "mark": mark}, {"_path": "x.png"})
    assert not ok and why.startswith("never floored")


def test_archive_and_reconstructed_stills_are_eligible_and_reconstructed_states_why():
    assert LV.eligible({"kind": "archive_still", "mark": "ARCHIVE"}, {"_path": "x.png"}) == (True, "an archive still")
    ok, why = LV.eligible({"kind": "archive_still", "mark": "RECONSTRUCTED"}, {"_path": "x.png"})
    assert ok and "scan of a real photograph" in why
    m = LV.measure(milky())
    rec = LV.decide({"kind": "archive_still", "mark": "RECONSTRUCTED"}, {}, m, {"p2": 12})
    assert rec["applied"] and rec["why_reconstructed"] == LV.RECONSTRUCTED_WHY and rec["materiality"] == LV.MATERIALITY


def test_an_opt_out_is_honoured_and_carries_its_reason():
    m = LV.measure(milky())
    rec = LV.decide({"kind": "archive_still", "mark": "ARCHIVE"}, {"levels": "none", "levels_reason": "the fade is the print"},
                    m, None)
    assert rec == {"version": LV.VERSION, "p0_5": m["p0_5"], "p2": m["p2"], "min0_5": m["min0_5"], "applied": False,
                   "opt_out": True,
                   "reason": "the fade is the print"}
    img = milky()
    assert LV.apply(img, rec) is img


def test_the_schema_refuses_none_without_a_reason():
    """#5's cine-schema (tour.item_schema) refuses levels: none with no levels_reason, and any other value."""
    from studio.engine import tour as T
    assert any("levels_reason" in p for p in T.item_schema({"levels": "none"})[0])
    assert any("levels_reason" in p for p in T.item_schema({"levels": "none", "levels_reason": " "})[0])
    assert any("levels is" in p for p in T.item_schema({"levels": "floor", "levels_reason": "x"})[0])
    assert not [p for p in T.item_schema({"levels": "none", "levels_reason": "the fade is the print"})[0] if "levels" in p]


# --------------------------------------------------------------------------
# grade-jump (guidance)
# --------------------------------------------------------------------------


def test_grade_jump_warns_over_20_across_a_cut_or_dissolve_after_floors():
    shots = [{"id": "a", "transition_in": {"type": "cut"}}, {"id": "b", "transition_in": {"type": "cut"}},
             {"id": "c", "transition_in": {"type": "dissolve", "s": 1}}, {"id": "d", "transition_in": {"type": "dip", "s": 1}},
             {"id": "e", "transition_in": {"type": "cut"}}]
    jumps = LV.grade_jumps(shots, {"a": 5, "b": 26, "c": 46, "d": 90, "e": 10})
    assert [(j["from"], j["to"], j["delta"], j["warn"]) for j in jumps] == [
        ("a", "b", 21, True), ("b", "c", 20, False), ("d", "e", 80, True)]     # c -> d is a dip, not a cut


# --------------------------------------------------------------------------
# The plan: applied once in source prep, the overlay, the journal, sources.json
# --------------------------------------------------------------------------


def _edit(path, fn):
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _archive_film(tmp_path, *, opt_out: bool = False):
    """The fixture with S3 and S4 as real archive stills (a milky sepia scan and a deep one) and S5 left DRAWN
    with a milky picture of its own (a picture the studio drew is never floored)."""
    film = make_film(tmp_path / "film")
    led = film / "stills-ledger.json"

    def real(d):
        for it in d["items"]:
            if it["id"] in ("FX-STILL-A", "FX-STILL-B"):
                for k in ("synthetic", "test_fixture", "generator", "content_date", "content_basis"):
                    it.pop(k, None)
                it.update(date="1947", archive="Test Archive", creator="A photographer", basis="public domain")
                if opt_out and it["id"] == "FX-STILL-A":
                    it.update(levels="none", levels_reason="the fade is the print")
    _edit(led, real)
    milky(1500, 1050, black=52).save(film / "stills" / "FX-STILL-A.png")
    deep = np.asarray(milky(395, 316, black=0, seed=1))
    Image.fromarray(deep).save(film / "stills" / "FX-STILL-B.png")
    milky(300, 420, black=60, seed=2).save(film / "stills" / "FX-STILL-C.png")
    _edit(film / "screenplay.json", lambda p: (_shot(p, "S3").update(mark="ARCHIVE"), _shot(p, "S4").update(mark="ARCHIVE")))
    return film


def _plan(film, name="levels"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def test_the_plan_floors_an_archive_still_logs_it_and_sources_json_states_it(tmp_path):
    film = _archive_film(tmp_path)
    plan, j = _plan(film)
    s3, s4, s5 = (next(s for s in plan["shots"] if s["id"] == k) for k in ("S3", "S4", "S5"))
    lv = s3["_levels"]
    assert lv["applied"] and lv["black_out"] == 10 and lv["white"] == 255 and lv["p2"] > 24 and lv["p2_after"] < lv["p2"]
    assert lv["materiality"] == LV.MATERIALITY and lv["version"] == LV.VERSION
    assert s4["_levels"]["applied"] is False and "at or under 24" in s4["_levels"]["why"]
    assert "_levels" not in s5                                 # DRAWN: never floored, even milky
    # the ledger overlay beside the ledger; the human ledger itself is untouched
    side = film / "stills-ledger.levels.json"
    doc = json.loads(side.read_text(encoding="utf-8"))
    a = doc["items"]["FX-STILL-A"]
    assert a["applied"] and a["materiality"] == LV.MATERIALITY and a["black_in"] == lv["black_in"] and len(a["sha256"]) == 64
    assert "levels" not in json.dumps(json.loads((film / "stills-ledger.json").read_text(encoding="utf-8")))
    # a still never floored is measured and cached there too, for grade-jump
    c = doc["items"]["FX-STILL-C"]
    assert c["applied"] is False and c["why"].startswith("never floored") and c["measure"]["p2"] > 24
    assert not list(film.glob(".*.tmp"))                       # written atomically, no temp left behind
    # the journal: a decision for the floor, a grade-jump lint at the S3 -> S4 dissolve
    evs = J.read(j.path)
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "black floor" in e["what"] for e in evs)
    gj = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "grade-jump"]
    assert [e["unit"] for e in gj] == ["S4", "S5"] and {e["severity"] for e in gj} == {"warn"}
    assert gj[0]["evidence"]["p2_from"] == lv["p2_after"] and gj[0]["status"] == "pass"   # after the floor: no jump
    assert gj[1]["status"] == "fail" and gj[1]["evidence"]["delta"] > 20     # the deep scan cut to the milky drawing
    # sources.json: the shot says what was done to it
    doc = R.sources_doc(plan, j, {})
    row = next(x for x in doc["shots"] if x["id"] == "S3")
    assert row["levels"]["applied"] and row["levels"]["what"] == LV.WHAT and row["mark"]["class"] == "ARCHIVE"
    assert next(x for x in doc["shots"] if x["id"] == "S5")["levels"] is None
    # applied once, in the source-still prep (before the pre-scale), the A7 check's reference with it
    pics = R.Pictures(plan)
    held = np.asarray(pics.still(s3))
    with Image.open(s3["_item"]["_path"]) as im:
        raw = im.convert("RGB")
    assert held.shape[:2] == (raw.height, raw.width) or held.shape[0] < raw.height
    expect = np.asarray(LV.apply(raw, lv).resize((held.shape[1], held.shape[0]), Image.Resampling.LANCZOS)) \
        if held.shape[:2] != (raw.height, raw.width) else np.asarray(LV.apply(raw, lv))
    assert np.abs(held.astype(int) - expect.astype(int)).max() <= 1
    assert LV.measure(Image.fromarray(held))["min0_5"] <= 11
    # the segment key changes with the floor
    k1 = R.shot_key(plan, plan["shots"].index(s3), {}, None)
    s3["_levels"] = dict(lv, black_in=lv["black_in"] + 1)
    assert R.shot_key(plan, plan["shots"].index(s3), {}, None) != k1


def test_the_plan_is_deterministic_and_reads_its_own_overlay_as_the_cache(tmp_path):
    film = _archive_film(tmp_path)
    p1, _ = _plan(film, "a")
    side = film / "stills-ledger.levels.json"
    first = side.read_bytes()
    p2, _ = _plan(film, "b")
    assert side.read_bytes() == first
    get = lambda p: next(s for s in p["shots"] if s["id"] == "S3")["_levels"]
    assert get(p1) == get(p2)
    # a cached measurement is used only for the same file under the same version
    doc = json.loads(first)
    doc["items"]["FX-STILL-A"]["measure"]["min0_5"] = 30
    side.write_text(json.dumps(doc), encoding="utf-8")
    assert get(_plan(film, "c")[0])["black_in"] == 30
    doc["items"]["FX-STILL-A"]["sha256"] = "0" * 64
    side.write_text(json.dumps(doc), encoding="utf-8")
    assert get(_plan(film, "d")[0]) == get(p1)


def test_an_opted_out_still_is_shown_as_held_and_the_record_says_why(tmp_path):
    film = _archive_film(tmp_path, opt_out=True)
    plan, j = _plan(film)
    s3 = next(s for s in plan["shots"] if s["id"] == "S3")
    assert s3["_levels"]["applied"] is False and s3["_levels"]["reason"] == "the fade is the print"
    with Image.open(s3["_item"]["_path"]) as im:
        raw = im.convert("RGB")
    held = R.Pictures(plan).still(s3)
    if held.size == raw.size:
        assert held.tobytes() == raw.tobytes()
    doc = json.loads((film / "stills-ledger.levels.json").read_text(encoding="utf-8"))
    assert doc["items"]["FX-STILL-A"]["opt_out"] is True and doc["items"]["FX-STILL-A"]["reason"] == "the fade is the print"
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "shown as held" in e["what"] for e in J.read(j.path))


def test_the_check_cli_reports_without_planning(tmp_path, capsys):
    film = _archive_film(tmp_path)
    out = tmp_path / "levels.json"
    assert LV.main(["--check", str(film), "--json", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert [r["id"] for r in rep["floored"]] == ["FX-STILL-A"] and [r["id"] for r in rep["untouched"]] == ["FX-STILL-B"]
    assert [(j["from"], j["to"]) for j in rep["grade_jumps"]] == [("S4", "S5")]
    assert not (film / "stills-ledger.levels.json").exists()      # read-only
    assert "floored (1)" in capsys.readouterr().out
