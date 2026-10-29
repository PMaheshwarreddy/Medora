from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select

from ..deps import Admin, Db, Kiosk
from ..models import IntakeSession, TriageReport, new_id, now
from ..offline import UNREACHABLE
from ..patients import service as patients
from ..schemas import ApiModel, SessionCreate, SessionOut
from ..vitals_need import vitals_needed

router = APIRouter(prefix="/api/sessions")
intake_router = APIRouter(prefix="/api/intake")


class VitalsCheck(ApiModel):
    symptoms: str = Field(max_length=4000)
    age: int | None = Field(default=None, ge=0, le=130)
    duration: str = Field(default="", max_length=200)
    language: Literal["en", "ml"] = "en"


@intake_router.post("/vitals-check")
async def vitals_check(body: VitalsCheck, request: Request, tenant: Kiosk) -> dict:
    """Whether this complaint calls for vitals. Offline the answer is always
    yes: only the hosted model may waive a measurement."""
    state = request.app.state
    if not state.runtime.online:
        return {"needed": True, "reason": ""}
    needed, reason = await vitals_needed(state.llm, body.symptoms, body.age, body.duration, body.language)
    return {"needed": needed, "reason": reason}


class PhoneLookup(ApiModel):
    phone: str = Field(min_length=7, max_length=32)


@intake_router.post("/patients")
def find_patients(body: PhoneLookup, db: Db, tenant: Kiosk, request: Request) -> list[dict]:
    """The people this hospital knows under a phone number, as masked names
    and ages, for "Have you visited before?". Nothing else about them."""
    if not request.app.state.runtime.online:
        return []
    try:
        return patients.lookup(db, tenant.id, body.phone)
    except UNREACHABLE:
        return []


@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, db: Db, tenant: Kiosk, request: Request):
    """Called by the kiosk when the patient confirms the review screen.
    Without internet the visit is held in memory and copied to the database
    when it is back (offline.py)."""
    state = request.app.state
    fields = body.model_dump(exclude={"patient_id"})
    row = IntakeSession(**fields, tenant_id=tenant.id, id=new_id(), created_at=now())
    stored = False
    if state.runtime.online:
        try:
            db.add(row)
            # The visit joins its patient record (a returning patient picked
            # at the kiosk, or a new one).
            patients.attach(db, row, body.patient_id)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            stored = True
        except UNREACHABLE:
            db.rollback()
            row = IntakeSession(**fields, tenant_id=tenant.id, id=row.id, created_at=row.created_at)
    state.offline.add_visit(row, stored)
    state.offline.record(
        state.engine,
        stored,
        "session.created",
        f"{body.mode} intake confirmed"
        + ("" if body.vitals else ", no vitals")
        + ("" if stored else " (offline)"),
        tenant_id=tenant.id,
    )
    return row


@router.get("", response_model=list[SessionOut], dependencies=[Admin])
def list_sessions(
    db: Db,
    tenant_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    query = select(IntakeSession).order_by(IntakeSession.created_at.desc()).limit(limit)
    if tenant_id:
        query = query.where(IntakeSession.tenant_id == tenant_id)
    rows = db.scalars(query).all()
    reported = set(
        db.scalars(
            select(TriageReport.session_id).where(
                TriageReport.session_id.in_([r.id for r in rows])
            )
        )
    )
    out = []
    for row in rows:
        item = SessionOut.model_validate(row)
        item.has_report = row.id in reported
        out.append(item)
    return out
