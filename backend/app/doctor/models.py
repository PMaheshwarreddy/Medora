from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import now


class DoctorReview(Base):
    """One doctor's consultation for one visit."""

    __tablename__ = "doctor_reviews"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    patient_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    doctor_id: Mapped[str] = mapped_column(String(32), index=True)
    doctor_name: Mapped[str] = mapped_column(String(200), default="")
    # in_consultation: a doctor has picked the patient; final: signed.
    status: Mapped[str] = mapped_column(String(20), default="in_consultation")
    picked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # [{"name", "notes"}]
    diagnosis: Mapped[list] = mapped_column(JSON, default=list)
    # [{"name", "form", "strength", "dose", "route", "frequency", "duration",
    #   "maxDaily", "instructions", "fromAi"}]
    medicines: Mapped[list] = mapped_column(JSON, default=list)
    tests: Mapped[list] = mapped_column(JSON, default=list)
    advice: Mapped[list] = mapped_column(JSON, default=list)
    follow_up: Mapped[str] = mapped_column(String(300), default="")
    # The doctor's own notes: never shown to the patient.
    private_notes: Mapped[str] = mapped_column(Text, default="")
    # The signed report as the patient receives it (patient_view shape plus
    # the doctor and hospital), made once at finalising.
    final_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
