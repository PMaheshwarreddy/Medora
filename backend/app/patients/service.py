"""Finding, creating and updating patient records, and the history a
doctor (and the report AI) may use."""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IntakeSession
from .models import Patient


def digits(phone: str) -> str:
    """The number without spaces or a country code, for matching: the last
    ten digits (Indian mobile numbers)."""
    only = re.sub(r"\D", "", phone or "")
    return only[-10:] if len(only) > 10 else only


def mask(name: str) -> str:
    """"Asha Rao" -> "A*** R***": enough for the patient to recognise
    themselves, not enough to tell a stranger who else uses the number."""
    return " ".join(part[0] + "***" for part in name.split() if part) or "***"


def age_of(patient: Patient) -> int | None:
    if patient.birth_year is None:
        return None
    return max(0, datetime.now(timezone.utc).year - patient.birth_year)


def lookup(db: Session, tenant_id: str, phone: str) -> list[dict]:
    """The people this hospital knows under a phone number, masked."""
    number = digits(phone)
    if len(number) < 7:
        return []
    rows = db.scalars(
        select(Patient)
        .where(Patient.tenant_id == tenant_id, Patient.phone == number)
        .order_by(Patient.created_at)
        .limit(8)
    )
    return [{"id": p.id, "label": mask(p.name), "age": age_of(p), "gender": p.gender} for p in rows]


def _merge(old: str, new: str) -> str:
    """Comma lists joined without repeats ("none" never stays beside items)."""
    items: list[str] = []
    for part in [*(old or "").split(","), *(new or "").split(",")]:
        part = part.strip()
        if part and part.lower() not in (i.lower() for i in items):
            items.append(part)
    real = [i for i in items if i.lower() not in ("none", "no", "nil", "no allergies", "ഒന്നുമില്ല", "അലർജിയില്ല")]
    return ", ".join(real or items[-1:])


def same_person(db: Session, session: IntakeSession) -> str | None:
    """For a visit saved offline (no "Have you visited before?" was possible):
    this hospital's record with the same phone number and name, if exactly
    one matches."""
    number = digits(session.phone)
    if len(number) < 7:
        return None
    name = " ".join((session.name or "").lower().split())
    found = [
        p.id
        for p in db.scalars(select(Patient).where(Patient.tenant_id == (session.tenant_id or ""), Patient.phone == number))
        if " ".join((p.name or "").lower().split()) == name
    ]
    return found[0] if len(found) == 1 else None


def attach(db: Session, session: IntakeSession, patient_id: str | None) -> Patient:
    """Links the visit to its patient (the one picked at the kiosk, if it is
    this hospital's) or a new record, and merges what was reported now.
    In the caller's transaction."""
    patient = db.get(Patient, patient_id) if patient_id else None
    if patient is None or patient.tenant_id != session.tenant_id:
        patient = Patient(
            tenant_id=session.tenant_id or "",
            name=session.name,
            birth_year=datetime.now(timezone.utc).year - session.age,
            gender=session.gender,
            phone=digits(session.phone),
        )
        db.add(patient)
    patient.email = session.email or patient.email
    patient.gender = session.gender or patient.gender
    patient.allergies = _merge(patient.allergies, session.allergies or "")
    patient.conditions = _merge(patient.conditions, getattr(session, "chronic_conditions", "") or "")
    patient.regular_medicines = _merge(patient.regular_medicines, getattr(session, "regular_medicines", "") or "")
    patient.surgeries = _merge(patient.surgeries, getattr(session, "past_surgeries", "") or "")
    if getattr(session, "weight_kg", None):
        patient.weight_kg = session.weight_kg
    patient.visits = (patient.visits or 0) + 1
    db.flush()
    session.patient_id = patient.id
    return patient


def history_text(db: Session, session: IntakeSession) -> str:
    """For the report AI: the patient's earlier, doctor-confirmed visits and
    what they reported before. Empty for a new patient. Never the AI's own
    earlier guesses."""
    from ..doctor.models import DoctorReview

    patient_id = getattr(session, "patient_id", None)
    if not patient_id:
        return ""
    patient = db.get(Patient, patient_id)
    if patient is None:
        return ""
    lines = []
    for label, value in (
        ("Long-term conditions reported before", patient.conditions),
        ("Regular medicines reported before", patient.regular_medicines),
        ("Allergies reported before", patient.allergies),
        ("Past operations", patient.surgeries),
    ):
        if value:
            lines.append(f"{label}: {value}")
    reviews = db.execute(
        select(DoctorReview, IntakeSession)
        .join(IntakeSession, IntakeSession.id == DoctorReview.session_id)
        .where(
            DoctorReview.patient_id == patient_id,
            DoctorReview.status == "final",
            DoctorReview.session_id != session.id,
        )
        .order_by(DoctorReview.finalized_at.desc())
        .limit(5)
    ).all()
    for review, visit in reviews:
        diagnosis = ", ".join(d.get("name", "") for d in review.diagnosis or [] if d.get("name")) or "no diagnosis recorded"
        medicines = ", ".join(m.get("name", "") for m in review.medicines or [] if m.get("name")) or "no medicines"
        lines.append(
            f"Visit on {visit.created_at:%d %b %Y}: complained of {visit.symptoms[:200]}; "
            f"doctor's diagnosis: {diagnosis}; prescribed: {medicines}"
        )
    if not lines:
        return ""
    return "Known history of this patient (from earlier visits at this hospital):\n- " + "\n- ".join(lines)


def timeline(db: Session, patient_id: str | None, exclude: str | None = None) -> list[dict]:
    """The patient's other visits, newest first, for the doctor portal."""
    from ..doctor.models import DoctorReview
    from ..models import TriageReport

    if not patient_id:
        return []
    rows = db.execute(
        select(IntakeSession, TriageReport, DoctorReview)
        .outerjoin(TriageReport, TriageReport.session_id == IntakeSession.id)
        .outerjoin(DoctorReview, DoctorReview.session_id == IntakeSession.id)
        .where(IntakeSession.patient_id == patient_id, IntakeSession.id != (exclude or ""))
        .order_by(IntakeSession.created_at.desc())
        .limit(20)
    ).all()
    out = []
    for visit, report, review in rows:
        final = review is not None and review.status == "final"
        out.append(
            {
                "id": visit.id,
                "at": visit.created_at.isoformat(),
                "symptoms": visit.symptoms,
                "vitals": visit.vitals,
                "urgency": (report.data or {}).get("urgency") if report else None,
                "aiDepartment": (report.data or {}).get("department") if report else None,
                "doctor": review.doctor_name if final else "",
                "diagnosis": [d.get("name") for d in (review.diagnosis or [])] if final else [],
                "medicines": [
                    " ".join(x for x in (m.get("name"), m.get("strength"), m.get("dose"), m.get("frequency")) if x)
                    for m in (review.medicines or [])
                ]
                if final
                else [],
                "followUp": review.follow_up if final else "",
            }
        )
    return out


def record_out(patient: Patient | None) -> dict | None:
    if patient is None:
        return None
    return {
        "id": patient.id,
        "name": patient.name,
        "age": age_of(patient),
        "gender": patient.gender,
        "phone": patient.phone,
        "allergies": patient.allergies,
        "conditions": patient.conditions,
        "regularMedicines": patient.regular_medicines,
        "surgeries": patient.surgeries,
        "weightKg": patient.weight_kg,
        "visits": patient.visits,
        "since": patient.created_at.isoformat(),
    }
