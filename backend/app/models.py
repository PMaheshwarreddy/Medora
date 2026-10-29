import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class IntakeSession(Base):
    """One patient's confirmed intake from the kiosk."""

    __tablename__ = "intake_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    mode: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(16))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str] = mapped_column(String(320), default="")
    symptoms: Mapped[str] = mapped_column(Text)
    duration: Mapped[str] = mapped_column(String(200), default="")
    medications: Mapped[str] = mapped_column(Text, default="")
    # Band readings; null when the client runs without a band.
    vitals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The client (hospital) whose kiosk took this intake.
    tenant_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Allergies to medicines, injections or anything else, as reported.
    allergies: Mapped[str] = mapped_column(Text, default="")
    # yes | no | unsure, only when the voice agent asked (complaints where
    # pregnancy matters); empty otherwise.
    pregnancy: Mapped[str] = mapped_column(String(8), default="")
    # The patient record this visit belongs to (patients/models.py).
    patient_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Health history asked at the visit (new patients, or updates).
    chronic_conditions: Mapped[str] = mapped_column(Text, default="")
    regular_medicines: Mapped[str] = mapped_column(Text, default="")
    past_surgeries: Mapped[str] = mapped_column(Text, default="")
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Smoking, tobacco and alcohol, as the patient said (voice asks adult men).
    habits: Mapped[str] = mapped_column(Text, default="")
    # en | ml: the language the patient used at the kiosk.
    language: Mapped[str] = mapped_column(String(8), default="en")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TriageReport(Base):
    """The generated report for one intake session."""

    __tablename__ = "triage_reports"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSON)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Tenant(Base):
    """A client (hospital) and what its kiosks are allowed to offer."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
    name: Mapped[str] = mapped_column(String(200), unique=True)
    # Kiosks without a key belong to the default client.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Only a hash of the kiosk key is kept; the key is shown once on creation.
    kiosk_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    kiosk_key_hint: Mapped[str] = mapped_column(String(12), default="")
    voice_intake: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_intake: Mapped[bool] = mapped_column(Boolean, default=True)
    smart_band: Mapped[bool] = mapped_column(Boolean, default=True)
    # A doctor reviews every report in the doctor portal before the patient
    # gets conditions and medicines (the kiosk shows a preliminary report).
    doctor_review: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityLog(Base):
    """What happened, per client: the back office's monitoring feed."""

    __tablename__ = "activity_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # info | warning | error
    level: Mapped[str] = mapped_column(String(8), default="info")
    # Machine-readable kind, e.g. "session.created", "voice.error".
    event: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, default="")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(Base):
    """Someone who may sign in to the back office."""

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    # New accounts wait for an existing administrator; the first approves itself.
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminSession(Base):
    """A signed-in browser. Only a hash of its token is stored."""

    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    """Lets a client's own system call the Medora API instead of a kiosk."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Only a hash is kept; the key is shown once on creation.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_hint: Mapped[str] = mapped_column(String(12), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiRequestLog(Base):
    """One request made with an API key."""

    __tablename__ = "api_request_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    api_key_id: Mapped[str] = mapped_column(String(32), index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)


class SystemSetting(Base):
    """Settings the back office can change without editing the server's files."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class FeatureConfig(Base):
    """Legacy single-client switches; read once to seed the default client."""

    __tablename__ = "feature_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voice_intake: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_intake: Mapped[bool] = mapped_column(Boolean, default=True)
    smart_band: Mapped[bool] = mapped_column(Boolean, default=True)


