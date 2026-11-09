"""placeholder-media (GRAMMAR 11.1): a ledger item that says it is a placeholder (``placeholder: true``, or a
``generator`` that begins "PLACEHOLDER") stands in for media not made yet, such as a grey slate for a table render or
a typeset page. A final render refuses any shot or heard line that cites one, naming every shot and item, at plan
time. A draft (--draft), a check render (--shots, --until, --audio-only) and the contact sheets keep it as a warning,
and a draft master's own record (its journal and sources.json) says it holds placeholders. A synthetic item that is
not a placeholder (a DRAWN map or typeset page made by a program) is unaffected."""
import json
import shutil
from pathlib import Path

import pytest

from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import sheets as SH

from conftest import HEIGHT, WORKERS

STANDIN = {"what": "a grey slate", "for": "the typeset page, drawn by the drawn-pages unit"}


def _mark(film: Path, ids: list[str], **fields) -> None:
    """Mark these items of the fixture's stills ledger as placeholders, as the Panama pilot's are."""
    p = film / "stills-ledger.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for it in d["items"]:
        if it["id"] in ids:
            it.update(fields or {"placeholder": True, "synthetic": True, "standin": STANDIN,
                                 "generator": "PLACEHOLDER: a DRAWN plate typesetting the cited page; nothing here is "
                                              "drawn yet"})
    p.write_text(json.dumps(d), encoding="utf-8")


def _copy(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("out", "cache"))
    return dest


@pytest.fixture
def one(film_safe, tmp_path):
    """The fixture with one placeholder: S4's still FX-STILL-B."""
    f = _copy(film_safe, tmp_path / "fixture")
    _mark(f, ["FX-STILL-B"])
    return f


def _plan(film, name, **kw):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j, **kw), j


def _lints(path, rule="placeholder-media"):
    return [e for e in J.read(path) if e.get("rule") == rule]


# --------------------------------------------------------------------------
# Which items are placeholders (pure)
# --------------------------------------------------------------------------


def test_is_placeholder_reads_the_flag_or_a_placeholder_generator():
    assert R.is_placeholder({"placeholder": True})
    assert R.is_placeholder({"synthetic": True, "generator": "PLACEHOLDER: a slate"})
    assert R.is_placeholder({"generator": "  placeholder: lower case still counts"})
    # a legitimate DRAWN map or typeset page is synthetic and has a generator, and is not a placeholder
    assert not R.is_placeholder({"synthetic": True, "generator": "studio/engine/maps.py, Natural Earth 1:10m"})
    assert not R.is_placeholder({"synthetic": True, "placeholder": False})
    assert not R.is_placeholder(None) and not R.is_placeholder({})
    # a standin block is a placeholder whatever the flag says (the stricter reading: a stand-in is never final)
    assert R.is_placeholder({"synthetic": True, "standin": STANDIN})
    assert R.is_placeholder({"placeholder": False, "standin": STANDIN})
    assert R.placeholder_why({"standin": STANDIN}).startswith("standin: ")
    assert not R.is_placeholder({"synthetic": True, "standin": None})


def test_a_series_titles_placeholder_record_is_named_where_it_is_burned_in():
    """A40: a title_sequence item's ``record`` is burned into the title master; a placeholder record is named on the
    title shot, as ``title-record``, beside a placeholder title master itself."""
    play = {"parts": [{"id": "series", "shots": [{"id": "TS1", "kind": "title_sequence", "asset": "TS-test"},
                                                 {"id": "S2", "kind": "archive_still", "asset": "REC"}]}]}
    assets = {"TS-test": {"record": "REC"}, "REC": {"placeholder": True}}
    assert R.placeholder_media(play, assets) == [
        {"unit": "TS1", "where": "title-record", "asset": "REC", "why": "placeholder: true"},
        {"unit": "S2", "where": "shot", "asset": "REC", "why": "placeholder: true"}]
    assets = {"TS-test": {"record": "REC", "standin": STANDIN}, "REC": {}}
    assert [x["where"] for x in R.placeholder_media(play, assets)] == ["shot"]
    # a record on a shot that is not a title is not read as one
    play["parts"][0]["shots"][0]["kind"] = "archive_still"
    assert R.placeholder_media(play, {"TS-test": {"record": "REC"}, "REC": {"placeholder": True}}) == [
        {"unit": "S2", "where": "shot", "asset": "REC", "why": "placeholder: true"}]


# --------------------------------------------------------------------------
# A final plan refuses; a draft, a check render and sheets warn
# --------------------------------------------------------------------------


def test_a_final_plan_refuses_a_placeholder_shot_naming_the_shot_and_the_item(one):
    with pytest.raises(R.Refused, match=r"placeholder-media.*S4.*FX-STILL-B"):
        _plan(one, "ph-final")


def test_the_refusal_lists_every_placeholder_shot_and_item(film_safe, tmp_path):
    f = _copy(film_safe, tmp_path / "fixture")
    _mark(f, ["FX-STILL-A", "FX-STILL-C"])
    j = J.Journal(film="ph-two")
    with pytest.raises(R.Refused) as e:
        R.build_plan(f, W=640, H=360, burn_subtitles=False, journal=j)
    assert "S3" in str(e.value) and "S5" in str(e.value) and "FX-STILL-A" in str(e.value) and "FX-STILL-C" in str(e.value)
    (ev,) = _lints(j.path)
    assert ev["status"] == "fail" and ev["severity"] == "block" and ev["grammar"] == "11.1"
    assert ev["phase"] == "preflight"
    assert ev["evidence"]["placeholder_media"] == [
        {"unit": "S3", "where": "shot", "asset": "FX-STILL-A", "why": "placeholder: true"},
        {"unit": "S5", "where": "shot", "asset": "FX-STILL-C", "why": "placeholder: true"}]
    assert ev["evidence"]["shots"] == ["S3", "S5"] and ev["evidence"]["items"] == ["FX-STILL-A", "FX-STILL-C"]


def test_a_final_render_refuses_before_any_frame(one, tmp_path):
    out = tmp_path / "out"
    j = J.Journal(film="ph-final-render", out_dir=out)
    with pytest.raises(R.Refused, match=r"placeholder-media.*S4.*FX-STILL-B"):
        R.render(one, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", journal=j)
    assert not (out / "master.mp4").exists() and not (out / "sources.json").exists()
    evs = J.read(j.path)
    assert not [e for e in evs if e.get("stage") in ("motion", "assembly") and e["kind"] == "stage"]
    assert evs[-1]["lens"] == "run.end" and evs[-1]["outcome"] == "refused" and "placeholder-media" in evs[-1]["message"]


def test_a_draft_plan_warns_and_carries_the_placeholders(one):
    plan, j = _plan(one, "ph-draft", draft=True)
    (ev,) = _lints(j.path)
    assert ev["status"] == "fail" and ev["severity"] == "warn"
    assert plan["placeholder_media"] == [{"unit": "S4", "where": "shot", "asset": "FX-STILL-B", "why": "placeholder: true"}]
    doc = R.sources_doc(plan, j, {"draft": True})
    assert doc["placeholder_media"] == plan["placeholder_media"]
    assert {s["id"]: s["placeholder"] for s in doc["shots"] if s["ledger_id"]} == {
        "S3": False, "S4": True, "S5": False, "S6": False}


def test_a_check_plan_warns(one):
    plan, j = _plan(one, "ph-check", check=True)
    (ev,) = _lints(j.path)
    assert ev["severity"] == "warn" and plan["placeholder_media"][0]["unit"] == "S4"


def test_a_placeholder_clip_is_named_as_a_still_is(film_safe, tmp_path):
    f = _copy(film_safe, tmp_path / "fixture")
    p = f / "footage-ledger.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for it in d["items"]:
        if it["id"] == "FX-TESTSRC":
            it["placeholder"] = True
    p.write_text(json.dumps(d), encoding="utf-8")
    plan, j = _plan(f, "ph-clip", draft=True)
    assert [(x["where"], x["unit"], x["asset"]) for x in plan["placeholder_media"]] == [("shot", "S6", "FX-TESTSRC")]


def test_the_contact_sheets_proceed_and_say_so(one, tmp_path):
    j = J.Journal(film="ph-sheets", kind="sheets")
    r = SH.build_sheets(one, out_dir=tmp_path / "sheets", journal=j, skip_sound_lints=True)
    assert r["sheets"]
    (ev,) = _lints(j.path)
    assert ev["severity"] == "warn" and ev["evidence"]["shots"] == ["S4"]


def test_a_synthetic_item_that_is_no_placeholder_is_unaffected(film_safe):
    """Every fixture still is synthetic with a generator (a DRAWN test image): the lint passes and nothing is listed."""
    plan, j = _plan(film_safe, "ph-none")
    (ev,) = _lints(j.path)
    assert ev["status"] == "pass" and ev["severity"] == "block"
    assert plan["placeholder_media"] == []
    doc = R.sources_doc(plan, j, {})
    assert doc["placeholder_media"] == [] and not any(s["placeholder"] for s in doc["shots"])
    assert {s["mark"]["class"] for s in doc["shots"] if s["ledger_id"] in ("FX-STILL-A", "FX-STILL-B")} == {"DRAWN"}


@pytest.fixture(scope="module")
def title_master(film, tmp_path_factory):
    """A40's synthetic burned title master (test_a40_title_sequence.make_master): an encode, no film render."""
    import test_a40_title_sequence as A
    d = tmp_path_factory.mktemp("ph-masters")
    return {"dir": d, "burned": A.make_master(d / "burned.mkv", film / "stills" / "FX-STILL-B.png")}


def test_a_fixture_title_with_a_placeholder_record_refuses_a_final_plan(title_master, tmp_path):
    import test_a40_title_sequence as A
    f = A.titled_film(tmp_path, title_master)
    _mark(f, ["FX-REC"], placeholder=True)
    with pytest.raises(R.Refused, match=r"placeholder-media.*TS1.*title-record.*FX-REC"):
        _plan(f, "ph-title")
    j = J.Journal(film="ph-title-draft")
    try:
        R.build_plan(f, W=640, H=360, burn_subtitles=False, journal=j, draft=True)
    except R.Refused as e:                 # a later A40 check may refuse the test record; this lint warned first
        assert "placeholder-media" not in str(e)
    (ev,) = _lints(j.path)
    assert ev["severity"] == "warn" and ev["evidence"]["shots"] == ["TS1"] and ev["evidence"]["items"] == ["FX-REC"]


def test_publish_refuses_a_placeholder_poster(tmp_path):
    from studio.engine import publish as P
    ledger = tmp_path / "stills-ledger.json"
    still = {"id": "S-020", "title": "A still", "licence": "Public domain", "shows_bodies": False}
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"jpg")
    for extra in ({"placeholder": True}, {"standin": STANDIN}, {"generator": "PLACEHOLDER: a grey slate"}):
        ledger.write_text(json.dumps({"items": [dict(still, **extra)]}), encoding="utf-8")
        with pytest.raises(R.Refused, match=r"S-020 is a placeholder .*never the poster"):
            P.poster_record(ledger, "S-020", poster)
    ledger.write_text(json.dumps({"items": [dict(still, synthetic=True, generator="studio/engine/maps.py")]}), encoding="utf-8")
    assert P.poster_record(ledger, "S-020", poster)["ledger_id"] == "S-020"     # a DRAWN still is no placeholder


def test_a_final_render_from_a_shot_refuses_a_placeholder_before_any_frame(one, tmp_path):
    out = tmp_path / "out"
    j = J.Journal(film="ph-from", out_dir=out)
    with pytest.raises(R.Refused, match=r"placeholder-media.*S4.*FX-STILL-B"):
        R.render(one, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", from_shot="S5",
                 journal=j)
    assert not [e for e in J.read(j.path) if e.get("stage") == "motion" and e["kind"] == "stage"]


# --------------------------------------------------------------------------
# Rendered: a draft master records its placeholders; a --shots span proceeds
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ph_film(film_safe, tmp_path_factory):
    f = _copy(film_safe, tmp_path_factory.mktemp("ph") / "fixture")
    _mark(f, ["FX-STILL-B"])
    return f


@pytest.fixture(scope="module")
def drafted(ph_film, tmp_path_factory):
    out = tmp_path_factory.mktemp("ph-out")
    s = R.render(ph_film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", draft=True)
    return {"summary": s, "out": out}


def test_a_draft_render_proceeds_and_its_record_says_it_holds_placeholders(drafted):
    s, out = drafted["summary"], drafted["out"]
    assert (out / "master.mp4").exists()
    doc = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert doc["draft"] is True
    assert doc["placeholder_media"] == [{"unit": "S4", "where": "shot", "asset": "FX-STILL-B", "why": "placeholder: true"}]
    assert next(x for x in doc["shots"] if x["id"] == "S4")["placeholder"] is True
    assert R.master_was_draft(out) is True
    evs = J.read(s["journal"])
    (ev,) = [e for e in evs if e.get("rule") == "placeholder-media"]
    assert ev["severity"] == "warn" and ev["status"] == "fail"
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--draft"
            and "placeholder" in e["what"] and "S4" in e["what"]]
    end = evs[-1]
    assert end["lens"] == "run.end" and end["outcome"] == "ok" and end["placeholder_media"] == doc["placeholder_media"]
    assert s["placeholder_media"] == doc["placeholder_media"]


def test_sources_only_keeps_a_draft_masters_placeholders_on_record(drafted, ph_film):
    out = drafted["out"]
    R.sources_only(ph_film, out)
    doc = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert doc["draft"] is True and [x["unit"] for x in doc["placeholder_media"]] == ["S4"]


def test_sources_only_refuses_a_placeholder_under_a_final_master(film_safe, rendered, tmp_path):
    """A master recorded as final whose ledger now cites a placeholder: --sources-only (release step a) refuses."""
    f = _copy(film_safe, tmp_path / "fixture")
    _mark(f, ["FX-STILL-B"])
    out = tmp_path / "out"
    out.mkdir()
    for name in ("master.mp4", "sources.json"):
        shutil.copy2(rendered["out"] / name, out / name)
    assert R.master_was_draft(out) is False
    with pytest.raises(R.Refused, match=r"placeholder-media.*S4.*FX-STILL-B"):
        R.sources_only(f, out)


def test_a_shots_check_render_proceeds_with_a_placeholder(ph_film, tmp_path):
    out = tmp_path / "out"
    s = R.render(ph_film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", shots="S4..S4")
    assert Path(s["master"]) == out / "master.shots-S4-S4.mp4" and Path(s["master"]).exists()
    assert s["sources"] is None and s["placeholder_media"][0]["unit"] == "S4"
    evs = J.read(s["journal"])
    (ev,) = [e for e in evs if e.get("rule") == "placeholder-media"]
    assert ev["severity"] == "warn"
    assert evs[-1]["outcome"] == "ok"


def test_an_until_check_render_proceeds_and_its_partial_sources_file_lists_the_placeholder(ph_film, plan, tmp_path):
    s4 = next(s for s in plan["shots"] if s["id"] == "S4")
    until = round(s4["f1"] / plan["fps"], 3)            # S4 starts before it, so it is rendered
    out = tmp_path / "out"
    s = R.render(ph_film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast", until_s=until)
    assert s["partial"] is True and Path(s["sources"]) == out / f"sources.check-{until:g}s.json"
    doc = json.loads(Path(s["sources"]).read_text(encoding="utf-8"))
    assert doc["partial"] is True and doc["draft"] is False
    assert doc["placeholder_media"] == [{"unit": "S4", "where": "shot", "asset": "FX-STILL-B", "why": "placeholder: true"}]
    assert not (out / "sources.json").exists() and not (out / "master.mp4").exists()
    evs = J.read(s["journal"])
    (ev,) = [e for e in evs if e.get("rule") == "placeholder-media"]
    assert ev["severity"] == "warn"
    assert [e for e in evs if e["kind"] == "human" and e.get("override") == "--until" and "partial sources file" in e["what"]]


def test_sources_only_refuses_a_master_whose_draft_status_cannot_be_read(film_safe, tmp_path):
    """Review of #103: an old sources.json with no draft field, whose run has no journal, once became draft: false (a
    guess written as final). It is refused, naming --draft, and the file is left as it was."""
    import subprocess
    out = tmp_path / "out"
    out.mkdir()
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=24", "-frames:v", "1",
                    str(out / "master.mp4")], check=True)
    old = {"v": 2, "slug": "fixture", "run": "r-20260101-gone"}     # before the draft field; its journal is gone
    (out / "sources.json").write_text(json.dumps(old), encoding="utf-8")
    assert R.master_was_draft(out) is None
    with pytest.raises(R.Refused, match=r"cannot tell whether this master was rendered with --draft.*--sources-only --draft"):
        R.sources_only(film_safe, out)
    assert json.loads((out / "sources.json").read_text(encoding="utf-8")) == old
