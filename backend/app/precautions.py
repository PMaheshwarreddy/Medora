"""The patient's precautions: from the knowledge base when it has them,
written for the case when it does not.

Either way nothing reaches the patient unchecked:

  1. Knowledge-base precautions for the likely conditions are the first
     choice, but they describe the disease in general (prevention, recovery),
     so a model picks the ones that suit this patient right now. It may only
     select, never reword them.
  2. If too few suit, the same step writes new ones under strict rules.
  3. Rules in code remove anything naming a medicine, a dose or a diagnosis.
  4. A second, independent model pass reviews every written line for safety
     and drops any it objects to. Lines from the knowledge base are not
     reviewed again; they were already chosen as stored.
"""

import logging
import re

from .ingest.transform import normalize
from .knowledge_base import Evidence, KnowledgeIndex
from .llm import Llm, LlmError

log = logging.getLogger("medora.precautions")

MAX_PRECAUTIONS = 6
# Stored lines shown at most, leaving room for the warning-signs line.
MAX_FROM_KNOWLEDGE = 4
# With fewer suitable knowledge-base lines than this, new ones are written.
ENOUGH_FROM_KNOWLEDGE = 3

EMERGENCY_FIRST = "Tell the hospital staff now that you need urgent help."

_SELECT = """You choose the precautions a hospital kiosk shows a patient who \
is waiting to see a doctor. Patient safety comes before helpfulness: when \
unsure, leave a line out. Return ONE JSON object:
{
  "keep": [numbers of the knowledge-base precautions that suit this patient now],
  "written": ["new precautions, only if needed"],
  "warning_signs": "one sentence, or an empty string"
}

keep: go through the numbered knowledge-base precautions. Keep a line only if
ALL of these hold:
- it is something this patient can do or avoid now or in the coming days;
- it is safe whichever of the listed possible conditions turns out to be true;
- it fits the urgency: for "urgent" or "emergency", advice about long-term
  prevention, diet, exercise, vaccination or returning to normal life does NOT fit;
- it fits the patient's age and gender;
- it does not say the same thing as a line you already kept.
You may not reword a knowledge-base line; only its number is returned. Keep at
most {kept_most}.

written: write new precautions ONLY when fewer than {enough} knowledge-base
lines were kept (or there were none), so that the patient gets {enough} to
{most} lines in total. Each new line must:
- be one plain imperative sentence of at most 18 words that a tired, unwell
  person understands ("Rest and avoid heavy activity until you are seen.");
- be safe for EVERY listed possible condition, not only the most likely one;
- be general supportive care or a safety action: rest, fluids, positioning,
  avoiding triggers, hygiene, not driving, not eating before possible
  procedures, and when to call for help;
- never name or hint at any medicine, supplement, herb, dose or home remedy;
- never state or imply a diagnosis, and never tell the patient to start,
  stop or change a treatment;
- for "urgent" or "emergency", be only about staying safe in the next minutes.
Do not repeat what a kept knowledge-base line already says.

warning_signs: for "routine" or "soon" urgency, always give ONE sentence of at
most 22 words naming the two or three changes, specific to this case, that
mean the patient should tell the staff straight away ("Tell the staff at once
if you get a fever, back pain or blood in your urine."). It follows the same
rules as a written line. For "urgent" or "emergency", return an empty string."""

_REVIEW = """You are the safety reviewer for advice a hospital kiosk shows a \
patient before they see a doctor. For each numbered line decide whether it is \
safe to show THIS patient. Return ONE JSON object:
{"unsafe": [{"number": n, "why": "short reason"}]}

Mark a line unsafe if it:
- could cause harm or delay care if any of the listed possible conditions is the real one;
- names or hints at a medicine, supplement, herb, dose or home remedy;
- states or implies a diagnosis, or tells the patient to start, stop or change a treatment;
- is wrong for the patient's age, gender, vitals or urgency;
- is vague, misleading, or could be misunderstood by a frightened patient.
Be strict. An empty list means every line is safe."""

# Things a precaution must never contain, whatever the model was told.
_FORBIDDEN = re.compile(
    r"\b(\d+\s?(mg|ml|mcg|g|iu|tablets?|pills?|capsules?|drops?)|dose|dosage|tablets?|pills?|"
    r"capsules?|antibiotics?|painkillers?|pain relievers?|supplements?|over[- ]the[- ]counter|"
    r"otc|medication|medicine|remedy|remedies|herbal|you have|diagnos\w*)\b",
    re.I,
)


def acceptable(line: str, kb: KnowledgeIndex | None) -> bool:
    """The rules a written precaution must pass before any model review."""
    words = line.split()
    return (
        4 <= len(words) <= 24
        and not _FORBIDDEN.search(line)
        and not (kb is not None and kb.mentions_drug(line))
    )


def from_knowledge(conditions: list[dict], evidence: Evidence) -> list[str]:
    """Stored precautions for the conditions the panel thinks likely or
    possible, the most likely condition's first."""
    by_key = {normalize(c.name): c for c in evidence.candidates}
    lines: list[str] = []
    for condition in conditions:
        if condition["likelihood"] == "low":
            continue
        candidate = by_key.get(normalize(condition.get("kbName") or condition["name"]))
        if candidate is not None:
            lines += candidate.precautions
    return list(dict.fromkeys(line.strip() for line in lines if line.strip()))[:15]


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) or "(none)"


def _numbers(value, count: int) -> list[int]:
    out = []
    for item in value if isinstance(value, list) else []:
        number = item.get("number") if isinstance(item, dict) else item
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= count and number not in out:
            out.append(number)
    return out


async def choose(
    llm: Llm,
    case: str,
    conditions: list[dict],
    urgency: str,
    evidence: Evidence,
    kb: KnowledgeIndex | None,
    select: bool = True,
) -> tuple[list[str], str]:
    """The precautions to show, and where they came from:
    "knowledge_base", "written", "mixed", or "none". With `select` false
    (offline, where each model call takes minutes) no model is asked: the
    stored lines for a calm case, as when the selection fails."""
    # Stored precautions are about prevention and recovery. A patient who
    # needs care now gets none of them, whatever a model thinks of each line.
    calm = urgency in ("routine", "soon")
    stored = from_knowledge(conditions, evidence) if calm else []
    listed = ", ".join(f"{c['name']} ({c['likelihood']})" for c in conditions) or "none named"
    context = f"{case}\n\nUrgency: {urgency}\nPossible conditions: {listed}"
    if not select:
        return _finish(stored[:MAX_FROM_KNOWLEDGE], [], urgency)

    try:
        raw = await llm.json(
            _SELECT.replace("{enough}", str(ENOUGH_FROM_KNOWLEDGE))
            .replace("{most}", str(MAX_PRECAUTIONS - 1))
            .replace("{kept_most}", str(MAX_FROM_KNOWLEDGE)),
            f"{context}\n\nKnowledge-base precautions:\n{_numbered(stored)}",
            thinking=512,
        )
    except LlmError as e:
        # Without a model to judge them, stored lines are only safe to show
        # when nothing urgent is going on.
        log.warning("Precaution selection failed: %s", e)
        return _finish(stored[:MAX_FROM_KNOWLEDGE], [], urgency)

    kept = [stored[n - 1] for n in _numbers(raw.get("keep"), len(stored))][:MAX_FROM_KNOWLEDGE]
    seen = {normalize(line) for line in kept}
    written: list[str] = []

    def consider(line) -> None:
        line = str(line or "").strip()
        if line and normalize(line) not in seen and acceptable(line, kb):
            seen.add(normalize(line))
            written.append(line)

    if len(kept) < ENOUGH_FROM_KNOWLEDGE:
        for line in raw.get("written") if isinstance(raw.get("written"), list) else []:
            consider(line)
    if calm:
        # Always last: what should make the patient call for help.
        consider(raw.get("warning_signs"))
    written = await _reviewed(llm, context, written)
    return _finish(kept, written, urgency)


async def _reviewed(llm: Llm, context: str, lines: list[str]) -> list[str]:
    """Written lines that an independent pass did not object to. If the
    review cannot run, written lines are not shown at all."""
    if not lines:
        return []
    try:
        raw = await llm.json(_REVIEW, f"{context}\n\nLines to review:\n{_numbered(lines)}", thinking=512)
    except LlmError as e:
        log.warning("Precaution review failed; dropping the written lines: %s", e)
        return []
    unsafe = set(_numbers(raw.get("unsafe"), len(lines)))
    return [line for i, line in enumerate(lines, 1) if i not in unsafe]


def _finish(kept: list[str], written: list[str], urgency: str) -> tuple[list[str], str]:
    lines = [*kept, *written]
    if urgency == "emergency":
        # Not left to a model: the one thing that must be said first.
        lines = [EMERGENCY_FIRST, *(line for line in lines if normalize(line) != normalize(EMERGENCY_FIRST))]
    source = (
        "mixed" if kept and written
        else "knowledge_base" if kept
        else "written" if written
        else "none"
    )  # fmt: skip
    return lines[:MAX_PRECAUTIONS], source
