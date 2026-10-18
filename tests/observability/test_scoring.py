import json

from backend.adjuster.testset import load_cases
from backend.config import LlmConfig
from scripts.score_adjuster import adjust_traced
from tests.observability.test_llm_spans import client


def test_each_scored_case_is_its_own_transaction_with_the_model_call_inside(sentry):
    case = load_cases("dev")[0]
    adjust_traced(case, LlmConfig(api_key="k"), client=client(json.dumps({"proposals": []})))
    txn = sentry.transactions("eval adjust")[0]
    assert txn["contexts"]["trace"]["data"]["eval.case"] == case.id
    assert any(a.get("llm.purpose") == "adjuster" for _, a in sentry.spans())
