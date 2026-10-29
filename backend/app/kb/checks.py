"""Checks in code that stand in for a person reviewing each page.

A page or row that fails goes to `kb_quarantine` with the reason; it is
never loaded silently and never dropped silently.
"""

import re

from .text import normalize, numbers, words

# Below this share of the page's own words, a transcription is incomplete.
MIN_COVERAGE = 0.85
# More than this share of one source's items refused = the reader is wrong
# for this file: fail the whole source instead of loading half of it.
MAX_REJECT_RATE = 0.25

_UNIT = re.compile(
    r"\d\s*(mg|mcg|µg|μg|microgram|g\b|gm|gram|kg|ml|mL|l\b|litre|liter|iu|unit|units|meq|mmol|%|drop|drops|tab|tablet|"
    r"cap|capsule|puff|puffs|sachet|vial|amp|ampoule|tsp|teaspoon|spoon|application|u\b|u/|ug|units?\b|million|ds\b|ss\b|"
    r"lakh|mu\b|meq)",
    re.I,
)
_NOT_A_DRUG = {
    "infusion rate", "rate", "fluid", "fluids", "dose", "dosage", "treatment", "therapy", "oxygen therapy",
    "platelet transfusion", "blood transfusion", "transfusion",
}


def unknown_numbers(extracted: str, source_text: str) -> set[str]:
    """Numbers in the extraction that the source page does not contain."""
    return numbers(extracted) - numbers(source_text)


def coverage(extracted: str, source_text: str) -> float:
    """Share of the source's distinct words (3+ letters) found in the extraction."""
    src = {w for w in words(source_text) if len(w) >= 3}
    if not src:
        return 1.0
    got = set(words(extracted))
    return len(src & got) / len(src)


def dose_problem(dose: dict, page_text: str) -> str:
    """Why a dose row cannot be stored, or '' when it can."""
    drug = normalize(dose.get("drug", ""))
    amount = (dose.get("dose") or "").strip()
    if not drug or len(drug) < 2:  # RL, NS and ORS are real
        return "no drug name"
    if drug in _NOT_A_DRUG:
        return f"'{dose.get('drug')}' is not a medicine"
    if not _UNIT.search(amount):
        return f"'{amount}' does not look like a dose"
    extra = unknown_numbers(" ".join(str(dose.get(k, "")) for k in ("dose", "frequency", "duration")), page_text)
    if extra:
        return f"numbers not on the page: {', '.join(sorted(extra))}"
    if not set(words(dose.get("drug", ""))) & set(words(page_text)):
        return "drug name not on the page"
    return ""


def too_many_rejects(kept: int, refused: int) -> bool:
    total = kept + refused
    return total >= 20 and refused / total > MAX_REJECT_RATE
