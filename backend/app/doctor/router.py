"""The doctor portal's API (`/api/doctor/...`) and the patient's view of
the doctor's result (`/api/sessions/{id}/final`).

A doctor works only on their own hospital's visits. Picking a patient locks
the visit to that doctor until they finalise or release it, so two doctors
never treat the same patient at once. The AI report is never edited: the
doctor's decisions go into `DoctorReview`, and finalising makes the signed
report the patient receives, in English or Malayalam, as the doctor chooses.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import select

from .. import languages
from ..deps import Db
from ..hospital import service as hospital
from ..hospital.models import Department, HospitalSettings, HospitalUser
from ..models import IntakeSession, Tenant, TriageReport
from ..offline import UNREACHABLE
from ..patient_view import build_patient_view
from ..patients import service as patients
from ..patients.models import Patient
from ..schemas import ApiModel
from .models import DoctorReview

router = APIRouter(prefix="/api/doctor")
patient_router = APIRouter(prefix="/api/sessions/{session_id}/final")

URGENCY_ORDER = {"emergency": 0, "urgent": 1, "soon": 2, "routine": 3}
# A pick older than this no longer blocks another doctor (a doctor who
# walked away without releasing the patient).
LOCK_HOURS = 3
# How far back the queue looks.
QUEUE_HOURS = 24


def doctor(user: Annotated[HospitalUser, Depends(hospital.signed_in)]) -> HospitalUser:
    if user.role != "doctor":
        raise HTTPException(403, "The doctor portal is for doctors")
    return user


Doctor = Annotated[HospitalUser, Depends(doctor)]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def visit_number(session_id: str) -> str:
    """What the kiosk shows the patient and the doctor calls out."""
    return session_id[:6].upper()


def _locked_by_other(review: DoctorReview | None, me: HospitalUser) -> bool:
    if review is None or review.status != "in_consultation" or review.doctor_id == me.id:
        return False
    return _utc(review.picked_at) > datetime.now(timezone.utc) - timedelta(hours=LOCK_HOURS)


def _own_visit(db: Db, me: HospitalUser, session_id: str) -> tuple[IntakeSession, TriageReport]:
    session = db.get(IntakeSession, session_id)
    if session is None or session.tenant_id != me.tenant_id:
        raise HTTPException(404, "Visit not found")
    report = db.get(TriageReport, session_id)
    if report is None:
        raise HTTPException(409, "Medora has not finished this patient's report yet")
    return session, report


def _my_department(db: Db, me: HospitalUser) -> Department | None:
    return db.get(Department, me.department_id) if me.department_id else None


# --- the queue ---------------------------------------------------------------------


@router.get("/me")
def whoami(me: Doctor, db: Db) -> dict:
    department = _my_department(db, me)
    settings = db.get(HospitalSettings, me.tenant_id)
    tenant = db.get(Tenant, me.tenant_id)
    return {
        "name": me.name,
        "qualification": me.qualification,
        "registrationNumber": me.registration_number,
        "department": department.name if department else "",
        "reportDepartment": department.report_department if department else "",
        "hospital": (settings.display_name if settings and settings.display_name else tenant.name if tenant else ""),
    }


@router.get("/queue")
def queue(me: Doctor, db: Db, scope: str = Query(default="department", pattern="^(department|all)$")) -> dict:
    """Patients with a Medora report from the last day who have not been
    finalised: the emergencies first, then by how long they have waited."""
    since = datetime.now(timezone.utc) - timedelta(hours=QUEUE_HOURS)
    rows = db.execute(
        select(IntakeSession, TriageReport, DoctorReview)
        .join(TriageReport, TriageReport.session_id == IntakeSession.id)
        .outerjoin(DoctorReview, DoctorReview.session_id == IntakeSession.id)
        .where(IntakeSession.tenant_id == me.tenant_id, IntakeSession.created_at >= since)
    ).all()
    department = _my_department(db, me)
    wanted = department.report_department if department and scope == "department" else ""
    now = datetime.now(timezone.utc)
    items, done_today = [], 0
    for session, report, review in rows:
        if review is not None and review.status == "final":
            if review.doctor_id == me.id:
                done_today += 1
            continue
        data = report.data or {}
        if wanted and (data.get("department") or "General OPD") != wanted:
            continue
        vitals = data.get("vitalsAssessment") or []
        items.append(
            {
                "id": session.id,
                "visitNumber": visit_number(session.id),
                "at": session.created_at.isoformat(),
                "waitingMinutes": int((now - _utc(session.created_at)).total_seconds() // 60),
                "name": session.name,
                "age": session.age,
                "gender": session.gender,
                "symptoms": session.symptoms,
                "urgency": data.get("urgency", "soon"),
                "department": data.get("department", ""),
                "abnormalVitals": sum(1 for v in vitals if v.get("status") in ("low", "high")),
                "returning": bool(session.patient_id and _visits(db, session.patient_id) > 1),
                "status": "in_consultation" if review is not None else "waiting",
                "withDoctor": review.doctor_name if review is not None else "",
                "mine": review is not None and review.doctor_id == me.id,
            }
        )
    items.sort(key=lambda i: (not i["mine"], URGENCY_ORDER.get(i["urgency"], 2), i["at"]))
    return {
        "patients": items,
        "department": department.name if department else "",
        "filtered": bool(wanted),
        "doneToday": done_today,
    }


def _visits(db: Db, patient_id: str) -> int:
    patient = db.get(Patient, patient_id)
    return patient.visits if patient else 0


# --- one consultation --------------------------------------------------------------


def _review_out(review: DoctorReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "status": review.status,
        "doctorId": review.doctor_id,
        "doctorName": review.doctor_name,
        "pickedAt": review.picked_at.isoformat() if review.picked_at else None,
        "finalizedAt": review.finalized_at.isoformat() if review.finalized_at else None,
        "diagnosis": review.diagnosis or [],
        "medicines": review.medicines or [],
        "tests": review.tests or [],
        "advice": review.advice or [],
        "followUp": review.follow_up,
        "privateNotes": review.private_notes,
    }


def _ai_medicines(data: dict) -> list[dict]:
    """Medora's suggestions as editable lines, marked as from Medora."""
    view = data.get("doctorView") or {}
    return [
        {
            "name": m.get("name", ""),
            "form": m.get("form", ""),
            "strength": m.get("strength", ""),
            "dose": m.get("dose", ""),
            "route": m.get("route", ""),
            "frequency": m.get("frequency", ""),
            "duration": m.get("duration", ""),
            "maxDaily": m.get("maxDaily", ""),
            "instructions": m.get("caution", ""),
            "fromAi": True,
        }
        for m in (view.get("medicines") or data.get("medicines") or [])
    ]


@router.post("/visits/{session_id}/pick")
def pick(session_id: str, me: Doctor, db: Db, request: Request) -> dict:
    """Takes the patient: locked to this doctor until finalised or released.
    The draft starts from Medora's suggested medicines and advice."""
    session, report = _own_visit(db, me, session_id)
    review = db.get(DoctorReview, session_id)
    if review is not None and review.status == "final":
        raise HTTPException(409, f"{review.doctor_name} has already finalised this patient's report")
    if _locked_by_other(review, me):
        raise HTTPException(409, f"{review.doctor_name} is already seeing this patient")
    data = report.data or {}
    if review is None:
        review = DoctorReview(
            session_id=session.id,
            tenant_id=me.tenant_id,
            patient_id=session.patient_id,
            doctor_id=me.id,
            doctor_name=me.name,
            medicines=_ai_medicines(data),
            advice=[*(data.get("precautions") or []), *(data.get("lifestyleAdvice") or [])][:8],
            diagnosis=[],
            tests=[],
        )
        db.add(review)
    else:
        # Taking over a stale pick, or picking again after releasing.
        review.doctor_id, review.doctor_name = me.id, me.name
        review.status = "in_consultation"
        review.picked_at = datetime.now(timezone.utc)
    hospital.audit(db, me, "patient.picked", f"{session.name} ({visit_number(session.id)})")
    db.commit()
    return _review_out(review)


@router.post("/visits/{session_id}/release", status_code=204)
def release(session_id: str, me: Doctor, db: Db) -> None:
    """Puts the patient back in the queue for any doctor."""
    session, _ = _own_visit(db, me, session_id)
    review = db.get(DoctorReview, session_id)
    if review is None or review.doctor_id != me.id or review.status != "in_consultation":
        raise HTTPException(409, "This patient is not with you")
    db.delete(review)
    hospital.audit(db, me, "patient.released", f"{session.name} ({visit_number(session.id)})")
    db.commit()


@router.get("/visits/{session_id}")
def visit(session_id: str, me: Doctor, db: Db) -> dict:
    """Everything the doctor needs: what the patient said, the vitals,
    Medora's doctor report (all conditions with an AI percentage, all
    suggested medicines), the patient's history, and the draft."""
    session, report = _own_visit(db, me, session_id)
    data = report.data or {}
    review = db.get(DoctorReview, session_id)
    hospital.audit(db, me, "visit.viewed", f"{session.name} ({visit_number(session.id)})")
    db.commit()
    patient = db.get(Patient, session.patient_id) if session.patient_id else None
    return {
        "id": session.id,
        "visitNumber": visit_number(session.id),
        "at": session.created_at.isoformat(),
        "mode": session.mode,
        "language": getattr(session, "language", "en") or "en",
        "patient": {
            "name": session.name,
            "age": session.age,
            "gender": session.gender,
            "phone": session.phone,
            "email": session.email,
            "weightKg": session.weight_kg,
        },
        "told": {
            "symptoms": session.symptoms,
            "duration": session.duration,
            "medicationsTaken": session.medications,
            "allergies": session.allergies,
            "pregnancy": session.pregnancy,
            "conditions": session.chronic_conditions,
            "regularMedicines": session.regular_medicines,
            "surgeries": session.past_surgeries,
            "habits": session.habits,
        },
        "ai": {
            "urgency": data.get("urgency"),
            "department": data.get("department"),
            "vitals": data.get("vitalsAssessment") or [],
            "vitalFlags": data.get("vitalFlags") or [],
            **(data.get("doctorView") or {
                "summary": data.get("summary", ""),
                "clinicalSummary": data.get("clinicalSummary", ""),
                "conditions": data.get("possibleConditions") or [],
                "medicines": data.get("medicines") or [],
                "doctorNotes": data.get("doctorNotes") or [],
            }),
            "precautions": data.get("precautions") or [],
            "generator": data.get("generator", ""),
            "note": data.get("panelNote", ""),
        },
        "record": patients.record_out(patient),
        "history": patients.timeline(db, session.patient_id, exclude=session.id),
        "review": _review_out(review),
        "lockedByOther": _locked_by_other(review, me),
    }


class Diagnosis(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=500)


class MedicineLine(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    form: str = Field(default="", max_length=40)
    strength: str = Field(default="", max_length=80)
    dose: str = Field(default="", max_length=80)
    route: str = Field(default="", max_length=40)
    frequency: str = Field(default="", max_length=80)
    duration: str = Field(default="", max_length=80)
    max_daily: str = Field(default="", max_length=80)
    instructions: str = Field(default="", max_length=300)
    from_ai: bool = False


class Draft(ApiModel):
    diagnosis: list[Diagnosis] = Field(default_factory=list, max_length=10)
    medicines: list[MedicineLine] = Field(default_factory=list, max_length=15)
    tests: list[str] = Field(default_factory=list, max_length=15)
    advice: list[str] = Field(default_factory=list, max_length=15)
    follow_up: str = Field(default="", max_length=300)
    private_notes: str = Field(default="", max_length=3000)
    # The language of the patient's signed report, chosen by the doctor
    # (English unless the doctor switches it).
    language: str = Field(default="en", max_length=8)


def _mine(db: Db, me: HospitalUser, session_id: str) -> tuple[IntakeSession, TriageReport, DoctorReview]:
    session, report = _own_visit(db, me, session_id)
    review = db.get(DoctorReview, session_id)
    if review is None or review.doctor_id != me.id:
        raise HTTPException(409, "Pick this patient from the queue first")
    if review.status == "final":
        raise HTTPException(409, "This report is already finalised")
    return session, report, review


class _InLanguage:
    """The visit as the patient-view builder reads it, in the language the
    doctor chose for the signed report (the stored visit is not changed)."""

    def __init__(self, session: IntakeSession, language: str) -> None:
        self._session = session
        self.language = language

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _apply(review: DoctorReview, body: Draft) -> None:
    review.diagnosis = [d.model_dump() for d in body.diagnosis]
    review.medicines = [m.model_dump(by_alias=True) for m in body.medicines]
    review.tests = [t.strip() for t in body.tests if t.strip()]
    review.advice = [a.strip() for a in body.advice if a.strip()]
    review.follow_up = body.follow_up.strip()
    review.private_notes = body.private_notes.strip()


@router.put("/visits/{session_id}/draft")
def save_draft(session_id: str, body: Draft, me: Doctor, db: Db) -> dict:
    _, _, review = _mine(db, me, session_id)
    _apply(review, body)
    db.commit()
    return _review_out(review)


@router.post("/visits/{session_id}/finalize")
async def finalize(session_id: str, body: Draft, me: Doctor, db: Db, request: Request) -> dict:
    """Signs the consultation: the patient's final report is made from the
    doctor's decisions (never the AI's), in the language the doctor chose
    (English or Malayalam), with the doctor's name and registration number."""
    session, report, review = _mine(db, me, session_id)
    if not body.diagnosis:
        raise HTTPException(422, "Add at least one diagnosis before finalising")
    for m in body.medicines:
        if not m.dose.strip() or not m.frequency.strip():
            raise HTTPException(422, f"Give the dose and how often for {m.name}")
    _apply(review, body)
    data = report.data or {}
    source = {
        "summary": "Your doctor's diagnosis: " + ", ".join(d.name for d in body.diagnosis) + ".",
        "clinicalSummary": "",
        # The doctor's diagnosis: no AI percentage on it.
        "possibleConditions": [{"name": d.name, "likelihood": "high", "probability": None} for d in body.diagnosis],
        "doctorDiagnosis": True,
        "medicines": [
            {
                "name": m.name,
                "form": m.form,
                "strength": m.strength,
                "dose": m.dose,
                "frequency": m.frequency,
                "duration": m.duration,
                "maxDaily": m.max_daily,
                "caution": m.instructions,
                "purpose": "",
                "prescription": True,
            }
            for m in body.medicines
        ],
        "vitalsAssessment": data.get("vitalsAssessment") or [],
        "vitalFlags": [],
        "precautions": review.advice,
        "lifestyleAdvice": [],
        "testsAdvised": review.tests,
        "followUp": review.follow_up,
        "medicinesNote": "" if body.medicines else "Your doctor has not prescribed any medicine.",
        "panelNote": "",
    }
    state = request.app.state
    language = languages.supported(body.language)
    view = await build_patient_view(state.llm if state.runtime.online else None, source, _InLanguage(session, language))
    department = _my_department(db, me)
    settings = db.get(HospitalSettings, me.tenant_id)
    tenant = db.get(Tenant, me.tenant_id)
    now = datetime.now(timezone.utc)
    review.final_report = {
        "view": view,
        "doctor": {
            "name": me.name,
            "qualification": me.qualification,
            "registrationNumber": me.registration_number,
            "department": department.name if department else "",
        },
        "hospital": {
            "name": (settings.display_name if settings and settings.display_name else tenant.name if tenant else ""),
            "address": settings.address if settings else "",
            "phone": settings.phone if settings else "",
            "email": settings.email if settings else "",
            "note": settings.letterhead_note if settings else "",
            "logo": settings.logo if settings else "",
        },
        "visitNumber": visit_number(session.id),
        "finalizedAt": now.isoformat(),
        "language": language,
    }
    review.status = "final"
    review.finalized_at = now
    hospital.audit(db, me, "consultation.finalized", f"{session.name} ({visit_number(session.id)})")
    # Only in the hospital's own audit log: the company's log never sees
    # what a hospital's doctors do.
    db.commit()
    return _review_out(review)


@router.get("/suggest")
async def suggest(
    request: Request,
    user: Doctor,
    kind: Annotated[str, Query(pattern="^(medicine|diagnosis|test)$")],
    q: Annotated[str, Query(max_length=80)] = "",
) -> list[dict]:
    """Type-ahead for the consultation: medicines (usual strength, form and
    route; brand names lead to the generic), diagnoses and tests. Fills in
    fields only; the doctor still sets the dose and how often."""
    from . import catalogue

    if len(q.strip()) < 2:
        return []
    state = request.app.state
    if kind == "medicine":
        retriever = getattr(state, "retriever", None)
        extra = retriever.drug_names() if retriever is not None else []
        return catalogue.medicines(q, extra)
    if kind == "diagnosis":
        kb = getattr(state, "kb", None)
        extra = kb.disease_names() if kb is not None and hasattr(kb, "disease_names") else []
        return catalogue.names(q, catalogue.DIAGNOSES, extra)
    return catalogue.names(q, catalogue.TESTS)


@router.get("/consultations")
def consultations(me: Doctor, db: Db, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    """This doctor's signed consultations, newest first."""
    rows = db.execute(
        select(DoctorReview, IntakeSession)
        .join(IntakeSession, IntakeSession.id == DoctorReview.session_id)
        .where(DoctorReview.doctor_id == me.id, DoctorReview.status == "final")
        .order_by(DoctorReview.finalized_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": visit.id,
            "visitNumber": visit_number(visit.id),
            "finalizedAt": review.finalized_at.isoformat() if review.finalized_at else None,
            "name": visit.name,
            "age": visit.age,
            "diagnosis": [d.get("name") for d in review.diagnosis or []],
            "medicines": len(review.medicines or []),
        }
        for review, visit in rows
    ]


# --- the patient's side ------------------------------------------------------------


def _final(db: Db, request: Request, session_id: str) -> tuple[IntakeSession, DoctorReview | None, dict | None]:
    """The visit, its doctor review and its report. Without internet (or the
    database out of reach) a visit made at this kiosk is read from memory:
    the patient's page then says it is waiting for the doctor."""
    state = request.app.state
    if state.runtime.online:
        try:
            session = db.get(IntakeSession, session_id)
            if session is not None:
                report = db.get(TriageReport, session_id)
                return session, db.get(DoctorReview, session_id), (report.data if report else None)
        except UNREACHABLE:
            db.rollback()
    held = state.offline.visit(session_id)
    if held is None:
        raise HTTPException(404, "Visit not found")
    return held.session, None, held.report


@patient_router.get("")
def final_status(session_id: str, db: Db, request: Request) -> dict:
    """For the patient's page (reached by the QR code on the kiosk): where
    their visit is, and the doctor's final report once signed. Guarded, like
    the report itself, by the visit's unguessable id."""
    session, review, data = _final(db, request, session_id)
    status = (
        "final" if review is not None and review.status == "final"
        else "in_consultation" if review is not None
        else "waiting" if data is not None and data.get("awaitingDoctor")
        else "no_review" if data is not None
        else "preparing"
    )  # fmt: skip
    return {
        "status": status,
        "visitNumber": visit_number(session.id),
        "name": session.name.split()[0] if session.name else "",
        "doctor": review.doctor_name if review is not None else "",
        "final": review.final_report if status == "final" else None,
    }


@patient_router.get(".pdf")
def final_pdf(session_id: str, db: Db, request: Request) -> Response:
    from ..report_pdf import render_final_pdf

    session, review, _ = _final(db, request, session_id)
    if review is None or review.status != "final" or not review.final_report:
        raise HTTPException(404, "Your doctor has not finalised your report yet")
    return Response(
        render_final_pdf(session, review.final_report),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="medora-prescription.pdf"'},
    )
