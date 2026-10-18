"""PubMed client for the evidence step: esearch for ids, efetch for records. Use when a real condition has
no table rule and the model needs abstracts to read. The search term is the canonical condition name, never
the nurse's typed text. HTTP goes through an injected `fetch(url, timeout) -> str` so tests never hit the net."""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from backend.config import ConditionsConfig

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_BYTES = 5_000_000
VITAL_TERMS = ('"vital signs"[Title/Abstract] OR "heart rate"[Title/Abstract] OR "respiratory rate"[Title/Abstract] '
               'OR "oxygen saturation"[Title/Abstract] OR "body temperature"[Title/Abstract]')
# Non-breaking hyphens and spaces would stop a copied passage from matching the abstract
_CHARS = str.maketrans({"‐": "-", "‑": "-", " ": " "})

Fetch = Callable[[str, float], str]


class PubmedError(Exception):
    pass


@dataclass(frozen=True)
class Record:
    pmid: str
    title: str
    year: int | None
    abstract: str
    publication_types: tuple[str, ...]


def http_get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lahacks-prototype"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_BYTES).decode("utf-8")


def _get(fetch: Fetch, url: str, timeout: float) -> str:
    try:
        return fetch(url, timeout)
    except (OSError, ValueError) as e:  # URLError, timeouts and bad bytes; the type is enough to log
        raise PubmedError(f"PubMed request failed: {type(e).__name__}") from None


def build_term(canonical: str) -> str:
    name = re.sub(r'["\x00-\x1f\s]+', " ", canonical).strip()  # stay one quoted phrase
    return f'"{name}"[Title/Abstract] AND ({VITAL_TERMS})'


def search_pmids(canonical: str, cfg: ConditionsConfig, fetch: Fetch) -> list[str]:
    qs = urlencode({"db": "pubmed", "term": build_term(canonical), "retmax": cfg.max_abstracts,
                    "retmode": "json", "sort": "relevance", "tool": "lahacks"})
    text = _get(fetch, f"{EUTILS}/esearch.fcgi?{qs}", cfg.pubmed_timeout_s)
    try:
        ids = json.loads(text)["esearchresult"]["idlist"]
    except (ValueError, KeyError, TypeError):
        raise PubmedError("PubMed search reply was not the expected JSON") from None
    return [i for i in ids if isinstance(i, str) and i.isdigit()][:cfg.max_abstracts]


def _flat(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).translate(_CHARS).strip() if el is not None else ""


def _year(article: ET.Element) -> int | None:
    for path in ("Journal/JournalIssue/PubDate/Year", "Journal/JournalIssue/PubDate/MedlineDate",
                 "ArticleDate/Year"):
        m = re.search(r"\d{4}", article.findtext(path) or "")
        if m:
            return int(m.group())
    return None


def _abstract(article: ET.Element) -> str:
    parts = []
    for sec in article.findall("Abstract/AbstractText"):
        text, label = _flat(sec), sec.get("Label")
        if text:
            parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts)


def parse_records(xml: str) -> list[Record]:
    """Records with a PMID and an abstract; anything else cannot be cited."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise PubmedError("PubMed record reply was not valid XML") from None
    out = []
    for art in root.findall("PubmedArticle"):
        pmid = (art.findtext("MedlineCitation/PMID") or "").strip()
        article = art.find("MedlineCitation/Article")
        if not pmid or article is None or not _abstract(article):
            continue
        types = tuple(_flat(t) for t in article.findall("PublicationTypeList/PublicationType"))
        out.append(Record(pmid, _flat(article.find("ArticleTitle")), _year(article), _abstract(article), types))
    return out


def fetch_records(canonical: str, *, cfg: ConditionsConfig, fetch: Fetch | None = None) -> list[Record]:
    """Up to cfg.max_abstracts records for the condition. Raises PubmedError on any transport or format failure."""
    fetch = fetch or http_get
    ids = search_pmids(canonical, cfg, fetch)
    if not ids:
        return []
    qs = urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "tool": "lahacks"})
    return parse_records(_get(fetch, f"{EUTILS}/efetch.fcgi?{qs}", cfg.pubmed_timeout_s))
