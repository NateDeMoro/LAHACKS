import pytest
from pydantic import ValidationError

from backend import contracts as C


def test_custom_conditions_is_a_list_of_text_on_i2():
    rec = C.IntakeRecord(custom_conditions=["sickle cell disease"])
    assert rec.custom_conditions == ["sickle cell disease"]
    assert C.IntakeRecord().custom_conditions is None


def test_adjustment_tier_defaults_to_null_meaning_danger_and_accepts_warning():
    assert C.Adjustment(vital="hr", bound="high", value=85).tier is None
    assert C.Adjustment(vital="hr", bound="high", value=85, tier="warning").tier == "warning"
    with pytest.raises(ValidationError):
        C.Adjustment(tier="critical")


def test_evidence_item_carries_sources_and_unreviewed():
    src = C.Source(kind="pmid", id="123", title="T", year=2020, passage="p")
    item = C.EvidenceItem(rule_id="draft:D57", fact="f", sources=[src], unreviewed=True)
    assert item.sources[0].id == "123" and item.unreviewed is True


def test_source_kind_is_closed():
    with pytest.raises(ValidationError):
        C.Source(kind="blog", id="1")
    for k in ("pmid", "pmc", "doi", "guideline_url"):
        assert C.Source(kind=k, id="1").kind == k


def test_condition_resolution_i16_statuses_are_closed():
    ok = C.ResolvedCondition(typed="sugar diabetes", status="checklist", checklist="diabetes")
    assert C.ConditionResolution(patient_id="p", items=[ok]).items[0].checklist == "diabetes"
    with pytest.raises(ValidationError):
        C.ResolvedCondition(status="maybe")
    with pytest.raises(ValidationError):
        C.ResolvedCondition(status="checklist", checklist="gout")


def test_drafted_rule_i17_has_picks_not_values():
    pick = C.DraftPick(vital="hr", bound="high", menu_id="hr_high_mild")
    rule = C.DraftedRule(code="D57", picks=[pick], evidence_label="medium", gates={"passage_in_abstract": True})
    assert rule.picks[0].menu_id == "hr_high_mild"
    assert "value" not in C.DraftPick.model_fields  # the model never writes a number
    with pytest.raises(ValidationError):
        C.DraftPick(vital="hr", bound="high", menu_id="x", value=85)


def test_i16_and_i17_are_registered_for_schema_export():
    assert C.INTERFACES["I16"] is C.ConditionResolution
    assert C.INTERFACES["I17"] is C.DraftedRule
