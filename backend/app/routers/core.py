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


def lan_address() -> str:
    """This machine's address on the local network, worked out fresh each
    time (a laptop's Wi-Fi address can change). A UDP "connect" sends
    nothing; it only asks the system which address it would use. Without a
    route (offline), the first private address of a network card."""
    import ipaddress
    import socket

    def private(ip: str) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        # 172.17.x is Docker's bridge, never the Wi-Fi.
        return a.version == 4 and a.is_private and not a.is_loopback and not ip.startswith("172.17.")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # a documentation address: nothing is sent
            ip = s.getsockname()[0]
            if private(ip):
                return ip
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if private(info[4][0]):
                return info[4][0]
    except OSError:
        pass
    try:  # Linux, no route at all: the addresses of the network cards
        import subprocess

        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout
        return next((ip for ip in out.split() if private(ip)), "")
    except (OSError, subprocess.SubprocessError):
        return ""


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
        lan_address=lan_address(),
    )


@router.get("/config", response_model=FeatureConfigBody)
def read_config(tenant: Kiosk):
    """The calling kiosk's feature switches, as set for its client."""
    return tenant
