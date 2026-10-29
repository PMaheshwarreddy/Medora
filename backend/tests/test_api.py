import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

ADMIN = {"X-Admin-Key": "test-key"}

SESSION = {
    "mode": "manual",
    "name": "Asha Rao",
    "age": 34,
    "gender": "female",
    "phone": "9876543210",
    "symptoms": "Headache and fever",
}


def _seed_admin(client, token="test-key"):
    """Signs a back-office user in, so `ADMIN` works as a session token."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import Session

    from app import auth
    from app.models import AdminSession, AdminUser

    with Session(client.app.state.engine) as db:
        user = AdminUser(email="owner@medora.test", name="Owner", password_hash=auth.hash_password("correct horse"), approved=True)
        db.add(user)
        db.flush()
        db.add(AdminSession(token_hash=auth._token_hash(token), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path / "data",
        max_upload_mb=1,
        background_tasks=False,
        ollama_embed_model="",
        offline_model="",
    )
    with TestClient(create_app(settings)) as c:
        _seed_admin(c)
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"api": "ok", "database": "ok"}


def test_default_client_config(client):
    assert client.get("/api/config").json() == {
        "voiceIntake": True,
        "manualIntake": True,
        "smartBand": True,
        "doctorReview": True,
    }
    assert client.get("/api/config", headers={"X-Kiosk-Key": "mk_wrong"}).status_code == 401


def test_session_create_is_public_but_listing_is_not(client):
    created = client.post("/api/sessions", json=SESSION)
    assert created.status_code == 201
    assert created.json()["vitals"] is None

    assert client.get("/api/sessions").status_code == 401
    listed = client.get("/api/sessions", headers=ADMIN).json()
    assert [s["name"] for s in listed] == ["Asha Rao"]


def test_session_validation(client):
    assert client.post("/api/sessions", json={**SESSION, "age": 400}).status_code == 422
    assert client.post("/api/sessions", json={**SESSION, "name": ""}).status_code == 422


def test_back_office_needs_a_signed_in_user(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions", headers={"X-Admin-Key": "guess"}).status_code == 401
    assert client.get("/api/sessions", headers=ADMIN).status_code == 200
    assert client.get("/api/sessions", headers={"Authorization": "Bearer test-key"}).status_code == 200


# --- Reports, delivery and voice ------------------------------------------

VITALS = {"heartRate": 118, "spo2": 91, "temperatureC": 38.6, "systolic": 128, "diastolic": 82}


class FakeLlm:
    name = "fake"

    def __init__(self, reply=None):
        self.reply = reply or {
            "summary": "Headache and fever for two days.",
            "urgency": "routine",
            "department": "General OPD",
            "precautions": ["Drink water", "Rest"],
            "doctor_notes": ["Ask about neck stiffness"],
        }
        self.calls = 0

    async def json(self, system, user, thinking=None, **_):
        self.calls += 1
        self.prompt = user
        return self.reply


def _new_session(client, **extra):
    return client.post("/api/sessions", json={**SESSION, **extra}).json()["id"]


def test_status_reports_unconfigured_services(client):
    status = client.get("/api/status").json()
    assert status["voice"]["available"] is False
    assert status["sms"]["available"] is False
    assert status["email"]["available"] is False
    assert status["knowledgeBase"]["available"] is False
    assert status["report"]["available"] is True


def test_vitals_are_what_the_band_measured(client):
    # A band without a blood-pressure or temperature sensor still counts.
    body = {**SESSION, "vitals": {"heartRate": 80, "spo2": 97}}
    assert client.post("/api/sessions", json=body).status_code == 201
    # Blood pressure is a pair, and an empty set is not a measurement.
    assert client.post("/api/sessions", json={**SESSION, "vitals": {"systolic": 120}}).status_code == 422
    assert client.post("/api/sessions", json={**SESSION, "vitals": {}}).status_code == 422


def test_unmeasured_vitals_are_named_in_the_case():
    from app.triage import vital_lines

    assert vital_lines({"heart_rate": 72, "spo2": None, "temperature_c": 36.84}) == [
        ("Heart rate", "72 bpm"), ("SpO2", "not measured"),
        ("Temperature", "36.8 °C"), ("Blood pressure", "not measured"),
    ]  # fmt: skip


def test_report_progress_is_readable_while_and_after_it_runs(client):
    client.app.state.llm = FakeLlm()
    sid = _new_session(client)
    assert client.get(f"/api/sessions/{sid}/report/progress").status_code == 404
    client.post(f"/api/sessions/{sid}/report")
    # Offline in tests: one model wrote it, no panel took part.
    assert client.get(f"/api/sessions/{sid}/report/progress").json()["stage"] == "done"


def test_report_vitals_can_only_raise_urgency(client):
    llm = client.app.state.llm = FakeLlm()
    sid = _new_session(client, vitals=VITALS)

    assert client.get(f"/api/sessions/{sid}/report").status_code == 404
    report = client.post(f"/api/sessions/{sid}/report").json()

    # The model said "routine"; SpO2 of 91% requires "urgent".
    assert report["urgency"] == "urgent"
    assert any("Oxygen saturation" in f for f in report["vitalFlags"])
    assert report["knowledgeUsed"] is False
    assert "SpO2 91%" in llm.prompt
    # Without the panel, no conditions or medicines are offered, and it says so.
    assert report["possibleConditions"] == [] and report["medicines"] == []
    assert "internet" in report["panelNote"]

    # Generated once, then served from the database.
    assert client.post(f"/api/sessions/{sid}/report").json() == report
    assert llm.calls == 1

    pdf = client.get(f"/api/sessions/{sid}/report.pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_report_without_vitals_and_with_bad_model_output(client):
    client.app.state.llm = FakeLlm({"urgency": "whatever", "precautions": "not a list"})
    sid = _new_session(client)
    report = client.post(f"/api/sessions/{sid}/report").json()
    assert report["urgency"] == "soon"
    assert report["department"] == "General OPD"
    assert report["precautions"] == []
    assert report["vitalsMeasured"] is False
    assert client.get(f"/api/sessions/{sid}/report.pdf").status_code == 200


def test_send_requires_configuration(client):
    client.app.state.llm = FakeLlm()
    sid = _new_session(client)
    client.post(f"/api/sessions/{sid}/report")
    for channel in ("sms", "email"):
        r = client.post(f"/api/sessions/{sid}/report/send", json={"channel": channel})
        assert r.status_code == 503
    assert client.post("/api/sessions/nope/report").status_code == 404


def test_voice_unavailable_without_provider(client):
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json()["type"] == "unavailable"


def test_voice_relays_between_browser_and_provider(client):
    class ScriptedProvider:
        name = "scripted"

        async def run(self, ctx, inbound, emit):
            await emit({"type": "ready"})
            await emit(b"\x01\x02")
            async for item in inbound:
                if isinstance(item, bytes):
                    await emit({"type": "transcript", "role": "patient", "text": f"{len(item)} bytes"})
                    await emit({"type": "request_vitals" if ctx.smart_band else "complete"})
                elif item["type"] == "vitals":
                    await emit({"type": "complete"})
                    return

    client.app.state.voice_provider = ScriptedProvider()
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "smartBand": True})
        assert ws.receive_json() == {"type": "ready"}
        assert ws.receive_bytes() == b"\x01\x02"
        ws.send_bytes(b"\x00" * 640)
        assert ws.receive_json()["text"] == "640 bytes"
        assert ws.receive_json() == {"type": "request_vitals"}
        ws.send_json({"type": "vitals", "captured": False})
        assert ws.receive_json() == {"type": "complete"}


def test_voice_tool_arguments_are_cleaned():
    from app.voice import clean_intake

    assert clean_intake(
        {"name": " Asha ", "age": "34", "gender": "Female", "phone": "", "bogus": 1}
    ) == {"name": "Asha", "age": 34, "gender": "female"}
    assert clean_intake({"age": 400, "gender": "robot"}) == {}


# --- Clients, logs, offline, mirroring ---------------------------------------


def _new_client(client, name="City Hospital", **switches):
    r = client.post("/api/admin/tenants", json={"name": name, **switches}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


def test_each_client_has_its_own_key_settings_and_sessions(client):
    assert client.post("/api/admin/tenants", json={"name": "X"}).status_code == 401
    city = _new_client(client, voiceIntake=False, smartBand=False)
    key = {"X-Kiosk-Key": city["kioskKey"]}
    assert city["kioskKey"].startswith("mk_") and city["kioskKeyHint"] == city["kioskKey"][:7] + "…"

    # The kiosk gets its own client's switches, not the default client's.
    assert client.get("/api/config", headers=key).json() == {
        "voiceIntake": False, "manualIntake": True, "smartBand": False, "doctorReview": True,
    }  # fmt: skip
    assert client.get("/api/config").json()["voiceIntake"] is True

    client.post("/api/sessions", json=SESSION, headers=key)
    client.post("/api/sessions", json={**SESSION, "name": "Default Patient"})
    mine = client.get(f"/api/sessions?tenant_id={city['id']}", headers=ADMIN).json()
    assert [s["name"] for s in mine] == ["Asha Rao"]
    assert len(client.get("/api/sessions", headers=ADMIN).json()) == 2

    listed = {t["name"]: t for t in client.get("/api/admin/tenants", headers=ADMIN).json()}
    assert listed["City Hospital"]["sessions"] == 1 and listed["Default client"]["isDefault"]
    assert "kioskKey" not in listed["City Hospital"] or listed["City Hospital"]["kioskKey"] is None

    # Names are unique; one intake mode must stay on.
    assert client.post("/api/admin/tenants", json={"name": "City Hospital"}, headers=ADMIN).status_code == 409
    r = client.patch(f"/api/admin/tenants/{city['id']}", json={"manualIntake": False}, headers=ADMIN)
    assert r.status_code == 422


def test_rotating_or_switching_off_a_client_locks_its_kiosks(client):
    city = _new_client(client)
    old = {"X-Kiosk-Key": city["kioskKey"]}
    rotated = client.post(f"/api/admin/tenants/{city['id']}/kiosk-key", headers=ADMIN).json()
    assert client.get("/api/config", headers=old).status_code == 401
    new = {"X-Kiosk-Key": rotated["kioskKey"]}
    assert client.get("/api/config", headers=new).status_code == 200

    # The client's one key is also its API key, and its calls are logged.
    assert client.post("/api/sessions", json=SESSION, headers={"X-Api-Key": city["kioskKey"]}).status_code == 401
    assert client.post("/api/sessions", json=SESSION, headers={"X-Api-Key": rotated["kioskKey"]}).status_code == 201
    keys = [k for k in client.get("/api/admin/api-keys", headers=ADMIN).json() if k["tenantId"] == city["id"]]
    assert sorted((k["revoked"], k["callsLast24h"]) for k in keys) == [(False, 1), (True, 0)]

    client.patch(f"/api/admin/tenants/{city['id']}", json={"active": False}, headers=ADMIN)
    assert client.get("/api/config", headers=new).status_code == 403
    assert client.post("/api/sessions", json=SESSION, headers=new).status_code == 403

    default = next(t for t in client.get("/api/admin/tenants", headers=ADMIN).json() if t["isDefault"])
    r = client.patch(f"/api/admin/tenants/{default['id']}", json={"active": False}, headers=ADMIN)
    assert r.status_code == 422


def test_activity_is_logged_per_client(client):
    client.app.state.llm = FakeLlm()
    city = _new_client(client)
    key = {"X-Kiosk-Key": city["kioskKey"]}
    sid = client.post("/api/sessions", json=SESSION, headers=key).json()["id"]
    client.post(f"/api/sessions/{sid}/report")

    class Broken:
        name = "broken"

        async def json(self, system, user, thinking=None, **_):
            from app.llm import LlmError

            raise LlmError("model is down")

    client.app.state.llm = Broken()
    other = client.post("/api/sessions", json=SESSION).json()["id"]
    assert client.post(f"/api/sessions/{other}/report").status_code == 503

    assert client.get("/api/admin/logs").status_code == 401
    logs = client.get(f"/api/admin/logs?tenant_id={city['id']}", headers=ADMIN).json()
    assert [entry["event"] for entry in logs] == ["report.generated", "session.created", "client.created"]
    errors = client.get("/api/admin/logs?level=error", headers=ADMIN).json()
    assert [(e["event"], e["message"]) for e in errors] == [("report.error", "model is down")]

    overview = client.get("/api/admin/overview", headers=ADMIN).json()
    assert overview["clients"] == 2 and overview["sessions"] == 2 and overview["reports"] == 1
    assert overview["errorsLast24h"] == 1


def test_offline_mode_is_reported_and_voice_needs_internet(client):
    class Online:
        name = "gemini-live:test"

        async def run(self, ctx, inbound, emit):
            await emit({"type": "ready"})

    client.app.state.voice_provider = Online()
    assert client.get("/api/status").json()["voice"] == {"available": True, "detail": "gemini-live:test"}

    client.app.state.runtime.online = False
    status = client.get("/api/status").json()
    assert status["online"] is False
    assert status["voice"] == {"available": False, "detail": "The voice agent needs an internet connection."}
    assert status["report"]["available"] is True  # reports fall back to the local model
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json() == {"type": "unavailable", "reason": "The voice agent needs an internet connection."}

    # With an offline provider installed, voice keeps working without internet.
    class Offline(Online):
        name = "offline:test"

    client.app.state.offline_voice_provider = Offline()
    assert client.get("/api/status").json()["voice"]["detail"] == "offline:test"
    # The intake itself never needed the internet.
    assert client.post("/api/sessions", json=SESSION).status_code == 201


def test_voice_respects_the_clients_switches(client):
    class Recorder:
        name = "recorder"

        async def run(self, ctx, inbound, emit):
            await emit({"type": "ready", "band": ctx.smart_band})

    client.app.state.voice_provider = Recorder()
    no_voice = _new_client(client, "No voice", voiceIntake=False)
    with client.websocket_connect(f"/ws/voice?key={no_voice['kioskKey']}") as ws:
        assert ws.receive_json()["type"] == "unavailable"
    no_band = _new_client(client, "No band", smartBand=False)
    with client.websocket_connect(f"/ws/voice?key={no_band['kioskKey']}") as ws:
        ws.send_json({"type": "start", "smartBand": True})
        assert ws.receive_json() == {"type": "ready", "band": False}
    events = [e["event"] for e in client.get(f"/api/admin/logs?tenant_id={no_band['id']}", headers=ADMIN).json()]
    assert events[:2] == ["voice.ended", "voice.started"]


def test_rows_are_mirrored_to_the_cloud_once(client, tmp_path):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app import background
    from app.db import make_engine
    from app.models import ActivityLog, IntakeSession, Tenant, TriageReport
    from app.tenancy import ensure_schema

    client.app.state.llm = FakeLlm()
    city = _new_client(client)
    sid = client.post("/api/sessions", json=SESSION, headers={"X-Kiosk-Key": city["kioskKey"]}).json()["id"]
    client.post(f"/api/sessions/{sid}/report")

    local = client.app.state.engine
    cloud = make_engine(f"sqlite:///{tmp_path / 'cloud.db'}")
    ensure_schema(cloud)
    assert background.pending(local) == 2 + 1 + 1 + 3  # clients, session, report, log lines

    assert background.mirror_once(local, cloud) == 7
    assert background.pending(local) == 0 and background.mirror_once(local, cloud) == 0
    with Session(cloud) as db:
        counts = [db.scalar(select(func.count()).select_from(m)) for m in (Tenant, IntakeSession, TriageReport, ActivityLog)]
        assert counts == [2, 1, 1, 3]
        assert db.get(IntakeSession, sid).tenant_id == city["id"]

    # A later change to a client is mirrored again; untouched rows are not.
    client.patch(f"/api/admin/tenants/{city['id']}", json={"smartBand": False}, headers=ADMIN)
    assert background.mirror_once(local, cloud) == 2  # the client, and the log line for the change
    with Session(cloud) as db:
        assert db.get(Tenant, city["id"]).smart_band is False


def test_older_databases_are_upgraded_in_place(tmp_path):
    from sqlalchemy import text

    from app.db import make_engine

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE intake_sessions (id VARCHAR(32) PRIMARY KEY, created_at TIMESTAMP, mode VARCHAR(16), name VARCHAR(200), age INTEGER, gender VARCHAR(16), phone VARCHAR(32), email VARCHAR(320), symptoms TEXT, duration VARCHAR(200), medications TEXT, vitals JSON)"))
        c.execute(text("CREATE TABLE feature_config (id INTEGER PRIMARY KEY, voice_intake BOOLEAN, manual_intake BOOLEAN, smart_band BOOLEAN)"))
        c.execute(text("INSERT INTO feature_config VALUES (1, 0, 1, 0)"))
    settings = Settings(_env_file=None, database_url=url, data_dir=tmp_path / "data", background_tasks=False)
    with TestClient(create_app(settings)) as c:
        # The old single-client switches carry over to the default client.
        assert c.get("/api/config").json() == {"voiceIntake": False, "manualIntake": True, "smartBand": False, "doctorReview": True}
        assert c.post("/api/sessions", json=SESSION).status_code == 201


# --- Knowledge management ----------------------------------------------------


def test_knowledge_browse_and_ingestion_from_the_back_office(client, tmp_path):
    assert client.get("/api/admin/knowledge/summary").status_code == 401
    assert client.get("/api/admin/knowledge/summary", headers=ADMIN).json() == {"ready": False, "legacyTables": []}
    assert client.get("/api/admin/knowledge/diseases", headers=ADMIN).status_code == 409
    assert client.post("/api/admin/knowledge/init", headers=ADMIN).json() == {"ready": True}

    class Planner:
        name = "planner"

        async def json(self, system, user, thinking=None, **_):
            return {"content": "records", "verdict": "usable", "summary": "Diseases and symptoms", "confidence": 0.95, "outputs": [
                {"kind": "link", "disease": {"sources": ["disease"]}, "symptom": {"sources": ["symptoms"], "split": ","}}]}  # fmt: skip

    client.app.state.ingest.llm = Planner()
    data = b"disease,symptoms\nInfluenza,\"fever, cough\"\nCommon cold,\"cough, sneezing\"\n"
    up = client.post("/api/admin/knowledge/ingest/upload", files={"file": ("../odd name.csv", data)}, headers=ADMIN)
    assert up.status_code == 201, up.text
    run = up.json()
    assert (run["filename"], run["status"], run["preview"]["links"]) == ("odd name.csv", "planned", 4)
    again = client.post("/api/admin/knowledge/ingest/upload", files={"file": ("copy.csv", data)}, headers=ADMIN)
    assert again.status_code == 409
    assert len(list((tmp_path / "data" / "knowledge").iterdir())) == 1

    act = lambda action, **body: client.post(  # noqa: E731
        f"/api/admin/knowledge/ingest/runs/{run['id']}/{action}", json=body or None, headers=ADMIN
    )
    assert act("load").status_code == 409  # not approved yet
    assert act("reject").status_code == 422  # a reason is required
    assert act("approve").json()["status"] == "approved"
    loaded = act("load").json()
    assert loaded["status"] == "loaded" and loaded["loaded"]["links"]["created"] == 4

    summary = client.get("/api/admin/knowledge/summary", headers=ADMIN).json()
    assert (summary["diseases"], summary["symptoms"], summary["symptomLinks"]) == (2, 3, 4)
    found = client.get("/api/admin/knowledge/symptoms?q=COUGH", headers=ADMIN).json()
    assert found["total"] == 1 and found["items"][0] == {"id": found["items"][0]["id"], "name": "Cough", "aliases": [], "links": 2, "description": ""}
    flu = client.get("/api/admin/knowledge/diseases?q=influ", headers=ADMIN).json()["items"][0]
    detail = client.get(f"/api/admin/knowledge/diseases/{flu['id']}", headers=ADMIN).json()
    assert detail["symptoms"] == ["Cough", "Fever"]

    detail = client.get(f"/api/admin/knowledge/ingest/runs/{run['id']}", headers=ADMIN).json()
    assert detail["outputs"][0]["kind"] == "link"
    assert act("undo").json()["status"] == "undone"
    assert client.get("/api/admin/knowledge/summary", headers=ADMIN).json()["diseases"] == 0
    events = [e["event"] for e in client.get("/api/admin/logs", headers=ADMIN).json()]
    assert events[:4] == ["knowledge.undo", "knowledge.load", "knowledge.approve", "knowledge.planned"]


# --- API keys, system settings, kiosk preview ---------------------------------


def test_api_keys_identify_the_client_and_every_call_is_logged(client):
    client.app.state.llm = FakeLlm()
    city = _new_client(client)
    assert client.post("/api/admin/api-keys", json={"tenantId": city["id"], "name": "HIS"}).status_code == 401
    created = client.post("/api/admin/api-keys", json={"tenantId": city["id"], "name": "Hospital system"}, headers=ADMIN)
    assert created.status_code == 201
    key = created.json()
    assert key["apiKey"].startswith("ma_") and key["tenantName"] == "City Hospital"
    api = {"X-Api-Key": key["apiKey"]}

    # The client's system creates a session and gets its report without a kiosk.
    sid = client.post("/api/sessions", json=SESSION, headers=api).json()["id"]
    assert client.post(f"/api/sessions/{sid}/report", headers=api).status_code == 200
    assert client.post("/api/sessions", json={**SESSION, "age": 999}, headers=api).status_code == 422
    assert client.post("/api/sessions", json=SESSION, headers={"X-Api-Key": "ma_wrong"}).status_code == 401
    assert client.get(f"/api/sessions?tenant_id={city['id']}", headers=ADMIN).json()[0]["id"] == sid

    logs = client.get("/api/admin/api-logs", headers=ADMIN).json()
    assert [(l["method"], l["status"]) for l in logs] == [("POST", 422), ("POST", 200), ("POST", 201)]
    assert logs[-1]["keyName"] == "Hospital system" and logs[-1]["path"] == "/api/sessions"
    listed = next(k for k in client.get("/api/admin/api-keys", headers=ADMIN).json() if k["name"] == "Hospital system")
    assert (listed["callsLast24h"], listed["errorsLast24h"], listed["apiKey"]) == (3, 1, None)
    assert listed["lastUsedAt"] is not None

    # Kiosk traffic is not API traffic.
    client.post("/api/sessions", json=SESSION)
    assert len(client.get("/api/admin/api-logs", headers=ADMIN).json()) == 3

    assert client.delete(f"/api/admin/api-keys/{key['id']}", headers=ADMIN).status_code == 204
    assert client.post("/api/sessions", json=SESSION, headers=api).status_code == 401
    assert next(k for k in client.get("/api/admin/api-keys", headers=ADMIN).json() if k["name"] == "Hospital system")["revoked"] is True


def test_back_office_can_preview_a_clients_kiosk(client):
    city = _new_client(client, voiceIntake=False)
    preview = {**ADMIN, "X-Tenant-Id": city["id"]}
    assert client.get("/api/config", headers=preview).json()["voiceIntake"] is False
    assert client.get("/api/config", headers={"X-Tenant-Id": city["id"]}).status_code == 401
    assert client.get("/api/config", headers={**ADMIN, "X-Tenant-Id": "nope"}).status_code == 404
    sid = client.post("/api/sessions", json=SESSION, headers=preview).json()["id"]
    assert client.get(f"/api/sessions?tenant_id={city['id']}", headers=ADMIN).json()[0]["id"] == sid

    class Hello:
        name = "hello"

        async def run(self, ctx, inbound, emit):
            await emit({"type": "ready"})

    client.app.state.voice_provider = Hello()
    default = next(t for t in client.get("/api/admin/tenants", headers=ADMIN).json() if t["isDefault"])
    with client.websocket_connect(f"/ws/voice?tenant={default['id']}&admin=wrong") as ws:
        assert ws.receive_json()["type"] == "unavailable"
    with client.websocket_connect(f"/ws/voice?tenant={default['id']}&admin=test-key") as ws:
        ws.send_json({"type": "start"})
        assert ws.receive_json() == {"type": "ready"}


def test_system_settings_and_dashboard_figures(client):
    system = client.get("/api/admin/system", headers=ADMIN).json()
    assert system["panelSize"] == 5 and system["panelMax"] == 18
    assert {i["name"]: i["ok"] for i in system["integrations"]}["Report by SMS"] is False
    assert client.put("/api/admin/system", json={"panelSize": 99}, headers=ADMIN).status_code == 422
    assert client.put("/api/admin/system", json={"panelSize": 8}, headers=ADMIN).json()["panelSize"] == 8

    client.post("/api/sessions", json=SESSION)
    client.post("/api/sessions", json=SESSION)
    overview = client.get("/api/admin/overview", headers=ADMIN).json()
    assert len(overview["sessionsByDay"]) == 7 and overview["sessionsByDay"][-1]["count"] == 2
    assert overview["sessionsByClient"] == [{"name": "Default client", "count": 2}]
    assert overview["recentActivity"][0]["event"] == "session.created"
    assert overview["apiCallsLast24h"] == 0


# --- Accounts -----------------------------------------------------------------


def _fresh(tmp_path, registration_open=False):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'fresh.db'}", data_dir=tmp_path / "data", background_tasks=False, ollama_embed_model="", registration_open=registration_open)
    return TestClient(create_app(settings))


def test_first_account_claims_the_installation_and_approves_the_rest(tmp_path):
    with _fresh(tmp_path) as c:
        assert c.get("/api/admin/tenants").status_code == 401

        weak = c.post("/api/auth/register", json={"email": "a@b.co", "password": "short"})
        assert weak.status_code == 422 and "8 characters" in weak.json()["detail"]
        assert c.post("/api/auth/register", json={"email": "not-an-email", "password": "long enough"}).status_code == 422

        first = c.post("/api/auth/register", json={"email": "  Owner@Medora.io ", "name": "Priya", "password": "correct horse"})
        assert first.status_code == 201
        owner = {"X-Admin-Key": first.json()["token"]}
        assert first.json()["user"]["email"] == "owner@medora.io" and first.json()["user"]["approved"]
        assert c.get("/api/auth/me", headers=owner).json()["name"] == "Priya"
        assert c.post("/api/auth/register", json={"email": "owner@medora.io", "password": "another one"}).status_code == 409

        # A second account is created but cannot sign in until approved.
        second = c.post("/api/auth/register", json={"email": "sam@medora.io", "password": "battery staple"})
        assert second.json()["token"] is None
        login = {"email": "sam@medora.io", "password": "battery staple"}
        waiting = c.post("/api/auth/login", json=login)
        assert waiting.status_code == 403 and "approval" in waiting.json()["detail"]

        users = c.get("/api/admin/users", headers=owner).json()
        sam = next(u for u in users if u["email"] == "sam@medora.io")
        assert c.patch(f"/api/admin/users/{sam['id']}", json={"approved": True}).status_code == 401
        assert c.patch(f"/api/admin/users/{sam['id']}", json={"approved": True}, headers=owner).json()["approved"]
        sam_token = {"X-Admin-Key": c.post("/api/auth/login", json=login).json()["token"]}
        assert c.get("/api/admin/tenants", headers=sam_token).status_code == 200

        # Switching an account off signs it out everywhere, at once.
        me = next(u for u in users if u["email"] == "owner@medora.io")
        assert c.patch(f"/api/admin/users/{me['id']}", json={"active": False}, headers=owner).status_code == 422
        c.patch(f"/api/admin/users/{sam['id']}", json={"active": False}, headers=owner)
        assert c.get("/api/admin/tenants", headers=sam_token).status_code == 401
        assert c.post("/api/auth/login", json=login).status_code == 403


def test_with_open_registration_every_account_works_at_once(tmp_path):
    with _fresh(tmp_path, registration_open=True) as c:
        c.post("/api/auth/register", json={"email": "owner@medora.io", "password": "correct horse"})
        second = c.post("/api/auth/register", json={"email": "sam@medora.io", "password": "battery staple"}).json()
        assert c.get("/api/admin/tenants", headers={"X-Admin-Key": second["token"]}).status_code == 200


def test_sign_in_sign_out_and_lockout(client):
    good = {"email": "OWNER@medora.test", "password": "correct horse"}
    token = client.post("/api/auth/login", json=good).json()["token"]
    assert client.get("/api/auth/me", headers={"X-Admin-Key": token}).json()["lastLoginAt"]
    assert client.post("/api/auth/logout", headers={"X-Admin-Key": token}).status_code == 204
    assert client.get("/api/auth/me", headers={"X-Admin-Key": token}).status_code == 401

    # Unknown email and wrong password answer alike.
    wrong = client.post("/api/auth/login", json={**good, "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@medora.test", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]

    for _ in range(4):
        client.post("/api/auth/login", json={**good, "password": "nope"})
    locked = client.post("/api/auth/login", json=good)  # even the right password waits
    assert locked.status_code == 429
    events = [e["event"] for e in client.get("/api/admin/logs", headers=ADMIN).json()]
    assert events.count("account.login_failed") == 6


def test_passwords_and_tokens_are_not_stored_readable(client):
    from sqlalchemy import text

    client.post("/api/auth/login", json={"email": "owner@medora.test", "password": "correct horse"})
    with client.app.state.engine.connect() as c:
        stored = " ".join(str(v) for row in c.execute(text("select * from admin_users")) for v in row)
        tokens = " ".join(str(v) for row in c.execute(text("select * from admin_sessions")) for v in row)
    assert "correct horse" not in stored and "scrypt$" in stored
    assert "test-key" not in tokens


# --- Vitals only when the complaint calls for them --------------------------


def test_vitals_are_skipped_only_on_a_clear_no_from_the_hosted_model(client):
    import asyncio

    from app.llm import LlmError
    from app.vitals_need import vitals_needed

    no = FakeLlm({"needed": False, "reason": "Your knee pain does not need a heart or oxygen check."})
    assert asyncio.run(vitals_needed(no, "Pain in my left knee since I twisted it", 30)) == (
        False, "Your knee pain does not need a heart or oxygen check.",
    )  # fmt: skip
    # The very young and the old always get them, whatever the model says.
    assert asyncio.run(vitals_needed(no, "Knee pain", 70))[0] is True
    assert asyncio.run(vitals_needed(no, "Knee pain", 3))[0] is True
    # A vague or failed answer means vitals are taken.
    assert asyncio.run(vitals_needed(FakeLlm({"reason": "?"}), "Knee pain", 30))[0] is True

    class Down:
        name = "gemini"

        async def json(self, system, user, thinking=None, **_):
            raise LlmError("429")

    assert asyncio.run(vitals_needed(Down(), "Knee pain", 30))[0] is True
    local = FakeLlm({"needed": False})
    local.name = "ollama:qwen"
    assert asyncio.run(vitals_needed(local, "Knee pain", 30))[0] is True

    # Over the API: vitals are a must at every visit by default.
    client.app.state.llm = no
    body = {"symptoms": "Knee pain", "age": 30}
    assert client.post("/api/intake/vitals-check", json=body).json()["needed"] is True
    # With the per-complaint decision switched back on: offline, always yes.
    client.app.state.settings.vitals_always = False
    client.app.state.runtime.online = False
    assert client.post("/api/intake/vitals-check", json=body).json()["needed"] is True
    client.app.state.runtime.online = True
    assert client.post("/api/intake/vitals-check", json=body).json() == {
        "needed": False, "reason": "Your knee pain does not need a heart or oxygen check.",
    }  # fmt: skip


def test_an_unexpected_failure_still_gives_the_patient_a_report(client):
    class Broken:
        name = "broken-panel"

        async def run(self, case, specialists, progress=None):
            raise RuntimeError("something nobody expected")

    client.app.state.llm = FakeLlm()
    client.app.state.panel = Broken()
    client.app.state.runtime.online = True
    sid = _new_session(client)
    response = client.post(f"/api/sessions/{sid}/report")
    assert response.status_code == 200
    report = response.json()
    assert report["summary"] == "Headache and fever for two days."
    assert report["possibleConditions"] == [] and report["medicines"] == []
    assert "problem" in report["panelNote"]
    logs = client.get("/api/admin/logs", headers=ADMIN).json()
    assert any(l["event"] == "report.error" and l["level"] == "error" for l in logs)


def test_voice_tools_decide_on_vitals_and_never_measure_twice():
    import asyncio

    from app.voice import IntakeTools, VoiceContext

    async def conversation(needed: bool):
        sent, asked = [], []

        async def emit(item):
            sent.append(item)

        async def check(symptoms, age):
            asked.append(symptoms)
            return needed, "" if needed else "Your back pain does not need a heart or oxygen check."

        tools = IntakeTools(VoiceContext(smart_band=True, vitals_check=check), emit)
        await tools.call("1", "update_intake", {"symptoms": "Lower back pain after lifting"})
        first = await tools.call("2", "vitals_needed", {})
        return tools, sent, asked, first

    async def scenario():
        # Not needed: the agent is told to skip, the kiosk is told why, and a
        # request_vitals anyway does not start the band.
        tools, sent, asked, first = await conversation(needed=False)
        assert first["needed"] is False and "Do not mention vitals" in first["result"]
        assert asked == ["Lower back pain after lifting"]
        assert {"type": "vitals_skipped", "reason": "Your back pain does not need a heart or oxygen check."} in sent
        assert (await tools.call("3", "request_vitals", {}))["result"].startswith("Vitals are not needed")
        assert {"type": "request_vitals"} not in sent

        # Needed: the band is shown once; asking again is answered from the
        # first measurement, and the decision is not asked twice.
        tools, sent, asked, first = await conversation(needed=True)
        assert first == {"needed": True}
        assert await tools.call("3", "request_vitals", {}) is None
        assert sent.count({"type": "request_vitals"}) == 1
        assert (await tools.call("4", "request_vitals", {}))["result"].startswith("The measurement is already running")
        call_id, result = tools.vitals_measured({"type": "vitals", "captured": True, "heartRate": 72, "spo2": 98})
        assert call_id == "3" and result["result"] == "Vitals measured: heart rate, oxygen level. Do not read the numbers out."
        again = await tools.call("5", "request_vitals", {})
        assert "do not ask again" in again["note"]
        assert (await tools.call("6", "vitals_needed", {}))["needed"] is False
        assert sent.count({"type": "request_vitals"}) == 1 and len(asked) == 1

        # Vitals are a must: finishing before they were taken is refused
        # (twice at most, then the review screen takes them).
        tools = IntakeTools(VoiceContext(smart_band=True), emit=lambda item: asyncio.sleep(0))
        assert (await tools.call("1", "finish_intake", {}))["result"].startswith("Not finished")
        assert not tools.finishing
        assert await tools.call("2", "request_vitals", {}) is None
        assert (await tools.call("3", "finish_intake", {})) == {"result": "ok"}
        tools = IntakeTools(VoiceContext(smart_band=True), emit=lambda item: asyncio.sleep(0))
        for i in range(IntakeTools.MAX_FINISH_REFUSALS):
            assert (await tools.call(str(i), "finish_intake", {}))["result"].startswith("Not finished")
        assert (await tools.call("9", "finish_intake", {})) == {"result": "ok"}

        # A measurement whose call was dropped (new line to the model)
        # still reaches the model, as a message.
        tools = IntakeTools(VoiceContext(smart_band=True), emit=lambda item: asyncio.sleep(0))
        await tools.call("1", "request_vitals", {})
        tools.drop_pending()
        call_id, result = tools.vitals_measured({"captured": True, "heartRate": 80})
        assert call_id is None and result["result"].startswith("Vitals measured: heart rate")
        assert tools.vitals_done and tools.vitals_measured({"captured": True}) is None

        # Vitals the kiosk already took (the page was reloaded) are not taken again.
        tools = IntakeTools(VoiceContext(smart_band=True, vitals_taken=True), emit=lambda item: asyncio.sleep(0))
        assert "already" in (await tools.call("1", "request_vitals", {}))["result"]
        assert (await tools.call("2", "finish_intake", {})) == {"result": "ok"}

        # A kiosk without a band never mentions vitals.
        tools = IntakeTools(VoiceContext(smart_band=False), emit=lambda item: asyncio.sleep(0))
        assert (await tools.call("1", "vitals_needed", {}))["needed"] is False

    asyncio.run(scenario())


def test_offline_visits_are_served_from_memory_and_copied_back(client):
    from app.models import IntakeSession, TriageReport
    from app.panel import PanelResult
    from sqlalchemy.orm import Session as DbSession

    state = client.app.state
    # Seen online once: the kiosk's client is remembered.
    assert client.get("/api/config").status_code == 200

    class LocalPanel:
        name = "local-panel:medgemma"

        def __init__(self):
            self.asked = None

        async def run(self, case, specialists, progress=None):
            self.asked = specialists
            return PanelResult([], {"summary": "Fever for two days.", "urgency": "soon", "department": "General OPD",
                                    "possible_conditions": [{"name": "Viral fever", "likelihood": "high"}]}, self.name)  # fmt: skip

    local = FakeLlm()
    local.name, local.clinical = "ollama:medgemma:4b", True
    state.offline_llm, state.offline_panel = local, LocalPanel()
    state.llm = FakeLlm()  # online model: must not be used offline
    state.runtime.online = False

    sid = _new_session(client)
    with DbSession(state.engine) as db:
        assert db.get(IntakeSession, sid) is None  # nothing saved while offline
    report = client.post(f"/api/sessions/{sid}/report").json()
    assert report["generator"] == "local-panel:medgemma" and state.llm.calls == 0
    assert report["department"] == "General OPD"
    # The local model's answers went through the same condition check.
    stored = state.offline.visit(sid).report
    assert "Viral fever" in [c["name"] for c in stored["possibleConditions"]] + stored["conditionsRuledOut"]
    # A doctor reviews this hospital's reports: the patient's copy holds the
    # AI's conditions back, and never carries the doctor's view.
    assert report["awaitingDoctor"] is True and report["possibleConditions"] == []
    assert "doctorView" not in report and stored["doctorView"]["conditions"]
    assert client.get(f"/api/sessions/{sid}/report").json() == report
    assert client.get(f"/api/sessions/{sid}/report.pdf").status_code == 200
    # The patient's page (QR) works offline too: waiting for the doctor.
    assert client.get(f"/api/sessions/{sid}/final").json()["status"] == "waiting"
    assert state.offline.pending() >= 2

    # The internet is back: the visit, its report and the log are copied.
    state.runtime.online = True
    assert state.offline.flush(state.engine) >= 2
    assert state.offline.pending() == 0
    with DbSession(state.engine) as db:
        assert db.get(IntakeSession, sid).name == "Asha Rao"
        assert db.get(TriageReport, sid).data["generator"] == "local-panel:medgemma"
    logs = client.get("/api/admin/logs", headers=ADMIN).json()
    assert any(l["event"] == "session.created" and "offline" in l["message"] for l in logs)


def test_a_small_local_model_is_still_not_trusted_offline(client):
    state = client.app.state
    state.offline_llm = state.offline_panel = None  # no medical model configured
    small = FakeLlm()
    small.name = "ollama:qwen2.5:3b"
    state.llm = small
    state.runtime.online = False
    sid = _new_session(client)
    report = client.post(f"/api/sessions/{sid}/report").json()
    assert report["possibleConditions"] == [] and report["medicines"] == []


def test_every_patient_report_comes_in_simple_english_and_malayalam(client):
    from app.patient_view import build_patient_view, how_to_take, plain_view
    from app.models import IntakeSession
    from sqlalchemy.orm import Session as DbSession

    class Wording(FakeLlm):
        name, clinical = "gemini:test", True

        def __init__(self, broken_numbers=False):
            super().__init__()
            self.broken_numbers = broken_numbers

        async def json(self, system, user, thinking=None, **_):
            if "patient's copy of a hospital" in system:
                lines = [l for l in user.splitlines() if l[:1].isdigit()]
                items = []
                for line in lines:
                    task, text = line.split("[", 1)[1].split("] ", 1)
                    en = text if not self.broken_numbers else text.replace("6", "8")
                    if task == "patient_words":
                        en = "fever, headache" if "പനി" in text else en
                    items.append({"en": f"Simple: {en}", "ml": f"മലയാളം {en}"})
                return {"items": items}
            return await super().json(system, user, thinking)

    state = client.app.state
    state.llm = Wording()
    state.panel = None  # the plain report path is enough here
    state.runtime.online = True
    sid = _new_session(client, language="ml", symptoms="പനി, തലവേദന", allergies="penicillin")
    with DbSession(state.engine) as db:
        assert db.get(IntakeSession, sid).language == "ml"
    report = client.post(f"/api/sessions/{sid}/report").json()
    view = report["patientView"]
    assert view["bilingual"] is True and report["language"] == "ml"
    assert view["patient"]["name"] == "Asha Rao"
    assert view["symptoms"]["en"] == "Simple: fever, headache" and view["symptoms"]["ml"].startswith("മലയാളം")
    assert view["allergies"]["en"].startswith("Simple")
    assert view["summary"]["en"].startswith("Simple") and view["summary"]["ml"].startswith("മലയാളം")
    assert all(line["ml"] for line in view["precautions"])
    assert client.get(f"/api/sessions/{sid}/report.pdf").status_code == 200

    # A dose instruction is built from the reviewed fields, never reworded,
    # and a translation that changes a number is not used.
    medicine = {"name": "Paracetamol", "form": "tablet", "dose": "500 mg", "frequency": "every 6 hours",
                "duration": "3 days", "maxDaily": "4000 mg"}  # fmt: skip
    assert how_to_take(medicine) == "500 mg, every 6 hours, for 3 days. At most 4000 mg in 24 hours."
    built = {**report, "medicines": [medicine]}
    with DbSession(state.engine) as db:
        session = db.get(IntakeSession, sid)
    view = asyncio.run(build_patient_view(Wording(broken_numbers=True), built, session))
    how = view["medicines"][0]["howToTake"]
    assert how["en"] == how_to_take(medicine) and how["ml"] is None

    # Without the hosted model: the report's own English, no Malayalam.
    local = Wording()
    local.name, local.clinical = "ollama:qwen", False
    view = asyncio.run(build_patient_view(local, built, session))
    assert view["translated"] is False and view["medicines"][0]["howToTake"].get("ml") is None
    assert plain_view(built, session)["patient"]["phone"] == "9876543210"


def test_an_english_visit_gets_an_english_only_report_with_the_doctors_medicines(client):
    from app.patient_view import _prompt
    from app.routers.reports import patient_medicines

    asked = []

    class Wording(FakeLlm):
        name, clinical = "gemini:test", True

        async def json(self, system, user, thinking=None, **_):
            if "patient's copy of a hospital" in system:
                asked.append(system)
                lines = [l for l in user.splitlines() if l[:1].isdigit()]
                return {"items": [{"en": l.split("] ", 1)[1]} for l in lines]}
            return await super().json(system, user, thinking)

    state = client.app.state
    state.llm = Wording()
    state.panel = None
    state.runtime.online = True
    sid = _new_session(client, language="en")
    view = client.post(f"/api/sessions/{sid}/report").json()["patientView"]
    assert view["language"] == "en" and view["translated"] is True
    assert "Malayalam" not in asked[0] and '"ml"' not in asked[0]
    assert all(set(line) == {"en"} for line in view["precautions"])
    assert "Malayalam" in _prompt("ml") and '"ml"' in _prompt("ml")
    assert client.get(f"/api/sessions/{sid}/report.pdf").status_code == 200

    # The patient's copy lists the doctor's reviewed medicines, emergency
    # care included, without pregnancy wording the patient did not raise.
    class Visit:
        symptoms, medications, pregnancy = "fever", "", ""

    data = {"medicines": [], "doctorView": {"medicines": [
        {"name": "Paracetamol", "dose": "650 mg", "caution": "Doctor to check LMP / hCG before giving.",
         "doctorOnly": True, "doseEvidence": {"found": True}},
        {"name": "Ondansetron", "dose": "4 mg", "caution": "Ask about pregnancy first. Take after food."},
    ]}}
    shown = patient_medicines(data, Visit())
    assert [m["name"] for m in shown] == ["Paracetamol", "Ondansetron"]
    assert shown[0]["doctorOnly"] is True and "doseEvidence" not in shown[0]
    assert shown[1]["caution"] == "Take after food."

def test_the_voice_agent_speaks_the_chosen_language():
    from app.voice import system_instruction

    english = system_instruction(True)
    malayalam = system_instruction(True, "ml")
    assert "simple English" in english and "Malayalam" not in english
    assert "simple Malayalam" in malayalam and "Speak ONLY Malayalam" in malayalam


def test_allergies_and_the_pregnancy_answer_reach_the_report_rules(client):
    from app import sensitive
    from app.models import IntakeSession
    from app.report_writer import _rules
    from app.voice import clean_intake, system_instruction
    from sqlalchemy.orm import Session as DbSession

    sid = _new_session(client, allergies="penicillin", pregnancy="no")
    with DbSession(client.app.state.engine) as db:
        row = db.get(IntakeSession, sid)
        assert (row.allergies, row.pregnancy) == ("penicillin", "no")
    assert client.post("/api/sessions", json={**SESSION, "pregnancy": "maybe"}).status_code == 422

    amoxicillin = {"name": "Amoxicillin", "dose": "500 mg", "frequency": "every 8 hours", "route": "oral"}
    paracetamol = {"name": "Paracetamol", "dose": "500 mg", "frequency": "every 6 hours", "route": "oral"}
    shown, _ = _rules([amoxicillin, paracetamol], "routine", 30, "male", {}, True, "", "allergic to penicillin")
    assert [m["name"] for m in shown] == ["Paracetamol"]
    # She said she may be pregnant: every medicine not known to be safe says so.
    ibuprofen = {"name": "Ibuprofen", "dose": "400 mg", "frequency": "every 8 hours", "route": "oral"}
    shown, _ = _rules([ibuprofen], "routine", 28, "female", {}, True, "", "", "yes")
    assert "may be pregnant" in shown[0]["caution"]

    # Her own answer lets the report speak of it; otherwise it stays hidden.
    report = {"possibleConditions": [{"name": "Threatened miscarriage"}], "precautions": [], "lifestyleAdvice": [],
              "doctorNotes": [], "summary": "", "clinicalSummary": "", "medicines": [], "panel": [], "discussion": ""}  # fmt: skip
    assert sensitive.clean(dict(report), "bleeding", "", True, "yes")["possibleConditions"]
    assert not sensitive.clean(dict(report), "bleeding", "", True, "no")["possibleConditions"]

    assert clean_intake({"pregnancy": "Yes", "allergies": "dust"}) == {"pregnancy": "yes", "allergies": "dust"}
    assert clean_intake({"pregnancy": "probably"}) == {}
    rules = system_instruction(True)
    assert "allergic to any medicine or injection" in rules
    assert "PREGNANCY, ONLY WHEN IT MATTERS" in rules



def test_status_gives_the_servers_network_address_for_qr_codes(client):
    import ipaddress

    address = client.get("/api/status").json()["lanAddress"]
    # A private IPv4 address, or empty on a machine with no network card.
    assert address == "" or ipaddress.ip_address(address).is_private
