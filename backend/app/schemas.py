from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """JSON is camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class FeatureConfigBody(ApiModel):
    voice_intake: bool = True
    manual_intake: bool = True
    smart_band: bool = True
    doctor_review: bool = True

    @model_validator(mode="after")
    def _one_way_in(self):
        if not self.voice_intake and not self.manual_intake:
            raise ValueError("Voice and manual intake cannot both be switched off")
        return self


class VitalsBody(ApiModel):
    """The readings the band took. A band measures only what its hardware
    supports, so any value may be missing, but not all of them, and blood
    pressure comes as a pair."""

    heart_rate: int | None = Field(default=None, ge=0, le=300)
    spo2: int | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = Field(default=None, ge=20, le=45)
    systolic: int | None = Field(default=None, ge=0, le=300)
    diastolic: int | None = Field(default=None, ge=0, le=200)

    @model_validator(mode="after")
    def _complete_enough(self):
        if (self.systolic is None) != (self.diastolic is None):
            raise ValueError("Blood pressure needs both systolic and diastolic")
        if all(v is None for v in (self.heart_rate, self.spo2, self.temperature_c, self.systolic)):
            raise ValueError("Send vitals only when the band measured at least one")
        return self


class SessionCreate(ApiModel):
    # phone: filled in on the patient's own phone (QR at the kiosk).
    mode: Literal["voice", "manual", "phone"]
    name: str = Field(min_length=1, max_length=200)
    age: int = Field(ge=0, le=120)
    gender: Literal["male", "female", "other"]
    phone: str = Field(min_length=7, max_length=32)
    email: str = Field(default="", max_length=320)
    symptoms: str = Field(min_length=1)
    duration: str = Field(default="", max_length=200)
    medications: str = ""
    vitals: VitalsBody | None = None
    allergies: str = Field(default="", max_length=1000)
    # Only asked when the complaint makes it matter; empty when not asked.
    pregnancy: Literal["", "yes", "no", "unsure"] = ""
    # A returning patient picked at the kiosk (patients/service.lookup);
    # empty for a new patient, who gets a record when the visit is saved.
    patient_id: str | None = Field(default=None, max_length=32)
    chronic_conditions: str = Field(default="", max_length=1000)
    regular_medicines: str = Field(default="", max_length=1000)
    past_surgeries: str = Field(default="", max_length=1000)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    habits: str = Field(default="", max_length=500)
    # The patient's language on the kiosk: en (English) or ml (Malayalam).
    # The report's patient-facing text is also given in this language.
    language: Literal["en", "ml"] = "en"


class SessionOut(SessionCreate):
    id: str
    created_at: datetime
    tenant_id: str | None = None
    has_report: bool = False


class Capability(ApiModel):
    available: bool
    detail: str = ""


class Status(ApiModel):
    """What this server can do right now, so the kiosk only offers what works."""

    # False when this server has no internet: it then runs in offline mode.
    online: bool
    voice: Capability
    report: Capability
    knowledge_base: Capability
    sms: Capability
    email: Capability
    # This server's address on the local network (e.g. 192.168.1.20), so a
    # kiosk opened as localhost can put a phone-reachable address in its QR
    # codes; empty when it has none.
    lan_address: str = ""


class TenantCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    voice_intake: bool = True
    manual_intake: bool = True
    smart_band: bool = True
    doctor_review: bool = True
    # The hospital's first administrator, created with the client (optional).
    admin_name: str = Field(default="", max_length=200)
    admin_email: str = Field(default="", max_length=320)
    admin_password: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _one_way_in(self):
        if not self.voice_intake and not self.manual_intake:
            raise ValueError("Voice and manual intake cannot both be switched off")
        return self


class TenantUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    voice_intake: bool | None = None
    manual_intake: bool | None = None
    smart_band: bool | None = None
    doctor_review: bool | None = None


class TenantOut(ApiModel):
    id: str
    created_at: datetime
    name: str
    is_default: bool
    active: bool
    kiosk_key_hint: str
    voice_intake: bool
    manual_intake: bool
    smart_band: bool
    doctor_review: bool = True
    sessions: int = 0
    last_session_at: datetime | None = None
    # Present only in the response that creates or rotates the key.
    kiosk_key: str | None = None


class LogOut(ApiModel):
    id: str
    at: datetime
    tenant_id: str | None
    level: str
    event: str
    message: str
