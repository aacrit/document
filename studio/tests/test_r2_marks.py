"""R2 (A31, BRAND-KIT 12): the provenance mark bottom right, smaller and
fainter; the label only on a change of class or year; AI-GENERATED always
labelled; the label-rate lint; the mark key card and its lint."""

import json

import numpy as np
import pytest
from PIL import Image

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R

FONTS = M.Fonts()
SIZES = [(1920, 1080), (1280, 720)]
LONG = "Reconstructed · 1946 · colour cast removed"


def lints(j, rule):
    return [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == rule]


def _alpha_box(img: Image.Image):
    a = np.asarray(img.getchannel("A"))
    ys, xs = np.nonzero(a)
    return xs.min(), ys.min(), xs.max(), ys.max()


# --------------------------------------------------------------------------
# Position (BRAND-KIT 12): bottom right, inside title safe, clear of every zone
# --------------------------------------------------------------------------


@pytest.mark.parametrize("W, H", SIZES)
def test_the_glyph_sits_bottom_right_inside_title_safe(W, H):
    L = M.Layout(W, H)
    gx, gy = M.glyph_origin(L)
    d = M.glyph_px(L)
    assert gx + d == round(0.96 * W) and gy + d == round(0.95 * H)              # 4% and 5% in: the watermark's insets, mirrored
    assert gy >= M.SUB["bottom"] / 100 * H                                      # below the subtitle cue
    zx0, zy0, zx1, zy1 = M.MARK_GLYPH_ZONE
    tile, (ox, oy) = M.glyph_tile(W, H, "ARCHIVE")
    assert zx0 * W <= ox and ox + tile.width <= zx1 * W and zy0 * H <= oy and oy + tile.height <= zy1 * H
    for x, y in M.glyph_shape_probes(L):                                       # the shape probes moved with it
        assert zx0 * W <= x <= zx1 * W and zy0 * H <= y <= zy1 * H


@pytest.mark.parametrize("W, H", SIZES)
@pytest.mark.parametrize("reveal", [1.0, 0.3])
def test_the_label_stays_in_its_zone_clear_of_subtitles_overlays_lower_thirds_and_the_watermark(W, H, reveal):
    L = M.Layout(W, H)
    tile, (x, y) = M._label_tile(L, LONG, 1.0, reveal, FONTS)                # A42: whole, or partly grown out of the glyph
    bx0, by0, bx1, by1 = _alpha_box(tile)
    x0, y0, x1, y1 = x + bx0, y + by0, x + bx1, y + by1                         # every pixel the label touches, shadow too
    gx, _ = M.glyph_origin(L)
    ring = max(1, L.px(M.LABEL["halo"]))
    assert x1 < gx - ring + 1                                                   # never on the glyph's tile (the lint's pixels)
    assert y0 >= M.SUB["bottom"] / 100 * H                                      # below the subtitle cue's scrim (93%)
    assert y0 >= M.OVERLAY["bottom"] / 100 * H                                  # below a date or count overlay (92%)
    assert y1 <= 0.965 * H                                                      # inside action safe (96.5%), shadow included
    assert x0 >= (M.LT["x"] + M.LT["max_w"]) / 100 * W                          # right of the lower third's measure (60%)
    assert y0 > (M.WM["top"] + M.WM["box"]) / 100 * H                           # nowhere near the watermark (top right)
    zx0, zy0, zx1, zy1 = M.MARK_ZONE
    assert zx0 * W <= x0 and x1 <= zx1 * W and zy0 * H <= y0


@pytest.mark.parametrize("W, H", SIZES)
def test_the_label_is_smaller_and_fainter_and_its_size_is_the_kits(W, H):
    L = M.Layout(W, H)
    assert L.px(M.LABEL["size"]) == {1080: 22, 720: 14}[H]          # 2.0% since the cinematography pass (was 17 / 12)
    assert M.glyph_px(L) == {1080: 9, 720: 6}[H]
    assert M.LABEL["alpha"] == 0.6 and M.LABEL["hold"] == 2.0


def test_a_label_that_would_reach_the_lower_third_measure_is_refused():
    L = M.Layout(1920, 1080)
    assert M.label_check(L, LONG, FONTS) > 0
    with pytest.raises(M.TextOverflow, match="lower third's measure"):
        M.label_check(L, "Reconstructed · 1946 · " + ", ".join(["colour cast removed"] * 4), FONTS)


# --------------------------------------------------------------------------
# Behaviour: only on a change of class or year; AI-GENERATED always labelled
# --------------------------------------------------------------------------


def _shots(*spec):
    return [{"start": float(t), "cls": c, "label": lab, **({"year": y} if y is not ... else {})}
            for t, c, lab, y in spec]


def test_change_only_surfacing_across_cuts_cards_and_dips():
    shots = _shots((0, "CARD", "", None),                                       # the title: a card has no label
                   (5, "ARCHIVE", "Archive · 1947", "1947"),                    # the first picture shot: surfaces
                   (6, "ARCHIVE", "Archive · 1947", "1947"),                    # the same class and year: runs on
                   (20, "CARD", "", None),                                      # a chapter card between
                   (24, "ARCHIVE", "Archive · 1947", "1947"),                   # same as the last picture shot: no
                   (30, "RECONSTRUCTED", "Reconstructed · 1947 · stabilised", "1947"),   # class changes: surfaces
                   (40, "RECONSTRUCTED", "Reconstructed · 1946 · stabilised", "1946"),   # year changes: surfaces
                   (50, "DRAWN", "Drawn · from Natural Earth", None),           # class changes
                   (51, "DRAWN", "Drawn · from the WHO table", None))           # a DRAWN source is not a class or a year
    plan = M.label_plan(shots)
    assert [e["surfaces"] for e in plan] == [False, True, False, False, False, True, True, True, False]
    assert [e["start"] for e in plan] == [None, 5.0, 5.0, None, None, 30.0, 40.0, 50.0, 50.0]
    assert M.mark_state(61.0, shots)["label_alpha"] == 0.0                      # run on, it still lets go on its own time
    assert M.label_surfacings(shots) == [5.0, 30.0, 40.0, 50.0]
    st = M.mark_state(6.5, shots)                                               # runs on, with the new shot's words
    assert st["label_alpha"] > 0.9 and st["label"] == "Archive · 1947" and st["label_start"] == 5.0
    assert M.mark_state(25.0, shots)["label_alpha"] == 0.0                      # glyph only after the card
    assert M.mark_state(51.5, shots)["label"] == "Drawn · from the WHO table"  # the words swap hard on the cut
    assert M.mark_state(51.5, shots)["label_alpha"] > 0.9


def test_the_year_is_read_from_the_label_when_the_shot_states_none():
    shots = [{"start": 0.0, "cls": "ARCHIVE", "label": "Archive · 1947"},
             {"start": 4.0, "cls": "ARCHIVE", "label": "Archive · 1948"},
             {"start": 8.0, "cls": "ARCHIVE", "label": "Archive · 1948"}]
    assert M.label_surfacings(shots) == [0.0, 4.0]


def test_ai_generated_is_labelled_whenever_it_is_on_screen():
    shots = _shots((0, "ARCHIVE", "Archive · 1947", "1947"),
                   (6, "AI-GENERATED", "AI-generated · context", None),
                   (12, "AI-GENERATED", "AI-generated · context", None),     # the same key: still full, never re-arriving
                   (30, "CARD", "", None),
                   (34, "AI-GENERATED", "AI-generated · context", None),     # the same key after a card: still labelled
                   (40, "ARCHIVE", "Archive · 1947", "1947"))
    for f in range(6 * 24, 30 * 24):
        assert M.mark_state(f / 24, shots)["label_alpha"] == 1.0, f
    for f in range(34 * 24, 40 * 24):
        assert M.mark_state(f / 24, shots)["label_alpha"] == 1.0, f
    assert M.label_surfacings(shots) == [0.0, 6.0, 40.0]                        # counted once per change of class
    img = Image.new("RGB", (1920, 1080), (90, 90, 90))
    a = np.asarray(M.mark_frame(img, 34.0, shots, FONTS).convert("RGB")).astype(int)   # its cut frame: words drawn, full
    L = M.Layout(1920, 1080)
    gx, gy = M.glyph_origin(L)
    assert (a[gy - 15:gy + 15, int(L.w(70)):gx - 2] > 150).any()                 # near-white words at 0.6 over grey 90


@pytest.mark.parametrize("W, H", SIZES)
def test_the_ai_label_keeps_a16s_size_and_opacity_and_stays_in_the_zone(W, H):
    L = M.Layout(W, H)
    assert M.label_type("AI-GENERATED") == (2.3, 0.72) and M.label_type("ARCHIVE") == (2.0, 0.6)
    text = M.mark_label("AI-GENERATED", None, "context")
    assert M.label_check(L, text, FONTS, "AI-GENERATED") > M.label_check(L, text, FONTS, "DRAWN")
    tile, (x, y) = M._label_tile(L, text, 1.0, 1.0, FONTS, "AI-GENERATED")
    bx0, by0, bx1, by1 = _alpha_box(tile)
    gx, _ = M.glyph_origin(L)
    assert x + bx1 < gx and y + by0 >= M.SUB["bottom"] / 100 * H and y + by1 <= 0.965 * H
    assert x + bx0 >= M.LABEL_MIN_X / 100 * W
    words = np.asarray(tile.getchannel("A")).max()
    assert words >= round(255 * 0.72) - 1                                       # its words at 0.72, not 0.6


def test_an_empty_label_on_an_ai_generated_shot_is_refused_at_plan_time():
    seen = []
    shots = [{"id": "A1", "mark": "AI-GENERATED", "label": "AI-generated · context"},
             {"id": "A2", "mark": "AI-GENERATED", "label": " "},
             {"id": "A3", "mark": "DRAWN", "label": ""}]
    R.ai_label_lint(lambda rule, ok, **kw: seen.append((rule, kw["unit"], ok)), shots)
    assert seen == [("ai-label", "A1", True), ("ai-label", "A2", False)]       # blocking: build_plan's lint refuses


@pytest.mark.parametrize("W, H", SIZES)
def test_the_glyph_shape_check_holds_at_the_new_position_with_the_label_up(W, H):
    """The bare-pixel probe method at A31's position, with the label at rest
    and at its first frame (nearest the glyph): a correct frame passes over any
    picture and the wrong shape at the same hue fails."""
    plan = {"W": W, "H": H}
    L = M.Layout(W, H)
    cx, cy = M.glyph_centre(L)
    for bg in [(0, 0, 0), (255, 255, 255), (47, 95, 168), (128, 128, 128), (237, 162, 60)]:
        img = Image.new("RGBA", (W, H), bg + (255,))
        for drawn in ("ARCHIVE", "DRAWN", "AI-GENERATED", "RECONSTRUCTED", "CARD"):
            shots = [{"start": 0.0, "cls": drawn,
                      "label": "" if drawn == "CARD" else M.mark_label(drawn, "1947" if drawn == "ARCHIVE" else None)}]
            for t in (1 / 24, 1.0):
                arr = np.asarray(M.mark_frame(img, t, shots, FONTS).convert("RGB"))
                if drawn != "CARD":                                             # the ring is hollow at its centre
                    assert tuple(arr[cy, cx]) == M.MARK_HUE[drawn], (W, bg, drawn, t)
                assert R.glyph_shape_ok(plan, arr, drawn, bg), (W, bg, drawn, t)
                if drawn in ("RECONSTRUCTED", "CARD"):                          # the two bones differ by shape
                    other = "CARD" if drawn == "RECONSTRUCTED" else "RECONSTRUCTED"
                    assert not R.glyph_shape_ok(plan, arr, other, bg), (W, bg, drawn, t)
                if drawn in ("DRAWN", "AI-GENERATED") and bg != M.MARK_HUE[drawn]:
                    other = "AI-GENERATED" if drawn == "DRAWN" else "DRAWN"
                    assert not R.glyph_shape_ok(plan, arr, other, bg), (W, bg, drawn, t)


# --------------------------------------------------------------------------
# label-rate
# --------------------------------------------------------------------------


def _rate_plan(n, dur):
    marks = [{"start": 0.0, "cls": "CARD", "label": ""}]
    marks += [{"start": 1.0 + k * (dur - 2) / max(n, 1), "cls": "ARCHIVE", "label": f"Archive · {1900 + k}",
               "year": str(1900 + k)} for k in range(n)]
    return {"marks": marks, "duration_s": float(dur)}


@pytest.mark.parametrize("n, dur, ok", [(4, 60, True), (5, 60, False), (38, 600, True), (41, 600, False), (2, 25, True),
                                        (3, 25, False)])
def test_label_rate_allows_one_surfacing_per_15_s(tmp_path, n, dur, ok):
    """A39 refined (founder, 2026-10-12): label-rate is a pacing guide, a
    warning and, past a cap, a reviewer item; never a refusal, final or draft."""
    for draft in (False, True):
        j = J.Journal(film=f"r2-rate-{draft}")
        assert R.label_rate_lint(j, _rate_plan(n, dur), draft=draft) == []
        e = lints(j, "label-rate")[0]
        assert (e["status"] == "pass") is ok and e["severity"] == "warn"
        assert e["evidence"]["surfacings"] == n and e["evidence"]["per_minute"] == round(60 * n / dur, 2)
        review = lints(j, "pacing-guide")
        assert [r["evidence"]["rule"] for r in review] == ([] if ok else ["label-rate"])
        assert all(r["severity"] == "review" and "A39" in r["grammar"] for r in review)


def test_label_rate_caps_the_busiest_minute_at_4_as_a_reviewer_item():
    def plan(times):
        return {"marks": [{"start": t, "cls": "ARCHIVE", "label": f"Archive · {1900 + k}", "year": str(1900 + k)}
                          for k, t in enumerate(times)], "duration_s": 1200.0}
    burst = [100.0, 110.0, 120.0, 130.0, 140.0]                                 # 5 in 40 s, in a film that allows 80
    j = J.Journal(film="r2-rate-burst")
    assert R.label_rate_lint(j, plan(burst)) == []                              # guidance: never a refusal
    e = lints(j, "label-rate")[0]
    assert e["evidence"]["busiest_minute"] == 5 and e["status"] == "fail" and e["severity"] == "warn"
    assert lints(j, "pacing-guide")[0]["evidence"]["found"]["busiest_minute"] == 5
    j = J.Journal(film="r2-rate-spread")
    assert R.label_rate_lint(j, plan([100.0, 110.0, 120.0, 130.0, 161.0])) == []    # the fifth 61 s after the first
    assert lints(j, "label-rate")[0]["status"] == "pass" and not lints(j, "pacing-guide")


def test_label_rate_counts_changes_not_cuts():
    marks = [{"start": float(k), "cls": "ARCHIVE", "label": "Archive · 1947", "year": "1947"} for k in range(30)]
    j = J.Journal(film="r2-rate-cuts")
    assert R.label_rate_lint(j, {"marks": marks, "duration_s": 30.0}) == []    # 30 cuts in 30 s, one surfacing
    assert lints(j, "label-rate")[0]["evidence"]["surfacings"] == 1


def test_the_fixture_plan_carries_the_year_and_surfaces_once(plan):
    assert all("year" in m for m in plan["marks"])
    assert M.label_surfacings(plan["marks"]) == [plan["shots"][2]["f0"] / 24]   # S3, the first picture shot
    j = J.Journal(film="r2-rate-fixture")
    assert R.label_rate_lint(j, plan) == []


def test_the_fixture_render_journals_the_two_r2_lints(rendered):
    evs = J.read(rendered["journal"])
    rate = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "label-rate"]
    key = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "mark-key"]
    assert rate and rate[0]["status"] == "pass" and rate[0]["evidence"]["surfacings"] == 1
    assert key == []                       # A56: the mark key is retired from films; nothing asks for one


@pytest.mark.parametrize("W, H", SIZES)
def test_the_ai_label_has_a_heavier_shadow_that_holds_on_a_bright_ground(W, H):
    """CoS 2026-10-11: a truth label must read on a bright, busy ground at 720p.
    Measured over a near-white ground with the same words: the AI-GENERATED
    label's shadow reaches far darker and covers far more pixels than any
    other class's, which keep theirs."""
    assert M.label_shadow("AI-GENERATED") != M.label_shadow("DRAWN")
    for cls in ("ARCHIVE", "RECONSTRUCTED", "DRAWN"):
        assert M.label_shadow(cls) == (M.LABEL["shadow"], M.LABEL["blur"], 1.8)
    L = M.Layout(W, H)
    img = Image.new("RGB", (W, H), (245, 245, 245))
    out = {}
    for cls in ("AI-GENERATED", "DRAWN"):
        shots = [{"start": 0.0, "cls": cls, "label": "AI-generated · context"}]
        a = np.asarray(M.mark_frame(img, 1.5, shots, FONTS).convert("L")).astype(int)
        out[cls] = a[int(0.92 * H):int(0.97 * H), int(L.w(M.LABEL_MIN_X)):M.glyph_origin(L)[0] - 2]
    ai, other = out["AI-GENERATED"], out["DRAWN"]
    assert ai.min() <= 90 and other.min() >= 140                                # its darkest edge: black enough to hold
    assert (ai < 200).sum() >= 3 * (other < 200).sum()                          # a denser ground under the words
    assert ai.max() >= 245                                                      # and the words stay near-white
