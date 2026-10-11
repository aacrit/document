"""R5b (GRAMMAR A32, BRAND-KIT 13): marks drawn over a georeferenced archive
sheet. The georef fit and its residual, every overlay lint in both
directions, the presets enforcement, the camera between geographic extents,
determinism and the provenance label. The sheet here is generated at test
time (a graticule on a blank page, its control points from a known
projection), never tracked."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio.engine import georef as GR
from studio.engine import motion as M
from studio.engine import overlays as OV

FIXTURE = Path(__file__).resolve().parent / "fixture"

# A sheet like an AMS U502 tile: 1.5 by 1 degree, Transverse Mercator, 40 m a pixel, turned 0.3 degrees in the scan.
LON0, LAT0, LON1, LAT1 = 75.0, 32.0, 76.5, 33.0
PROJ = {"name": "tm", "lon0": 75.0, "lat0": 0.0, "spheroid": "everest1830"}
SIZE = (3900, 3100)
_ROT = math.radians(0.3)
_E0, _N0 = GR.tm_forward(LON0, LAT1, 75.0, 0.0, "everest1830")


def true_px(lon: float, lat: float) -> tuple[float, float]:
    """The sheet's own (known) pixel for a lon, lat: TM, 40 m a pixel, a small rotation, a margin of 150 px."""
    e, n = GR.tm_forward(lon, lat, 75.0, 0.0, "everest1830")
    x, y = (e - _E0) / 40.0, (_N0 - n) / 40.0
    return (150 + x * math.cos(_ROT) - y * math.sin(_ROT), 150 + x * math.sin(_ROT) + y * math.cos(_ROT))


def graticule(noise=None) -> list[dict]:
    out = []
    for i, lon in enumerate(np.arange(LON0, LON1 + 1e-9, 0.25)):
        for j, lat in enumerate(np.arange(LAT0, LAT1 + 1e-9, 0.25)):
            x, y = true_px(float(lon), float(lat))
            if noise is not None:
                dx, dy = noise(i, j)
                x, y = x + dx, y + dy
            out.append({"px": [x, y], "lonlat": [float(lon), float(lat)], "from": f"15' graticule {lon:.2f}E {lat:.2f}N"})
    return out


def make_georef(fit: str = "tm", noise=None, **over) -> dict:
    g = {"projection": dict(PROJ, name=fit if fit != "affine" else "tm"), "stated": "Transverse Mercator (test sheet)",
         "fit": fit, "control": graticule(noise), "neatline": [LON0, LAT0, LON1, LAT1], "drawn_precision_m": 200,
         "verified_by": "test"}
    g = GR.record(g)
    g.update(over)
    return g


@pytest.fixture(scope="module")
def georef() -> dict:
    # a scan's error: a deterministic +-1 px wobble at each control point
    return make_georef(noise=lambda i, j: (0.8 * math.sin(i * 1.7 + j), 0.8 * math.cos(i + 2.3 * j)))


# --------------------------------------------------------------------------
# The georef: fit, residual, inverse
# --------------------------------------------------------------------------


def test_a_tm_fit_recovers_a_tm_sheet_exactly():
    g = make_georef()
    f = GR.fit(g)
    assert f.rmse_px < 0.01 and f.max_px < 0.02
    assert abs(f.m_per_px - 40.0) < 0.4                 # the sheet's own scale, within the sphere's 1%
    for lon, lat in ((75.1, 32.1), (75.9, 32.6), (76.4, 32.95)):
        x, y = f.to_px(lon, lat)
        tx, ty = true_px(lon, lat)
        assert math.hypot(x - tx, y - ty) < 0.02


def test_an_affine_on_degrees_cannot_fit_a_tm_sheet():
    """Meridians converge on a TM sheet, so an affine fit on longitude and latitude misses by pixels: the
    reason the U502 sheets are fitted in their own projection (affine 5.5 px rms on NI 43-15, tm 1.0)."""
    f = GR.fit(make_georef("affine"))
    assert f.rmse_px > 2.0


def test_the_residual_is_the_root_mean_square_of_the_control_points(georef):
    f = GR.fit(georef)
    assert f.rmse_px == pytest.approx(float(np.sqrt(np.mean(np.square(f.residuals)))))
    assert 0.3 < f.rmse_px < 1.2 and f.max_px >= f.rmse_px
    assert georef["rmse_px"] == pytest.approx(f.rmse_px, abs=1e-3)


def test_the_inverse_returns_the_coordinates(georef):
    f = GR.fit(georef)
    for lon, lat in ((75.2, 32.2), (76.3, 32.9)):
        assert f.to_lonlat(*f.to_px(lon, lat)) == pytest.approx((lon, lat), abs=1e-7)


def test_polyconic_and_tm_agree_on_one_sheet():
    a = GR.tm_forward(75.5, 32.5, 75.5, 32.0, "everest1830")
    b = GR.polyconic_forward(75.5, 32.5, 75.5, 32.0, "everest1830")
    assert a == pytest.approx(b, abs=1e-6)              # on the central meridian both are the meridian arc


def test_a_good_georef_has_no_problems(georef):
    assert GR.problems(georef) == []


@pytest.mark.parametrize("change, needle", [
    (lambda g: g.update(control=g["control"][:3]), "control points"),
    (lambda g: g["control"][0].update({"from": ""}), "does not say what it was read from"),
    (lambda g: g.update(rmse_px=0.2), "recorded rmse_px"),
    (lambda g: g.update(m_per_px=55.0), "recorded m_per_px"),
    (lambda g: g.update(fit="mercator"), "cannot be fitted"),
    (lambda g: g.update(neatline=None), "neatline"),
    (lambda g: g.update(drawn_precision_m=None), "drawn_precision_m"),
])
def test_a_bad_georef_is_refused(georef, change, needle):
    g = copy.deepcopy(georef)
    change(g)
    assert any(needle in p for p in GR.problems(g)), GR.problems(g)


def test_a_residual_over_budget_is_refused():
    g = make_georef(noise=lambda i, j: (3.0 * (-1) ** (i + j), 2.5 * (-1) ** i))
    assert any("over the budget" in p for p in GR.problems(g))


def test_no_georef_means_shown_plain():
    assert GR.problems(None) == ["the sheet has no georef: it is shown plain and may carry no mark"]


# --------------------------------------------------------------------------
# The lints, each in both directions
# --------------------------------------------------------------------------

AWARD = {"id": "src-test:item1", "licence": "public (test)", "used_for": "where the line runs", "year": 1947,
         "runs": {"ends": [[75.30, 32.70]], "tol_m": 1500}}
W, H = 1280, 720


def line_mark(**over) -> dict:
    pts = [list(true_px(75.30, 32.70)), list(true_px(75.25, 32.50)), list(true_px(75.0, 32.30))]   # ends on the west edge
    m = {"id": "K1", "kind": "line", "name": "a test line", "geometry": {"sheet_px": pts},
         "traced": {"on": "SHEET", "what": "the test sheet's printed line", "error_px": 3},
         "source": copy.deepcopy(AWARD), "feature_year": 1947, "precision_m": 400,
         "enter": {"preset": "trace", "at_s": 1.0}, "exit": {"ease": "let_go", "at_s": 6.0}}
    m.update(over)
    return m


def halo_mark(**over) -> dict:
    m = {"id": "K2", "kind": "halo", "name": "Testpur", "spelling": "sheet", "geometry": {"sheet_px": list(true_px(75.95, 32.45))},
         "traced": {"on": "SHEET", "what": "the town's symbol", "error_px": 5},
         "source": dict(AWARD, used_for="the place the record names"), "feature_year": 1947, "precision_m": 700,
         "enter": {"preset": "whisper", "at_s": 2.0}, "exit": {"ease": "let_go", "at_s": 6.0}}
    m.update(over)
    return m


def outline_mark(**over) -> dict:
    ring = [list(true_px(lon, lat)) for lon, lat in ((75.4, 32.3), (75.8, 32.3), (75.8, 32.6), (75.4, 32.6))]
    m = {"id": "K3", "kind": "outline", "name": "a tahsil as printed", "geometry": {"sheet_px": ring},
         "traced": {"on": "SHEET", "what": "the printed tahsil boundary", "error_px": 3},
         "source": dict(AWARD, used_for="the tahsil the record names"), "feature_year": 1947, "precision_m": 400,
         "enter": {"preset": "settle", "at_s": 2.0}}
    m.update(over)
    return m


def shot_for(georef, marks, *, kind="archive_still", mark="ARCHIVE", fill=True, extent=(75.0, 32.0, 76.5, 32.75), path=None):
    s = {"id": "S1", "kind": kind, "asset": "SHEET", "mark": mark, "fill_ok": fill, "preset": "FIND",
         "find": {"to": {"extent": list(extent)}}, "_dur": 6.0, "marks": marks,
         "_item": {"id": "SHEET", "year": 1955, "georef": georef, "_path": path}}
    s["_cam"] = OV.find_camera(s, SIZE, W, H, open_s=1.5)
    s["label"] = M.mark_label(mark, OV.label_year(s["_item"]), OV.MARKS_DRAWN)
    return s


PLAY = {"era": {"from": 1946, "to": 1948}}


def problems(georef, mark, play=PLAY, **kw) -> dict:
    s = shot_for(georef, [mark], **kw)
    fit, _ = OV.sheet_fit(s["_item"])
    return OV.mark_problems(s, mark, fit, georef, s["_cam"], W, H, play)


def failing(p: dict) -> set:
    return {k for k, v in p.items() if v}


@pytest.mark.parametrize("make", [line_mark, halo_mark, outline_mark])
def test_a_good_mark_passes_every_rule(georef, make):
    assert failing(problems(georef, make())) == set(), problems(georef, make())


class Lints:
    def __init__(self):
        self.calls = []

    def __call__(self, rule, ok, **kw):
        self.calls.append((rule, ok, kw))

    def failed(self) -> set:
        return {r for r, ok, _ in self.calls if not ok}


def test_overlay_georef_passes_on_a_georeferenced_archive_sheet(georef):
    lint = Lints()
    s = shot_for(georef, [line_mark()])
    OV.lints(lint, [s], W, H, PLAY)
    assert lint.failed() == set() and ("overlay-georef", True) in [(r, ok) for r, ok, _ in lint.calls]


def test_overlay_georef_refuses_a_sheet_without_a_georef(georef):
    lint = Lints()
    s = shot_for(georef, [line_mark()])
    s["_item"]["georef"] = None
    OV.lints(lint, [s], W, H, PLAY)
    assert "overlay-georef" in lint.failed() and "_overlay" not in s           # shown plain, nothing drawn


def test_overlay_georef_refuses_a_residual_over_budget(georef):
    lint = Lints()
    s = shot_for(georef, [line_mark()])
    s["_item"]["georef"] = dict(georef, rmse_px=2.4)
    OV.lints(lint, [s], W, H, PLAY)
    assert "overlay-georef" in lint.failed()


def test_overlay_georef_refuses_marks_on_a_drawn_frame(georef):
    lint = Lints()
    OV.lints(lint, [shot_for(georef, [line_mark()], mark="DRAWN")], W, H, PLAY)
    assert "overlay-georef" in lint.failed()


def test_overlay_precision_refuses_a_claim_finer_than_its_sources(georef):
    p = problems(georef, line_mark(precision_m=150))
    assert any("finer than its sources allow" in x for x in p["overlay-precision"])


def test_overlay_precision_counts_the_georef_the_sheet_and_the_tracing(georef):
    f = GR.fit(georef)
    need = OV.needed_precision_m(line_mark(), f, georef)
    assert need["georef_m"] == pytest.approx(f.max_px * f.m_per_px)
    assert need["sheet_drawn_m"] == 200 and need["trace_m"] == pytest.approx(3 * f.m_per_px)
    claim = math.ceil(need["total_m"])
    assert "overlay-precision" not in failing(problems(georef, line_mark(precision_m=claim)))
    assert "overlay-precision" in failing(problems(georef, line_mark(precision_m=claim - 2)))


def test_overlay_precision_refuses_a_band_narrower_than_the_claim(georef):
    assert "overlay-precision" in failing(problems(georef, line_mark(style={"band": 0.05})))
    assert "overlay-precision" not in failing(problems(georef, line_mark(style={"band": 1.0})))


def test_an_auto_band_is_as_wide_as_the_claim_at_the_closest_zoom(georef):
    s = shot_for(georef, [line_mark(precision_m=900)])
    fit, _ = OV.sheet_fit(s["_item"])
    r = OV.resolve(s, s["marks"][0], fit, s["_cam"], H)
    want = 100 * 900 / OV.frame_m_per_px(fit, s["_cam"], H) / H
    assert r["style"]["band"] == pytest.approx(max(OV.STYLE["line"]["band"], want))
    assert r["style"]["band"] > OV.STYLE["line"]["band"]


def test_overlay_precision_refuses_a_line_too_coarse_for_the_zoom(georef):
    p = problems(georef, line_mark(precision_m=8000))
    assert any("too coarse" in x for x in p["overlay-precision"])


def test_overlay_precision_refuses_a_halo_finer_than_its_claim(georef):
    assert "overlay-precision" in failing(problems(georef, halo_mark(precision_m=20000)))


def test_overlay_precision_draws_a_line_only_where_its_source_runs(georef):
    m = line_mark()
    m["source"].pop("runs")
    assert any("only where its cited source runs" in x for x in problems(georef, m)["overlay-precision"])
    m = line_mark()
    m["geometry"]["sheet_px"].insert(0, list(true_px(75.6, 32.85)))     # starts 30 km past the source's end
    assert any("runs past its source" in x for x in problems(georef, m)["overlay-precision"])
    m = line_mark()
    m["source"]["runs"]["bbox"] = [75.2, 32.4, 75.4, 32.8]
    assert any("outside where the source runs" in x for x in problems(georef, m)["overlay-precision"])


def test_overlay_precision_refuses_a_point_off_the_map_face(georef):
    m = line_mark()
    m["geometry"]["sheet_px"].append([20.0, 3000.0])                       # in the margin, off the neatline
    assert any("off the sheet's map face" in x for x in problems(georef, m)["overlay-precision"])


def test_overlay_era_refuses_a_feature_after_the_films_era(georef):
    assert "overlay-era" in failing(problems(georef, line_mark(feature_year=1972)))
    assert "overlay-era" not in failing(problems(georef, line_mark(feature_year=1947)))


def test_overlay_era_needs_the_films_era(georef):
    assert any("declares no era" in x for x in problems(georef, line_mark(), play={})["overlay-era"])


def test_overlay_era_refuses_todays_dataset_on_a_period_sheet(georef):
    ll = [[75.30, 32.70], [75.25, 32.50], [75.0, 32.30]]
    young = line_mark(geometry={"lonlat": ll}, traced=None, geometry_year=2020)
    old = line_mark(geometry={"lonlat": ll}, traced=None, geometry_year=1950)
    assert any("younger than the 1955 sheet" in x for x in problems(georef, young)["overlay-era"])
    assert "overlay-era" not in failing(problems(georef, old))


@pytest.mark.parametrize("make, style, ok", [
    (outline_mark, {"fill": 0.08}, True),
    (outline_mark, {"fill": 0.25}, False),
    (line_mark, {"fill": 0.05}, False),        # a line has no fill at all
    (halo_mark, {"opacity": 0.9}, False),
    (line_mark, {"opacity": 0.62}, False),
    (line_mark, {"opacity": 0.60}, True),
])
def test_overlay_no_fill(georef, make, style, ok):
    assert ("overlay-no-fill" not in failing(problems(georef, make(style=style)))) is ok


@pytest.mark.parametrize("make, enter, exit_, ok", [
    (line_mark, {"preset": "trace", "at_s": 1.0}, {"ease": "let_go"}, True),
    (line_mark, {"preset": "drift", "at_s": 1.0}, {"ease": "let_go"}, False),        # a line draws on at trace's pace
    (line_mark, {"preset": "ease-in-out", "at_s": 1.0}, {"ease": "let_go"}, False),  # not a house spring
    (line_mark, {"preset": "trace", "at_s": 1.0, "dur_s": 0.5}, {"ease": "let_go"}, False),   # no inline timing
    (line_mark, {"preset": "trace", "at_s": 1.0, "bezier": [0.2, 0, 0, 1]}, {"ease": "let_go"}, False),
    (halo_mark, {"preset": "whisper", "at_s": 2.0}, {"ease": "fade_out"}, False),     # a mark is let go
    (halo_mark, {"preset": "trace", "at_s": 2.0}, {"ease": "let_go"}, False),
    (halo_mark, {"preset": "settle", "at_s": 2.0}, {"ease": "let_go"}, True),
    (outline_mark, {"preset": "settle", "at_s": 2.0}, {}, True),
])
def test_overlay_presets(georef, make, enter, exit_, ok):
    p = problems(georef, make(enter=enter, exit=exit_))
    assert ("overlay-presets" not in failing(p)) is ok, p["overlay-presets"]


def test_the_presets_are_the_motion_modules_and_nothing_else():
    names = OV.preset_names()
    assert names == tuple(s.name for s in M.PRESETS)
    assert all(OV.preset(n) is s for n, s in zip(names, M.PRESETS))
    for bad in ("linear", "ease-in", "cubic-bezier(0.2,0,0,1)", "Trace", "rostrum", ""):
        with pytest.raises(KeyError):
            OV.preset(bad)
    for kind, allowed in OV.ENTER_PRESETS.items():
        assert set(allowed) <= set(names), kind


def test_trace_is_defined_once_in_the_motion_module():
    tr = [s for s in M.PRESETS if s.name == "trace"]
    assert len(tr) == 1 and (tr[0].k, tr[0].c, tr[0].m) == (14, 7.5, 1.3)
    assert 0.85 < tr[0].zeta < 0.9 and 1.4 < tr[0].settle_time() < 1.7
    assert M.TRACE is tr[0]


def test_overlay_names(georef):
    assert "overlay-names" in failing(problems(georef, halo_mark(spelling=None)))
    assert "overlay-names" in failing(problems(georef, halo_mark(spelling="record")))           # cites no record
    assert "overlay-names" not in failing(problems(georef, halo_mark(spelling="record", name_source="src-test:item1")))


def test_overlay_cited(georef):
    m = line_mark()
    m["source"].pop("licence")
    assert "overlay-cited" in failing(problems(georef, m))
    assert "overlay-cited" in failing(problems(georef, line_mark(traced=None)))     # read off the sheet, not said so
    assert "overlay-cited" in failing(problems(georef, line_mark(traced={"on": "OTHER", "what": "x", "error_px": 2})))


def test_overlay_timing(georef):
    assert "overlay-timing" in failing(problems(georef, line_mark(enter={"preset": "trace", "at_s": 7.0})))
    assert "overlay-timing" not in failing(problems(georef, line_mark()))


def test_overlay_label(georef):
    lint = Lints()
    s = shot_for(georef, [line_mark()])
    s["label"] = "Archive · 1955"
    OV.lints(lint, [s], W, H, PLAY)
    assert lint.failed() == {"overlay-label"}


# --------------------------------------------------------------------------
# Camera, drawing and determinism
# --------------------------------------------------------------------------


def test_find_opens_whole_and_ends_on_the_extent(georef):
    s = shot_for(georef, [], extent=(75.0, 32.0, 76.5, 32.75))
    cam = s["_cam"]
    assert cam["path"][0] == {"z": 1.0, "x": 0.5, "y": 0.5} and cam["preset"] == "FIND"
    end = OV.framing_at(cam, 6.0, 6.0)
    src, _ = M.still_view(SIZE, M.Layout(W, H), z=end["z"], cx=end["x"], cy=end["y"], clamp=cam["clamp"])
    for lon, lat in ((75.05, 32.05), (76.45, 32.7)):             # the extent is inside the last framing
        x, y = GR.fit(georef).to_px(lon, lat)
        assert src[0] <= x <= src[2] and src[1] <= y <= src[3]
    assert OV.framing_at(cam, 0.5, 6.0) == cam["path"][0]       # A7: whole until the move begins


def test_find_past_the_old_still_cap_is_allowed_up_to_the_scans_own_resolution(georef):
    """A32 refined (CoS 2026-10-11): a push deeper than the old flat 1.3 still
    cap is now allowed on a georeferenced archive sheet, as long as it stays
    inside what the scan's own resolution supports at this delivery frame."""
    s = shot_for(georef, [], extent=(75.3, 32.5, 75.7, 32.8))
    cam = s["_cam"]
    assert cam["z_rel_max"] > 1.3                   # deeper than the superseded still cap
    assert cam["requested_z_max"] <= cam["scan_zmax"] + 1e-9    # and still inside the scan's own support
    assert cam["z_max"] == pytest.approx(cam["requested_z_max"])  # so nothing was clamped


def test_find_past_the_scans_resolution_is_clamped_and_reported(georef):
    s = shot_for(georef, [], extent=(75.4, 32.3, 75.6, 32.4))
    cam = s["_cam"]
    assert cam["requested_z_max"] > cam["scan_zmax"]             # asked for more than the scan supports
    assert cam["z_max"] == pytest.approx(cam["scan_zmax"])       # the camera clamps to it, never past it
    assert cam["z_max"] < cam["requested_z_max"]


@pytest.mark.parametrize("size, W, H, want", [
    ((3900, 3100), 1280, 720, 720 / 3100),
    ((3900, 3100), 1920, 1080, 1080 / 3100),
    ((100, 80), 1280, 720, None),            # a scan already smaller than the frame: never under 1.0
])
def test_scan_zmax_is_the_scans_own_resolution_against_the_frame(size, W, H, want):
    z = OV.scan_zmax(size, W, H)
    if want is None:
        assert z == 1.0
    else:
        assert z == pytest.approx(1.0 / want)


def test_scan_zmax_is_lower_at_a_higher_delivery_resolution():
    """The same scan supports a shallower relative push at 1080p than at
    720p: more of its own pixels are already spent fitting the bigger frame
    at z = 1 (A32 refined, CoS 2026-10-11: computed per delivery resolution)."""
    z720 = OV.scan_zmax(SIZE, 1280, 720)
    z1080 = OV.scan_zmax(SIZE, 1920, 1080)
    assert z720 > 1.3 and z1080 > 1.3           # both still deeper than the old flat cap
    assert z1080 < z720


def test_overlay_zoom_passes_a_request_the_scan_supports(georef):
    lint = Lints()
    s = shot_for(georef, [], extent=(75.3, 32.5, 75.7, 32.8))
    OV.lints(lint, [s], W, H, PLAY)
    assert "overlay-zoom" not in lint.failed()


def test_overlay_zoom_refuses_a_request_tighter_than_the_scan_supports(georef):
    lint = Lints()
    s = shot_for(georef, [], extent=(75.4, 32.3, 75.6, 32.4))
    OV.lints(lint, [s], W, H, PLAY)
    assert "overlay-zoom" in lint.failed()


def test_overlay_zoom_is_per_delivery_resolution(georef):
    """The same extent can fit 720p's scan support and miss 1080p's."""
    ext = (75.3, 32.5, 75.7, 32.8)
    lint720, lint1080 = Lints(), Lints()
    s720 = shot_for(georef, [], extent=ext)
    OV.lints(lint720, [s720], 1280, 720, PLAY)
    s1080 = shot_for(georef, [], extent=ext)
    s1080["_cam"] = OV.find_camera(s1080, SIZE, 1920, 1080, open_s=1.5)
    OV.lints(lint1080, [s1080], 1920, 1080, PLAY)
    assert "overlay-zoom" not in lint720.failed()
    assert "overlay-zoom" in lint1080.failed()


def test_overlay_precision_still_binds_at_the_deeper_zoom(georef):
    """GRAMMAR A32(c) is unchanged by the deeper push: a mark's claimed
    precision still has to fit the frame it is actually shown at, now that
    the frame can be a much deeper one than 1.3 allowed."""
    s = shot_for(georef, [line_mark(precision_m=380)], extent=(75.3, 32.5, 75.7, 32.8))
    fit, _ = OV.sheet_fit(s["_item"])
    p = OV.mark_problems(s, s["marks"][0], fit, s["_item"]["georef"], s["_cam"], W, H, PLAY)
    assert p["overlay-precision"] == []          # fine at this deeper zoom
    s2 = shot_for(georef, [line_mark(precision_m=500)], extent=(75.3, 32.5, 75.7, 32.8))
    fit2, _ = OV.sheet_fit(s2["_item"])
    p2 = OV.mark_problems(s2, s2["marks"][0], fit2, s2["_item"]["georef"], s2["_cam"], W, H, PLAY)
    assert any("too coarse" in x for x in p2["overlay-precision"])   # too coarse once pushed this deep


def sheet_png(path: Path) -> Path:
    img = Image.new("RGB", SIZE, (244, 238, 226))
    d = ImageDraw.Draw(img)
    for lon in np.arange(LON0, LON1 + 1e-9, 0.25):
        d.line([true_px(float(lon), float(lat)) for lat in np.linspace(LAT0, LAT1, 9)], fill=(60, 60, 60), width=3)
    for lat in np.arange(LAT0, LAT1 + 1e-9, 0.25):
        d.line([true_px(float(lon), float(lat)) for lon in np.linspace(LON0, LON1, 9)], fill=(60, 60, 60), width=3)
    img.save(path)
    return path


@pytest.fixture(scope="module")
def drawn_shot(georef, tmp_path_factory):
    path = sheet_png(tmp_path_factory.mktemp("sheet") / "sheet.png")
    s = shot_for(georef, [line_mark(), halo_mark(), outline_mark(style={"fill": 0.06})], path=str(path))
    lint = Lints()
    OV.lints(lint, [s], W, H, PLAY)
    assert lint.failed() == set()
    return s


def frame(s, t):
    img = Image.open(s["_item"]["_path"]).convert("RGB")
    f = OV.framing_at(s["_cam"], t, s["_dur"])
    pic = M.fit_still(img, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp=s["_cam"]["clamp"])
    return pic, OV.draw(pic, s, t, f, M.Layout(W, H), img.size)


def test_the_same_frame_renders_the_same_pixels_twice(drawn_shot):
    a = hashlib.sha256(frame(drawn_shot, 4.0)[1].tobytes()).hexdigest()
    b = hashlib.sha256(frame(drawn_shot, 4.0)[1].tobytes()).hexdigest()
    assert a == b


def test_marks_sit_on_their_cited_coordinates(drawn_shot, georef):
    bare, drawn = frame(drawn_shot, 5.0)
    diff = np.abs(np.asarray(drawn, dtype=int) - np.asarray(bare, dtype=int)).sum(2)
    f = OV.framing_at(drawn_shot["_cam"], 5.0, 6.0)
    src, dst = M.still_view(SIZE, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp=drawn_shot["_cam"]["clamp"])
    x, y = GR.fit(georef).to_px(75.25, 32.50)                  # a vertex of the line
    fx = dst[0] + (x - src[0]) * (dst[2] - dst[0]) / (src[2] - src[0])
    fy = dst[1] + (y - src[1]) * (dst[3] - dst[1]) / (src[3] - src[1])
    assert diff[int(round(fy)) - 1:int(round(fy)) + 2, int(round(fx)) - 1:int(round(fx)) + 2].max() > 20
    assert diff[10:60, 600:700].max() == 0                     # nothing is drawn where no mark is


def test_a_line_draws_on_and_never_past_its_end(drawn_shot):
    m = drawn_shot["_overlay"]["marks"][0]
    assert OV.mark_alpha(m, 0.5) == (0.0, 0.0, 1.0)             # before it enters, nothing
    _, early, _ = OV.mark_alpha(m, 1.3)
    _, late, _ = OV.mark_alpha(m, 1.0 + M.TRACE.settle_time())
    assert 0.0 < early < late <= 1.0
    for t in np.arange(1.0, 6.0, 1 / 24):                       # trace overshoots 0.3%; the draw-on is clamped
        assert OV.mark_alpha(m, float(t))[1] <= 1.0
    assert OV.mark_alpha(m, 5.99)[0] < 0.05 and OV.mark_alpha(m, 6.0)[0] == 0.0     # let go by the shot's end
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert OV._cut(pts, 1.004) == pts and OV._cut(pts, 0.5)[-1] == pytest.approx((10.0, 0.0))


def test_the_halo_is_a_ring_that_leaves_the_place_itself_uncovered(drawn_shot, georef):
    bare, drawn = frame(drawn_shot, 5.0)
    diff = np.abs(np.asarray(drawn, dtype=int) - np.asarray(bare, dtype=int)).sum(2)
    f = OV.framing_at(drawn_shot["_cam"], 5.0, 6.0)
    src, dst = M.still_view(SIZE, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp=drawn_shot["_cam"]["clamp"])
    x, y = GR.fit(georef).to_px(75.95, 32.45)
    fx = dst[0] + (x - src[0]) * (dst[2] - dst[0]) / (src[2] - src[0])
    fy = dst[1] + (y - src[1]) * (dst[3] - dst[1]) / (src[3] - src[1])
    r = M.Layout(W, H).h(OV.STYLE["halo"]["radius"])
    assert diff[int(fy), int(fx)] == 0                          # the place's own pixels are untouched
    assert diff[int(fy), int(round(fx + r))] > 10               # the ring is at its radius


# --------------------------------------------------------------------------
# A32 refined (CoS 2026-10-11): a ring kept clear of the printed place name
# at the deeper zoom (a low finding from the proof), in both directions.
# --------------------------------------------------------------------------


def test_halo_ring_geometry_keeps_the_default_clearance_when_the_label_is_unknown():
    centre, safe = OV.halo_ring_geometry({}, [100.0, 200.0])
    assert centre == [100.0, 200.0] and safe == OV.HALO_LABEL_CLEAR_PX


def test_halo_ring_geometry_keeps_its_full_reach_when_a_known_label_is_far():
    """A known box, unlike an unknown one, is a real boundary: when it is
    far away it imposes no clearance cap of its own (resolve()'s min against
    STYLE's own radius is what keeps the ring sane)."""
    box = {"sheet_px": [100.0 + 500.0, 200.0, 100.0 + 560.0, 220.0]}
    centre, safe = OV.halo_ring_geometry({"label_box": box}, [100.0, 200.0])
    assert centre == [100.0, 200.0]
    assert safe > OV.HALO_LABEL_CLEAR_PX                         # far past the unknown-box default clearance


def test_halo_ring_geometry_sizes_down_to_clear_a_near_label():
    box = {"sheet_px": [120.0, 190.0, 180.0, 210.0]}            # 20 px east of the point
    centre, safe = OV.halo_ring_geometry({"label_box": box}, [100.0, 200.0])
    assert centre == [100.0, 200.0]                             # sized, not offset: the point itself is clear
    assert OV.HALO_MIN_RADIUS_PX <= safe < OV.HALO_LABEL_CLEAR_PX
    x0, y0, x1, y1 = box["sheet_px"]
    gap = math.hypot(max(x0 - centre[0], 0.0, centre[0] - x1), max(y0 - centre[1], 0.0, centre[1] - y1))
    assert safe <= gap                                          # the ring never reaches into the box


def test_halo_ring_geometry_offsets_away_when_the_point_sits_on_the_label():
    box = {"sheet_px": [95.0, 185.0, 125.0, 205.0]}             # the point (100, 200) is inside this box
    centre, safe = OV.halo_ring_geometry({"label_box": box}, [100.0, 200.0])
    assert centre != [100.0, 200.0]                             # offset, since sizing alone cannot clear it
    cx, cy = centre
    x0, y0, x1, y1 = box["sheet_px"]
    gap = math.hypot(max(x0 - cx, 0.0, cx - x1), max(y0 - cy, 0.0, cy - y1))
    assert gap >= safe - 1e-6                                   # the offset centre's own ring still clears it


def test_a_halo_ring_keeps_its_usual_size_when_a_known_label_is_far(georef, tmp_path_factory):
    path = sheet_png(tmp_path_factory.mktemp("sheet-halo-far") / "sheet.png")
    px, py = true_px(75.95, 32.45)
    m = halo_mark(label_box={"sheet_px": [px + 500, py + 500, px + 560, py + 520]})
    s = shot_for(georef, [m], path=str(path))
    lint = Lints()
    OV.lints(lint, [s], W, H, PLAY)
    assert lint.failed() == set()
    assert s["_overlay"]["marks"][0]["style"]["radius"] == pytest.approx(OV.STYLE["halo"]["radius"])


def test_a_halo_ring_does_not_cross_into_a_known_nearby_label_box(georef, tmp_path_factory):
    """The proof's low finding: at this shot's deepest zoom, a ring drawn
    at its usual (fixed frame %) radius would reach a label only 50 sheet
    px from the place it marks; sized down by its own label_box, it does
    not, and the place's own symbol stays uncovered (A32(e): a ring, never
    a disc, over the place)."""
    path = sheet_png(tmp_path_factory.mktemp("sheet-halo-near") / "sheet.png")
    px, py = true_px(75.95, 32.45)
    box = [px + 50, py - 10, px + 110, py + 10]          # a label close enough to be at risk, east of the place
    m = halo_mark(label_box={"sheet_px": box})
    s = shot_for(georef, [m], path=str(path))
    lint = Lints()
    OV.lints(lint, [s], W, H, PLAY)
    assert lint.failed() == set()
    resolved = s["_overlay"]["marks"][0]
    assert resolved["style"]["radius"] < OV.STYLE["halo"]["radius"]        # sized down from its usual radius

    bare, drawn = frame(s, 5.0)
    diff = np.abs(np.asarray(drawn, dtype=int) - np.asarray(bare, dtype=int)).sum(2)
    f = OV.framing_at(s["_cam"], 5.0, 6.0)
    src, dst = M.still_view(SIZE, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp=s["_cam"]["clamp"])

    def to_frame(x, y):
        fx = dst[0] + (x - src[0]) * (dst[2] - dst[0]) / (src[2] - src[0])
        fy = dst[1] + (y - src[1]) * (dst[3] - dst[1]) / (src[3] - src[1])
        return fx, fy

    x0f, y0f = to_frame(box[0], box[1])
    x1f, y1f = to_frame(box[2], box[3])
    xa, xb = sorted((int(round(x0f)), int(round(x1f))))
    ya, yb = sorted((int(round(y0f)), int(round(y1f))))
    assert diff[max(0, ya):yb + 1, max(0, xa):xb + 1].max() == 0           # nothing drawn over the label's box
    fx, fy = to_frame(px, py)
    assert diff[int(fy), int(fx)] == 0                                    # the place itself stays uncovered


# --------------------------------------------------------------------------
# Provenance through the renderer: label, credits, sources.json, a refused sheet
# --------------------------------------------------------------------------


def mini_film(tmp: Path, georef: dict | None, *, marks=True) -> Path:
    """A one-shot film over a generated sheet. The sheet is a graticule drawn by this test (never tracked); its
    ledger item is written as an archive sheet would be so the A32 path (ARCHIVE with marks) is exercised."""
    film = tmp / "film"
    film.mkdir(parents=True, exist_ok=True)
    (film / "stills").mkdir(exist_ok=True)
    sheet_png(film / "stills" / "sheet.png")
    item = {"id": "SHEET", "file": "sheet.png", "title": "Test sheet, a graticule drawn by the R5b tests",
            "archive": "R5b test sheet", "archive_short": "test sheet", "licence": "Public domain", "date": "1955",
            "year": 1955, "people": False, "shows_bodies": False, "credit": "R5b test sheet", "georef": georef}
    (film / "stills-ledger.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    shot = {"id": "S1", "kind": "archive_still", "asset": "SHEET", "mark": "ARCHIVE", "fill_ok": True, "start_s": 0.0,
            "dur_s": 6.0, "transition_in": {"type": "cut"}, "preset": "FIND",
            "find": {"to": {"extent": [75.0, 32.0, 76.5, 32.75]}}, "why": "R5b test"}
    if marks:
        shot["marks"] = [line_mark(traced={"on": "SHEET", "what": "the test line", "error_px": 3}), halo_mark()]
    play = {"title": "R5b test", "slug": "r5b-test", "era": {"from": 1946, "to": 1948},
            "languages": {"spoken": "en", "subtitles": ["en"]}, "runtime_target_s": 6,
            "ledgers": {"stills": {"path": "stills-ledger.json", "media": "stills"}},
            "cast": {"speakers": [], "voices": []},
            "parts": [{"id": "ch-1", "kind": "chapter", "number": 1, "title": "Test", "dates": "1947",
                       "shots": [shot], "lines": [], "cues": [], "text": []}], "subtitle_source": []}
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    return film


def build(film: Path, h: int = 360):
    from studio.engine.journal import Journal
    from studio.engine.render import build_plan, frame_size
    Wf, Hf = frame_size(h)
    return build_plan(film, W=Wf, H=Hf, burn_subtitles=False, journal=Journal(film="r5b-test"))


@pytest.fixture(scope="module")
def film_plan(georef, tmp_path_factory):
    return build(mini_film(tmp_path_factory.mktemp("r5b"), georef))


def test_the_label_says_marks_drawn_and_the_class_stays_archive(film_plan):
    s = film_plan["shots"][0]
    assert s["mark"] == "ARCHIVE" and s["label"] == "Archive · 1955 map · marks drawn"
    assert film_plan["marks"][0]["cls"] == "ARCHIVE"


def test_a_sheet_without_marks_keeps_its_plain_label():
    from studio.engine.render import mark_label
    item = {"year": 1959}
    assert mark_label({"mark": "ARCHIVE"}, item) == "Archive · 1959"
    assert mark_label({"mark": "ARCHIVE", "marks": [{}]}, item) == "Archive · 1959 map · marks drawn"
    assert mark_label({"mark": "RECONSTRUCTED", "alterations": ["stabilised"], "marks": [{}]}, item) == \
        "Reconstructed · 1959 map · stabilised, marks drawn"


def test_the_credits_list_every_mark_and_its_source(film_plan):
    blocks = dict(film_plan["credits"])
    lines = " ".join(blocks["Marks drawn"])
    assert "a test line: src-test:item1, public (test)" in lines and "Testpur" in lines


def test_sources_json_carries_the_marks_and_the_georef(film_plan, georef):
    from studio.engine.journal import Journal
    from studio.engine.render import sources_doc
    doc = sources_doc(film_plan, Journal(film="r5b-test"), {})
    s = doc["shots"][0]
    assert [m["id"] for m in s["marks"]] == ["K1", "K2"]
    assert s["marks"][0]["source"]["id"] == "src-test:item1" and s["marks"][0]["traced"]["on"] == "SHEET"
    assert s["georef"]["rmse_px"] == georef["rmse_px"] and s["georef"]["control_points"] == 35
    assert s["mark"]["label"] == "Archive · 1955 map · marks drawn"


def test_the_renderer_draws_the_marks_and_repeats_itself(film_plan):
    from studio.engine.render import Pictures, render_frame
    f = int(5.0 * 24)
    pics = Pictures(film_plan)
    a, b = render_frame(film_plan, f, pics), render_frame(film_plan, f, pics)
    pics.close()
    assert hashlib.sha256(a.tobytes()).hexdigest() == hashlib.sha256(b.tobytes()).hexdigest()
    bare = dict(film_plan, shots=[dict(film_plan["shots"][0], _overlay=None)])
    c = render_frame(bare, f)
    assert np.abs(a.astype(int) - c.astype(int)).max() > 20       # the marks are on the frame


def test_the_renderer_refuses_marks_on_a_sheet_without_a_georef(tmp_path):
    from studio.engine.render import Refused
    with pytest.raises(Refused, match="overlay-georef"):
        build(mini_film(tmp_path, None))


def test_a_sheet_without_a_georef_and_without_marks_is_shown_plain(tmp_path, georef):
    film = mini_film(tmp_path, None, marks=False)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    sh = play["parts"][0]["shots"][0]
    sh["preset"] = "HOLD"
    sh.pop("find")
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    plan = build(film)
    assert plan["shots"][0]["label"] == "Archive · 1955" and not plan["shots"][0].get("_overlay")


def test_the_renderer_refuses_a_find_tighter_than_the_scan_supports(tmp_path, georef):
    """A32 refined (CoS 2026-10-11): still-zoom-limit's flat 1.3 no longer
    governs FIND; a request past the scan's own resolution is refused by
    overlay-zoom instead."""
    from studio.engine.render import Refused
    film = mini_film(tmp_path, georef, marks=False)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    play["parts"][0]["shots"][0]["find"]["to"]["extent"] = [75.4, 32.3, 75.6, 32.4]
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    with pytest.raises(Refused, match="overlay-zoom"):
        build(film)


def test_the_render_still_camera_wires_find_to_the_scans_resolution(georef, tmp_path_factory):
    """render.still_camera (what build_plan actually calls to set ``_cam``)
    dispatches FIND to OV.find_camera, so the full pipeline's camera carries
    scan_zmax too, and a push past the old 1.3 still cap goes through it
    unclamped as long as the scan supports it."""
    from studio.engine.render import still_camera
    path = sheet_png(tmp_path_factory.mktemp("sheet3") / "sheet.png")
    item = {"id": "SHEET", "year": 1955, "georef": georef, "_path": str(path)}
    shot = {"id": "S1", "kind": "archive_still", "asset": "SHEET", "mark": "ARCHIVE", "fill_ok": True,
            "preset": "FIND", "find": {"to": {"extent": [75.3, 32.5, 75.7, 32.8]}}, "_dur": 9.0, "_item": item}
    cam = still_camera(shot, SIZE, W, H)
    assert cam["preset"] == "FIND" and cam["z_rel_max"] > 1.3
    assert cam["scan_zmax"] > 1.3
    assert cam["z_max"] == pytest.approx(cam["requested_z_max"])
