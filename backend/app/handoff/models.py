from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import now


class PhoneHandoff(Base):
    __tablename__ = "phone_handoffs"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # open: waiting for the phone; submitted: details arrived; done: the
    # kiosk saved the visit (session_id set), so the phone can follow it.
    status: Mapped[str] = mapped_column(String(16), default="open")
    language: Mapped[str] = mapped_column(String(8), default="en")
    intake: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
