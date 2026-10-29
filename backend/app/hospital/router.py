"""The hospital portal's API (`/api/hospital/...`), and the two company
back-office endpoints that open a hospital's portal by creating its first
administrators (`/api/admin/tenants/{id}/hospital-admins`).

Every hospital endpoint works on the signed-in person's own hospital
(`user.tenant_id`); none takes a hospital from the request.
"""

import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import auth
from ..deps import Admin, Db
from ..models import ActivityLog, IntakeSession, Tenant, TriageReport
from ..panel import DEPARTMENTS
from ..schemas import ApiModel
from ..tenancy import record
from . import service
from .models import AuditEntry, Department, HospitalSettings, HospitalUser
from .service import HospitalAdmin, HospitalError, Signed

router = APIRouter(prefix="/api/hospital")
company_router = APIRouter(prefix="/api/admin/tenants/{tenant_id}/hospital-admins", dependencies=[Admin])


def _fail(e: HospitalError):
    raise HTTPException(e.status, str(e)) from e


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _user_out(user: HospitalUser, departments: dict[str, str] | None = None) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "active": user.active,
        "mustChangePassword": user.must_change_password,
        "phone": user.phone,
        "departmentId": user.department_id,
        "department": (departments or {}).get(user.department_id or "", ""),
        "registrationNumber": user.registration_number,
        "qualification": user.qualification,
        "jobTitle": user.job_title,
        "createdAt": _iso(user.created_at),
        "lastLoginAt": _iso(user.last_login_at),
    }


def _settings(db: Db, tenant_id: str) -> HospitalSettings:
    row = db.get(HospitalSettings, tenant_id)
    if row is None:
        tenant = db.get(Tenant, tenant_id)
        row = HospitalSettings(tenant_id=tenant_id, display_name=tenant.name if tenant else "")
        db.add(row)
        db.flush()
    return row


def _hospital_out(db: Db, tenant_id: str) -> dict:
    tenant = db.get(Tenant, tenant_id)
    s = _settings(db, tenant_id)
    return {
        "id": tenant_id,
        "name": s.display_name or (tenant.name if tenant else ""),
        "logo": s.logo,
    }


def _departments(db: Db, tenant_id: str) -> dict[str, str]:
    return {
        d.id: d.name for d in db.scalars(select(Department).where(Department.tenant_id == tenant_id))
    }


# --- sign-in -----------------------------------------------------------------------


class Credentials(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


@router.post("/auth/login")
def login(body: Credentials, db: Db, request: Request) -> dict:
    try:
        user, token = service.sign_in(db, body.email, body.password)
    except HospitalError as e:
        _fail(e)
    service.audit(db, user, "account.signed_in")
    db.commit()
    return {"user": _user_out(user, _departments(db, user.tenant_id)), "token": token, "hospital": _hospital_out(db, user.tenant_id)}


@router.get("/auth/me")
def me(user: Signed, db: Db) -> dict:
    return {"user": _user_out(user, _departments(db, user.tenant_id)), "hospital": _hospital_out(db, user.tenant_id)}


@router.post("/auth/logout", status_code=204)
def logout(db: Db, request: Request) -> None:
    token = service.hospital_token(
        request.headers.get("x-hospital-token", ""), request.headers.get("authorization", "")
    )
    service.sign_out(db, token)


class PasswordChange(ApiModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, user: Signed, db: Db) -> None:
    try:
        service.set_password(db, user, body.current, body.new)
    except HospitalError as e:
        _fail(e)
    service.audit(db, user, "account.password_changed")
    db.commit()


# --- dashboard -----------------------------------------------------------------------


def _local_midnight(db: Db, tenant_id: str, days_back: int = 0) -> datetime:
    try:
        zone = ZoneInfo(_settings(db, tenant_id).timezone or "Asia/Kolkata")
    except Exception:
        zone = ZoneInfo("Asia/Kolkata")
    local = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return local.astimezone(timezone.utc)


def _visit_rows(db: Db, tenant_id: str, since: datetime | None = None, limit: int = 200, search: str = "") -> list:
    query = (
        select(IntakeSession, TriageReport)
        .outerjoin(TriageReport, TriageReport.session_id == IntakeSession.id)
        .where(IntakeSession.tenant_id == tenant_id)
        .order_by(IntakeSession.created_at.desc())
        .limit(limit)
    )
    if since is not None:
        query = query.where(IntakeSession.created_at >= since)
    if search.strip():
        like = f"%{search.strip()}%"
        query = query.where(or_(IntakeSession.name.ilike(like), IntakeSession.phone.ilike(like)))
    return db.execute(query).all()


def _visit_out(session: IntakeSession, report: TriageReport | None) -> dict:
    data = report.data if report is not None else {}
    return {
        "id": session.id,
        "at": _iso(session.created_at),
        "name": session.name,
        "age": session.age,
        "gender": session.gender,
        "phone": session.phone,
        "mode": session.mode,
        "language": getattr(session, "language", "en") or "en",
        "symptoms": session.symptoms,
        "hasReport": report is not None,
        "urgency": data.get("urgency"),
        "department": data.get("department"),
    }


@router.get("/dashboard")
def dashboard(user: HospitalAdmin, db: Db) -> dict:
    tid = user.tenant_id
    today = _visit_rows(db, tid, since=_local_midnight(db, tid), limit=2000)
    week = _visit_rows(db, tid, since=_local_midnight(db, tid, 6), limit=10000)
    by_urgency = {u: 0 for u in ("routine", "soon", "urgent", "emergency")}
    by_department: dict[str, int] = {}
    for _, report in today:
        if report is None:
            continue
        urgency = report.data.get("urgency")
        if urgency in by_urgency:
            by_urgency[urgency] += 1
        department = report.data.get("department") or "General OPD"
        by_department[department] = by_department.get(department, 0) + 1
    zone_start = _local_midnight(db, tid, 6)
    per_day = []
    for day in range(7):
        start = zone_start + timedelta(days=day)
        end = start + timedelta(days=1)
        count = 0
        for session, _ in week:
            at = session.created_at if session.created_at.tzinfo else session.created_at.replace(tzinfo=timezone.utc)
            if start <= at < end:
                count += 1
        per_day.append({"date": _iso(start), "visits": count})
    people = db.execute(
        select(HospitalUser.role, func.count())
        .where(HospitalUser.tenant_id == tid, HospitalUser.active)
        .group_by(HospitalUser.role)
    ).all()
    counts = {role: n for role, n in people}
    return {
        "hospital": _hospital_out(db, tid),
        "today": {
            "visits": len(today),
            "reports": sum(1 for _, r in today if r is not None),
            "urgent": by_urgency["urgent"] + by_urgency["emergency"],
            "byUrgency": by_urgency,
            "byDepartment": sorted(
                ({"department": k, "visits": v} for k, v in by_department.items()),
                key=lambda x: -x["visits"],
            ),
        },
        "week": per_day,
        "recent": [_visit_out(s, r) for s, r in today[:8]] or [_visit_out(s, r) for s, r in week[:8]],
        "people": {
            "doctors": counts.get("doctor", 0),
            "staff": counts.get("staff", 0),
            "admins": counts.get("hospital_admin", 0),
            "departments": db.scalar(
                select(func.count()).select_from(Department).where(Department.tenant_id == tid, Department.active)
            ),
        },
    }


# --- departments -------------------------------------------------------------------


class DepartmentBody(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    report_department: str = Field(default="", max_length=80)
    active: bool = True


def _department_out(d: Department, doctors: int = 0) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "reportDepartment": d.report_department,
        "active": d.active,
        "doctors": doctors,
    }


def _check_report_department(value: str) -> str:
    if value and value not in DEPARTMENTS:
        raise HTTPException(422, "Choose a department from the list")
    return value


@router.get("/departments")
def list_departments(user: HospitalAdmin, db: Db) -> dict:
    doctors = dict(
        db.execute(
            select(HospitalUser.department_id, func.count())
            .where(HospitalUser.tenant_id == user.tenant_id, HospitalUser.role == "doctor", HospitalUser.active)
            .group_by(HospitalUser.department_id)
        ).all()
    )
    rows = db.scalars(
        select(Department).where(Department.tenant_id == user.tenant_id).order_by(Department.name)
    ).all()
    return {
        "departments": [_department_out(d, doctors.get(d.id, 0)) for d in rows],
        # What a report can send a patient to, for linking a department.
        "reportDepartments": DEPARTMENTS,
    }


@router.post("/departments", status_code=201)
def create_department(body: DepartmentBody, user: HospitalAdmin, db: Db) -> dict:
    d = Department(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        report_department=_check_report_department(body.report_department),
        active=body.active,
    )
    db.add(d)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A department with this name already exists") from e
    service.audit(db, user, "department.created", d.name)
    db.commit()
    return _department_out(d)


@router.patch("/departments/{department_id}")
def update_department(department_id: str, body: DepartmentBody, user: HospitalAdmin, db: Db) -> dict:
    d = db.get(Department, department_id)
    if d is None or d.tenant_id != user.tenant_id:
        raise HTTPException(404, "Department not found")
    d.name = body.name.strip()
    d.report_department = _check_report_department(body.report_department)
    d.active = body.active
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A department with this name already exists") from e
    service.audit(db, user, "department.updated", f"{d.name} ({'active' if d.active else 'off'})")
    db.commit()
    return _department_out(d)


# --- people: doctors, staff, admins -----------------------------------------------


class PersonCreate(ApiModel):
    email: str = Field(max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: Literal["hospital_admin", "doctor", "staff"]
    phone: str = Field(default="", max_length=32)
    department_id: str | None = None
    registration_number: str = Field(default="", max_length=64)
    qualification: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=100)


class PersonUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    department_id: str | None = None
    registration_number: str | None = Field(default=None, max_length=64)
    qualification: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=100)
    active: bool | None = None


def _own_department(db: Db, user: HospitalUser, department_id: str | None) -> str | None:
    if not department_id:
        return None
    d = db.get(Department, department_id)
    if d is None or d.tenant_id != user.tenant_id:
        raise HTTPException(422, "Choose one of this hospital's departments")
    return d.id


def _own_person(db: Db, user: HospitalUser, person_id: str) -> HospitalUser:
    person = db.get(HospitalUser, person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(404, "Account not found")
    return person


@router.get("/people")
def list_people(user: HospitalAdmin, db: Db, role: str | None = None) -> list[dict]:
    query = select(HospitalUser).where(HospitalUser.tenant_id == user.tenant_id).order_by(HospitalUser.name)
    if role:
        query = query.where(HospitalUser.role == role)
    departments = _departments(db, user.tenant_id)
    return [_user_out(p, departments) for p in db.scalars(query)]


@router.post("/people", status_code=201)
def create_person(body: PersonCreate, user: HospitalAdmin, db: Db, request: Request) -> dict:
    if body.role == "doctor" and not body.registration_number.strip():
        raise HTTPException(422, "Enter the doctor's medical registration number")
    try:
        person, password = service.create_user(
            db,
            user.tenant_id,
            email=body.email,
            name=body.name,
            role=body.role,
            phone=body.phone.strip(),
            department_id=_own_department(db, user, body.department_id),
            registration_number=body.registration_number.strip(),
            qualification=body.qualification.strip(),
            job_title=body.job_title.strip(),
        )
    except HospitalError as e:
        _fail(e)
    service.audit(db, user, f"{body.role}.created", f"{person.name} <{person.email}>")
    db.commit()  # in the hospital's audit log only, never the company's
    # The temporary password is shown once; only its hash is kept.
    return {"person": _user_out(person, _departments(db, user.tenant_id)), "temporaryPassword": password}


@router.patch("/people/{person_id}")
def update_person(person_id: str, body: PersonUpdate, user: HospitalAdmin, db: Db) -> dict:
    person = _own_person(db, user, person_id)
    changes = body.model_dump(exclude_unset=True)
    if person.id == user.id and changes.get("active") is False:
        raise HTTPException(422, "You cannot switch off your own account")
    if "email" in changes and changes["email"] is not None:
        try:
            changes["email"] = service._check_email(db, changes["email"], ignore_id=person.id)
        except HospitalError as e:
            _fail(e)
    if "department_id" in changes:
        changes["department_id"] = _own_department(db, user, changes["department_id"])
    for field, value in changes.items():
        if value is not None or field == "department_id":
            setattr(person, field, value.strip() if isinstance(value, str) else value)
    if person.role == "doctor" and not person.registration_number:
        raise HTTPException(422, "A doctor needs a medical registration number")
    if not person.active:
        service.end_sessions(db, person.id)
    service.audit(db, user, f"{person.role}.updated", f"{person.name}: {', '.join(changes)}")
    db.commit()
    return _user_out(person, _departments(db, user.tenant_id))


@router.post("/people/{person_id}/reset-password")
def reset_password(person_id: str, user: HospitalAdmin, db: Db) -> dict:
    person = _own_person(db, user, person_id)
    password = service.temporary_password()


    person.password_hash = auth.hash_password(password)
    person.must_change_password = True
    service.end_sessions(db, person.id)
    service.audit(db, user, f"{person.role}.password_reset", person.name)
    db.commit()
    return {"temporaryPassword": password}


# --- visits and reports -----------------------------------------------------------


@router.get("/visits")
def list_visits(
    user: HospitalAdmin,
    db: Db,
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    from ..doctor.models import DoctorReview

    rows = _visit_rows(db, user.tenant_id, limit=limit, search=search)
    reviews = {
        r.session_id: r
        for r in db.scalars(select(DoctorReview).where(DoctorReview.session_id.in_([v.id for v, _ in rows])))
    }
    out = []
    for visit, report in rows:
        item = _visit_out(visit, report)
        review = reviews.get(visit.id)
        item["doctorStatus"] = (
            "signed" if review is not None and review.status == "final"
            else "with_doctor" if review is not None
            else "waiting" if report is not None and (report.data or {}).get("awaitingDoctor")
            else ""
        )  # fmt: skip
        item["doctor"] = review.doctor_name if review is not None else ""
        out.append(item)
    return out


@router.get("/visits/{visit_id}")
def visit(visit_id: str, user: HospitalAdmin, db: Db) -> dict:
    session = db.get(IntakeSession, visit_id)
    if session is None or session.tenant_id != user.tenant_id:
        raise HTTPException(404, "Visit not found")
    report = db.get(TriageReport, visit_id)
    # Opening a patient's record is always written down.
    service.audit(db, user, "visit.viewed", f"{session.name} ({visit_id[:8].upper()})")
    db.commit()
    return {
        **_visit_out(session, report),
        "email": session.email,
        "duration": session.duration,
        "medications": session.medications,
        "allergies": getattr(session, "allergies", "") or "",
        "pregnancy": getattr(session, "pregnancy", "") or "",
        "vitals": session.vitals,
        "report": report.data if report is not None else None,
    }


# --- audit and activity --------------------------------------------------------------


@router.get("/audit")
def audit_log(user: HospitalAdmin, db: Db, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    rows = db.scalars(
        select(AuditEntry)
        .where(AuditEntry.tenant_id == user.tenant_id)
        .order_by(AuditEntry.at.desc())
        .limit(limit)
    )
    return [
        {"id": a.id, "at": _iso(a.at), "user": a.user_name, "role": a.role, "action": a.action, "detail": a.detail}
        for a in rows
    ]


@router.get("/activity")
def activity(user: HospitalAdmin, db: Db, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    """What the hospital's kiosks did: visits, reports, voice, errors."""
    rows = db.scalars(
        select(ActivityLog)
        .where(ActivityLog.tenant_id == user.tenant_id)
        .order_by(ActivityLog.at.desc())
        .limit(limit)
    )
    return [{"id": a.id, "at": _iso(a.at), "level": a.level, "event": a.event, "message": a.message} for a in rows]


# --- settings ------------------------------------------------------------------------

_LOGO = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)$")
MAX_LOGO_BYTES = 300 * 1024


class SettingsBody(ApiModel):
    display_name: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=320)
    letterhead_note: str = Field(default="", max_length=300)
    logo: str = Field(default="", max_length=MAX_LOGO_BYTES * 2)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)


def _settings_out(s: HospitalSettings) -> dict:
    return {
        "displayName": s.display_name,
        "address": s.address,
        "phone": s.phone,
        "email": s.email,
        "letterheadNote": s.letterhead_note,
        "logo": s.logo,
        "timezone": s.timezone,
    }


@router.get("/settings")
def get_settings_(user: HospitalAdmin, db: Db) -> dict:
    s = _settings(db, user.tenant_id)
    db.commit()
    return _settings_out(s)


@router.put("/settings")
def put_settings(body: SettingsBody, user: HospitalAdmin, db: Db) -> dict:
    if body.logo:
        match = _LOGO.match(body.logo)
        if match is None:
            raise HTTPException(422, "The logo must be a PNG or JPEG image")
        if len(base64.b64decode(match.group(2))) > MAX_LOGO_BYTES:
            raise HTTPException(422, "The logo must be 300 KB or smaller")
    try:
        ZoneInfo(body.timezone)
    except Exception as e:
        raise HTTPException(422, "Unknown time zone") from e
    s = _settings(db, user.tenant_id)
    for field, value in body.model_dump().items():
        setattr(s, field, value.strip() if isinstance(value, str) and field != "logo" else value)
    service.audit(db, user, "settings.updated")
    db.commit()
    return _settings_out(s)


# --- company back office: opening a hospital's portal ----------------------------


class AdminCreate(ApiModel):
    email: str = Field(max_length=320)
    name: str = Field(min_length=1, max_length=200)
    # Optional: a password the company chooses; otherwise a temporary one.
    password: str = Field(default="", max_length=200)


def _company_tenant(db: Db, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Client not found")
    return tenant


@company_router.get("")
def list_hospital_admins(tenant_id: str, db: Db) -> list[dict]:
    _company_tenant(db, tenant_id)
    rows = db.scalars(
        select(HospitalUser)
        .where(HospitalUser.tenant_id == tenant_id, HospitalUser.role == "hospital_admin")
        .order_by(HospitalUser.created_at)
    )
    return [_user_out(u) for u in rows]


@company_router.post("", status_code=201)
def create_hospital_admin(tenant_id: str, body: AdminCreate, db: Db, request: Request) -> dict:
    """The hospital's first administrator, who then adds everyone else."""
    tenant = _company_tenant(db, tenant_id)
    try:
        if body.password and len(body.password) < auth.MIN_PASSWORD:
            raise HospitalError(f"The password needs at least {auth.MIN_PASSWORD} characters")
        user, password = service.create_user(
            db, tenant.id, email=body.email, name=body.name, role="hospital_admin",
            password=body.password or None, chosen=bool(body.password),
        )
    except HospitalError as e:
        _fail(e)
    db.add(
        AuditEntry(
            tenant_id=tenant.id,
            user_name="Medora (company)",
            role="company",
            action="hospital_admin.created",
            detail=f"{user.name} <{user.email}>",
        )
    )
    db.commit()
    record(request.app.state.engine, "hospital.admin_created", f"Hospital admin {user.email} created for {tenant.name}", tenant.id)
    return {"person": _user_out(user), "temporaryPassword": password}


@company_router.post("/{user_id}/reset-password")
def reset_hospital_admin(tenant_id: str, user_id: str, db: Db) -> dict:
    user = db.get(HospitalUser, user_id)
    if user is None or user.tenant_id != tenant_id or user.role != "hospital_admin":
        raise HTTPException(404, "Account not found")


    password = service.temporary_password()
    user.password_hash = auth.hash_password(password)
    user.must_change_password = True
    user.active = True
    service.end_sessions(db, user.id)
    db.add(
        AuditEntry(tenant_id=tenant_id, user_name="Medora (company)", role="company",
                   action="hospital_admin.password_reset", detail=user.name)  # fmt: skip
    )
    db.commit()
    return {"temporaryPassword": password}
