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
@pytest.mark.parametrize("arriving", [False, True])
def test_the_label_stays_in_its_zone_clear_of_subtitles_overlays_lower_thirds_and_the_watermark(W, H, arriving):
    L = M.Layout(W, H)
    dx = M.LABEL["drift"] * L.px(M.LABEL["size"]) if arriving else 0.0      # at its first frame it is nearest the glyph
    tile, (x, y) = M._label_tile(L, LONG, 1.0, dx, FONTS)
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
    assert L.px(M.LABEL["size"]) == {1080: 17, 720: 12}[H]
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
def test_the_glyph_shape_check_holds_at_the_new_position_with_the_label_up(W, H):
    """The bare-pixel probe method at A31's position, with the label at rest
    and at its first frame (nearest the glyph): a correct frame passes over any
    picture and the wrong shape at the same hue fails."""
    plan = {"W": W, "H": H}
    L = M.Layout(W, H)
    cx, cy = M.glyph_centre(L)
    for bg in [(0, 0, 0), (255, 255, 255), (47, 95, 168), (128, 128, 128), (237, 162, 60)]:
        img = Image.new("RGBA", (W, H), bg + (255,))
        for drawn in ("ARCHIVE", "DRAWN", "AI-GENERATED", "RECONSTRUCTED"):
            shots = [{"start": 0.0, "cls": drawn, "label": M.mark_label(drawn, "1947" if drawn == "ARCHIVE" else None)}]
            for t in (1 / 24, 1.0):
                arr = np.asarray(M.mark_frame(img, t, shots, FONTS).convert("RGB"))
                assert tuple(arr[cy, cx]) == M.MARK_HUE[drawn], (W, bg, drawn, t)
                assert R.glyph_shape_ok(plan, arr, drawn, bg), (W, bg, drawn, t)
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


@pytest.mark.parametrize("n, dur, ok", [(4, 60, True), (5, 60, False), (40, 600, True), (41, 600, False), (2, 25, True),
                                        (3, 25, False)])
def test_label_rate_allows_one_surfacing_per_15_s(tmp_path, n, dur, ok):
    j = J.Journal(film="r2-rate")
    out = R.label_rate_lint(j, _rate_plan(n, dur))
    e = lints(j, "label-rate")[0]
    assert (e["status"] == "pass") is ok and (out == []) is ok and e["severity"] == "block"
    assert e["evidence"]["surfacings"] == n and e["evidence"]["per_minute"] == round(60 * n / dur, 2)
    j2 = J.Journal(film="r2-rate-draft")
    assert R.label_rate_lint(j2, _rate_plan(n, dur), draft=True) == []
    assert lints(j2, "label-rate")[0]["severity"] == "warn"


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


# --------------------------------------------------------------------------
# The mark key card
# --------------------------------------------------------------------------


@pytest.mark.parametrize("W, H", SIZES)
def test_the_key_is_drawn_from_the_class_table(W, H):
    L = M.Layout(W, H)
    lay = M.mark_key_layout(L, FONTS)
    assert M.KEY_CLASSES == ("ARCHIVE", "RECONSTRUCTED", "DRAWN", "AI-GENERATED")
    assert M.mark_key_drawn_text(lay) == ["What the marks mean", "Archive", "Reconstructed", "Drawn", "AI-generated"]
    assert [r["text"] for r in lay["rows"]] == [M.CLASS_WORD[c] for c in M.KEY_CLASSES]
    assert 0.10 * H <= lay["top"] and lay["bottom"] <= 0.90 * H                # inside the statement card's safe band
    for r in lay["rows"]:
        assert r["x"] + r["w"] <= L.w(50 + M.KEY["max_w"] / 2)
    img = M.mark_key_frame(Image.new("RGB", (W, H)), 4.0, start=0.0, end=5.0, fonts=FONTS)
    arr = np.asarray(img.convert("RGB")).astype(int)
    for r in lay["rows"]:                                                       # each glyph in its class hue, at its centre
        gx, gy, d = r["glyph"]
        assert tuple(arr[gy + d // 2, gx + d // 2]) == M.MARK_HUE[r["cls"]], r["cls"]
    rows = {r["cls"]: r for r in lay["rows"]}
    sq, dm = rows["DRAWN"]["glyph"], rows["AI-GENERATED"]["glyph"]              # the two blues differ by shape
    assert tuple(arr[sq[1], sq[0]]) == M.MARK_HUE["DRAWN"] and not arr[dm[1], dm[0]].any()
    assert not arr[int(0.92 * H):].any() and not arr[:int(0.08 * H)].any()     # black ground, nothing at the edges


def test_the_key_uses_the_house_motion():
    W, H = 1280, 720
    blank = Image.new("RGB", (W, H))
    first = np.asarray(M.mark_key_frame(blank, 0.0, start=0.0, end=5.0, fonts=FONTS).convert("RGB"))
    held = np.asarray(M.mark_key_frame(blank, 2.5, start=0.0, end=5.0, fonts=FONTS).convert("RGB")).astype(int)
    leaving = np.asarray(M.mark_key_frame(blank, 4.7, start=0.0, end=5.0, fonts=FONTS).convert("RGB")).astype(int)
    assert not first.any()                                                      # it arrives; nothing pops in on frame 0
    assert 0 < leaving.max() < held.max()                                       # let go: thinning out, not moving
    assert np.array_equal(np.nonzero(leaving.sum(axis=2) > 0)[0].min(), np.nonzero(held.sum(axis=2) > 0)[0].min())
    lay = M.mark_key_layout(M.Layout(W, H), FONTS)
    r = lay["rows"][-1]
    t_last = M.KEY["row_delay"] + 3 * M.KEY["stagger"]
    a = np.asarray(M.mark_key_frame(blank, t_last + 0.01, start=0.0, end=5.0, fonts=FONTS).convert("RGB"))
    gx, gy, d = r["glyph"]
    assert a[gy - 2:gy + d + 4, gx - 2:gx + d + 2].max() < 200                  # the last row is still surfacing (whisper)


def test_a_key_heading_that_does_not_fit_is_refused(monkeypatch):
    monkeypatch.setattr(M, "KEY_HEADING", "What the marks mean " * 8)
    with pytest.raises(M.TextOverflow, match="mark key"):
        M.mark_key_layout(M.Layout(1280, 720), FONTS)


def test_a_key_card_draws_no_typed_text_and_is_laid_out_at_plan_time(plan):
    s = {"id": "K1", "kind": "card", "card": "mark_key", "mark": "CARD", "text": [], "_part_kind": "chapter",
         "_first_in_part": False}
    c = R.card_text_check(s, plan["W"], plan["H"])
    assert c["card"] == "mark_key" and c["fits"] and c["missing"] == []
    typed = dict(s, text=["Amber is archive"])
    assert R.card_text_check(typed, plan["W"], plan["H"])["missing"] == [{"index": 0, "intended": "Amber is archive",
                                                                         "drawn": None}]
    pics = R.Pictures(plan)
    try:
        img = pics.card(dict(s, _card="mark_key", _dur=5.0), 2.0)
    finally:
        pics.close()
    assert plan["key_classes"] == ["DRAWN"]                                     # the fixture's picture shots are all DRAWN
    want = M.mark_key_frame(Image.new("RGB", (plan["W"], plan["H"])), 2.0, start=0.0, end=5.0, fonts=M.Fonts(),
                            classes=("DRAWN",))
    assert np.array_equal(np.asarray(img), np.asarray(want.convert("RGB")))


# --------------------------------------------------------------------------
# The key shows only the film's classes (CoS 2026-10-11), both directions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("W, H", SIZES)
def test_a_film_without_ai_shows_its_classes_and_says_none_is_ai_generated(W, H):
    L = M.Layout(W, H)
    marks = [{"cls": "CARD"}, {"cls": "ARCHIVE"}, {"cls": "DRAWN"}, {"cls": "ARCHIVE"}]
    used = M.key_classes(marks)
    assert used == ("ARCHIVE", "DRAWN")                                         # only what the film uses, in key order
    lay = M.mark_key_layout(L, FONTS, used)
    assert M.mark_key_drawn_text(lay) == ["What the marks mean", "Archive", "Drawn",
                                          "No picture in this film is AI-generated."]
    assert lay["note"]["text"] == M.KEY_NO_AI and 0.10 * H <= lay["top"] and lay["bottom"] <= 0.90 * H
    assert lay["note"]["x"] >= L.w(50 - M.KEY["max_w"] / 2) and lay["note"]["baseline"] > lay["rows"][-1]["baseline"]
    arr = np.asarray(M.mark_key_frame(Image.new("RGB", (W, H)), 4.0, start=0.0, end=5.0, fonts=FONTS,
                                      classes=used).convert("RGB")).astype(int)
    n = lay["note"]
    band = arr[int(n["baseline"] - 0.8 * L.px(M.KEY["word"])):int(n["baseline"]) + 2, int(n["x"]):int(n["x"] + n["w"])]
    assert band.max() > 150                                                     # the line is drawn
    for r in lay["rows"]:
        gx, gy, d = r["glyph"]
        assert tuple(arr[gy + d // 2, gx + d // 2]) == M.MARK_HUE[r["cls"]]
    assert not any(r["cls"] in ("RECONSTRUCTED", "AI-GENERATED") for r in lay["rows"])


@pytest.mark.parametrize("W, H", SIZES)
def test_a_film_that_adds_an_ai_shot_loses_the_line_and_gains_the_class(W, H):
    L = M.Layout(W, H)
    before = M.key_classes([{"cls": "ARCHIVE"}, {"cls": "DRAWN"}])
    after = M.key_classes([{"cls": "ARCHIVE"}, {"cls": "DRAWN"}, {"cls": "AI-GENERATED"}])
    assert "AI-GENERATED" not in before and after == ("ARCHIVE", "DRAWN", "AI-GENERATED")
    lb, la = M.mark_key_layout(L, FONTS, before), M.mark_key_layout(L, FONTS, after)
    assert lb["note"] is not None and la["note"] is None
    assert M.mark_key_drawn_text(la) == ["What the marks mean", "Archive", "Drawn", "AI-generated"]
    assert M.KEY_NO_AI not in M.mark_key_drawn_text(la)
    arr = np.asarray(M.mark_key_frame(Image.new("RGB", (W, H)), 4.0, start=0.0, end=5.0, fonts=FONTS,
                                      classes=after).convert("RGB")).astype(int)
    gx, gy, d = la["rows"][-1]["glyph"]
    assert tuple(arr[gy + d // 2, gx + d // 2]) == M.MARK_HUE["AI-GENERATED"]
    assert not arr[int(la["bottom"]) + 4:].any()                                # nothing drawn below the last row


def test_the_plan_derives_the_key_and_its_segment_follows_it(plan):
    assert plan["key_classes"] == list(M.key_classes(plan["shots"])) == ["DRAWN"]
    shots = [dict(s) for s in plan["shots"]]
    k = next(i for i, s in enumerate(shots) if s["kind"] == "card")
    shots[k] = dict(shots[k], _card="mark_key", text=[])
    p1 = dict(plan, shots=shots)
    p2 = dict(p1, key_classes=["DRAWN", "AI-GENERATED"])
    assert R.shot_key(p1, k, {}) != R.shot_key(p2, k, {})                       # a new class re-renders the key card
    other = next(i for i, s in enumerate(shots) if s["kind"] != "card")
    assert R.shot_key(p1, other, {}) == R.shot_key(p2, other, {})              # and nothing else
    c1 = R.card_text_check(shots[k], plan["W"], plan["H"], key_classes=("DRAWN",))
    assert c1["fits"] and c1["missing"] == []


# --------------------------------------------------------------------------
# mark-key lint
# --------------------------------------------------------------------------


def _key_plan(seq, dur=1200.0):
    shots = []
    for k, (card, mark, d) in enumerate(seq):
        shots.append({"id": f"X{k}", "kind": "card" if card not in (None, "black") else ("black" if card == "black" else "archive_still"),
                      "_card": card if card not in (None,) else None, "mark": mark, "_dur": d})
    return {"shots": shots, "duration_s": dur, "runtime_target_s": dur}


FILM = [(None, "ARCHIVE", 6), ("title", "CARD", 5), ("mark_key", "CARD", 5), ("chapter", "CARD", 4),
        (None, "ARCHIVE", 10), (None, "DRAWN", 10), ("title", "CARD", 5), ("mark_key", "CARD", 5),
        ("statement", "CARD", 8), ("black", "CARD", 2)]


def test_mark_key_passes_with_a_key_after_the_title_and_before_the_attribution_card():
    j = J.Journal(film="r2-key")
    assert R.mark_key_lints(j, _key_plan(FILM)) == []
    es = lints(j, "mark-key")
    assert {e["unit"]: e["status"] for e in es} == {"mark-key:head": "pass", "mark-key:end": "pass"}
    assert all(e["severity"] == "block" for e in es)


@pytest.mark.parametrize("drop, unit", [(2, "head"), (7, "end")])
def test_mark_key_refuses_a_film_without_its_key(drop, unit):
    seq = [x for k, x in enumerate(FILM) if k != drop]
    j = J.Journal(film="r2-key-missing")
    out = R.mark_key_lints(j, _key_plan(seq))
    assert out and unit in out[0]
    e = next(e for e in lints(j, "mark-key") if e["unit"] == f"mark-key:{unit}")
    assert e["status"] == "fail" and "card: mark_key" in e["evidence"]["fix"]


def test_mark_key_refuses_a_key_in_the_wrong_place_or_too_short():
    late = [FILM[0], FILM[1], FILM[3], FILM[2], *FILM[4:]]                     # after the chapter card is still before a
    assert R.mark_key_lints(J.Journal(film="r2-key-late"), _key_plan(late)) == []   # picture: allowed
    after_pic = [FILM[0], FILM[1], FILM[3], FILM[4], FILM[2], *FILM[5:]]        # after the first picture: not a key at the head
    assert R.mark_key_lints(J.Journal(film="r2-key-after"), _key_plan(after_pic))
    after_attr = [*FILM[:7], FILM[8], FILM[7], FILM[9]]                         # after the attribution card
    assert R.mark_key_lints(J.Journal(film="r2-key-after-attr"), _key_plan(after_attr))
    short = [x if k != 2 else ("mark_key", "CARD", 3) for k, x in enumerate(FILM)]
    j = J.Journal(film="r2-key-short")
    assert R.mark_key_lints(j, _key_plan(short))
    assert "lengthen" in next(e for e in lints(j, "mark-key") if e["unit"] == "mark-key:head")["evidence"]["fix"]


def test_mark_key_warns_on_a_draft_or_a_short_piece_and_skips_a_film_without_pictures():
    seq = [x for k, x in enumerate(FILM) if k not in (2, 7)]
    j = J.Journal(film="r2-key-draft")
    assert R.mark_key_lints(j, _key_plan(seq), draft=True) == []
    assert {e["severity"] for e in lints(j, "mark-key")} == {"warn"}
    j = J.Journal(film="r2-key-short-piece")
    assert R.mark_key_lints(j, _key_plan(seq, dur=90.0)) == []
    assert {e["severity"] for e in lints(j, "mark-key")} == {"warn"}
    cards = [("title", "CARD", 5), ("statement", "CARD", 8)]
    j = J.Journal(film="r2-key-cards")
    assert R.mark_key_lints(j, _key_plan(cards)) == [] and not j.path.exists()   # nothing journaled: no picture marks


def test_the_fixture_render_journals_the_two_r2_lints(rendered):
    evs = J.read(rendered["journal"])
    rate = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "label-rate"]
    key = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "mark-key"]
    assert rate and rate[0]["status"] == "pass" and rate[0]["evidence"]["surfacings"] == 1
    # the fixture is a 25 s short piece with no key card: both key lints are warnings, never a refusal
    assert {e["unit"] for e in key} == {"mark-key:head", "mark-key:end"}
    assert all(e["status"] == "fail" and e["severity"] == "warn" for e in key)
    json.dumps(key)
