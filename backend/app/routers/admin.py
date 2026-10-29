"""Back office: clients, monitoring and logs. Every route needs the admin key."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import auth, background
from ..deps import Admin, Db
from pydantic import Field

from .. import delivery
from ..models import ActivityLog, ApiKey, ApiRequestLog, IntakeSession, Tenant, TriageReport
from ..panel import SPECIALISTS
from ..schemas import ApiModel, LogOut, TenantCreate, TenantOut, TenantUpdate
from ..tenancy import HOSPITAL_EVENTS, get_setting, new_api_key, new_kiosk_key, record, set_setting
from ..voice import voice_capability

router = APIRouter(prefix="/api/admin", dependencies=[Admin])


def _tenant_out(db: Db, tenant: Tenant, kiosk_key: str | None = None) -> TenantOut:
    sessions, last = db.execute(
        select(func.count(), func.max(IntakeSession.created_at)).where(
            IntakeSession.tenant_id == tenant.id
        )
    ).one()
    out = TenantOut.model_validate(tenant)
    out.sessions, out.last_session_at, out.kiosk_key = sessions, last, kiosk_key
    return out


def _get(db: Db, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Client not found")
    return tenant


def _issue_client_key(db: Db, tenant: Tenant) -> None:
    """A client has ONE key: its kiosks send it, and so does its own system
    as `X-Api-Key`. Registering it as an API key too is what makes those
    calls authenticate and appear in the request log. Earlier keys of the
    client stop working."""
    now = datetime.now(timezone.utc)
    for old in db.scalars(select(ApiKey).where(ApiKey.tenant_id == tenant.id, ApiKey.revoked_at.is_(None))):
        old.revoked_at = now
    db.add(ApiKey(tenant_id=tenant.id, name="Client key", key_hash=tenant.kiosk_key_hash, key_hint=tenant.kiosk_key_hint))


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Db):
    tenants = db.scalars(select(Tenant).order_by(Tenant.is_default.desc(), Tenant.name)).all()
    return [_tenant_out(db, t) for t in tenants]


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreate, db: Db, request: Request):
    """A new client (hospital), with its first hospital administrator when
    an email is given: the client and the account are created together or
    not at all."""
    from ..hospital import service as hospital
    from ..hospital.models import AuditEntry

    admin = body.admin_email.strip()
    if admin and not body.admin_name.strip():
        raise HTTPException(422, "Enter the administrator's name")
    if admin and body.admin_password and len(body.admin_password) < auth.MIN_PASSWORD:
        raise HTTPException(422, f"The password needs at least {auth.MIN_PASSWORD} characters")
    key, key_hash, hint = new_kiosk_key()
    fields = body.model_dump(exclude={"admin_name", "admin_email", "admin_password"})
    tenant = Tenant(**fields, kiosk_key_hash=key_hash, kiosk_key_hint=hint)
    db.add(tenant)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "A client with this name already exists") from None
    _issue_client_key(db, tenant)
    user = None
    if admin:
        try:
            user, _ = hospital.create_user(
                db,
                tenant.id,
                email=admin,
                name=body.admin_name,
                role="hospital_admin",
                password=body.admin_password or None,
                chosen=bool(body.admin_password),
            )
        except hospital.HospitalError as e:
            db.rollback()
            raise HTTPException(e.status, str(e)) from e
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
    record(request.app.state.engine, "client.created", f"Client {tenant.name!r} created", tenant.id)
    if user is not None:
        record(request.app.state.engine, "hospital.admin_created", f"Hospital admin {user.email} created for {tenant.name}", tenant.id)
    return _tenant_out(db, tenant, kiosk_key=key)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(tenant_id: str, body: TenantUpdate, db: Db, request: Request):
    tenant = _get(db, tenant_id)
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(tenant, field, value)
    if not tenant.voice_intake and not tenant.manual_intake:
        raise HTTPException(422, "Voice and manual intake cannot both be switched off")
    if tenant.is_default and not tenant.active:
        raise HTTPException(422, "The default client cannot be switched off")
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "A client with this name already exists") from None
    summary = ", ".join(f"{k}={v}" for k, v in changes.items())
    record(request.app.state.engine, "client.updated", f"Settings changed: {summary}", tenant.id)
    return _tenant_out(db, tenant)


@router.post("/tenants/{tenant_id}/kiosk-key", response_model=TenantOut)
def rotate_kiosk_key(tenant_id: str, db: Db, request: Request):
    """Issues a new kiosk key. The previous key stops working at once."""
    tenant = _get(db, tenant_id)
    key, tenant.kiosk_key_hash, tenant.kiosk_key_hint = new_kiosk_key()
    _issue_client_key(db, tenant)
    db.commit()
    record(request.app.state.engine, "client.key_rotated", "A new kiosk key was issued", tenant.id, "warning")
    return _tenant_out(db, tenant, kiosk_key=key)


@router.get("/logs", response_model=list[LogOut])
def list_logs(
    db: Db,
    tenant_id: str | None = None,
    level: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    query = (
        select(ActivityLog)
        .where(ActivityLog.event.not_in(HOSPITAL_EVENTS))
        .order_by(ActivityLog.at.desc())
        .limit(limit)
    )
    if tenant_id:
        query = query.where(ActivityLog.tenant_id == tenant_id)
    if level:
        query = query.where(ActivityLog.level == level)
    return db.scalars(query).all()


# --- API keys ----------------------------------------------------------------


class ApiKeyCreate(ApiModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=120)


def _api_key_out(db: Db, key: ApiKey, names: dict[str, str], secret: str | None = None) -> dict:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    calls, errors = db.execute(
        select(
            func.count(),
            func.count().filter(ApiRequestLog.status >= 400),
        ).where(ApiRequestLog.api_key_id == key.id, ApiRequestLog.at >= day_ago)
    ).one()
    return {
        "id": key.id,
        "name": key.name,
        "tenantId": key.tenant_id,
        "tenantName": names.get(key.tenant_id, "–"),
        "keyHint": key.key_hint,
        "createdAt": key.created_at.isoformat(),
        "lastUsedAt": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked": key.revoked_at is not None,
        "callsLast24h": calls,
        "errorsLast24h": errors,
        # Present only in the response that creates the key.
        "apiKey": secret,
    }


def _tenant_names(db: Db) -> dict[str, str]:
    return dict(db.execute(select(Tenant.id, Tenant.name)).all())


@router.get("/api-keys")
def list_api_keys(db: Db) -> list[dict]:
    names = _tenant_names(db)
    keys = db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
    return [_api_key_out(db, k, names) for k in keys]


@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyCreate, db: Db, request: Request) -> dict:
    tenant = _get(db, body.tenant_id)
    secret, key_hash, hint = new_api_key()
    key = ApiKey(tenant_id=tenant.id, name=body.name, key_hash=key_hash, key_hint=hint)
    db.add(key)
    db.commit()
    record(request.app.state.engine, "api_key.created", f"API key {body.name!r} created", tenant.id)
    return _api_key_out(db, key, {tenant.id: tenant.name}, secret)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: str, db: Db, request: Request) -> None:
    """Stops the key working at once. The key and its request log are kept."""
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
        record(request.app.state.engine, "api_key.revoked", f"API key {key.name!r} revoked", key.tenant_id, "warning")


@router.get("/api-logs")
def list_api_logs(
    db: Db,
    tenant_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    query = select(ApiRequestLog).order_by(ApiRequestLog.at.desc()).limit(limit)
    if tenant_id:
        query = query.where(ApiRequestLog.tenant_id == tenant_id)
    key_names = dict(db.execute(select(ApiKey.id, ApiKey.name)).all())
    return [
        {
            "id": row.id,
            "at": row.at.isoformat(),
            "tenantId": row.tenant_id,
            "keyName": key_names.get(row.api_key_id, "–"),
            "method": row.method,
            "path": row.path,
            "status": row.status,
            "durationMs": row.duration_ms,
        }
        for row in db.scalars(query)
    ]


# --- System -------------------------------------------------------------------


class SystemUpdate(ApiModel):
    panel_size: int = Field(ge=1, le=len(SPECIALISTS))


def _system(db: Db, request: Request) -> dict:
    state = request.app.state
    settings = state.settings
    voice_available, voice_detail = voice_capability(state)

    def item(name: str, ok: bool, detail: str, setting: str = "") -> dict:
        return {"name": name, "ok": ok, "detail": detail, "setting": setting}

    return {
        "panelSize": int(get_setting(db, "panel_size", settings.panel_size)),
        "panelMax": len(SPECIALISTS),
        "specialists": list(SPECIALISTS),
        "integrations": [
            item("Voice agent", voice_available, voice_detail, "MEDORA_GEMINI_API_KEY, MEDORA_GEMINI_LIVE_MODEL"),
            item(
                "Specialist panel",
                state.panel is not None,
                state.panel.name if state.panel else "Needs a Gemini key; reports use one model without it",
                "MEDORA_GEMINI_TEXT_MODEL, MEDORA_GEMINI_PANEL_MODEL",
            ),
            item("Offline report model", True, f"ollama:{settings.ollama_model}", "MEDORA_OLLAMA_MODEL"),
            item(
                "Knowledge search",
                state.kb.available(),
                f"Embeddings: {settings.ollama_embed_model or 'off, matching by name only'}",
                "MEDORA_OLLAMA_EMBED_MODEL",
            ),
            item(
                "Report by email",
                delivery.email_configured(settings),
                settings.smtp_from or "Not set up",
                "MEDORA_SMTP_HOST, MEDORA_SMTP_USER, MEDORA_SMTP_PASSWORD, MEDORA_SMTP_FROM",
            ),
            item(
                "Report by SMS",
                delivery.sms_configured(settings),
                settings.twilio_from or "Not set up",
                "MEDORA_TWILIO_ACCOUNT_SID, MEDORA_TWILIO_AUTH_TOKEN, MEDORA_TWILIO_FROM",
            ),
            item(
                "Central database copy",
                state.runtime.sync.configured and not state.runtime.sync.last_error,
                state.runtime.sync.last_error
                or ("Mirroring to the central database" if state.runtime.sync.configured else "Not set up"),
                "MEDORA_CLOUD_DATABASE_URL",
            ),
        ],
    }


@router.get("/system")
def read_system(db: Db, request: Request) -> dict:
    return _system(db, request)


@router.put("/system")
def update_system(body: SystemUpdate, db: Db, request: Request) -> dict:
    set_setting(db, "panel_size", body.panel_size)
    db.commit()
    record(request.app.state.engine, "system.updated", f"Specialists per case set to {body.panel_size}")
    return _system(db, request)


@router.get("/overview")
def overview(db: Db, request: Request) -> dict:
    state = request.app.state
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where))

    voice_available, voice_detail = voice_capability(state)
    sync = state.runtime.sync

    # Sessions per day for the last week, oldest first, including empty days.
    today = datetime.now(timezone.utc).date()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    per_day = {today - timedelta(days=offset): 0 for offset in range(6, -1, -1)}
    for (created,) in db.execute(
        select(IntakeSession.created_at).where(IntakeSession.created_at >= week_ago)
    ):
        day = created.astimezone(timezone.utc).date() if created.tzinfo else created.date()
        if day in per_day:
            per_day[day] += 1
    names = _tenant_names(db)
    per_client = db.execute(
        select(IntakeSession.tenant_id, func.count())
        .group_by(IntakeSession.tenant_id)
        .order_by(func.count().desc())
        .limit(6)
    ).all()
    recent = db.scalars(
        select(ActivityLog).where(ActivityLog.event.not_in(HOSPITAL_EVENTS)).order_by(ActivityLog.at.desc()).limit(8)
    ).all()
    return {
        "sessionsByDay": [{"date": d.isoformat(), "count": n} for d, n in per_day.items()],
        "sessionsByClient": [
            {"name": names.get(tenant_id, "–"), "count": n} for tenant_id, n in per_client
        ],
        "recentActivity": [
            {
                "at": row.at.isoformat(),
                "level": row.level,
                "event": row.event,
                "message": row.message,
                "client": names.get(row.tenant_id, "System"),
            }
            for row in recent
        ],
        "apiCallsLast24h": count(ApiRequestLog, ApiRequestLog.at >= day_ago),
        "apiKeys": count(ApiKey, ApiKey.revoked_at.is_(None)),
        "online": state.runtime.online,
        "clients": count(Tenant),
        "activeClients": count(Tenant, Tenant.active),
        "sessions": count(IntakeSession),
        "sessionsLast24h": count(IntakeSession, IntakeSession.created_at >= day_ago),
        "reports": count(TriageReport),
        "errorsLast24h": count(ActivityLog, ActivityLog.level == "error", ActivityLog.at >= day_ago),
        "voice": {"available": voice_available, "detail": voice_detail},
        "reportModel": state.llm.name,
        "sync": {
            "configured": sync.configured,
            "pending": background.pending(state.engine) if sync.configured else 0,
            "lastSuccess": sync.last_success.isoformat() if sync.last_success else None,
            "lastError": sync.last_error,
            "mirroredTotal": sync.mirrored_total,
        },
    }
