from fastapi import APIRouter, Request
from sqlalchemy import text

from .. import delivery
from ..deps import AppSettings, Db, Kiosk
from ..schemas import Capability, FeatureConfigBody, Status
from ..voice import voice_capability

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db: Db) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    return {"api": "ok", "database": database}


@router.get("/status", response_model=Status)
def status(request: Request, db: Db, settings: AppSettings):
    state = request.app.state
    online = state.runtime.online
    not_set_up = "Not set up on this server"
    needs_internet = "Needs an internet connection"

    def delivery_capability(configured: bool) -> Capability:
        if not configured:
            return Capability(available=False, detail=not_set_up)
        return Capability(available=online, detail="" if online else needs_internet)

    available, detail = voice_capability(state)
    return Status(
        online=online,
        voice=Capability(available=available, detail=detail),
        # Offline the report runs on the local medical model when one is set.
        report=Capability(
            available=True, detail=(state.llm if online else (state.offline_llm or state.llm)).name
        ),
        knowledge_base=Capability(available=True)
        if state.kb.available()
        else Capability(available=False, detail="No knowledge data has been ingested"),
        sms=delivery_capability(delivery.sms_configured(settings)),
        email=delivery_capability(delivery.email_configured(settings)),
    )


@router.get("/config", response_model=FeatureConfigBody)
def read_config(tenant: Kiosk):
    """The calling kiosk's feature switches, as set for its client."""
    return tenant
