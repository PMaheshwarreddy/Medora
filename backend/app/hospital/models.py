"""Tables of the hospital portal. Created at startup with the app's own
tables (`tenancy.ensure_schema`), because they share `db.Base`."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import new_id, now

# What a hospital account may do. Doctors and staff get their own portals
# later; for now only hospital admins have a portal (`/hospital`).
ROLES = ("hospital_admin", "doctor", "staff")


class HospitalUser(Base):
    """Someone who works at one hospital: its admin, a doctor, or staff."""

    __tablename__ = "hospital_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # hospital_admin | doctor | staff
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set for an account created or reset with a temporary password.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    # Doctors: their department, medical council registration number (it
    # goes on prescriptions) and qualification ("MBBS, MD").
    department_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registration_number: Mapped[str] = mapped_column(String(64), default="")
    qualification: Mapped[str] = mapped_column(String(200), default="")
    # Staff: what they do ("Nurse", "Front desk").
    job_title: Mapped[str] = mapped_column(String(100), default="")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HospitalSession(Base):
    """A signed-in hospital browser. Only a hash of its token is stored."""

    __tablename__ = "hospital_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Department(Base):
    """A department of the hospital; doctors belong to one, and the doctor
    queue (later) is per department."""

    __tablename__ = "hospital_departments"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # The report department this one takes (one of panel.DEPARTMENTS), so
    # a report's "Cardiology" reaches this hospital's cardiology queue.
    report_department: Mapped[str] = mapped_column(String(80), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HospitalSettings(Base):
    """How the hospital presents itself: on its reports and portal."""

    __tablename__ = "hospital_settings"

    tenant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    # A line under the name on reports, e.g. registration or accreditation.
    letterhead_note: Mapped[str] = mapped_column(String(300), default="")
    # A small logo as a data URL (image/png or image/jpeg, at most 300 KB).
    logo: Mapped[str] = mapped_column(Text, default="")
    # For "today" on the dashboard.
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")


class AuditEntry(Base):
    """Who did what in the hospital portal, including who opened which
    patient's record: health data needs that trail."""

    __tablename__ = "hospital_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), default="")
    user_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="")
    # e.g. "visit.viewed", "doctor.created", "settings.updated"
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
