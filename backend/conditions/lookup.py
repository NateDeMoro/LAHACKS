"""Vocabulary lookup for typed conditions (I16). Typed text is untrusted: it is only a search string sent to
NLM Clinical Tables and echoed back in `typed`. Nothing here reads it as an instruction, and no model is involved.
Synchronous; the caller runs it in a thread."""
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Callable, NamedTuple

from backend.config import CONFIG, ConditionsConfig
from backend.contracts import Candidate, ResolvedCondition

NLM_URL = "https://clinicaltables.nlm.nih.gov/api/conditions/v3/search"
VOCABULARY = "nlm_conditions"
MAX_TERMS = 5
MAX_CHARS = 80
MAX_LIST = 50  # results are not ranked by closeness, so ask for plenty and score them here
MAX_CANDIDATES = 5
AMBIGUOUS_GAP = 0.05
MAX_BYTES = 2_000_000

Fetch = Callable[[str, float], object]

# ICD-10-CM categories (inclusive range) to the intake checklist flag. D10-D36 are benign, so not cancer.
CHECKLIST_RANGES = [
    ("I10", "I16", "hypertension"), ("J45", "J45", "asthma"),
    ("C00", "C96", "cancer"), ("D00", "D09", "cancer"),
    ("E08", "E13", "diabetes"), ("E00", "E07", "thyroid"),
    ("J41", "J44", "copd"), ("K70", "K77", "liver"),
    ("I20", "I25", "heart_disease"), ("I60", "I69", "stroke"), ("I50", "I50", "heart_failure"),
]

# Typed words that mean a checklist item; checked before the network so they work offline.
SYNONYMS = {
    "hypertension": ["hypertension", "high blood pressure", "htn", "hbp", "high bp"],
    "asthma": ["asthma"],
    "cancer": ["cancer"],
    "diabetes": ["diabetes", "sugar diabetes", "dm", "type 1 diabetes", "type 2 diabetes", "t2dm"],
    "thyroid": ["thyroid", "thyroid disease", "underactive thyroid", "overactive thyroid"],
    "copd": ["copd", "emphysema", "chronic bronchitis"],
    "liver": ["liver", "liver disease", "cirrhosis", "fatty liver"],
    "heart_disease": ["heart disease", "cad", "coronary artery disease", "heart attack", "myocardial infarction"],
    "stroke": ["stroke", "cva"],
    "heart_failure": ["heart failure", "chf", "congestive heart failure"],
}
SYNONYM_FLAG = {word: flag for flag, words in SYNONYMS.items() for word in words}


class Hit(NamedTuple):
    name: str
    code: str | None


def sanitize_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in terms:
        t = _clean(raw) if isinstance(raw, str) else ""
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TERMS]


def _clean(raw: str) -> str:
    # Cc and Cf cover NUL, escapes, bidi overrides and zero-width characters that can hide text.
    kept = (" " if c.isspace() else c for c in raw if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf"))
    return " ".join("".join(kept).split())[:MAX_CHARS].strip()


def search_url(term: str) -> str:
    query = {"terms": term.replace("'", "").replace("’", ""), "maxList": MAX_LIST,
             "df": "primary_name", "ef": "icd10cm_codes"}
    return f"{NLM_URL}?{urllib.parse.urlencode(query)}"


def http_get(url: str, timeout: float) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (url always starts with NLM_URL)
        return json.loads(r.read(MAX_BYTES))


def resolve(terms: list[str], *, fetch: Fetch | None = None,
            cfg: ConditionsConfig = CONFIG.conditions) -> list[ResolvedCondition]:
    fetch = fetch or http_get
    return [_resolve_one(t, fetch, cfg) for t in sanitize_terms(terms)]


def _resolve_one(typed: str, fetch: Fetch, cfg: ConditionsConfig) -> ResolvedCondition:
    flag = SYNONYM_FLAG.get(_norm(typed))
    if flag:
        return ResolvedCondition(typed=typed, canonical=flag.replace("_", " "), status="checklist", checklist=flag)
    try:
        hits = _parse(fetch(search_url(typed), cfg.nlm_timeout_s))
    except Exception:  # any failure means "could not ask", which must never read as "not found"
        return ResolvedCondition(typed=typed, status="unavailable")
    return _pick(typed, hits, cfg.match_threshold)


def _parse(resp: object) -> list[Hit]:
    """NLM answer: [total, ids, {"icd10cm_codes": [...]}, [[primary_name], ...]]."""
    if not (isinstance(resp, list) and len(resp) >= 4 and isinstance(resp[3], list)):
        raise ValueError("unexpected NLM response")
    extra = resp[2] if isinstance(resp[2], dict) else {}
    codes = extra.get("icd10cm_codes")
    codes = codes if isinstance(codes, list) else []
    hits = []
    for i, row in enumerate(resp[3]):
        if not (isinstance(row, list) and row and isinstance(row[0], str)):
            raise ValueError("unexpected NLM row")
        hits.append(Hit(row[0], _first_code(codes[i]) if i < len(codes) else None))
    return hits


def _first_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.split(",")[0].strip() or None


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[-,]", " ", text.lower().replace("'", "").replace("’", "")).split())


def _score(typed_norm: str, name: str) -> float:
    # "Renal failure - acute" also counts as "Renal failure": the part after the dash is a subtype.
    forms = (name, name.split(" - ")[0])
    return max(SequenceMatcher(None, typed_norm, _norm(f)).ratio() for f in forms)


def checklist_of(code: str | None) -> str | None:
    cat = code[:3].upper() if code else ""
    return next((flag for lo, hi, flag in CHECKLIST_RANGES if lo <= cat <= hi), None)


def _pick(typed: str, hits: list[Hit], threshold: float) -> ResolvedCondition:
    tn = _norm(typed)
    scored = sorted(((_score(tn, h.name), h) for h in hits), key=lambda p: -p[0])
    above = [(s, h) for s, h in scored if s >= threshold]
    if not above:
        return ResolvedCondition(typed=typed, status="not_found")
    exact = next((h for _, h in above if _norm(h.name) == tn), None)
    if exact:
        return _found(typed, exact)
    flags = {checklist_of(h.code) for _, h in above}
    if len(flags) == 1 and None not in flags:
        return _found(typed, above[0][1])
    close = [h for s, h in above if above[0][0] - s <= AMBIGUOUS_GAP]
    if len({h.code or h.name for h in close}) >= 2:
        return ResolvedCondition(typed=typed, vocabulary=VOCABULARY, status="ambiguous",
                                 candidates=[Candidate(canonical=h.name, code=h.code)
                                             for h in close[:MAX_CANDIDATES]])
    return _found(typed, close[0])


def _found(typed: str, hit: Hit) -> ResolvedCondition:
    flag = checklist_of(hit.code)
    return ResolvedCondition(typed=typed, canonical=hit.name, vocabulary=VOCABULARY, code=hit.code,
                             status="checklist" if flag else "found", checklist=flag)
