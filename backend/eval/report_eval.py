"""Measures the whole report (CrewAI panel, writer, pharmacist review, code
rules, guideline RAG) on eval/report_cases.json, live on Gemini.

    cd backend && uv run python eval/report_eval.py            # every case
    cd backend && uv run python eval/report_eval.py uti-woman  # some cases

Per case: is the most likely condition right, is a must-rule-out listed, no
wrong condition or sensitive word, urgency and department acceptable, the
expected medicine present and a wrong one absent (or no medicine at all when
none may be shown), and how long it took. Writes eval/report_results.json.
Nothing is saved to the database. The expected answers are DRAFT (see the
cases file) until a doctor confirms them.
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402
from app.models import IntakeSession  # noqa: E402
from app.routers.reports import patient_medicines  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.triage import build_report  # noqa: E402

HERE = Path(__file__).parent
CONCURRENT = 2  # the Gemini key's per-minute limit is shared by every call


def _session(case: dict) -> IntakeSession:
    v = case.get("vitals") or {}
    return IntakeSession(
        id=f"eval{case['id']}"[:32].ljust(32, "0"), created_at=datetime.now(timezone.utc), mode="manual",
        name="Eval Patient", age=case["age"], gender=case["gender"], phone="9000000000", email="",
        symptoms=case["symptoms"], duration=case.get("duration", ""), medications=case.get("taken", ""),
        allergies=case.get("allergies", "none"), pregnancy="", language="en",
        chronic_conditions=case.get("conditions", ""), regular_medicines=case.get("regular", ""),
        past_surgeries="", weight_kg=case.get("weight"), habits="", vitals=v or None,
    )


def _has(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def score(case: dict, data: dict) -> dict:
    conditions = [c.get("name", "") for c in data.get("possibleConditions", [])]
    meds = [f"{m.get('name', '')} {m.get('dose', '')}".strip() for m in data.get("medicines", [])]
    doctor_meds = [m.get("name", "") for m in (data.get("doctorView") or {}).get("medicines", [])]
    patient_text = json.dumps(data.get("patientView") or {}, ensure_ascii=False).lower()
    checks: dict[str, bool] = {}
    checks["top"] = bool(conditions) and _has(conditions[0], case["top"])
    checks["in_top3"] = any(_has(c, case["top"]) for c in conditions[:3])
    if case.get("listed"):
        checks["listed"] = all(any(_has(c, group) for c in conditions) for group in case["listed"])
    if case.get("never"):
        checks["never"] = not any(_has(c, case["never"]) for c in conditions) and not _has(patient_text, case["never"])
    checks["urgency"] = data.get("urgency") in case["urgency"]
    checks["department"] = data.get("department") in case["department"]
    if case.get("no_meds"):
        checks["no_meds"] = not meds
    if case.get("meds_any"):
        checks["meds_any"] = any(_has(m, case["meds_any"]) for m in meds)
    if case.get("meds_never"):
        checks["meds_never"] = not any(_has(m, case["meds_never"]) for m in meds + doctor_meds)
    return {
        "id": case["id"], "ok": all(checks.values()), "checks": checks,
        "conditions": conditions, "urgency": data.get("urgency"), "department": data.get("department"),
        "medicines": meds, "doctorMedicines": doctor_meds,
        "rejected": [f"{x.get('name')}: {x.get('reason', '')[:120]}" for x in (data.get("doctorView") or {}).get("medicinesRejected", [])],
        "panel": [p.get("specialist") for p in data.get("panel", []) if p.get("relevant", True)],
        "passages": len((data.get("doctorView") or {}).get("guidelineEvidence", [])),
        "generator": data.get("generator"), "note": data.get("panelNote", ""),
    }


async def main(wanted: list[str]) -> None:
    cases = json.loads((HERE / "report_cases.json").read_text())["cases"]
    if wanted:
        cases = [c for c in cases if c["id"] in wanted]
    app = create_app(Settings(background_tasks=False))
    state = app.state
    if state.retriever is not None:
        await asyncio.to_thread(state.retriever.warm)
    await asyncio.to_thread(state.kb.warm)
    gate = asyncio.Semaphore(CONCURRENT)
    results = []

    async def one(case: dict) -> None:
        async with gate:
            session = _session(case)
            started = time.time()
            try:
                data = await build_report(session, state.llm, state.kb, state.panel, 5, None, "", state.retriever,
                                          writer_llm=state.report_llm)
                data["medicines"] = data.get("medicines", [])
                data["patientMedicines"] = patient_medicines(data, session)
                result = score(case, data)
            except Exception as e:  # noqa: BLE001 - one failed case must not stop the run
                result = {"id": case["id"], "ok": False, "checks": {"ran": False}, "error": f"{type(e).__name__}: {e}"}
            result["seconds"] = round(time.time() - started)
            results.append(result)
            failed = [k for k, v in result["checks"].items() if not v]
            print(f"{'PASS' if result['ok'] else 'FAIL'} {case['id']:22} {result['seconds']:>3}s "
                  f"{'' if result['ok'] else 'failed: ' + ', '.join(failed)}", flush=True)
            if not result["ok"]:
                print("     conditions:", result.get("conditions"), "| urgency:", result.get("urgency"),
                      "| dept:", result.get("department"), flush=True)
                print("     medicines:", result.get("medicines"), "| rejected:", result.get("rejected"), result.get("error", ""), flush=True)

    await asyncio.gather(*(one(c) for c in cases))
    results.sort(key=lambda r: r["id"])
    checks: dict[str, list[bool]] = {}
    for r in results:
        for k, v in r["checks"].items():
            checks.setdefault(k, []).append(v)
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} cases fully right")
    for k, vs in checks.items():
        print(f"  {k:12} {sum(vs)}/{len(vs)}")
    secs = [r["seconds"] for r in results]
    print(f"  time: median {sorted(secs)[len(secs) // 2]} s, max {max(secs)} s")
    (HERE / "report_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
