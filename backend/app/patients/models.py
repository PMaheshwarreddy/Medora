from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import new_id, now


class Patient(Base):
    """A person known to one hospital. Health details are what the patient
    reported at their visits (merged); doctor-confirmed history lives in the
    doctor's reviews (`doctor.models.DoctorReview`)."""

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # From the age given at the first visit; matching tolerates a year.
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str] = mapped_column(String(16), default="")
    # Digits only, so "98765 43210" and "+91 9876543210" match.
    phone: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(320), default="")
    allergies: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[str] = mapped_column(Text, default="")
    regular_medicines: Mapped[str] = mapped_column(Text, default="")
    surgeries: Mapped[str] = mapped_column(Text, default="")
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    visits: Mapped[int] = mapped_column(Integer, default=0)
