"""A42 (founder, 2026-10-17): "the dot (class glyph, bottom right) is the only
source indicator. Its label grows out of the dot, lingers, then folds back
into it. On a long clip it animates again after an interval." The grow, the
fold, the repeat every LABEL.repeat_s within one shot, and what A31 and A16
keep."""

import math

import numpy as np
import pytest
from PIL import Image

from studio.engine import motion as M

FONTS = M.Fonts()
W, H = 640, 360
TEXT = "Archive · 1947"


def _shot(start, cls="ARCHIVE", label=TEXT, year="1947", end=None):
    s = {"start": float(start), "cls": cls, "label": label, "year": year}
    if end is not None:
        s["end"] = float(end)
    return s


def _alpha_cols(tile):
    a = np.asarray(tile.getchannel("A"))
    return np.nonzero(a.max(axis=0) > 0)[0]


# --------------------------------------------------------------------------
# Grow, linger, fold
# --------------------------------------------------------------------------

def test_the_reveal_grows_monotonically_holds_then_folds_to_nothing():
    grow = M.WHISPER.settle_time()
    ts = [k / 240 for k in range(int(grow * 240) + 1)]
    r = [M.label_reveal(t, 0.0) for t in ts]
    assert r[0] == 0.0
    assert all(b >= a - 1e-4 for a, b in zip(r, r[1:]))                  # monotonic (whisper's overshoot is under 1e-4)
    assert max(r) <= 1.0                                                 # never wider than the label
    assert M.label_reveal(grow + 0.01, 0.0) == 1.0
    assert M.label_reveal(grow + M.LABEL["hold"] * 0.9, 0.0) == 1.0      # lingers
    fold = [M.label_reveal(M.LABEL_MAX_S - M.LABEL["exit"] + k / 100, 0.0) for k in range(76)]
    assert all(b <= a + 1e-12 for a, b in zip(fold, fold[1:]))           # folds back steadily
    assert M.label_reveal(M.LABEL_MAX_S, 0.0) == 0.0 and M.label_reveal(M.LABEL_MAX_S + 5, 0.0) == 0.0
    assert M.label_reveal(-0.1, 0.0) == 0.0
    # the opacity rises with the grow and falls with the fold
    assert M.label_alpha(0.0, 0.0) == 0.0 and M.label_alpha(grow + 0.5, 0.0) == pytest.approx(1.0, abs=1e-3)
    assert M.label_alpha(M.LABEL_MAX_S, 0.0) == 0.0


@pytest.mark.parametrize("reveal", [0.05, 0.25, 0.5, 0.75, 1.0])
def test_the_label_grows_out_of_the_glyph_and_is_never_wider_than_its_words(reveal):
    L = M.Layout(W, H)
    x0, x1 = M.label_reveal_span(L, TEXT, reveal, FONTS)
    full0, full1 = M.label_reveal_span(L, TEXT, 1.0, FONTS)
    assert x1 == full1 == pytest.approx(M.label_right(L))                # anchored at the words' end, by the glyph
    assert x1 - x0 == pytest.approx(reveal * (full1 - full0))
    assert x1 - x0 <= full1 - full0 + 1e-9
    tile, (tx, _) = M._label_tile(L, TEXT, 1.0, reveal, FONTS)
    cols = _alpha_cols(tile) + tx
    gx, _ = M.glyph_origin(L)
    assert cols.size and cols.max() < gx                                 # never on the glyph
    if reveal < 1.0:                                                     # the drawn tile: nothing left of the reveal
        feather = max(1.0, M.LABEL["feather"] * L.px(M.LABEL["size"]))   # (but its soft edge, a shadow's width)
        assert cols.min() >= math.floor(x0 - feather) - 1
        a = np.asarray(tile.getchannel("A")).astype(int)
        whole, _ = M._label_tile(L, TEXT, 1.0, 1.0, FONTS)
        full = np.asarray(whole.getchannel("A")).astype(int)
        right_of = slice(int(math.ceil(x0)) - tx + 1, None)              # right of the edge: the label as drawn whole
        assert np.array_equal(a[:, right_of], full[:, right_of])


def test_the_revealed_width_widens_with_the_reveal():
    L = M.Layout(W, H)
    lefts = []
    for r in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0):
        tile, (tx, _) = M._label_tile(L, TEXT, 1.0, r, FONTS)
        lefts.append(_alpha_cols(tile).min() + tx)
    assert all(b <= a for a, b in zip(lefts, lefts[1:]))                 # the left edge moves left: it grows leftward


def test_the_glyph_never_moves_while_the_label_grows_and_folds():
    L = M.Layout(W, H)
    shots = [_shot(0.0, end=10.0)]
    bg = Image.new("RGB", (W, H), (90, 90, 90))
    tile, at = M.glyph_tile(W, H, "ARCHIVE")
    for t in (0.0, 0.1, 0.3, 1.0, 2.5, 2.9, 3.05, 5.0):
        img = np.asarray(M.mark_frame(bg, t, shots, FONTS).convert("RGB")).astype(int)
        ref = np.asarray(M.mark_frame(bg, 9.0, shots, FONTS).convert("RGB")).astype(int)   # glyph alone
        y0, x0 = at[1], at[0]
        box = (slice(y0, y0 + tile.height), slice(x0, x0 + tile.width))
        assert np.array_equal(img[box], ref[box]), t                    # the glyph's pixels are the same on every frame
    assert M.mark_state(9.0, shots)["label_reveal"] == 0.0


# --------------------------------------------------------------------------
# Repeat every LABEL.repeat_s within one shot
# --------------------------------------------------------------------------

def test_a_long_shot_grows_its_label_again_every_40_s_if_the_whole_grow_fits():
    assert M.LABEL["repeat_s"] == 40.0
    assert M.label_surfacings([_shot(0.0, end=100.0)]) == [0.0, 40.0, 80.0]
    assert M.label_surfacings([_shot(0.0, end=82.0)]) == [0.0, 40.0]    # 80 + 3.1 s runs past 82 - 1
    assert M.label_surfacings([_shot(0.0, end=80.0 + M.LABEL_MAX_S + M.LABEL["repeat_tail"])]) == [0.0, 40.0, 80.0]
    st = M.mark_state(80.5, [_shot(0.0, end=100.0)])
    assert st["label_start"] == 80.0 and 0.0 < st["label_reveal"] <= 1.0
    assert M.mark_state(60.0, [_shot(0.0, end=100.0)])["label_reveal"] == 0.0    # folded between


def test_a_cut_that_repeats_class_and_year_brings_no_new_surfacing():
    a, b = _shot(0.0, end=30.0), _shot(30.0, end=42.0)
    assert M.label_surfacings([a, b]) == [0.0]                           # A31's run on: nothing at the cut
    assert M.mark_state(30.5, [a, b])["label_reveal"] == 0.0
    b = _shot(30.0, end=60.0)                                            # 40 s after the last one, inside the shot
    assert M.label_surfacings([a, b]) == [0.0, 40.0]
    b = _shot(30.0, end=100.0)                                           # within the long second shot, 40 s after 0
    assert M.label_surfacings([a, b]) == [0.0, 40.0, 80.0]
    c = _shot(30.0, cls="ARCHIVE", label="Archive · 1948", year="1948", end=100.0)   # a year change surfaces at the cut
    assert M.label_surfacings([a, c]) == [0.0, 30.0, 70.0]


def test_after_a_card_a_same_key_shot_still_grows_its_label_when_due():
    """The reviewer's case: Real World labels every shot 'Archive · 2001'; after a card a same-key shot showed the
    glyph alone and never repeated. The 40 s clock runs across cards and glyph-only shots."""
    shots = [_shot(0.0, end=10.0), _shot(10.0, cls="CARD", label="", year=None, end=15.0), _shot(15.0, end=75.0)]
    plan = M.label_plan(shots)
    assert plan[2]["start"] is None and not plan[2]["surfaces"]           # no surfacing at the cut (A31)
    assert plan[2]["repeats"] == [40.0]                                   # due 40 s after 0, inside the shot
    assert M.mark_state(41.0, shots)["label_reveal"] > 0.9
    late = [_shot(0.0, end=10.0), _shot(10.0, cls="CARD", label="", year=None, end=60.0), _shot(60.0, end=120.0)]
    assert M.label_plan(late)[2]["repeats"] == [61.0, 101.0]              # overdue: 1 s into the shot, never the cut


def test_many_short_same_key_shots_between_cards_recur_about_every_40_s_never_on_a_cut():
    shots, t = [], 0.0
    for k in range(30):                                                   # 8 s pictures and 2 s cards for 300 s
        shots.append(_shot(t, end=t + 8.0))
        shots.append(_shot(t + 8.0, cls="CARD", label="", year=None, end=t + 10.0))
        t += 10.0
    times = M.label_surfacings(shots)
    cuts = {s["start"] for s in shots}
    assert times[0] == 0.0 and len(times) >= 6
    assert all(b - a >= M.LABEL["repeat_s"] - 1e-9 for a, b in zip(times, times[1:]))
    assert all(b - a <= M.LABEL["repeat_s"] + 10.0 for a, b in zip(times, times[1:]))   # about every 40 s
    assert not any(u in cuts for u in times[1:])                         # never on a cut frame
    for u in times:                                                       # each one whole inside its own shot
        s = max((x for x in shots if x["start"] <= u), key=lambda x: x["start"])
        assert s["cls"] == "ARCHIVE" and u + M.LABEL_MAX_S <= s["end"] - M.LABEL["repeat_tail"] + 1e-9


def test_a_repeat_never_lands_on_a_cut_that_repeats_class_and_year():
    shots = [_shot(0.0, end=40.0), _shot(40.0, end=100.0)]
    times = M.label_surfacings(shots)
    assert 40.0 not in times and times == [0.0, 41.0, 81.0]


def test_a_shot_without_its_end_never_repeats():
    assert M.label_surfacings([_shot(0.0)]) == [0.0]                     # the titles' timeline and the kit's demo


def test_the_ai_generated_label_is_unchanged_and_never_repeats():
    shots = [_shot(0.0, cls="AI-GENERATED", label="AI-generated · context", year=None, end=120.0)]
    assert M.label_surfacings(shots) == [0.0]
    for t in (0.0, 1 / 24, 3.5, 40.0, 41.0, 100.0):
        st = M.mark_state(t, shots)
        assert st["label_alpha"] == 1.0 and st["label_reveal"] == 1.0, t


def test_a_card_has_no_label_and_the_glyph_still_crossfades_on_a_class_change():
    shots = [_shot(0.0, end=5.0), _shot(5.0, cls="CARD", label="", year=None, end=10.0)]
    assert M.mark_state(7.0, shots)["label_reveal"] == 0.0
    st = M.mark_state(5.0 + M.LABEL["fade"] / 2, shots)
    assert 0.0 < st["mix"] < 1.0


def test_the_label_rate_guide_counts_repeats_and_40_s_keeps_within_it():
    shots = [_shot(0.0, end=600.0)]
    times = M.label_surfacings(shots)
    assert times == [40.0 * k for k in range(15)]                        # 0 to 560
    assert len(times) <= math.ceil(600.0 / 15.0)                         # one per 15 s of film
    assert max(sum(1 for u in times if t <= u < t + 60.0) for t in times) <= 4   # and 4 in any 60 s


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def test_frames_draw_without_error_through_a_long_shot_at_640x360():
    shots = [_shot(0.0, end=50.0), _shot(50.0, cls="DRAWN", label="Drawn · from the census", year=None, end=60.0)]
    bg = Image.new("RGB", (W, H), (120, 110, 100))
    for t in [k / 24 for k in range(0, 24 * 4, 3)] + [40.0 + k / 24 for k in range(0, 24 * 4, 3)] + [50.0, 50.2, 59.0]:
        out = M.mark_frame(bg, t, shots, FONTS)
        assert out.size == (W, H)
    mid = np.asarray(M.mark_frame(bg, 41.5, shots, FONTS).convert("RGB")).astype(int)
    off = np.asarray(M.mark_frame(bg, 20.0, shots, FONTS).convert("RGB")).astype(int)
    assert np.abs(mid - off).sum() > 0                                   # the repeat is drawn
