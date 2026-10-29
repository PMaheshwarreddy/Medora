"""Measures the guideline search on eval/rag_cases.json.

    cd backend && uv run python eval/rag_eval.py [k]

For each case: whether an expected passage is in the top k (hit@k), its
rank (for mean reciprocal rank), the share of top-k passages from Indian
sources (tier 1), and the time taken. Uses MEDORA_KNOWLEDGE_DATABASE_URL and
the same source switches as reports (MEDORA_KNOWLEDGE_TESTING_SOURCES ...).
Targets from the plan: hit@8 >= 85%, search time a few seconds.

As in a report: a diagnosis question also reads the pages of the conditions
the symptom-understanding step (Gemini) names to look up, and a treatment
question ("X treatment and dose for ...") the pages of X. `--plain` searches
the question alone.
"""

import asyncio
from types import SimpleNamespace

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.kb.__main__ import _retriever  # noqa: E402
from app.kb.retrieve import DIAGNOSIS, TREATMENT  # noqa: E402
from app.llm import make_llm  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.triage import understand  # noqa: E402


def _look_up(llm, question: str) -> list[str]:
    """What the understanding step names for this presentation."""
    session = SimpleNamespace(age=30, gender="", symptoms=question, duration="", medications="", allergies="",
                              vitals=None, chronic_conditions="", regular_medicines="", past_surgeries="",
                              habits="", pregnancy="", weight_kg=None)
    return asyncio.run(understand(session, llm))[2]


def main(k: int = 8, plain: bool = False) -> None:
    cases = json.loads((Path(__file__).with_name("rag_cases.json")).read_text())["cases"]
    settings = Settings()
    retriever = _retriever(settings)
    llm = None if plain else make_llm(settings)
    retriever.search("warm up", DIAGNOSIS, k=1)  # load the models before timing
    hits, rr, tier1, times = 0, 0.0, [], []
    for case in cases:
        if plain:
            topics, hint = [], ""
        elif case["kind"] == "diagnosis":
            topics, hint = _look_up(llm, case["q"]), ""
        else:
            topics, hint = [], case["q"].split(" treatment")[0]
        started = time.time()
        ev = retriever.search(case["q"], DIAGNOSIS if case["kind"] == "diagnosis" else TREATMENT, k=k,
                              topic_hint=hint, topics=topics)
        took = time.time() - started
        times.append(took)
        rank = next((i + 1 for i, p in enumerate(ev.passages)
                     if any(e in (p.breadcrumb + " " + p.body[:200]).lower() for e in case["expect"])), None)
        hits += rank is not None
        rr += 1 / rank if rank else 0
        tier1.append(sum(p.tier == 1 for p in ev.passages) / max(1, len(ev.passages)))
        mark = f"#{rank}" if rank else "MISS"
        top = ev.passages[0].breadcrumb[:80] if ev.passages else ev.note
        print(f"{mark:5} {took:4.1f}s  {case['q'][:60]:60}  top: {top}" + (f"  [look up: {', '.join(topics)}]" if topics else ""))
    n = len(cases)
    print(f"\nhit@{k}: {hits}/{n} = {hits / n:.0%}   MRR: {rr / n:.2f}   tier-1 share: {sum(tier1) / n:.0%}   "
          f"median time: {sorted(times)[n // 2]:.1f}s")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--plain"]
    main(int(args[0]) if args else 8, "--plain" in sys.argv)
