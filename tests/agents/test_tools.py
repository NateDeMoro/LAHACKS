"""Coordinator tools against a fake backend: the intake starts on a free wearable with no invented fields,
and the card summary says what was understood, what changed and from which sources."""
import asyncio

from agent import tools

CARD = {
    "adjuster": "done",
    "conditions": {"state": "done", "suggestions": [{"code": "I26.9", "reason": "not allowed"}], "infra_errors": [],
                   "resolution": {"items": [
                       {"typed": "sepsis", "status": "found", "canonical": "Sepsis", "code": "A41.9", "checklist": None},
                       {"typed": "blorptic", "status": "not_found", "canonical": None, "code": None, "checklist": None}]}},
    "i15_items": [
        {"rule_id": "suspected_infection", "fact": "fever", "quote": "fever and chills", "unreviewed": None},
        {"rule_id": "draft:A41.9", "fact": "Sepsis: resp_rate high (resp_rate_high_mild)", "quote": None, "unreviewed": True,
         "sources": [{"id": "111", "title": "Sepsis study", "year": 2020, "passage": "x"}]}],
    "ranges": {"hr": {"safe_low": 51, "safe_high": 90, "danger_low": 40, "danger_high": 131, "source": "population"},
               "resp_rate": {"safe_low": 12, "safe_high": 18, "danger_low": 8, "danger_high": 22}, "sbp": {"safe_low": 1}},
}


def test_summary_separates_table_rules_from_unreviewed_drafts():
    s = tools.summarize_card(CARD)
    assert [r["rule"] for r in s["table_rules"]] == ["suspected_infection"]
    assert s["drafted_limits_unreviewed"] == [{"rule": "draft:A41.9", "fact": "Sepsis: resp_rate high (resp_rate_high_mild)",
                                               "sources": [{"pmid": "111", "title": "Sepsis study", "year": 2020}]}]
    assert [c["status"] for c in s["conditions"]] == ["found", "not_found"]
    assert s["limits"]["resp_rate"]["safe_high"] == 18 and "sbp" not in s["limits"]


def test_submit_picks_the_lowest_free_wearable_and_sends_only_what_was_given(monkeypatch):
    sent = {}

    async def get(path):
        return [{"wearable_id": 1, "patient_id": "taken"}, {"wearable_id": 103, "patient_id": None},
                {"wearable_id": 102, "patient_id": None}]

    async def post(path, body):
        sent.update(path=path, body=body)
        return {"patient_id": "pt-1"}

    monkeypatch.setattr(tools, "_get", get)
    monkeypatch.setattr(tools, "_post", post)
    out = asyncio.run(tools.submit_intake(67, "male", conditions=["sepsis"]))
    assert sent["path"] == "/intake" and sent["body"] == {"wearable_id": 102, "age": 67, "sex": "male",
                                                           "custom_conditions": ["sepsis"]}
    assert out["patient_id"] == "pt-1"


def test_submit_reports_when_no_wearable_is_free(monkeypatch):
    async def get(path):
        return [{"wearable_id": 1, "patient_id": "taken"}]
    monkeypatch.setattr(tools, "_get", get)
    assert "error" in asyncio.run(tools.submit_intake(67, "male"))


def test_check_waits_for_pending_work_and_stops_at_the_limit(monkeypatch):
    pending = {**CARD, "conditions": {**CARD["conditions"], "state": "pending"}}
    cards = [pending, pending, CARD]

    async def get(path):
        return cards.pop(0) if len(cards) > 1 else cards[0]

    async def no_sleep(_s):
        pass

    monkeypatch.setattr(tools, "_get", get)
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)
    assert asyncio.run(tools.check_intake("pt-1"))["finished"] is True
    cards[:] = [pending]
    assert asyncio.run(tools.check_intake("pt-1", wait_s=0))["finished"] is False
