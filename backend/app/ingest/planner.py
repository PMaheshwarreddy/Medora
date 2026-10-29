"""Asks the model what a file is and how it maps onto the knowledge tables."""

import asyncio
import json
import logging
import time

from pydantic import ValidationError

from ..llm import GeminiLlm, Llm, LlmError, OllamaLlm
from ..settings import Settings
from .plan import Plan
from .sniff import Sniffed

log = logging.getLogger("medora.ingest")

PLANNER_SYSTEM = """You are the planning step of a medical-knowledge ETL \
pipeline. You are shown a description and a small sample of ONE source file. \
File names are unreliable; judge only by content. You do not transform data \
yourself: you return a JSON plan that code will apply to every record.

TARGET TABLES
  diseases(name, aliases, description, causes)
  symptoms(name, aliases, description)
  drugs(name, aliases, dosage, uses, side_effects)
  disease_links: one fact per row, either "disease has symptom" or "disease is treated with drug"
  precautions: a short piece of advice for a disease and/or a symptom

RETURN ONE JSON OBJECT
{
  "content": "records" | "article" | "none",
  "verdict": "usable" | "junk" | "not_data",
  "summary": "one line: what this file contains",
  "reason": "why this verdict; anything a human reviewer must know",
  "confidence": 0.0-1.0,
  "outputs": [ ... ]
}

content
  "records": rows or objects that the outputs below can map.
  "article": free-running prose about a single disease (for example an
             encyclopedia article). Leave outputs empty; another step extracts it.
  "none":    nothing to ingest.

verdict
  "usable":   real medical data that fits at least one target table.
  "not_data": source code, logs, configuration, or anything that is not a dataset.
  "junk":     looks like data but must not be trusted or does not fit. Use it when
              the sample is medically wrong or self-contradictory (for example a
              viral disease typed as genetic, or unrelated organisms listed for a
              disease), when values look randomly combined or machine-generated,
              or when no column can fill a target table correctly.
  Be strict: wrong medical facts in the database are worse than a skipped file.
  A file that merely repeats rows is still usable; duplicates are removed later.

outputs (only for usable records files). A "col" is
  {"sources": ["field", "fallback_field"], "split": "," or null}
  where sources are copied EXACTLY from "Fields available", the first non-empty
  one is used, and split is set when one cell holds several values.

  {"kind": "entity", "table": "diseases"|"symptoms"|"drugs",
   "mode": "upsert"|"enrich_only", "name": col, "aliases": col or null,
   "fields": {"<column of that table>": col}}
  {"kind": "link", "disease": col, "symptom": col}      (or "drug": col instead of "symptom")
  {"kind": "precaution", "disease": col or null, "symptom": col or null, "text": col}

RULES
- A link output already creates the disease, symptom or drug names it mentions;
  add an entity output only when the file also has descriptive text for them.
- A name column must hold short names ("Asthma", "skin rash", "ibuprofen").
  If a column called "symptom" or "treatment" actually holds whole sentences of
  prose, it is NOT a name: do not map it as a name or as a link target. Prose
  about one disease may fill that disease's description or causes instead.
- Map a text field only when the content truly matches:
    diseases.description = what the disease is.  diseases.causes = why it happens.
    drugs.uses = what the drug treats.  drugs.dosage = how much to take and how
    often.  drugs.side_effects = unwanted effects.
  Package sizes, strengths, product codes and ingredient lists are NOT dosage.
  Prose about a disease's symptoms or its treatment is NOT a description or a
  cause; there is no target for it. If a file offers nothing else, the verdict
  is "junk" with the reason "no column fits a target table".
- For drugs, use the generic (substance) name as the name and brand names as
  aliases.
- Aliases must be other names for the very same thing. The separate
  ingredients of a combination product, broader or narrower terms, and
  related conditions are NOT aliases.
- mode: use "enrich_only" for every ontology, terminology or product
  catalogue: a file of standalone terms (often with definitions and synonyms,
  or thousands of product listings) that does not say which disease each term
  belongs to. Such a file may add aliases and descriptions to rows that
  already exist but must not flood the table with new ones. Use "upsert" only
  when the file ties its terms to diseases or carries real descriptive
  content for them (for example full drug label text).
- Ignore identifier, URL, count and bookkeeping columns.
- If you are unsure a mapping is right, lower the confidence and say why."""


class RetryingLlm:
    """Rides out rate limits and brief outages; spaces calls for a free tier."""

    def __init__(self, inner: Llm, min_interval: float = 4.5, attempts: int = 6):
        self._inner = inner
        self._min_interval = min_interval
        self._attempts = attempts
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.name = inner.name

    async def json(self, system: str, user: str) -> dict:
        async with self._lock:
            error: LlmError | None = None
            for attempt in range(self._attempts):
                wait = self._last + self._min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
                try:
                    return await self._inner.json(system, user)
                except LlmError as e:
                    error = e
                    transient = any(
                        marker in str(e)
                        for marker in (
                            "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "valid JSON",
                            # network trouble on our side
                            "timed out", "name resolution", "Errno", "onnect",
                        )  # fmt: skip
                    )
                    if not transient:
                        raise
                    delay = min(60, 8 * (attempt + 1))
                    log.warning("Model call failed (%s); retrying in %ss", str(e)[:160], delay)
                    await asyncio.sleep(delay)
            raise error or LlmError("The model did not answer")


def make_ingest_llm(settings: Settings) -> Llm:
    """Planning needs the stronger model. It never falls back silently to the
    small offline one, because a weak plan would load wrong data."""
    if settings.gemini_api_key:
        return RetryingLlm(GeminiLlm(settings.gemini_api_key, settings.gemini_text_model))
    return RetryingLlm(OllamaLlm(settings.ollama_url, settings.ollama_model), min_interval=0)


async def make_plan(
    llm: Llm, filename: str, sniffed: Sniffed, revise: tuple[Plan, str] | None = None
) -> Plan:
    """The model's plan, validated. An unexecutable plan is sent back with
    the reason; if it is still wrong after that, the error is raised.

    `revise` is a previous plan and a reviewer's instruction for changing it.
    """
    prompt = f"File name (unreliable): {filename}\n{sniffed.describe()}"
    if revise:
        previous, instruction = revise
        prompt += (
            "\n\nA human reviewer looked at this plan:\n"
            + previous.model_dump_json(exclude={"model"})
            + f"\nand requires this change: {instruction}\n"
            "Return the corrected plan. Follow the reviewer even where it "
            "differs from the general rules, and keep everything else as it was."
        )
    feedback = ""
    problems: list[str] = []
    for _ in range(3):
        raw = await llm.json(PLANNER_SYSTEM, prompt + feedback)
        try:
            plan = Plan.model_validate(raw)
        except ValidationError as e:
            problems = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        else:
            problems = plan.check_against(sniffed)
            if not problems:
                plan.model = llm.name
                return plan
        feedback = (
            "\n\nYour previous plan was rejected:\n- "
            + "\n- ".join(problems[:12])
            + "\nPrevious plan: "
            + json.dumps(raw)[:3000]
            + "\nReturn a corrected plan."
        )
    raise LlmError("The model could not produce a valid plan: " + "; ".join(problems[:5]))
