"""`/api/handoffs`: the kiosk's side (open, wait, mark done), and the
phone's side (`/api/handoffs/{code}/phone`), which needs nothing but the
code from the QR.

Without internet it keeps working: the phone reaches the kiosk server over
the hospital's own Wi-Fi, and a hand-off opened while the database cannot be
reached is kept in memory (`offline.handoffs`) for its 30 minutes."""

import secrets
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ..deps import Db, Kiosk
from ..hospital.models import HospitalSettings
from ..models import IntakeSession, Tenant
from ..offline import UNREACHABLE
from ..patients import service as patients
from ..schemas import ApiModel
from .models import PhoneHandoff

router = APIRouter(prefix="/api/handoffs")

LIFETIME = timedelta(minutes=30)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _live(db: Db, request: Request, code: str):
    """The hand-off, from memory (opened offline) or the database."""
    memory = request.app.state.offline.handoffs
    handoff = memory.get(code)
    if handoff is None and request.app.state.runtime.online:
        try:
            handoff = db.get(PhoneHandoff, code)
        except UNREACHABLE:
            db.rollback()
    if handoff is None or _utc(handoff.expires_at) < datetime.now(timezone.utc):
        memory.pop(code, None)
        raise HTTPException(404, "This link has expired. Scan the code on the kiosk again.")
    return handoff


def _save(db: Db, handoff) -> None:
    """Changes to a hand-off in memory are already kept; a row is committed."""
    if isinstance(handoff, PhoneHandoff):
        db.commit()


class Opening(ApiModel):
    language: Literal["en", "ml"] = "en"


@router.post("", status_code=201)
def open_handoff(body: Opening, db: Db, tenant: Kiosk, request: Request) -> dict:
    """The kiosk asks for a code to show as a QR."""
    fields = {
        "code": secrets.token_urlsafe(18),
        "tenant_id": tenant.id,
        "expires_at": datetime.now(timezone.utc) + LIFETIME,
        "language": body.language,
    }
    stored = False
    if request.app.state.runtime.online:
        try:
            db.add(PhoneHandoff(**fields))
            db.commit()
            stored = True
        except UNREACHABLE:
            db.rollback()
    if not stored:
        memory = request.app.state.offline.handoffs
        now = datetime.now(timezone.utc)
        for code in [c for c, h in memory.items() if h.expires_at < now]:
            del memory[code]
        memory[fields["code"]] = SimpleNamespace(
            **fields, status="open", intake=None, session_id=None, created_at=now
        )
    return {"code": fields["code"], "expiresAt": fields["expires_at"].isoformat()}


@router.get("/{code}")
def kiosk_status(code: str, db: Db, tenant: Kiosk, request: Request) -> dict:
    """The kiosk waits for the phone; once submitted, it gets the details."""
    handoff = _live(db, request, code)
    if handoff.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    return {"status": handoff.status, "intake": handoff.intake if handoff.status != "open" else None}


class Done(ApiModel):
    session_id: str = Field(max_length=32)


@router.post("/{code}/done", status_code=204)
def kiosk_done(code: str, body: Done, db: Db, tenant: Kiosk, request: Request) -> None:
    """The kiosk saved the visit: the phone can now follow its report."""
    handoff = _live(db, request, code)
    held = request.app.state.offline.visit(body.session_id)  # saved while offline
    session = held.session if held is not None else None
    if session is None and isinstance(handoff, PhoneHandoff):
        session = db.get(IntakeSession, body.session_id)
    if handoff.tenant_id != tenant.id or session is None or session.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    handoff.status, handoff.session_id = "done", session.id
    _save(db, handoff)


# --- the phone ---------------------------------------------------------------------


@router.get("/{code}/phone")
def phone_view(code: str, db: Db, request: Request) -> dict:
    handoff = _live(db, request, code)
    tenant, settings = None, None
    if isinstance(handoff, PhoneHandoff):
        try:
            tenant = db.get(Tenant, handoff.tenant_id)
            settings = db.get(HospitalSettings, handoff.tenant_id)
        except UNREACHABLE:
            db.rollback()
    tenant = tenant or request.app.state.offline.tenant_by_id(handoff.tenant_id)
    return {
        "status": handoff.status,
        "language": handoff.language,
        "hospital": (settings.display_name if settings and settings.display_name else tenant.name if tenant else ""),
        "sessionId": handoff.session_id,
    }


class PhoneIntake(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    age: int = Field(ge=0, le=120)
    gender: Literal["male", "female", "other"]
    phone: str = Field(min_length=7, max_length=32)
    email: str = Field(default="", max_length=320)
    symptoms: str = Field(min_length=1, max_length=4000)
    duration: str = Field(default="", max_length=200)
    medications: str = Field(default="", max_length=1000)
    allergies: str = Field(default="", max_length=1000)
    chronic_conditions: str = Field(default="", max_length=1000)
    regular_medicines: str = Field(default="", max_length=1000)
    past_surgeries: str = Field(default="", max_length=1000)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    habits: str = Field(default="", max_length=500)
    patient_id: str | None = Field(default=None, max_length=32)
    language: Literal["en", "ml"] = "en"


@router.post("/{code}/phone", status_code=204)
def phone_submit(code: str, body: PhoneIntake, db: Db, request: Request) -> None:
    handoff = _live(db, request, code)
    if handoff.status != "open":
        raise HTTPException(409, "These details were already sent. Go back to the kiosk.")
    handoff.intake = body.model_dump(by_alias=True)
    handoff.language = body.language
    handoff.status = "submitted"
    _save(db, handoff)


class PhoneLookup(ApiModel):
    phone: str = Field(min_length=7, max_length=32)


@router.post("/{code}/phone/patients")
def phone_lookup(code: str, body: PhoneLookup, db: Db, request: Request) -> list[dict]:
    """"Have you visited before?" from the phone: masked names only. Offline
    the records cannot be read, so the visit starts a new one (as on the
    kiosk)."""
    handoff = _live(db, request, code)
    if not request.app.state.runtime.online:
        return []
    try:
        return patients.lookup(db, handoff.tenant_id, body.phone)
    except UNREACHABLE:
        db.rollback()
        return []
