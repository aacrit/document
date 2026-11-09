"""Founder ruling, 2026-11-08: the series title shortens to 683 frames at 24 fps (28.4583 s), not the old 1018
(42.4167 s): the picture runs to the cut in 539 frames (672 at 30000/1001, 852 frames total there), plus the
unchanged 6.0 s lockup (144 / 180 frames). Point 1 of the ruling: the slot's length is data-driven, from the
series-title item's own frames and fps (A44), never a new fixed constant beside the one house default
(``titles.HOUSE_SLOT_FRAMES``, 683 at 24 fps). This file checks the pure helpers directly, and that a master at
each of the three lengths in play (the new house default at 24 and at 30000/1001, and the old 1018-frame v11
still carried by the live films until they are re-released) passes A40's lints end to end, its lockup and its
record read from the item, not from any fixed assumption."""

from __future__ import annotations

import json
from fractions import Fraction

import pytest

import test_a40_title_sequence as A
from studio.engine import cadence as CAD
from studio.engine import render as R
from studio.engine import titles as TS
from test_cine6_fps import make_master_at

# The three lengths in play (founder ruling 2026-11-08):
HOUSE_N, HOUSE_PICTURE = 683, 539            # 24 fps: 28.4583 s total, the cut at 539 frames (22.4583 s)
NTSC_N, NTSC_PICTURE = 852, 672              # 30000/1001: a separately authored native master, its own frame count
V11_N, V11_PICTURE = 1018, 874               # the old length (42.4167 s), still carried by the live films


def _tl_dip(archive_at: int, card_at: int) -> tuple[list[dict], dict]:
    """A timeline and dip like the module's own (TL, DIP), scaled to ``card_at`` (the cut from the record to the
    lockup) instead of the fixture's fixed 60 of 96. A one-frame dip, so the lockup's own dwell (the dip's end to
    the master's last frame) is, within rounding, exactly the gap from ``card_at`` to the master's end."""
    tl = [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
          {"frame": archive_at, "cls": "ARCHIVE", "label": "Archive · 1947"},
          {"frame": card_at, "cls": "CARD"}]
    return tl, {"centre_frame": card_at, "s": 1 / 24}


def _build(tmp_path, film, *, n: int, picture: int, rate: str):
    """A titled_film fixture whose series title is ``n`` frames at ``rate``, the cut (the record to the lockup)
    at frame ``picture``: its own master, burned with its own lockup, no separate lockup card needed (A40 lockup
    is met by the master's own, ``title-lockup``'s ``in_master``)."""
    r = float(Fraction(rate))
    archive_at = max(24, picture // 3)
    tl, dip = _tl_dip(archive_at, picture)
    d = tmp_path / "masters"
    d.mkdir()
    rec = film / "stills" / "FX-STILL-B.png"
    path = make_master_at(d / "master.mkv", rec, rate, n, tl, dip)
    item = {"fps": rate, "frames": n, "marks": tl, "dip": dip,
            "record_frames": [archive_at + 5, archive_at + 15], "lockup_frame": picture + (n - picture) // 2,
            "burned": True}
    title_s = n / r
    delta = title_s - A.TITLE_S                 # the template's other parts assumed the old 4 s title

    def edit(play):
        def move(x, by):
            for k in ("start_s", "end_s"):
                if isinstance(x.get(k), (int, float)):
                    x[k] = round(x[k] + by, 4)
        for part in play["parts"]:
            if part["id"] in ("cold", "series"):
                continue
            for coll in ("shots", "lines", "cues", "text"):
                for x in part.get(coll, []):
                    move(x, delta)
        for x in play.get("subtitle_source", []) + play.get("music", []) + play.get("moments", []):
            move(x, delta)
        play["runtime_target_s"] = play["runtime_target_s"] + delta
        play.setdefault("settings", {})["master_fps"] = rate       # the film masters at the title's own rate: "own"

    masters = {"dir": d, "burned": path}
    return A.titled_film(tmp_path / "film", masters, item=item, shot={"dur_s": title_s}, edit=edit)


@pytest.mark.parametrize("n, picture, rate", [
    (HOUSE_N, HOUSE_PICTURE, "24"),
    (NTSC_N, NTSC_PICTURE, "30000/1001"),
    (V11_N, V11_PICTURE, "24"),
], ids=["house-24", "house-ntsc", "v11-24"])
def test_a40_a_master_at_its_own_declared_length_passes_every_lint(tmp_path, film, n, picture, rate):
    """A 683-frame 24 fps master (the new house length), an 852-frame 30000/1001 one (its own native delivery) and
    the old 1018-frame v11 master (the live films' own, until re-released) each pass A40 end to end: the item's
    own declared frames and fps are what the plan, the format check and the lockup read, never a fixed assumption
    tied to one length."""
    film_dir = _build(tmp_path, film, n=n, picture=picture, rate=rate)
    plan, j = A.plan_of(film_dir)
    assert not isinstance(plan, Exception), plan
    for rule in A.RULES:
        assert A.passed(j, rule), (rule, A.lints(j, rule))
    s = next(x for x in plan["shots"] if x["id"] == "TS1")
    assert s["f1"] - s["f0"] == n
    lock = A.lints(j, "title-lockup")[0]
    assert lock["evidence"]["in_master"] is True and lock["evidence"]["card_min_s"] == pytest.approx(6.0, abs=0.05)


def test_house_slot_frames_is_683_at_24_fps_and_conforms_at_30000_1001():
    """Point 1 of the ruling: the one house default, used only with no item (A40 title slot has none)."""
    assert TS.HOUSE_SLOT_FRAMES == 683 and TS.HOUSE_SLOT_FPS == 24
    assert TS.house_slot_frames(24) == 683
    assert TS.house_slot_frames(30000 / 1001) == CAD.output_slot(682, 24, Fraction(30000, 1001)) + 1 == 853


def test_house_lockup_frames_is_144_at_24_fps_unchanged_and_180_at_30000_1001():
    assert TS.HOUSE_LOCKUP_FRAMES == 144
    assert TS.house_lockup_frames(24) == 144 and TS.house_lockup_frames(30000 / 1001) == 180


def test_slot_length_with_no_item_is_the_house_default_conformed():
    assert TS.slot_length(None, 24) == 683
    assert TS.slot_length(None, 30000 / 1001) == 853
    assert TS.slot_length({"record": "R"}, 24) == 683          # an item with no usable frames: the house default too


def test_slot_length_with_an_item_is_its_own_declared_frames_not_the_house_default():
    item = {"fps": 24, "frames": V11_N, "marks": [], "dip": {}}
    assert TS.slot_length(item, 24) == V11_N
    item2 = {"fps": "30000/1001", "frames": NTSC_N, "marks": [], "dip": {}}
    assert TS.slot_length(item2, 30000 / 1001) == NTSC_N
    # a 24 fps-only item conformed into a 29.97 film (A44, drop or repeat) still reads its own frames, not 683/852
    assert TS.slot_length({"fps": 24, "frames": V11_N}, 30000 / 1001) == CAD.output_slot(V11_N - 1, 24, Fraction(30000, 1001)) + 1


def test_slot_lockup_start_reads_the_items_own_dip_not_a_fixed_offset():
    tl, dip = _tl_dip(300, HOUSE_PICTURE)
    item = {"fps": 24, "frames": HOUSE_N, "marks": tl, "dip": dip}
    dip_end = round(dip["centre_frame"] + dip["s"] / 2 * 24)       # the dip's own end: its centre plus half its s
    assert TS.slot_lockup_start(item, 24) == dip_end
    assert TS.slot_length(item, 24) - TS.slot_lockup_start(item, 24) == HOUSE_N - dip_end
    # no item, or an item declaring no dip (A40 title slot): the house default's own split
    assert TS.slot_lockup_start(None, 24) == 683 - 144
    assert TS.slot_lockup_start({"record": "R"}, 24) == 683 - 144


# The real v11 ledger's own shape (C:/Users/aacri/document-work/title-sequence/masters-ledger.json, TS-v11-*):
# no ``dip`` key at all, only a CARD mark and a ``lockup_frame`` that is that span's own rough midpoint, not its
# start. Reviewer finding on PR #104: the helpers fell through to the house default for these real items, so
# every live film's lint shipped false evidence (lockup_card_min_s ~19.95 s instead of ~6.0 s).
V11_LEDGER_ITEM = {
    "frames": 1271, "fps": "30000/1001",
    "marks": [{"frame": 0, "cls": "DRAWN", "label": "Drawn · from period records"},
              {"frame": 878, "cls": "ARCHIVE", "label": "Archive · 1947"},
              {"frame": 1091, "cls": "CARD", "label": ""}],
    "lockup_frame": 1181,                   # (1091 + 1271) // 2: the CARD span's own midpoint, not its start
}


def test_slot_lockup_start_reads_the_real_ledgers_card_mark_with_no_dip_at_its_own_rate():
    """No ``dip``: the start is the last CARD mark (1091), not ``lockup_frame`` (1181, that span's own midpoint).
    Before the fix this fell through to the house default (slot_lockup_start 673, lockup_card_min_s ~19.95 s)."""
    r = Fraction(30000, 1001)
    assert TS.slot_lockup_start(V11_LEDGER_ITEM, r) == 1091
    assert TS.slot_length(V11_LEDGER_ITEM, r) == 1271
    assert TS.lockup_card_min_s(V11_LEDGER_ITEM, r) == pytest.approx(180 / float(r), abs=1e-6)   # 6.006 s, its own
    assert TS.lockup_card_min_s(V11_LEDGER_ITEM, r) == pytest.approx(6.0, abs=0.01)


def test_slot_lockup_start_reads_the_real_ledgers_card_mark_conformed_to_24_fps():
    """The same item, drop-conformed into a 24 fps film (A44): its own CARD mark's frame conformed (874 of 1018),
    not the house default's (539 of 683) and not its ``lockup_frame`` either."""
    assert TS.slot_length(V11_LEDGER_ITEM, 24) == 1018            # the live films' own v11 length, exactly
    assert TS.slot_lockup_start(V11_LEDGER_ITEM, 24) == 874
    assert TS.lockup_card_min_s(V11_LEDGER_ITEM, 24) == pytest.approx(6.0, abs=1e-6)


def test_lockup_card_min_s_is_derived_from_the_items_own_dip_not_the_old_title_json_4_625():
    # a one-frame dip (s small), so its own min dwell is (almost) exactly the house 6.0 s split used here
    tl, dip = _tl_dip(300, HOUSE_PICTURE)
    dip = dict(dip, s=1 / 24)
    item = {"fps": 24, "frames": HOUSE_N, "marks": tl, "dip": dip}
    assert TS.lockup_card_min_s(item, 24) == pytest.approx(144 / 24, abs=0.05)       # about 6.0 s, this master's own
    v11_tl, v11_dip = _tl_dip(300, V11_PICTURE)
    v11_dip = dict(v11_dip, s=1 / 24)
    v11_item = {"fps": 24, "frames": V11_N, "marks": v11_tl, "dip": v11_dip}
    assert TS.lockup_card_min_s(v11_item, 24) == pytest.approx(144 / 24, abs=0.05)   # the v11 master's own, also ~6.0 s
    # no item, or one without a dip (the old global 4.625 s no longer binds any master or the house default)
    assert TS.lockup_card_min_s(None, 24) == pytest.approx(6.0, abs=1e-9)
    assert TS.lockup_card_min_s({"record": "R"}, 24) != pytest.approx(4.625, abs=1e-6)
