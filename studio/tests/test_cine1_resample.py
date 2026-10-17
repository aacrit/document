"""Cinematography ticket 1 (founder-approved, 2026-10-17): fit_still reduces
with a filter. ``Image.transform(EXTENT, BICUBIC)`` point-sampled a reduction,
so a 3-px line pattern reduced 3:1 read mean 0, 0, 0, 30, 152 as the window
slid by sub-pixels (the groundwork's measure) and halftones, engravings, map
hatching and type twinkled at every 2-3x stop. ``resample-prefilter`` is the
blocking regression: a filtered reduction holds the pattern's mean flat, and
the old sampling, kept here as the control, must fail the same test so the
test is known to bite. Small synthetic images only; nothing is rendered."""

import math

import numpy as np
from PIL import Image

from studio.engine import motion as M
from studio.engine import render as R

W, H = 320, 180
L = M.Layout(W, H)
FPS = 24
LEVELS = 2.0            # the spec: flat within 2 levels (a Lanczos run measured 85.0 throughout)
JUMP = 0.25             # a 5 s creep over a halftone: no frame-to-frame mean jump above a quarter level
                        # (measured: 0.03 filtered, 1.57 with the old bicubic transform)


def _old_fit_still(still, L, *, z=1.0, cx=0.5, cy=0.5, clamp="frame"):
    """The sampling before this ticket (motion.py at 6dd508f), the control."""
    src, dst = M.still_view(still.size, L, z=z, cx=cx, cy=cy, clamp=clamp)
    rgb = still.convert("RGB")
    if dst == (0.0, 0.0, float(L.W), float(L.H)):
        return rgb.transform((L.W, L.H), Image.Transform.EXTENT, src,
                             resample=Image.Resampling.BICUBIC, fillcolor=M.PALETTE["letterbox"])
    x0, y0 = int(round(dst[0])), int(round(dst[1]))
    dw, dh = int(round(dst[2])) - x0, int(round(dst[3])) - y0
    out = Image.new("RGB", (L.W, L.H), M.PALETTE["letterbox"])
    out.paste(rgb.transform((dw, dh), Image.Transform.EXTENT, src, resample=Image.Resampling.BICUBIC,
                            fillcolor=M.PALETTE["letterbox"]), (x0, y0))
    return out


def _mean(img) -> float:
    return float(np.asarray(img.convert("L"), dtype=np.float64).mean())


def _lines(z):
    """One white column in three on black (mean 85), sized so the window at
    zoom z is exactly three image pixels per frame pixel."""
    iw = round(3 * W * z)
    ih = round(iw * H / W)
    a = np.zeros((ih, iw), dtype=np.uint8)
    a[:, ::3] = 255
    return Image.fromarray(a).convert("RGB")


def _line_means(fit, z=1.1, steps=13):
    """The frame's mean as the window slides by 0 to 1.5 image pixels."""
    img = _lines(z)
    iw = img.width
    return [_mean(fit(img, L, z=z, cx=0.5 + k * 0.125 / iw, cy=0.5, clamp="frame")) for k in range(steps)]


def test_resample_prefilter_line_pattern_holds_its_mean_across_subpixel_shifts():
    means = _line_means(M.fit_still)
    assert max(means) - min(means) <= LEVELS, means
    assert all(abs(m - 85.0) <= LEVELS for m in means), means


def test_resample_prefilter_bites_the_old_bicubic_transform():
    means = _line_means(_old_fit_still)
    assert max(means) - min(means) > LEVELS * 10, means       # the groundwork's 0 to 152


def _halftone(iw, ih, period=2.7):
    """A binary halftone screen at 45 degrees, a print's dots finer than a frame pixel at a 3x stop."""
    y, x = np.mgrid[0:ih, 0:iw].astype(np.float64)
    u, v = (x + y) / math.sqrt(2), (x - y) / math.sqrt(2)
    tone = np.cos(2 * math.pi * u / period) * np.cos(2 * math.pi * v / period)
    return Image.fromarray(np.where(tone > 0.2, 255, 0).astype(np.uint8)).convert("RGB")


def _creep_jumps(fit):
    """A 3x stop (three image pixels to a frame pixel) creeping in for 5 s at
    the tour's creep rate, drifting a little: the largest frame-to-frame jump
    in the frame's mean."""
    iw = 3 * W
    img = _halftone(iw, round(iw * H / W))
    rate = M.TOUR["creep_scale_per_s"]
    means = []
    for k in range(5 * FPS):
        t = k / FPS
        means.append(_mean(fit(img, L, z=1.0 * (1 + rate) ** t, cx=0.5 + 0.002 * t, cy=0.5, clamp="image")))
    return max(abs(b - a) for a, b in zip(means, means[1:]))


def test_resample_prefilter_halftone_creep_does_not_twinkle():
    assert _creep_jumps(M.fit_still) <= JUMP


def test_resample_prefilter_halftone_creep_twinkled_with_the_old_sampling():
    assert _creep_jumps(_old_fit_still) > JUMP * 4


def test_fit_still_keeps_the_field_and_the_shape_on_every_clamp():
    """The callers' contract: the pillarboxed whole (native and frame at z=1)
    keeps the field outside the photograph; a fill covers the frame."""
    field = M.PALETTE["letterbox"]
    portrait = Image.new("RGB", (900, 1200), (200, 180, 160))
    for clamp in ("frame", "native", "image"):
        pic = M.fit_still(portrait, L, z=1.0, clamp=clamp)
        assert pic.size == (W, H) and pic.mode == "RGB"
        a = np.asarray(pic)
        assert tuple(a[H // 2, 0]) == field and tuple(a[H // 2, W - 1]) == field      # whole: pillarboxed
        assert tuple(a[H // 2, W // 2]) == (200, 180, 160)
    filled = np.asarray(M.fit_still(portrait, L, z=3.0, clamp="image"))       # narrower than the photograph
    assert (filled == (200, 180, 160)).all()                                          # a fill: no field
    wide = np.asarray(M.fit_still(Image.new("RGB", (1600, 900), (10, 20, 30)), L))
    assert (wide == (10, 20, 30)).all()


def test_fit_still_matches_the_old_geometry():
    """Only the filter changed: on a smooth picture the new frame sits where the old one did."""
    y, x = np.mgrid[0:600, 0:800].astype(np.float64)
    smooth = Image.fromarray(np.dstack([x / 800 * 255, y / 600 * 255, (x + y) / 1400 * 255]).astype(np.uint8))
    for kw in (dict(z=1.0), dict(z=1.7, cx=0.3, cy=0.6, clamp="image"), dict(z=1.3, cx=0.7, clamp="native"),
               dict(z=1.2, cx=0.1, cy=0.9, clamp="frame")):
        a = np.asarray(M.fit_still(smooth, L, **kw), dtype=np.int16)
        b = np.asarray(_old_fit_still(smooth, L, **kw), dtype=np.int16)
        assert np.median(np.abs(a - b)) <= 1, kw
        assert (np.abs(a - b) > 8).mean() < 0.01, kw            # edges of the photograph may move by a pixel


def test_shot_key_names_the_sampling(plan):
    """A cached segment of the old sampling is never reused."""
    a = R.shot_key(plan, 2, {})
    old, M.RESAMPLE = M.RESAMPLE, "bicubic-transform-0"
    try:
        assert R.shot_key(plan, 2, {}) != a
    finally:
        M.RESAMPLE = old


def _line_centroid_error(still_size, col, kw):
    """A one-pixel bright column at image column ``col`` (a 64 field, 192 line):
    how far its centroid in the frame lies from where the window maps it, in frame pixels."""
    iw, ih = still_size
    a = np.full((ih, iw), 64, np.uint8)
    a[:, col] = 192
    pic = np.asarray(M.fit_still(Image.fromarray(a).convert("RGB"), L, **kw).convert("L"), np.float64)
    src, dst = M.still_view(still_size, L, **kw)
    if dst == (0.0, 0.0, float(W), float(H)):
        dx0, dw = 0.0, float(W)
    else:                                                    # fit_still draws src into the rounded dst
        dx0 = float(round(dst[0]))
        dw = float(round(dst[2])) - dx0
    ideal = dx0 + (col + 0.5 - src[0]) * dw / (src[2] - src[0]) - 0.5      # frame pixel index (centre at +0.5)
    k = int(round(ideal))
    xs = np.arange(max(0, k - 8), min(W, k + 9))
    y = int(round((dst[1] + dst[3]) / 2)) if dst[1] > 0 else H // 2
    w = pic[y, xs] - 64.0
    return float((w * xs).sum() / w.sum()) - ideal


def test_fit_still_geometry_a_thin_line_lands_within_a_quarter_pixel():
    """The line's centroid against the window's own mapping, at sub-pixel positions:
    a fill at z 1, a z 1.5 stop off centre, and a pillarboxed whole portrait."""
    cases = [((1000, 562), dict(z=1.0, clamp="frame")),
             ((1000, 562), dict(z=1.5, cx=0.37, cy=0.6, clamp="image")),
             ((600, 800), dict(z=1.0, clamp="native"))]
    for size, kw in cases:
        src, _ = M.still_view(size, L, **kw)
        lo, hi = src[0] + 20, src[2] - 20
        for k in range(9):                                   # columns at many phases against the frame grid
            col = int(lo + (hi - lo) * (k + 0.5) / 9) + k % 3
            err = _line_centroid_error(size, col, kw)
            assert abs(err) <= 0.25, (size, kw, col, err)
