"""Builds the triage report from a confirmed intake.

  1. Symptom understanding   a model turns the patient's words into symptom
                             terms and suggests which specialists to consult
  2. Evidence                the knowledge base is searched and candidate
                             diseases are scored (no model involved)
  3. Specialist panel        CrewAI agents, one per specialty, give opinions
                             and a chair concludes (online); offline, a single
                             local model writes the summary instead
     Precautions             from the knowledge base when it has suitable
                             ones, otherwise written and safety-reviewed
                             (precautions.py)
  4. Safety and grounding    code, not a model, has the last word: vitals set
                             a minimum urgency, and only medicines that the
                             knowledge base links to the conditions are kept
"""

import asyncio
import copy
import logging

import anyio

from . import precautions
from .ingest.transform import normalize
from .kb import rag
from .kb.drugnames import indian as indian_name
from .knowledge_base import Evidence, KnowledgeIndex
from . import sensitive
from .llm import Llm, LlmError, clinical
from .models import IntakeSession
from . import report_writer
from .progress import ReportProgress
from .vitals import assess as assess_vitals
from .vitals import describe as describe_vitals
from .panel import (
    DEPARTMENTS,
    EMERGENCY_DEPT,
    GENERAL_OPD,
    OBGYN,
    PEDIATRICS,
    SPECIALISTS,
    PanelError,
    SpecialistPanel,
)

log = logging.getLogger("medora.triage")

URGENCY = ["routine", "soon", "urgent", "emergency"]
LIKELIHOOD = ["low", "medium", "high"]

DISCLAIMER = (
    "This report is an automated pre-consultation summary. It is not a "
    "diagnosis and does not replace examination by a doctor. Possible "
    "conditions and medicines are listed for the doctor to confirm; do not "
    "start, stop or change any medicine because of this report."
)


def _raise(current: str, to: str) -> str:
    return max(current, to, key=URGENCY.index)


def vital_lines(v: dict) -> list[tuple[str, str]]:
    """Each vital as (label, value); one the band did not measure says so."""

    def show(value, template: str) -> str:
        return template.format(value) if value is not None else "not measured"

    bp = (
        f"{v['systolic']}/{v['diastolic']} mmHg"
        if v.get("systolic") is not None and v.get("diastolic") is not None
        else "not measured"
    )
    return [
        ("Heart rate", show(v.get("heart_rate"), "{} bpm")),
        ("SpO2", show(v.get("spo2"), "{}%")),
        ("Temperature", show(v.get("temperature_c"), "{:.1f} °C")),
        ("Blood pressure", bp),
    ]


def vital_flags(vitals: dict | None, age: int) -> tuple[list[str], str]:
    """Out-of-range vitals and the minimum urgency they require.

    Thresholds are common adult triage cut-offs and must be reviewed by a
    clinician before real use. Heart rate and blood pressure are only checked
    for adults because normal ranges for children differ by age.
    """
    flags: list[str] = []
    floor = "routine"
    if not vitals:
        return flags, floor

    def flag(message: str, urgency: str) -> None:
        nonlocal floor
        flags.append(message)
        floor = _raise(floor, urgency)

    spo2 = vitals.get("spo2")
    if spo2 is not None:
        if spo2 < 90:
            flag(f"Oxygen saturation is very low ({spo2}%)", "emergency")
        elif spo2 < 94:
            flag(f"Oxygen saturation is below normal ({spo2}%)", "urgent")

    temp = vitals.get("temperature_c")
    if temp is not None:
        if temp >= 40:
            flag(f"Very high temperature ({temp:.1f} °C)", "urgent")
        elif temp >= 38:
            flag(f"Fever ({temp:.1f} °C)", "soon")
        elif temp < 35:
            flag(f"Low body temperature ({temp:.1f} °C)", "urgent")

    if age >= 18:
        hr = vitals.get("heart_rate")
        if hr is not None:
            if hr > 130 or hr < 40:
                flag(f"Heart rate is far outside the normal range ({hr} bpm)", "urgent")
            elif hr > 100:
                flag(f"Heart rate is elevated ({hr} bpm)", "soon")
            elif hr < 50:
                flag(f"Heart rate is low ({hr} bpm)", "soon")

        sys, dia = vitals.get("systolic"), vitals.get("diastolic")
        if sys is not None and dia is not None:
            if sys >= 180 or dia >= 120:
                flag(f"Blood pressure is severely raised ({sys}/{dia} mmHg)", "urgent")
            elif sys < 90:
                flag(f"Blood pressure is low ({sys}/{dia} mmHg)", "urgent")
            elif sys >= 140 or dia >= 90:
                flag(f"Blood pressure is raised ({sys}/{dia} mmHg)", "soon")

    return flags, floor


# --- step 1: symptom understanding -------------------------------------------

_UNDERSTAND = """You prepare a patient's intake for a hospital's specialist \
panel. From the intake, return ONE JSON object:
{
  "symptoms": [{"term": "short standard clinical term", "plain": "the same symptom in everyday words"}],
  "specialists": ["the specialties this case concerns, most relevant first"],
  "look_up": ["up to 3 conditions whose guidelines a doctor would read for this presentation"]
}
symptoms: one entry per distinct symptom. "term" is 1-4 words, the way a
clinical symptom list would name it ("dysuria", "fever", "chest pain",
"dyspnea"). "plain" is how a symptom checker for the public would name it
("burning sensation during urination", "high temperature", "shortness of
breath"). Only what the patient reports; no diagnoses, and no negatives
("no vomiting" is not a symptom). Always write both in English, even when the
patient wrote in Malayalam or another language: translate the meaning.
specialists: screen the case against EVERY specialty on the roster below and
list each one this patient's problem concerns, the most relevant first: those
whose field a reported symptom could come from, and those that must rule out a
dangerous cause of it. Leave out every specialty that has nothing to do with
these symptoms; do not add one just to fill the list. A symptom every field
shares (fever, tiredness, body aches) does not concern a specialty on its own.
Most cases concern one to four; a plain viral fever or cold may concern none
(an empty list is right then: a general physician sees it). Copy the names
exactly.
look_up: only for finding guideline pages, never shown to anyone: the most
likely condition and any dangerous one this presentation must be checked
for, by their usual names (fever with chills on alternate days -> malaria;
fever for a week with abdominal pain -> typhoid; a snake bite -> snake bite).
Empty when nothing specific is suggested.
Roster:
""" + "\n".join(f"- {name}: {s.scope}" for name, s in SPECIALISTS.items())


def _case_lines(session: IntakeSession, flags: list[str]) -> list[str]:
    v = session.vitals or {}
    lines = [
        f"Age: {session.age}",
        f"Gender: {session.gender}",
        f"Symptoms, in the patient's words: {session.symptoms}",
        f"Duration: {session.duration or 'not stated'}",
        f"Medication already taken: {session.medications or 'none stated'}",
        f"Allergies: {getattr(session, 'allergies', '') or 'none stated'}",
    ]
    for label, key in (
        ("Long-term conditions", "chronic_conditions"),
        ("Regular medicines", "regular_medicines"),
        ("Past operations", "past_surgeries"),
        ("Smoking, tobacco or alcohol", "habits"),
    ):
        if getattr(session, key, ""):
            lines.append(f"{label}: {getattr(session, key)}")
    if getattr(session, "weight_kg", None):
        lines.append(f"Weight: {session.weight_kg:g} kg")
    pregnancy = getattr(session, "pregnancy", "") or ""
    if pregnancy:
        # Asked only when the complaint made it matter (voice.py).
        lines.append(f"Could she be pregnant (her answer): {pregnancy}")
    if (getattr(session, "language", None) or "en") != "en":
        # The report is for the doctor and is checked in English; the
        # patient's copy is written afterwards (patient_view.py).
        lines.append("The patient used the kiosk in Malayalam. Read their words in Malayalam, but write everything you return in English.")
    if v:
        lines.append("Vitals, from the kiosk's smart band: "
            + "; ".join(f"{label} {value}" for label, value in vital_lines(v)))
    else:
        lines.append("Vitals: not measured")
    if flags:
        lines.append("Vital sign alerts: " + "; ".join(flags))
    return lines


async def understand(session: IntakeSession, llm: Llm) -> tuple[list[list[str]], list[str], list[str]]:
    """The patient's symptoms, each as a group of wordings for it, the
    specialists to consult, and up to 3 conditions to look up in the
    guidelines. Falls back to the raw text and general medicine when the
    model cannot be used."""
    try:
        # A simple extraction: no thinking needed, and it gates every later step.
        raw = await llm.json(_UNDERSTAND, "\n".join(_case_lines(session, [])), thinking=0, answer_tokens=700)
    except LlmError as e:
        log.warning("Symptom understanding failed, using the raw text: %s", e)
        raw = {}
    symptoms: list[list[str]] = []
    for item in raw.get("symptoms") if isinstance(raw.get("symptoms"), list) else []:
        wordings = (
            [item.get("term"), item.get("plain")] if isinstance(item, dict) else [item]
        )
        wordings = [str(w).strip() for w in wordings if w and str(w).strip()]
        if wordings:
            symptoms.append(wordings)
    symptoms = symptoms[:20] or [
        [part.strip()]
        for part in session.symptoms.replace(" and ", ",").split(",")
        if part.strip()
    ]
    specialists = [s for s in _strings(raw.get("specialists"), len(SPECIALISTS)) if s in SPECIALISTS]
    look_up = [s[:80] for s in _strings(raw.get("look_up"), 3)]
    return symptoms, specialists, look_up


def choose_panel(suggested: list[str], age: int, gender: str, size: int) -> list[str]:
    """Who is asked to look at the case: the specialists the screening found
    it concerns, in order of relevance, up to `size`. Children always get a
    paediatrician. Specialists who cannot apply to this patient are never
    asked. The list may be empty: a complaint no specialty owns goes to the
    panel chair alone, who is a general physician."""
    panel = [PEDIATRICS] if age < 16 else []
    for name in suggested:
        excluded = (name == PEDIATRICS and age >= 18) or (name == OBGYN and gender == "male")
        if name in SPECIALISTS and name not in panel and not excluded:
            panel.append(name)
    # Online at least one is asked (the back office allows 1 and up); offline
    # the size may be 0: the chair alone.
    return panel[:size] if size > 0 else []


# --- step 3 input -------------------------------------------------------------


# Offline (lean) the local model reads about 20 tokens a second: the case
# carries fewer, shorter passages and candidates.
LEAN_PASS1, LEAN_PASS2, LEAN_CHARS, LEAN_CANDIDATES = 3, 4, 500, 5


def _evidence_text(evidence: Evidence, most: int | None = None) -> str:
    if not evidence.used:
        return "Knowledge base: no matching evidence was found for these symptoms."
    lines = [
        "Evidence from the hospital's knowledge base (candidate conditions ranked "
        "by how well they explain the reported symptoms; 1.00 is a perfect match):"
    ]
    for c in evidence.candidates[:most]:
        lines.append(
            f"- {c.name}: score {c.score:.2f}; explains {', '.join(c.matched)}"
            + (f". {c.description[:260]}" if c.description else "")
        )
    drugs = sorted(evidence.drug_names().values())
    if drugs:
        lines.append("Medicines in the knowledge base for these candidates: " + ", ".join(drugs))
    return "\n".join(lines)


# --- helpers ------------------------------------------------------------------


def _strings(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _one_of(value, allowed: list[str], default: str) -> str:
    value = str(value or "").strip().lower()
    return value if value in allowed else default


def _candidate_for(key: str, evidence: Evidence):
    """The knowledge-base candidate a condition name refers to: the same
    name or another name of it ("scabies" for Acariasis), or a name that
    contains it ("acute myocardial infarction")."""
    padded = f" {key} "
    best = None
    for candidate in evidence.candidates:
        candidate_key = normalize(candidate.name)
        if candidate_key == key or key in getattr(candidate, "aliases", ()):
            return candidate
        if f" {candidate_key} " in padded and (
            best is None or len(candidate_key) > len(normalize(best.name))
        ):
            best = candidate
    return best


def _conditions(raw, evidence: Evidence, members: list[str], opinions: list[dict]) -> list[dict]:
    """The panel's conditions, each tied back to the evidence where there is any."""
    # Which specialists named which condition in their own opinion.
    named: dict[str, list[str]] = {}
    for opinion in opinions:
        for item in opinion.get("conditions") or []:
            if isinstance(item, dict) and item.get("name"):
                named.setdefault(opinion["specialist"], []).append(normalize(str(item["name"])))
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        name = str(item["name"]).strip()[:120]
        candidate = _candidate_for(normalize(name), evidence)
        key = normalize(candidate.name if candidate else name)
        if key in seen:
            continue
        seen.add(key)
        raised = str(item.get("raised_by") or "")
        credited = [m for m in members if m.lower() in raised.lower()] or [
            # The chair did not say: credit whoever listed it themselves.
            m for m in members if any(key in n or n in key for n in named.get(m, []))
        ]
        out.append(
            {
                # The name the panel wrote: it is told to use the one an
                # Indian doctor would (scabies, not acariasis). The knowledge
                # base's own name is kept for its medicines and precautions.
                "name": name,
                "kbName": candidate.name if candidate else "",
                "likelihood": _one_of(item.get("likelihood"), LIKELIHOOD, "low"),
                "probability": _percent(item.get("probability")),
                "reasoning": str(item.get("reasoning") or "").strip()[:400],
                # Only specialists who actually sat on this panel are credited.
                "raisedBy": ", ".join(credited),
                # None when the condition is not in the knowledge base.
                # 0 when it is in the knowledge base but the search did not rank it.
                "inKnowledgeBase": candidate is not None,
                "evidenceScore": candidate.score if candidate else None,
                "matchedSymptoms": candidate.matched if candidate else [],
            }
        )
    return out[:5]


def _percent(value) -> int | None:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


# When the chair gave no number: a rough share by its likelihood word.
_DEFAULT_PERCENT = {"high": 60, "medium": 25, "low": 8}


def with_probabilities(conditions: list[dict]) -> list[dict]:
    """Every condition with a consistent "AI estimate" percentage, for the
    doctor: missing ones filled from the likelihood, never above 100 in
    total, and never higher than a condition listed before it."""
    out = [dict(c) for c in conditions]
    for c in out:
        if c.get("probability") is None:
            c["probability"] = _DEFAULT_PERCENT.get(c.get("likelihood"), 8)
    total = sum(c["probability"] for c in out)
    if total > 100:
        for c in out:
            c["probability"] = int(c["probability"] * 100 / total)
    for previous, c in zip(out, out[1:]):
        c["probability"] = min(c["probability"], previous["probability"])
    return out


def _add_named_conditions(kb: KnowledgeIndex, evidence: Evidence, raw) -> None:
    for item in raw if isinstance(raw, list) else []:
        name = str(item.get("name") or "") if isinstance(item, dict) else ""
        if name and _candidate_for(normalize(name), evidence) is None:
            found = kb.lookup(name)
            if found is not None and found.disease_id not in {c.disease_id for c in evidence.candidates}:
                evidence.candidates.append(found)


def _known_medicines(evidence: Evidence, conditions: list[dict]) -> dict[str, str]:
    """Knowledge-base medicines linked to the listed conditions, with what
    they are used for. (Stored dosage text is not trusted: the sources were
    inconsistent about it.)"""
    listed = {normalize(c.get("kbName") or c["name"]) for c in conditions}
    return {
        d["name"]: d.get("uses", "")
        for c in evidence.candidates
        if normalize(c.name) in listed
        for d in c.drugs
    }


def _hosted(llm: Llm) -> bool:
    """Whether the last answer came from a clinical model (Gemini, or the
    offline medical model). The small general model is not trusted with
    conditions or medicines."""
    return clinical(llm)


def _patient_advice(items: list[str], kb: KnowledgeIndex | None) -> list[str]:
    """Advice lines for the patient, without any that name a medicine:
    medicines are for the doctor to decide, whatever the model wrote."""
    if kb is None:
        return items
    return [item for item in items if not kb.mentions_drug(item)]


# --- the pipeline ---------------------------------------------------------------

_SOLO = """You are a clinical triage assistant preparing a pre-consultation \
summary for a hospital doctor. You do not diagnose. Reply with one JSON object \
with exactly these keys:
"summary": two or three plain sentences restating the patient's complaint.
"urgency": one of "routine", "soon", "urgent", "emergency".
"department": the one department best suited to see this patient, copied exactly \
from: """ + ", ".join(DEPARTMENTS) + f""". "{GENERAL_OPD}" when no specialty owns \
the complaint, "{EMERGENCY_DEPT}" when the urgency is emergency.
"precautions": up to four short, safe self-care instructions for the patient \
while they wait. Never name a medicine or a dose.
"lifestyle_advice": up to three short points on rest, diet or habits.
"doctor_notes": up to four short points the doctor may want to check or ask.
Use only the information given. If something is unknown, do not invent it."""


OFFLINE_NOTE = (
    "Possible conditions and medicines come from the specialist panel, which "
    "needs an internet connection. This report was written without it."
)


def _department(value, urgency: str, age: int | None = None) -> str:
    """One of `DEPARTMENTS`. An emergency always goes to the emergency
    department, whatever the model said; a child (under 16, as for the
    panel) whom the model sent to General OPD goes to Pediatrics."""
    if urgency == "emergency":
        return EMERGENCY_DEPT
    wanted = str(value or "").strip().lower()
    found = next((name for name in DEPARTMENTS if name.lower() == wanted), GENERAL_OPD)
    if found == GENERAL_OPD and age is not None and age < 16:
        return PEDIATRICS
    return found


def _report(conclusion: dict, urgency: str, flags: list[str], session: IntakeSession, **extra) -> dict:
    base = {
        "urgency": urgency,
        "department": _department(conclusion.get("department"), urgency, session.age),
        "summary": str(conclusion.get("summary") or "").strip(),
        "possibleConditions": [],
        "medicines": [],
        "medicinesDropped": 0,
        "medicinesNote": "",
        "clinicalSummary": "",
        # Each measured vital against its normal range (vitals.py).
        "vitalsAssessment": assess_vitals(session.vitals, session.age),
        "precautions": _strings(conclusion.get("precautions"), 5),
        # knowledge_base | written | mixed | none | unreviewed (see precautions.py)
        "precautionsSource": "unreviewed",
        "lifestyleAdvice": _strings(conclusion.get("lifestyle_advice"), 4),
        "doctorNotes": _strings(conclusion.get("doctor_notes"), 5),
        "panel": [],
        "discussion": "",
        "panelNote": "",
        "matchedSymptoms": [],
        "vitalFlags": flags,
        "vitalsMeasured": bool(session.vitals),
        "knowledgeUsed": False,
        "disclaimer": DISCLAIMER,
        # The vitals came from the test band in the back office's preview.
    }
    full = base | extra
    # The doctor sees everything, before the patient filter (sensitive.py
    # hides pregnancy and sexual-health wording from the patient only).
    full["doctorView"] = copy.deepcopy({
        "summary": full.get("summary", ""),
        "clinicalSummary": full.get("clinicalSummary", ""),
        "conditions": full.get("doctorConditions")
        or with_probabilities(full.get("possibleConditions") or []),
        "medicines": full.get("doctorMedicines") or full.get("medicines") or [],
        "doctorNotes": full.get("doctorNotes", []),
        "discussion": full.get("discussion", ""),
        "panel": full.get("panel", []),
        # Medicines the writer suggested and the review or the rules refused, and why.
        "medicinesRejected": full.get("medicinesRejected", []),
        # RAG: the guideline passages the models were given, [S1].. as cited.
        "guidelineEvidence": full.get("guidelineEvidence", []),
        "guidelineNote": full.get("guidelineNote", ""),
    })
    full.pop("doctorConditions", None)
    full.pop("doctorMedicines", None)
    full.pop("guidelineEvidence", None)
    full.pop("medicinesRejected", None)
    full.pop("guidelineNote", None)
    could_conceive = session.gender == "female" and 12 <= session.age <= 50
    return sensitive.clean(
        full, session.symptoms, session.medications or "", could_conceive,
        getattr(session, "pregnancy", "") or "",
    )


async def _solo(
    session: IntakeSession, llm: Llm, flags: list[str], floor: str, case: str, note: str
) -> dict:
    """One model writes the summary. It is not trusted to name conditions or
    medicines: a small offline model gets those wrong too often."""
    conclusion = await llm.json(_SOLO, case)
    urgency = _raise(_one_of(conclusion.get("urgency"), URGENCY, "soon"), floor)
    # No second model checks these, so the rules in code are all they get.
    advice = [
        line for line in _strings(conclusion.get("precautions"), 5)
        if precautions.acceptable(line, None)
    ]  # fmt: skip
    return _report(
        conclusion, urgency, flags, session,
        precautions=advice, panelNote=note, generator=llm.name,
    )  # fmt: skip


FALLBACK_NOTE = (
    "A problem stopped the full review of this case, so possible conditions and "
    "medicines are not included in this report."
)


async def fallback_report(session: IntakeSession, llm: Llm) -> dict:
    """A plain report for when the full pipeline failed unexpectedly: the
    patient still leaves with a summary, urgency and advice."""
    flags, floor = vital_flags(session.vitals, session.age)
    return await _solo(session, llm, flags, floor, "\n".join(_case_lines(session, flags)), FALLBACK_NOTE)


async def build_report(
    session: IntakeSession,
    llm: Llm,
    kb: KnowledgeIndex | None,
    panel: SpecialistPanel | None = None,
    panel_size: int = 5,
    progress: ReportProgress | None = None,
    history: str = "",
    retriever=None,
    writer_llm: Llm | None = None,
    lean: bool = False,
) -> dict:
    """`progress`, when given, follows each step for the waiting screen.
    `history` is the patient's earlier, doctor-confirmed visits
    (patients.service.history_text), empty for a new patient.
    `retriever` (app.kb.retrieve.Retriever) searches the guideline database
    twice: before the panel (pass 1) and before the writer (pass 2).
    `writer_llm` (optional, `gemini_report_model`) writes the final report:
    the draft, the condition check and the pharmacist review; it falls back
    to the main model on its own. `lean` (offline, on the slow local model):
    the stored precautions are used without a model choosing among them,
    and the case carries fewer, shorter guideline passages."""
    writer = writer_llm or llm
    progress = progress or ReportProgress()
    flags, floor = vital_flags(session.vitals, session.age)
    if panel is None:
        progress.at("writing")
        return await _solo(session, llm, flags, floor, "\n".join(_case_lines(session, flags)), OFFLINE_NOTE)

    symptoms, suggested, look_up = await understand(session, llm)
    progress.at("evidence")

    async def old_evidence() -> Evidence:
        if kb is None:
            return Evidence(unmatched=[g[0] for g in symptoms])
        return await anyio.to_thread.run_sync(kb.retrieve, symptoms, session.symptoms)

    # Side by side: the symptom-overlap search, RAG pass 1 (guideline passages
    # on how this presentation is assessed) and the brand look-up.
    evidence, guide1, brands = await asyncio.gather(
        old_evidence(),
        anyio.to_thread.run_sync(rag.pass1, retriever, session, symptoms, look_up),
        anyio.to_thread.run_sync(rag.brands_taken, retriever, session.medications or ""),
    )
    rag.number(guide1)

    case = "\n".join([
        *_case_lines(session, flags), *([brands] if brands else []), *([history] if history else []), "",
        _evidence_text(evidence, LEAN_CANDIDATES if lean else None),
        "", guide1.prompt("Guideline passages on assessing this presentation",
                          *((LEAN_PASS1, LEAN_CHARS) if lean else ())),
    ])  # fmt: skip
    asked = choose_panel(suggested, session.age, session.gender, panel_size)
    progress.panel(asked)
    try:
        result = await panel.run(case, asked, progress)
    except PanelError as e:
        log.warning("The specialist panel failed: %s", e)
        result = None

    if result is None:
        # Online but without the panel: one model triages, and the report
        # writer below names conditions and medicines under the same review.
        progress.at("writing")
        conclusion = await llm.json(_SOLO, "\n".join(_case_lines(session, flags)))
        if not _hosted(llm):
            return await _solo(
                session, llm, flags, floor, "\n".join(_case_lines(session, flags)),
                "The specialist panel could not be reached, so possible conditions and "
                "medicines are not included in this report.",
            )  # fmt: skip
        opinions: list[dict] = []
        conditions: list[dict] = []
        generator = llm.name
        note = (
            "The specialist panel could not be reached, so this report was prepared "
            "without its discussion."
        )
    else:
        conclusion = result.conclusion
        opinions = [
            {
                "specialist": o["specialist"],
                "relevant": bool(o.get("relevant", True)),
                "assessment": str(o.get("assessment") or "").strip()[:700],
                "urgency": _one_of(o.get("urgency"), URGENCY, "routine"),
            }
            for o in result.opinions
        ]
        # Only specialists who took part are credited with anything.
        members = [o["specialist"] for o in opinions if o["relevant"]]
        raw_conditions = conclusion.get("possible_conditions")
        if kb is not None:
            # A condition the panel named but the search did not surface may
            # still be in the knowledge base, with its drugs and precautions.
            await anyio.to_thread.run_sync(_add_named_conditions, kb, evidence, raw_conditions)
        conditions = _conditions(raw_conditions, evidence, members, result.opinions)
        generator = result.model
        note = ""

    urgency = _raise(_one_of(conclusion.get("urgency"), URGENCY, "soon"), floor)
    # A specialist who called an emergency is not overruled below "urgent".
    if any(o["relevant"] and o["urgency"] == "emergency" for o in opinions):
        urgency = _raise(urgency, "urgent")

    # The report writer (report_writer.py): a draft with medicines and
    # doses, a check of every condition against what the patient said, an
    # independent review, then the rules in code. Steps that do not depend
    # on each other run side by side.
    progress.at("precautions")
    case_text = "\n".join(_case_lines(session, flags))
    vitals_line = describe_vitals(assess_vitals(session.vitals, session.age))
    chair = None if result is None else conclusion
    known = _known_medicines(evidence, conditions)
    # The condition check reads only the case, not the treatment passages:
    # it starts now and runs while pass 2 searches.
    check_task = (
        asyncio.create_task(report_writer.check_conditions(writer, case, vitals_line, conditions))
        if result is not None else None
    )  # fmt: skip
    # RAG pass 2: treatment and doses for the conditions the panel concluded
    # (without the panel, for the presentation as a whole).
    if conditions:
        guide2 = await anyio.to_thread.run_sync(rag.pass2, retriever, session, conditions)
    else:
        guide2 = await anyio.to_thread.run_sync(
            lambda: rag.pass2(retriever, session, [{"name": rag.pass1_question(session, symptoms)}])
        )
    sources = rag.number(guide1, guide2)
    printed_text, printed_rows = await anyio.to_thread.run_sync(
        rag.printed_doses, retriever, session, conditions if conditions else []
    )
    case = case + "\n\n" + guide2.prompt("Guideline passages on treatment and doses",
                                         *((LEAN_PASS2, LEAN_CHARS) if lean else ()))
    if printed_text:
        case = case + "\n\n" + printed_text
    ruled_out: list[str] = []
    # Doubted by the condition check, with why: the doctor sees them all.
    doubted: list[dict] = []
    try:
        if check_task is not None:
            draft = await report_writer.draft(writer, case, vitals_line, urgency, conditions, chair, known)
            kept = await check_task
        else:
            draft = await report_writer.draft(writer, case, vitals_line, urgency, [], None, known)
            named = report_writer.written_conditions(draft)
            kept = await report_writer.check_conditions(writer, case, vitals_line, named)
            # Written conditions are shown only once checked.
            raw = [{**c, "raised_by": ""} for c in named if kept is not None and c["name"] in kept]
            if kb is not None:
                await anyio.to_thread.run_sync(_add_named_conditions, kb, evidence, raw)
            conditions = _conditions(raw, evidence, [], [])
            known = _known_medicines(evidence, conditions)
            kept = None
        if kept is not None:
            # The panel can let through a condition the knowledge base matched
            # on one shared symptom; the check drops what does not fit.
            ruled_out = [c["name"] for c in conditions if c["name"] not in kept]
            reasons = getattr(kept, "reasons", {})
            doubted = [
                {**c, "doubtReason": reasons.get(c["name"], "")}
                for c in conditions
                if c["name"] not in kept
            ]
            conditions = [c for c in conditions if c["name"] in kept]
        written, (precaution_lines, precaution_source) = await asyncio.gather(
            report_writer.finish(
                writer, draft, case, vitals_line, urgency, session.age, session.gender,
                conditions, chair, known, session.medications or "",
                getattr(session, "allergies", "") or "", getattr(session, "pregnancy", "") or "",
                getattr(session, "weight_kg", None),
                dose_notes=rag.dose_conflicts(report_writer.drafted_medicines(draft), guide2, printed_rows),
            ),
            precautions.choose(llm, case_text, conditions, urgency, evidence, kb, select=not lean),
        )  # fmt: skip
        # Names as an Indian prescription writes them (paracetamol, not acetaminophen).
        for key in ("medicines", "doctorMedicines"):
            written[key] = [{**m, "name": indian_name(m.get("name", ""))} for m in written.get(key) or []]
        written["medicines"] = report_writer.label(written["medicines"], known)
        written["doctorMedicines"] = await anyio.to_thread.run_sync(
            rag.check_doses, retriever, written.get("doctorMedicines", []), guide2, printed_rows
        )
        written["medicines"] = await anyio.to_thread.run_sync(
            rag.check_doses, retriever, written["medicines"], guide2, printed_rows
        )
    except LlmError as e:
        if check_task is not None and not check_task.done():
            check_task.cancel()
        log.warning("The report writer failed: %s", e)
        written = {
            "clinicalSummary": "", "medicines": [],
            "medicinesNote": "Medicines could not be prepared for this report; the doctor will decide.",
            "medicinesReviewed": 0, "lifestyleAdvice": [], "doctorNotes": [], "doctorMedicines": [],
        }  # fmt: skip
        precaution_lines, precaution_source = await precautions.choose(
            llm, case_text, conditions, urgency, evidence, kb, select=not lean
        )

    return _report(
        conclusion,
        urgency,
        flags,
        session,
        possibleConditions=conditions,
        # Named by the panel, rejected by the review as not fitting the case.
        conditionsRuledOut=ruled_out,
        # For the doctor portal: every condition with an AI percentage, the
        # doubted ones last with the check's reason, and the wider medicine
        # list (injections, children's weight-based doses, emergency care).
        doctorConditions=with_probabilities(conditions) + [
            {**c, "probability": min(c.get("probability") or 5, 10)} for c in doubted
        ],
        doctorMedicines=written.get("doctorMedicines", []),
        medicinesRejected=written.get("medicinesRejected", []),
        medicines=written["medicines"],
        medicinesNote=written["medicinesNote"],
        # Medicines a model wrote but the review or the rules refused.
        medicinesDropped=written["medicinesReviewed"] - len(written["medicines"]),
        clinicalSummary=written["clinicalSummary"],
        precautions=precaution_lines,
        precautionsSource=precaution_source,
        lifestyleAdvice=_patient_advice(
            written["lifestyleAdvice"] or _strings(conclusion.get("lifestyle_advice"), 4), kb
        ),
        doctorNotes=written["doctorNotes"] or _strings(conclusion.get("doctor_notes"), 5),
        panel=opinions,
        discussion=str(conclusion.get("discussion") or "").strip(),
        panelNote=note,
        matchedSymptoms=[m.name for m in evidence.matches],
        knowledgeUsed=evidence.used,
        # The guideline passages both passes gave the models, with labels the
        # summary and medicines may cite (for the doctor; never the patient).
        guidelineEvidence=[p.cite() for p in sources],
        guidelineNote="; ".join(n for n in (guide1.note, guide2.note) if n),
        generator=generator,
        reportWriter=getattr(writer, "name", ""),
    )
