"""Series titles: the credit by kind (founder ruling 18, 2026-11-07) and the sources record of a series title."""

from studio.engine import render as R
from studio.engine import titles as TS


def _items(rec, scans, tex, lic="CC0"):
    return ([{"id": f"R{i}", "licence": "public domain", "credit_kind": "period record"} for i in range(rec)]
            + [{"id": f"S{i}", "licence": lic, "credit_kind": "museum-object scan"} for i in range(scans)]
            + [{"id": f"T{i}", "licence": "CC0 1.0", "credit_kind": "studio texture"} for i in range(tex)])


def test_ruling_18_the_founders_wording():
    assert TS.credit_by_kind(_items(14, 6, 4)) == ("drawn from 14 period records, with six museum-object scans and "
                                                   "four studio textures (CC0), no AI")


def test_credit_by_kind_singulars_cc_by_and_records_only():
    assert TS.credit_by_kind(_items(1, 1, 0)) == "drawn from one period record, with one museum-object scan (CC0), no AI"
    assert TS.credit_by_kind(_items(3, 2, 1, lic="CC BY 4.0")) == ("drawn from three period records, with two "
                                                                    "museum-object scans and one studio texture, no AI")
    assert TS.credit_by_kind(_items(21, 0, 0)) == "drawn from 21 period records, no AI"
    # no period record: the records clause is dropped
    assert TS.credit_by_kind(_items(0, 6, 4)) == "drawn from six museum-object scans and four studio textures (CC0), no AI"


def test_credit_kind_must_be_stated_and_spelled_right():
    import pytest
    typo = [{"id": "T-05", "licence": "CC0", "credit_kind": "museum object scan"}]
    missing = [{"id": "T-10", "licence": "CC0"}]
    assert "T-05: credit_kind 'museum object scan' is not one of" in TS.credit_kind_problem(typo[0])
    assert TS.credit_kind_problem(missing[0]).startswith("T-10: no credit_kind")
    with pytest.raises(ValueError, match="T-05"):
        TS.credit_by_kind(typo)
    with pytest.raises(ValueError, match="T-10"):
        TS.credit_by_kind(missing)


def test_a_series_title_is_not_a_test_fixture_on_the_sources_page():
    title = {"kind": TS.KIND}
    made = {"generator": "Blender Cycles (scene_title_v11.py)", "ai": False}
    assert R.is_synthetic(made)                                       # a studio-made master has a generator ...
    assert R.sources_test_fixture(title, made) is False               # ... but the title is no test stand-in
    assert R.sources_test_fixture(title, dict(made, test_fixture=True)) is True
    assert R.sources_test_fixture(title, dict(made, synthetic=True)) is True
    assert R.sources_test_fixture({"kind": "still"}, made) is True     # other shots: unchanged (is_synthetic)
