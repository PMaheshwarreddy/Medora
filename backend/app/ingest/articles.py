"""AI extraction for free-text articles about a single disease.

Unlike structured files there are no columns to map, so the model reads the
article and returns the facts. To keep invented facts out of the database,
every extracted name must be found in the article itself.
"""

from ..llm import Llm, LlmError
from .plan import Plan
from .transform import normalize

MAX_ARTICLE_CHARS = 60_000

EXTRACT_SYSTEM = """You extract structured medical knowledge from ONE article \
about a single disease or condition. Use ONLY what the article states; never \
add facts from your own knowledge. Return one JSON object:

{
  "disease": "the condition's standard name",
  "aliases": ["other names or abbreviations the article gives for it"],
  "description": "2-4 plain sentences: what the condition is",
  "causes": "1-4 plain sentences: what causes it or raises the risk; empty string if not stated",
  "symptoms": ["short symptom names"],
  "drugs": ["generic drug names the article says are used to treat it"],
  "precautions": ["short practical advice for a patient"]
}

Rules
- symptoms: names of 1-5 words as a patient or clinician would say them
  ("fever", "shortness of breath", "night sweats"), using the article's own
  wording. No sentences, no body parts alone, no test results, no other diseases.
  Give up to 25, the most characteristic first.
- drugs: specific medicines only, by generic name as written in the article
  ("isoniazid", "salbutamol"). No drug classes ("antibiotics"), no procedures,
  no vaccines unless the article presents them as the treatment. Up to 20.
- precautions: up to 8 items, each one imperative sentence under 25 words on
  prevention or self-care that the article supports ("Wash hands often with
  soap."). Never include doses or advice to start or stop a medicine.
- aliases: only other names that mean exactly this condition, up to 8. Not
  subtypes, stages, complications, or episodes of it.
- If the text is not an article about one disease, return {"disease": ""}."""

# The plan every extracted article is loaded with.
ARTICLE_PLAN = Plan.model_validate(
    {
        "content": "records",
        "verdict": "usable",
        "confidence": 1,
        "outputs": [
            {
                "kind": "entity",
                "table": "diseases",
                "name": {"sources": ["disease"]},
                "aliases": {"sources": ["aliases"]},
                "fields": {
                    "description": {"sources": ["description"]},
                    "causes": {"sources": ["causes"]},
                },
            },
            {"kind": "link", "disease": {"sources": ["disease"]}, "symptom": {"sources": ["symptoms"]}},
            {"kind": "link", "disease": {"sources": ["disease"]}, "drug": {"sources": ["drugs"]}},
            {"kind": "precaution", "disease": {"sources": ["disease"]}, "text": {"sources": ["precautions"]}},
        ],
    }
)


def _grounded(phrase: str, text_key: str, text_words: set[str]) -> bool:
    """True when the phrase, or all of its meaningful words, occur in the text."""
    key = normalize(phrase)
    if not key:
        return False
    if key in text_key:
        return True
    words = [w for w in key.split() if len(w) > 3]
    return bool(words) and all(w in text_words for w in words)


def _strings(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()][:limit]


async def extract_article(llm: Llm, text: str) -> tuple[dict, list[str]]:
    """The article as one record for ARTICLE_PLAN, plus the names that were
    dropped because the article does not contain them."""
    text = text[:MAX_ARTICLE_CHARS]
    raw = await llm.json(EXTRACT_SYSTEM, text)
    disease = str(raw.get("disease") or "").strip()
    if not disease:
        raise LlmError("The text is not an article about a single disease")

    text_key = normalize(text)
    text_words = set(text_key.split())
    dropped: list[str] = []

    def keep(items: list[str], label: str) -> list[str]:
        kept = []
        for item in items:
            if _grounded(item, text_key, text_words):
                kept.append(item)
            else:
                dropped.append(f"{label}: {item}")
        return kept

    if not _grounded(disease, text_key, text_words):
        raise LlmError(f"Extracted disease name {disease!r} does not occur in the article")

    record = {
        "disease": disease,
        "aliases": keep(_strings(raw.get("aliases"), 8), "alias"),
        "description": str(raw.get("description") or "").strip(),
        "causes": str(raw.get("causes") or "").strip(),
        "symptoms": keep(_strings(raw.get("symptoms"), 25), "symptom"),
        "drugs": keep(_strings(raw.get("drugs"), 20), "drug"),
        "precautions": _strings(raw.get("precautions"), 8),
    }
    return record, dropped
