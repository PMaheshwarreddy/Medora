import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import delivery
from ..deps import AppSettings, Db, note_api_key
from ..llm import LlmError
from ..models import IntakeSession, Tenant, TriageReport
from ..patients import service as patients
from ..offline import UNREACHABLE
from ..report_pdf import render_pdf
from ..schemas import ApiModel
from ..tenancy import get_setting, record
from .. import sensitive
from ..patient_view import build_patient_view
from ..triage import build_report, fallback_report

log = logging.getLogger("medora.reports")

# The session id is a random 128-bit value handed only to the kiosk that
# created it; knowing it is what grants access to that patient's report.
router = APIRouter(
    prefix="/api/sessions/{session_id}/report", dependencies=[Depends(note_api_key)]
)


def _session(request: Request, db: Db, session_id: str) -> IntakeSession:
    """The visit, from memory first (recent and offline visits), then the
    database."""
    visit = request.app.state.offline.visit(session_id)
    if visit is not None:
        return visit.session
    try:
        session = db.get(IntakeSession, session_id)
    except UNREACHABLE as e:
        raise HTTPException(503, "This visit cannot be opened without internet.") from e
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


def _stored_report(request: Request, db: Db, session_id: str) -> dict | None:
    visit = request.app.state.offline.visit(session_id)
    if visit is not None and visit.report is not None:
        return visit.report
    if visit is not None and not visit.session_stored:
        return None  # an offline visit: nothing in the database yet
    try:
        row = db.get(TriageReport, session_id)
    except UNREACHABLE:
        return None
    return None if row is None else row.data


# Kept in the stored report for the doctor portal and the hospital, never
# sent to the patient's screen or PDF.
_DOCTOR_ONLY = ("doctorView", "guidelineEvidence", "guidelineNote")
# Also held back while a doctor has still to review the report.
_BEFORE_DOCTOR = (
    "possibleConditions", "conditionsRuledOut", "medicines", "panel",
    "discussion", "doctorNotes", "clinicalSummary",
)  # fmt: skip


def patient_medicines(data: dict, session) -> list[dict]:
    """The medicines for the patient's copy: the doctor's list (reviewed,
    with injections and emergency care marked doctorOnly), else the
    patient list; wording on pregnancy or sexual health only if the patient
    raised it (sensitive.py), as in the rest of the patient's report."""
    medicines = (data.get("doctorView") or {}).get("medicines") or data.get("medicines") or []
    raised = sensitive.raised_by_patient(session.symptoms or "", session.medications or "") or (
        getattr(session, "pregnancy", "") in ("yes", "unsure"))
    out = []
    for m in medicines:
        m = {k: v for k, v in m.items() if k != "doseEvidence"}
        if not raised:
            if sensitive.mentions(m.get("forCondition", "")) or sensitive.mentions(m.get("name", "")):
                continue
            for key in ("caution", "purpose"):
                m[key] = sensitive.strip_sentences(m.get(key, ""))
        out.append(m)
    return out


def for_patient(data: dict) -> dict:
    """The stored report as the patient may see it."""
    hidden = _DOCTOR_ONLY + (_BEFORE_DOCTOR if data.get("awaitingDoctor") else ())
    out = {k: v for k, v in data.items() if k not in hidden}
    if out.get("medicines"):  # where a dose was found is for the doctor
        out["medicines"] = [{k: v for k, v in m.items() if k != "doseEvidence"} for m in out["medicines"]]
    if data.get("awaitingDoctor"):
        out.update(possibleConditions=[], medicines=[], panel=[], doctorNotes=[], conditionsRuledOut=[])
    return out


def _report(request: Request, db: Db, session_id: str) -> dict:
    data = _stored_report(request, db, session_id)
    if data is None:
        raise HTTPException(404, "The report has not been generated yet")
    return data


@router.post("")
async def generate(session_id: str, db: Db, request: Request) -> dict:
    """Generates the report once; later calls return the stored one. Online
    it runs on Gemini; offline on the local medical model, with the same
    steps, review and rules (fewer specialists, as they take turns). A
    request made while the report is still being written waits for that
    one instead of starting another."""
    session = _session(request, db, session_id)
    existing = _stored_report(request, db, session_id)
    if existing is not None:
        return for_patient(existing)
    running: dict = request.app.state.report_tasks
    task = running.get(session_id)
    if task is None:
        task = asyncio.create_task(_generate(session, session_id, request))
        running[session_id] = task
        task.add_done_callback(lambda _: running.pop(session_id, None))
    # Shielded: a kiosk that stops waiting does not cancel the report.
    return for_patient(await asyncio.shield(task))


async def _generate(session: IntakeSession, session_id: str, request: Request) -> dict:
    # Its own database session: the request's closes when the request ends.
    with Session(request.app.state.engine) as db:
        return await _write_report(session, session_id, db, request)


async def _write_report(session: IntakeSession, session_id: str, db: Session, request: Request) -> dict:
    state = request.app.state
    online = state.runtime.online
    if online:
        llm, panel = state.llm, state.panel
        try:
            panel_size = int(get_setting(db, "panel_size", state.settings.panel_size))
        except UNREACHABLE:
            online = False
    if not online:
        # Without a local medical model only the plain summary is possible.
        llm = state.offline_llm or state.llm
        panel = state.offline_panel
        panel_size = state.settings.offline_panel_size
    # The patient's doctor-confirmed history, and whether a doctor reviews
    # this hospital's reports before the patient sees conditions and
    # medicines (the hospital's "doctor review" switch).
    history, doctor_review = "", False
    if online:
        try:
            history = patients.history_text(db, session)
            tenant = db.get(Tenant, session.tenant_id) if session.tenant_id else None
            doctor_review = bool(tenant and getattr(tenant, "doctor_review", False))
        except UNREACHABLE:
            pass
    else:
        tenant = state.offline.tenant_by_id(session.tenant_id or "")
        doctor_review = bool(tenant and getattr(tenant, "doctor_review", False))
    progress = state.progress.start(session_id)
    try:
        data = await build_report(
            session, llm, state.kb, panel, panel_size, progress, history, getattr(state, "retriever", None),
            # the stronger report model only online (offline the local model writes it all)
            writer_llm=getattr(state, "report_llm", None) if online else None,
            lean=not online,
        )
        progress.at("done")
    except LlmError as e:
        progress.at("failed")
        state.offline.record(state.engine, online, "report.error", str(e), session.tenant_id, "error")
        raise HTTPException(503, f"The report could not be generated. {e}") from e
    except Exception as e:
        # Never leave a patient without a report: anything unexpected falls
        # back to the plain report, and is logged for the operators.
        log.exception("Report pipeline failed for session %s", session_id)
        state.offline.record(state.engine, online, "report.error", f"Full report failed, plain report given: {e}", session.tenant_id, "error")
        try:
            data = await fallback_report(session, llm)
            progress.at("done")
        except Exception as again:
            progress.at("failed")
            raise HTTPException(503, "The report could not be generated. Please try again.") from again

    # The patient's copy: simple English with Malayalam beneath each part
    # (patient_view.py). Offline it is the report's own English.
    data["language"] = getattr(session, "language", None) or "en"
    data["awaitingDoctor"] = doctor_review
    # The patient's copy shows the reviewed medicines the doctor sees,
    # emergency and doctor-given ones included, under "the doctor decides:
    # take nothing until told" (the user's rule of 2026-10-28, replacing the
    # empty list before doctor review and in emergencies).
    shown = {**data, "medicines": patient_medicines(data, session)}
    if not shown["medicines"]:
        shown["medicinesNote"] = data.get("medicinesNote") or "Your doctor will see you and decide on any medicines."
    data["patientView"] = await build_patient_view(state.llm if online else None, shown, session)

    if state.offline.visit(session_id) is None:
        state.offline.add_visit(session, stored=True)
    stored = False
    if online and state.offline.visit(session_id).session_stored:
        try:
            db.add(TriageReport(session_id=session_id, data=data))
            db.commit()
            stored = True
        except UNREACHABLE:
            db.rollback()
    state.offline.set_report(session_id, data, stored)
    state.offline.record(
        state.engine,
        stored,
        "report.generated",
        f"Urgency {data['urgency']}, {data['department']}; "
        f"{len(data['panel'])} specialists, {len(data['possibleConditions'])} conditions "
        f"({data['generator']})" + (f". {data['panelNote']}" if data["panelNote"] else ""),
        session.tenant_id,
    )
    return data


@router.get("/progress")
def progress(session_id: str, request: Request) -> dict:
    """What the report being generated for this session is doing now."""
    current = request.app.state.progress.get(session_id)
    if current is None:
        raise HTTPException(404, "No report is being generated for this session")
    return current.to_json()


@router.get("")
def read(session_id: str, db: Db, request: Request) -> dict:
    _session(request, db, session_id)
    return for_patient(_report(request, db, session_id))


@router.get(".pdf")
def pdf(session_id: str, db: Db, request: Request) -> Response:
    session = _session(request, db, session_id)
    return Response(
        render_pdf(session, for_patient(_report(request, db, session_id))),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="medora-report.pdf"'},
    )


class SendBody(ApiModel):
    channel: Literal["sms", "email"]


@router.post("/send", status_code=204)
async def send(
    session_id: str, body: SendBody, db: Db, settings: AppSettings, request: Request
) -> None:
    session = _session(request, db, session_id)
    report = for_patient(_report(request, db, session_id))
    try:
        if body.channel == "email":
            if not delivery.email_configured(settings):
                raise HTTPException(503, "Email delivery is not set up on this server")
            if not session.email:
                raise HTTPException(400, "No email address was given")
            await delivery.send_email(
                settings, session, report, render_pdf(session, report)
            )
        else:
            if not delivery.sms_configured(settings):
                raise HTTPException(503, "SMS delivery is not set up on this server")
            await delivery.send_sms(settings, session, report)
    except delivery.DeliveryError as e:
        record(request.app.state.engine, "report.send_failed", f"{body.channel}: {e}", session.tenant_id, "error")
        raise HTTPException(502, str(e)) from e
    record(request.app.state.engine, "report.sent", f"Sent by {body.channel}", session.tenant_id)
