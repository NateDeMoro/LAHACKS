import json

from backend.conditions import store as S
from backend.contracts import DraftedRule, DraftPick, Source
from backend.timeutil import now_la


def _rule():
    return DraftedRule(vocabulary="icd10cm", code="E05.90", canonical="Hyperthyroidism",
                       picks=[DraftPick(vital="hr", bound="high", menu_id="hr_high_mild")],
                       sources=[Source(kind="pmid", id="1001", title="t", year=2019, passage="p")],
                       evidence_label="strong", retrieved_ts=now_la(), evidence_hash="abc",
                       gates={"hr_high_mild.sources": True})


def test_rule_round_trips_frozen(tmp_path):
    path = tmp_path / "sub" / "store.json"  # parent dirs are created
    rule = _rule()
    S.put(path, "k", rule, {})
    hit = S.get(path, "k")
    assert hit.rule == rule and hit.failed == {}
    assert hit.rule.retrieved_ts.utcoffset() is not None


def test_abstention_round_trips_with_its_failed_gates(tmp_path):
    path = tmp_path / "store.json"
    S.put(path, "k", None, {"hr_high_mild": ["sources"]})
    hit = S.get(path, "k")
    assert hit.rule is None and hit.failed == {"hr_high_mild": ["sources"]}


def test_missing_file_and_missing_key_are_a_miss(tmp_path):
    assert S.get(tmp_path / "none.json", "k") is None
    S.put(tmp_path / "s.json", "other", None, {})
    assert S.get(tmp_path / "s.json", "k") is None


def test_corrupt_file_is_a_miss_not_an_error_and_put_recovers(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    assert S.get(path, "k") is None
    S.put(path, "k", None, {})
    assert S.get(path, "k") is not None


def test_non_dict_json_and_stale_entry_shape_are_misses(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("[1, 2]")
    assert S.get(path, "k") is None
    path.write_text(json.dumps({"k": {"rule": {"bogus_field": 1}, "failed": {}}}))
    assert S.get(path, "k") is None


def test_put_keeps_other_entries_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "s.json"
    S.put(path, "a", None, {})
    S.put(path, "b", _rule(), {})
    assert S.get(path, "a") is not None and S.get(path, "b") is not None
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


def test_key_changes_with_code_menu_version_prompt_version_and_model():
    base = S.key("E05", 1, "p1", "m1")
    assert S.key("E05", 1, "p1", "m1") == base
    assert len({base, S.key("E06", 1, "p1", "m1"), S.key("E05", 2, "p1", "m1"),
                S.key("E05", 1, "p2", "m1"), S.key("E05", 1, "p1", "m2")}) == 5
