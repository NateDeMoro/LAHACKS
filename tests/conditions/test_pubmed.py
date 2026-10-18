import json
from pathlib import Path

import pytest

from backend.conditions import pubmed as P
from backend.config import ConditionsConfig

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "conditions"
HYPER = (FIX / "pubmed_hyperthyroid.xml").read_text()
RECORDED = (FIX / "pubmed_recorded.xml").read_text()


def test_parses_hand_written_records_and_skips_one_without_an_abstract():
    recs = P.parse_records(HYPER)
    assert [r.pmid for r in recs] == ["1001", "1002", "1003"]  # 1004 has no abstract: nothing to cite
    r = recs[0]
    assert r.title.startswith("Resting heart rate in hyperthyroidism")
    assert r.year == 2019
    assert r.publication_types == ("Journal Article", "Systematic Review")
    assert "RESULTS: Resting heart rate was higher" in r.abstract  # section labels kept, sections joined


def test_year_falls_back_to_medline_date_and_inline_tags_are_flattened():
    r = P.parse_records(HYPER)[1]
    assert r.year == 2015
    assert r.title == "Untreated hyperthyroidism and pulse rate: a randomized trial."


def test_parses_a_real_recorded_efetch_response():
    recs = P.parse_records(RECORDED)
    assert recs[0].pmid == "42828611" and recs[0].year == 2026
    assert "Journal Article" in recs[0].publication_types
    assert "vital signs at examination" in recs[0].abstract
    assert "‑" not in recs[0].abstract  # non-breaking hyphens become "-" so quotes can match


def test_malformed_xml_is_a_pubmed_error():
    with pytest.raises(P.PubmedError):
        P.parse_records("<PubmedArticleSet><oops")


def _fake(urls, esearch_ids=("1001", "1002")):
    def fetch(url, timeout):
        urls.append((url, timeout))
        if "esearch" in url:
            return json.dumps({"esearchresult": {"idlist": list(esearch_ids)}})
        return HYPER
    return fetch


def test_search_then_fetch_uses_canonical_name_and_the_configured_timeout():
    urls = []
    cfg = ConditionsConfig(max_abstracts=5, pubmed_timeout_s=3.0)
    recs = P.fetch_records("Hyperthyroidism", cfg=cfg, fetch=_fake(urls))
    assert [r.pmid for r in recs] == ["1001", "1002", "1003"]
    search, fetch = urls[0][0], urls[1][0]
    assert "esearch" in search and "Hyperthyroidism" in search and "retmax=5" in search
    assert "vital+signs" in search or "vital%20signs" in search
    assert "efetch" in fetch and "id=1001%2C1002" in fetch.replace(",", "%2C")
    assert all(t == 3.0 for _, t in urls)


def test_quotes_in_the_condition_name_cannot_break_out_of_the_query():
    urls = []
    P.fetch_records('asthma" OR "x', cfg=ConditionsConfig(), fetch=_fake(urls))
    from urllib.parse import parse_qs, urlparse
    term = parse_qs(urlparse(urls[0][0]).query)["term"][0]
    assert term.startswith('"asthma OR x"[Title/Abstract] AND ')  # stays one quoted phrase


def test_no_search_hits_means_no_records_and_no_efetch_call():
    urls = []
    assert P.fetch_records("nothing", cfg=ConditionsConfig(), fetch=_fake(urls, esearch_ids=())) == []
    assert len(urls) == 1


def test_non_numeric_ids_from_search_are_ignored():
    urls = []
    P.fetch_records("x", cfg=ConditionsConfig(), fetch=_fake(urls, esearch_ids=("1001", "../etc", "1002")))
    assert "id=1001%2C1002&" in urls[1][0]


@pytest.mark.parametrize("exc", [OSError("down"), TimeoutError(), ValueError("bad")])
def test_transport_failures_become_pubmed_error(exc):
    def fetch(url, timeout):
        raise exc
    with pytest.raises(P.PubmedError):
        P.fetch_records("x", cfg=ConditionsConfig(), fetch=fetch)


def test_bad_esearch_json_is_a_pubmed_error():
    with pytest.raises(P.PubmedError):
        P.fetch_records("x", cfg=ConditionsConfig(), fetch=lambda u, t: "not json")
