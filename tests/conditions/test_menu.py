import json

import pytest

from backend.conditions import menu as M
from backend.contracts import LimitMenu, MenuEntry
from backend.risk_engine import ranges


def _menu(*entries):
    return LimitMenu(version=1, entries=list(entries))


def _e(**kw):
    base = dict(id="x", vital="hr", bound="high", kind="relative", amount=5, label="mild", source="design constant")
    return MenuEntry(**{**base, **kw})


def test_shipped_menu_loads_with_unique_ids_and_a_version():
    m = M.load_menu()
    ids = [e.id for e in m.entries]
    assert m.version >= 1 and len(ids) == len(set(ids)) > 0


def test_every_shipped_entry_actually_tightens_the_default_news2_band():
    """The reviewer's no-op finding: a menu value outside the safe band does nothing. Pin that none do."""
    m = M.load_menu()
    for e in m.entries:
        lo, hi = ranges.SCORE0[e.vital]
        edge = M.target_edge(e, lo, hi)
        assert edge is not None, e.id
        assert (edge < hi) if e.bound == "high" else (edge > lo), e.id


def test_every_shipped_entry_bites_for_real_patient_profiles():
    """Fitted bands are narrower than score-0 (a 50-year-old's temp ceiling is 37.3), so check real profiles.
    Pinned finding: an absolute 37.8 C entry would be a no-op for every profile, so the menu does not carry one."""
    from backend.contracts import PatientContext
    m = M.load_menu()
    for age in (20, 35, 50, 65, 85):
        for sex in ("male", "female"):
            band = ranges.build_population_ranges(PatientContext(patient_id="p", age=age, sex=sex, height_cm=170, weight_kg=70))
            for e in m.entries:
                rng = getattr(band, e.vital)
                edge = M.target_edge(e, rng.safe_low, rng.safe_high)
                if (e.id, age) == ("temp_c_high_strong", 85):  # 36.1-37.2 minus 0.6 leaves 0.5, under the 0.6 minimum
                    assert edge is None
                else:
                    assert edge is not None, (e.id, age, sex)


def test_shipped_absolute_values_sit_inside_score0():
    for e in M.load_menu().entries:
        if e.kind == "absolute":
            lo, hi = ranges.SCORE0[e.vital]
            assert lo < e.amount < hi, e.id


def test_shipped_menu_never_offers_sbp_which_is_not_graded():
    assert all(e.vital != "sbp" for e in M.load_menu().entries)


def test_relative_high_and_low_steps():
    assert M.target_edge(_e(amount=5), 51, 90) == 85
    assert M.target_edge(_e(bound="low", amount=5), 51, 90) == 56


def test_absolute_value_is_used_as_is_when_inside_the_band():
    assert M.target_edge(_e(vital="temp_c", kind="absolute", amount=37.8), 36.1, 38.0) == 37.8


def test_no_op_when_the_edge_would_not_tighten():
    assert M.target_edge(_e(vital="temp_c", kind="absolute", amount=38.3), 36.1, 38.0) is None
    assert M.target_edge(_e(vital="temp_c", kind="absolute", amount=37.8), 36.1, 37.5) is None


def test_no_op_when_the_band_would_get_too_narrow():
    assert M.target_edge(_e(amount=30), 51, 90) is None  # 51-60 is under the hr minimum width
    assert M.target_edge(_e(vital="resp_rate", amount=5), 12, 20) is None  # 12-15 is under the rr minimum


def test_edge_is_rounded_to_one_decimal():
    assert M.target_edge(_e(vital="temp_c", amount=0.3), 36.1, 38.0) == 37.7


def test_loader_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(_menu(_e(id="a"), _e(id="a")).model_dump_json())
    with pytest.raises(ValueError, match="duplicate"):
        M.load_menu(p)


def test_loader_rejects_absolute_value_outside_score0(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(_menu(_e(id="t", vital="temp_c", kind="absolute", amount=38.3)).model_dump_json())
    with pytest.raises(ValueError, match="score-0"):
        M.load_menu(p)


def test_loader_rejects_non_positive_relative_amount(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"version": 1, "entries": [_e(id="z", amount=0).model_dump()]}))
    with pytest.raises(ValueError, match="amount"):
        M.load_menu(p)


def test_only_allowed_vitals_are_offered():
    m = M.load_menu()
    assert {e.id for e in M.allowed(m, ("temp_c",))} <= {e.id for e in m.entries if e.vital == "temp_c"}
    assert M.allowed(m, ()) == []
