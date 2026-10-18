"""phone-legibility (cinematography pass, founder 2026-10-17): every must-read text reads at 7 px or more on a
693 px landscape phone; the provenance label is 2.0 % of H and the lower third's source line 2.2 %."""
from studio.engine import maps as MP
from studio.engine import motion as M


def test_label_and_source_sizes():
    assert M.LABEL["size"] == 2.0
    assert M.LT["source"] == 2.2


def test_dot_timings_unchanged():
    # the cinematography pass changes sizes only: the dot's whisper, hold and fold stay as A42 set them
    assert (M.LABEL["hold"], M.LABEL["exit"], M.LABEL["repeat_s"]) == (2.0, 0.75, 40.0)


def test_house_text_all_legible_on_the_phone():
    rows = M.phone_legibility(1920, 1080)
    assert rows and all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
    label = next(r for r in rows if r["element"] == "provenance label")
    assert abs(label["px"] - 7.8) < 0.01


def test_the_measure_is_proportional_to_the_frame():
    a = {r["element"]: r["px"] for r in M.phone_legibility(1920, 1080)}
    b = {r["element"]: r["px"] for r in M.phone_legibility(1280, 720)}
    assert all(abs(a[k] - b[k]) < 0.02 for k in a)        # same 16:9 frame on the same phone: same size


def test_small_text_is_reported():
    rows = M.phone_legibility(1920, 1080, extra={"tiny": 1.0})
    tiny = next(r for r in rows if r["element"] == "tiny")
    assert not tiny["ok"] and tiny["px"] < M.PHONE["min_px"]


def test_map_sizes_are_measured_too():
    extra = {f"map {k}": v for k, v in MP.SIZES.items()}
    rows = M.phone_legibility(1920, 1080, extra=extra)
    assert {f"map {k}" for k in MP.SIZES} <= {r["element"] for r in rows}
