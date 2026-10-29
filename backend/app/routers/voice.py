import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..auth import user_for_token
from ..models import Tenant
from ..tenancy import find_tenant, record
from ..vitals_need import vitals_needed
from ..voice import VoiceContext, clean_intake, pick_provider

router = APIRouter()
log = logging.getLogger("medora.voice")


@router.websocket("/ws/voice")
async def voice(ws: WebSocket, key: str = "", tenant: str = "", admin: str = "") -> None:
    """`key` is the kiosk key; browsers cannot set headers on a WebSocket.
    `tenant` + `admin` let the back office preview a client's kiosk."""
    await ws.accept()
    engine = ws.app.state.engine
    preview_id = tenant
    with Session(engine) as db:
        if preview_id:
            # `admin` is the back-office session token.
            signed_in = user_for_token(db, admin) is not None
            tenant = db.get(Tenant, preview_id) if signed_in else None
        else:
            tenant = find_tenant(db, key)
        tenant_id = tenant.id if tenant and tenant.active else None
        allowed = tenant_id is not None and tenant.voice_intake
        band_allowed = bool(tenant and tenant.smart_band)
    if not allowed:
        await ws.send_json({"type": "unavailable", "reason": "Voice is not enabled for this kiosk."})
        await ws.close()
        return

    provider, reason = pick_provider(ws.app.state)
    if provider is None:
        await ws.send_json({"type": "unavailable", "reason": reason})
        await ws.close()
        return

    try:
        start = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return
    state = ws.app.state

    async def vitals_check(symptoms: str, age: int | None) -> tuple[bool, str]:
        if not state.runtime.online:
            return True, ""
        # The language the patient chose by then (set_language).
        return await vitals_needed(state.llm, symptoms, age, language=ctx.language)

    language = start.get("language") if start.get("language") in ("auto", "en", "ml") else "en"
    known = start.get("known")
    ctx = VoiceContext(
        smart_band=bool(start.get("smartBand", True)) and band_allowed,
        # Vitals at every visit unless the settings bring back the
        # per-complaint decision.
        vitals_check=None if state.settings.vitals_always else vitals_check,
        language=language,
        known=clean_intake(known) if isinstance(known, dict) else {},
        vitals_taken=bool(start.get("vitalsTaken")),
    )

    async def inbound():
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                yield message["bytes"]
            elif message.get("text"):
                try:
                    data = json.loads(message["text"])
                except ValueError:
                    continue
                if isinstance(data, dict):
                    yield data

    async def emit(item) -> None:
        if isinstance(item, bytes):
            await ws.send_bytes(item)
        else:
            await ws.send_json(item)

    record(engine, "voice.started", f"Conversation started ({provider.name})", tenant_id)
    try:
        await provider.run(ctx, inbound(), emit)
    except (WebSocketDisconnect, asyncio.CancelledError):
        record(engine, "voice.ended", "The kiosk closed the conversation", tenant_id)
        return
    except Exception as e:
        log.exception("Voice session failed")
        record(engine, "voice.error", f"{type(e).__name__}: {e}", tenant_id, "error")
        try:
            await ws.send_json(
                {"type": "error", "message": "The conversation with Dr. Medora stopped."}
            )
        except Exception:
            return
    else:
        record(engine, "voice.ended", "Conversation finished", tenant_id)
    try:
        await ws.close()
    except Exception:
        pass
