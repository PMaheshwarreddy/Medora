"""Clients (tenants), their kiosk keys, and the activity log."""

import hashlib
import logging
import secrets

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from .db import Base
from .models import ActivityLog, ApiKey, FeatureConfig, SystemSetting, Tenant

log = logging.getLogger("medora")

# Columns added after a table first shipped. `create_all` never alters an
# existing table, so these are added by hand on startup.
_ADDED_COLUMNS = {
    "intake_sessions": {"tenant_id": "VARCHAR(32)", "synced_at": "TIMESTAMP", "language": "VARCHAR(8) DEFAULT 'en'",
                        "allergies": "TEXT DEFAULT ''", "pregnancy": "VARCHAR(8) DEFAULT ''",
                        "patient_id": "VARCHAR(32)", "chronic_conditions": "TEXT DEFAULT ''",
                        "regular_medicines": "TEXT DEFAULT ''", "past_surgeries": "TEXT DEFAULT ''",
                        "weight_kg": "FLOAT", "habits": "TEXT DEFAULT ''"},
    "tenants": {"doctor_review": "BOOLEAN DEFAULT TRUE"},
    "triage_reports": {"synced_at": "TIMESTAMP"},
}


def ensure_schema(engine: Engine) -> None:
    """Creates the app's tables and adds any column an older database lacks."""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP"
    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, kind in columns.items():
                if name not in existing:
                    kind = timestamp if kind == "TIMESTAMP" else kind
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {kind}'))


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_kiosk_key() -> tuple[str, str, str]:
    """A fresh key, its hash, and a hint to recognise it by."""
    key = "mk_" + secrets.token_urlsafe(24)
    return key, hash_key(key), key[:7] + "…"


def ensure_default_tenant(engine: Engine) -> None:
    """Kiosks that send no key belong to the default client. It inherits the
    switches of the old single-client setup the first time it is created."""
    with Session(engine) as db:
        if db.scalar(select(Tenant).where(Tenant.is_default)) is not None:
            return
        legacy = db.get(FeatureConfig, 1)
        db.add(
            Tenant(
                name="Default client",
                is_default=True,
                voice_intake=legacy.voice_intake if legacy else True,
                manual_intake=legacy.manual_intake if legacy else True,
                smart_band=legacy.smart_band if legacy else True,
            )
        )
        db.commit()


def new_api_key() -> tuple[str, str, str]:
    """A fresh API key, its hash, and a hint to recognise it by."""
    key = "ma_" + secrets.token_urlsafe(30)
    return key, hash_key(key), key[:7] + "…"


def find_api_key(db: Session, key: str) -> ApiKey | None:
    """The live API key with this value, if any."""
    return db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_key(key), ApiKey.revoked_at.is_(None))
    )


def get_setting(db: Session, key: str, default):
    row = db.get(SystemSetting, key)
    return row.value.get("value", default) if row else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value={"value": value}))
    else:
        row.value = {"value": value}


def find_tenant(db: Session, kiosk_key: str) -> Tenant | None:
    if not kiosk_key:
        return db.scalar(select(Tenant).where(Tenant.is_default))
    return db.scalar(select(Tenant).where(Tenant.kiosk_key_hash == hash_key(kiosk_key)))


# Events written by older versions for what a hospital's own people did (a
# doctor signing, a hospital admin adding staff). They belong to the hospital
# alone (its audit log), so the company's back office never shows them.
HOSPITAL_EVENTS = ("consultation.finalized", "hospital.account_created")


def record(
    engine: Engine,
    event: str,
    message: str = "",
    tenant_id: str | None = None,
    level: str = "info",
) -> None:
    """Writes one activity-log line in its own transaction, so it survives
    whatever happens to the request that caused it. Never raises."""
    try:
        with Session(engine) as db:
            db.add(ActivityLog(event=event, message=message[:2000], tenant_id=tenant_id, level=level))
            db.commit()
    except Exception:
        log.exception("Could not write activity log entry %s", event)
