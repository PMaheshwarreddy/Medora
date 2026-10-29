"""Patients, the doctor portal, the signed final report, and the phone
hand-off."""

from test_api import ADMIN, SESSION, FakeLlm, client  # noqa: F401  (pytest fixture)
from test_hospital import _admin_of, _hospital


def _doctor(client, admin_token, email="dr.nair@city.in", department=None):
    made = client.post(
        "/api/hospital/people",
        json={"email": email, "name": "Dr. Anita Nair", "role": "doctor", "registrationNumber": "KMC-12345",
              "qualification": "MBBS, MD", "departmentId": department},
        headers=admin_token,
    ).json()  # fmt: skip
    login = client.post("/api/hospital/auth/login", json={"email": email, "password": made["temporaryPassword"]})
    return {"X-Hospital-Token": login.json()["token"]}


class Writer(FakeLlm):
    """Answers every model call the report pipeline makes, plainly."""

    name, clinical = "gemini:test", True

    async def json(self, system, user, thinking=None, **_):
        if "patient's copy of a hospital" in system:
            count = sum(1 for line in user.splitlines() if line[:1].isdigit())
            return {"items": [{"en": "plain words", "ml": "മലയാളം"} for _ in range(count)]}
        return await super().json(system, user, thinking)


def _visit(client, kiosk_key, **extra):
    client.app.state.llm = Writer()
    client.app.state.panel = None
    client.app.state.runtime.online = True
    sid = client.post("/api/sessions", json={**SESSION, **extra}, headers={"X-Kiosk-Key": kiosk_key}).json()["id"]
    report = client.post(f"/api/sessions/{sid}/report").json()
    return sid, report


def test_returning_patients_are_recognised_by_phone_with_masked_names(client):
    tenant_id, key = _hospital(client)
    headers = {"X-Kiosk-Key": key}
    first = client.post("/api/sessions", json={**SESSION, "allergies": "penicillin"}, headers=headers).json()
    found = client.post("/api/intake/patients", json={"phone": "+91 98765 43210"}, headers=headers).json()
    assert [(p["label"], p["age"]) for p in found] == [("A*** R***", 34)]
    # Someone else at the same number is a separate person.
    client.post("/api/sessions", json={**SESSION, "name": "Ravi Rao", "age": 60}, headers=headers)
    found = client.post("/api/intake/patients", json={"phone": "9876543210"}, headers=headers).json()
    assert [p["label"] for p in found] == ["A*** R***", "R*** R***"]
    # The default client does not see this hospital's patients.
    assert client.post("/api/intake/patients", json={"phone": "9876543210"}).json() == []

    # Picking yourself links the visit and merges what you report now.
    again = client.post(
        "/api/sessions",
        json={**SESSION, "patientId": found[0]["id"], "allergies": "sulfa", "chronicConditions": "diabetes"},
        headers=headers,
    ).json()
    from app.models import IntakeSession
    from app.patients.models import Patient
    from sqlalchemy.orm import Session as DbSession

    with DbSession(client.app.state.engine) as db:
        patient = db.get(Patient, found[0]["id"])
        assert patient.visits == 2 and patient.allergies == "penicillin, sulfa" and patient.conditions == "diabetes"
        assert db.get(IntakeSession, again["id"]).patient_id == db.get(IntakeSession, first["id"]).patient_id


def test_the_doctor_report_shows_everything_but_the_patient_waits_for_the_doctor(client):
    tenant_id, key = _hospital(client)
    sid, report = _visit(client, key)
    # The kiosk gets a preliminary report: no AI conditions or medicines,
    # and never the doctor's view.
    assert report["awaitingDoctor"] is True
    assert report["possibleConditions"] == [] and report["medicines"] == [] and "doctorView" not in report
    assert client.get(f"/api/sessions/{sid}/report").json()["medicines"] == []
    assert client.get(f"/api/sessions/{sid}/final").json()["status"] == "waiting"
    assert client.get(f"/api/sessions/{sid}/report.pdf").status_code == 200

    # Without doctor review the kiosk report is as before.
    client.patch(f"/api/admin/tenants/{tenant_id}", json={"doctorReview": False}, headers=ADMIN)
    sid2, report2 = _visit(client, key, name="Other")
    assert report2["awaitingDoctor"] is False
    assert client.get(f"/api/sessions/{sid2}/final").json()["status"] == "no_review"


def test_a_doctor_picks_reviews_and_signs_and_the_patient_gets_the_final_report(client):
    tenant_id, key = _hospital(client)
    admin = _admin_of(client, tenant_id)
    dr = _doctor(client, admin)
    other = _doctor(client, admin, email="dr.menon@city.in")
    sid, _ = _visit(client, key)

    queue = client.get("/api/doctor/queue?scope=all", headers=dr).json()
    assert [p["id"] for p in queue["patients"]] == [sid]
    entry = queue["patients"][0]
    assert entry["status"] == "waiting" and entry["visitNumber"] == sid[:6].upper()
    # A hospital admin is not a doctor.
    assert client.get("/api/doctor/queue", headers=admin).status_code == 403

    picked = client.post(f"/api/doctor/visits/{sid}/pick", headers=dr)
    assert picked.status_code == 200 and picked.json()["status"] == "in_consultation"
    # The patient is locked to this doctor.
    assert client.post(f"/api/doctor/visits/{sid}/pick", headers=other).status_code == 409
    assert client.get("/api/doctor/queue?scope=all", headers=other).json()["patients"][0]["withDoctor"] == "Dr. Anita Nair"
    assert client.get(f"/api/sessions/{sid}/final").json()["status"] == "in_consultation"

    visit = client.get(f"/api/doctor/visits/{sid}", headers=dr).json()
    assert visit["patient"]["name"] == "Asha Rao" and "conditions" in visit["ai"]
    assert visit["review"]["doctorName"] == "Dr. Anita Nair"

    draft = {
        "diagnosis": [{"name": "Viral fever"}],
        "medicines": [{"name": "Paracetamol", "form": "tablet", "strength": "500 mg", "dose": "1 tablet",
                       "frequency": "every 6 hours if fever", "duration": "3 days", "maxDaily": "4 tablets"}],
        "tests": ["Dengue NS1 if fever lasts beyond 3 days"],
        "advice": ["Drink plenty of fluids"],
        "followUp": "Come back in 3 days if not better",
        "privateNotes": "Likely viral; watch for dengue signs.",
    }  # fmt: skip
    assert client.put(f"/api/doctor/visits/{sid}/draft", json=draft, headers=dr).status_code == 200
    assert client.put(f"/api/doctor/visits/{sid}/draft", json=draft, headers=other).status_code == 409
    assert client.post(f"/api/doctor/visits/{sid}/finalize", json={**draft, "diagnosis": []}, headers=dr).status_code == 422
    bad = {**draft, "medicines": [{"name": "Paracetamol", "dose": "", "frequency": ""}]}
    assert client.post(f"/api/doctor/visits/{sid}/finalize", json=bad, headers=dr).status_code == 422
    done = client.post(f"/api/doctor/visits/{sid}/finalize", json=draft, headers=dr)
    assert done.status_code == 200 and done.json()["status"] == "final"

    final = client.get(f"/api/sessions/{sid}/final").json()
    assert final["status"] == "final" and final["doctor"] == "Dr. Anita Nair"
    report = final["final"]
    assert report["doctor"]["registrationNumber"] == "KMC-12345"
    view = report["view"]
    assert view["bilingual"] is True
    assert view["medicines"][0]["name"] == "Paracetamol"
    # The dose instruction is the doctor's, never reworded.
    assert view["medicines"][0]["howToTake"]["en"].startswith("1 tablet, every 6 hours if fever, for 3 days.")
    assert view["tests"] and view["followUp"]
    # The doctor's private notes never reach the patient.
    assert "watch for dengue" not in str(final)
    pdf = client.get(f"/api/sessions/{sid}/final.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # Finalised patients leave the queue and the record shows the visit.
    assert client.get("/api/doctor/queue?scope=all", headers=dr).json()["patients"] == []
    assert client.get("/api/doctor/consultations", headers=dr).json()[0]["diagnosis"] == ["Viral fever"]
    assert client.post(f"/api/doctor/visits/{sid}/pick", headers=other).status_code == 409

    # Next visit of the same patient: the doctor sees this one in the history,
    # and the report AI is told the doctor-confirmed diagnosis.
    from app.models import IntakeSession
    from app.patients.service import history_text
    from sqlalchemy.orm import Session as DbSession

    patient_id = client.post("/api/intake/patients", json={"phone": "9876543210"}, headers={"X-Kiosk-Key": key}).json()[0]["id"]
    sid2, _ = _visit(client, key, patientId=patient_id)
    visit2 = client.get(f"/api/doctor/visits/{sid2}", headers=dr).json()
    assert visit2["history"][0]["diagnosis"] == ["Viral fever"]
    with DbSession(client.app.state.engine) as db:
        assert "Viral fever" in history_text(db, db.get(IntakeSession, sid2))

    actions = [a["action"] for a in client.get("/api/hospital/audit", headers=admin).json()]
    assert {"patient.picked", "visit.viewed", "consultation.finalized", "doctor.created"} <= set(actions)
    # What the hospital's people did stays with the hospital: the company's
    # back office log never shows it.
    company = client.get("/api/admin/logs", headers=ADMIN).json()
    assert not {"consultation.finalized", "hospital.account_created"} & {e["event"] for e in company}
    assert "Dr. Anita Nair" not in str(company) and "dr.nair@city.in" not in str(company)


def test_the_doctor_chooses_the_language_of_the_signed_report(client):
    tenant_id, key = _hospital(client)
    dr = _doctor(client, _admin_of(client, tenant_id))
    sid, _ = _visit(client, key)
    client.post(f"/api/doctor/visits/{sid}/pick", headers=dr)
    draft = {
        "diagnosis": [{"name": "Viral fever"}],
        "medicines": [{"name": "Paracetamol", "strength": "650 mg", "dose": "1 tablet", "frequency": "every 6 hours"}],
        "language": "ml",
    }  # fmt: skip
    assert client.post(f"/api/doctor/visits/{sid}/finalize", json=draft, headers=dr).status_code == 200
    report = client.get(f"/api/sessions/{sid}/final").json()["final"]
    assert report["language"] == "ml" and report["view"]["language"] == "ml"
    assert report["view"]["summary"]["ml"] == "മലയാളം"
    # The visit itself keeps the language the patient used.
    assert client.get(f"/api/doctor/visits/{sid}", headers=dr).json()["language"] == "en"
    assert client.get(f"/api/sessions/{sid}/final.pdf").content.startswith(b"%PDF")


def test_old_hospital_lines_are_hidden_from_the_company_log(client):
    from app.tenancy import record

    record(client.app.state.engine, "consultation.finalized", "Dr. X signed ABC123", None)
    record(client.app.state.engine, "session.created", "manual intake confirmed", None)
    events = {e["event"] for e in client.get("/api/admin/logs", headers=ADMIN).json()}
    assert "session.created" in events and "consultation.finalized" not in events
    overview = client.get("/api/admin/overview", headers=ADMIN).json()
    assert "consultation.finalized" not in str(overview)


def test_the_queue_follows_the_doctors_department_and_a_release_frees_the_patient(client):
    tenant_id, key = _hospital(client)
    admin = _admin_of(client, tenant_id)
    cardio = client.post(
        "/api/hospital/departments", json={"name": "Cardiology", "reportDepartment": "Cardiology"}, headers=admin
    ).json()
    cardiologist = _doctor(client, admin, department=cardio["id"])
    general = _doctor(client, admin, email="gp@city.in")
    sid, _ = _visit(client, key)  # the fake report sends the patient to General OPD

    assert client.get("/api/doctor/queue", headers=cardiologist).json()["patients"] == []
    assert len(client.get("/api/doctor/queue?scope=all", headers=cardiologist).json()["patients"]) == 1
    assert len(client.get("/api/doctor/queue", headers=general).json()["patients"]) == 1

    client.post(f"/api/doctor/visits/{sid}/pick", headers=general)
    assert client.post(f"/api/doctor/visits/{sid}/release", headers=cardiologist).status_code == 409
    assert client.post(f"/api/doctor/visits/{sid}/release", headers=general).status_code == 204
    assert client.post(f"/api/doctor/visits/{sid}/pick", headers=cardiologist).status_code == 200

    # Another hospital's doctor cannot see or take the visit.
    other_id, _ = _hospital(client, "Other Hospital")
    stranger = _doctor(client, _admin_of(client, other_id, "admin@other.in"), email="dr@other.in")
    assert client.get(f"/api/doctor/visits/{sid}", headers=stranger).status_code == 404
    assert client.get("/api/doctor/queue?scope=all", headers=stranger).json()["patients"] == []


def test_doctor_only_medicines_and_ai_percentages():
    from app.report_writer import _rules, doctor_medicines
    from app.triage import with_probabilities

    ceftriaxone = {"name": "Ceftriaxone", "dose": "1 g", "frequency": "once daily", "route": "injection"}
    paracetamol = {"name": "Paracetamol", "dose": "15 mg/kg (270 mg)", "frequency": "every 6 hours", "route": "oral"}
    morphine = {"name": "Morphine", "dose": "5 mg", "frequency": "every 4 hours", "route": "oral"}

    adult = doctor_medicines([ceftriaxone, paracetamol, morphine], "urgent", 40, "male", {}, True)
    assert [m["name"] for m in adult] == ["Ceftriaxone", "Paracetamol"]  # never a controlled drug
    assert adult[0]["doctorOnly"] is True and adult[0]["form"] == "injection"
    shown, _ = _rules([ceftriaxone, paracetamol], "urgent", 40, "male", {}, True)
    assert [m["name"] for m in shown] == ["Paracetamol"]  # the patient never sees an injection

    # A child's dose only with a weight, and only for the doctor.
    assert doctor_medicines([paracetamol], "soon", 6, "female", {}, True) == []
    child = doctor_medicines([paracetamol], "soon", 6, "female", {}, True, weight_kg=18)
    assert child[0]["doctorOnly"] is True
    assert _rules([paracetamol], "soon", 6, "female", {}, True, weight_kg=18)[0] == []
    # Nothing without the safety review.
    assert doctor_medicines([paracetamol], "soon", 40, "male", {}, False) == []

    conditions = with_probabilities(
        [{"name": "A", "likelihood": "high", "probability": 80}, {"name": "B", "likelihood": "low", "probability": 50},
         {"name": "C", "likelihood": "low"}]  # fmt: skip
    )
    assert sum(c["probability"] for c in conditions) <= 100
    assert [c["probability"] for c in conditions] == sorted((c["probability"] for c in conditions), reverse=True)


def test_the_intake_can_be_filled_on_the_patients_phone(client):
    tenant_id, key = _hospital(client)
    kiosk = {"X-Kiosk-Key": key}
    opened = client.post("/api/handoffs", json={"language": "ml"}, headers=kiosk).json()
    code = opened["code"]
    assert len(code) >= 20

    phone = client.get(f"/api/handoffs/{code}/phone").json()
    assert phone["status"] == "open" and phone["language"] == "ml" and phone["hospital"] == "City Hospital"
    assert client.get(f"/api/handoffs/{code}", headers=kiosk).json() == {"status": "open", "intake": None}
    # Another kiosk cannot read it.
    assert client.get(f"/api/handoffs/{code}").status_code == 404

    intake = {k: v for k, v in SESSION.items() if k != "mode"} | {"allergies": "penicillin", "language": "ml"}
    assert client.post(f"/api/handoffs/{code}/phone", json=intake).status_code == 204
    assert client.post(f"/api/handoffs/{code}/phone", json=intake).status_code == 409
    waiting = client.get(f"/api/handoffs/{code}", headers=kiosk).json()
    assert waiting["status"] == "submitted" and waiting["intake"]["allergies"] == "penicillin"

    sid = client.post("/api/sessions", json={**waiting["intake"], "mode": "phone"}, headers=kiosk).json()["id"]
    assert client.post(f"/api/handoffs/{code}/done", json={"sessionId": sid}, headers=kiosk).status_code == 204
    assert client.get(f"/api/handoffs/{code}/phone").json()["sessionId"] == sid
    assert client.get("/api/handoffs/not-a-real-code/phone").status_code == 404


def test_the_phone_hand_off_works_offline_and_the_visit_joins_its_record_later(client):
    from app.models import IntakeSession
    from sqlalchemy.orm import Session as DbSession

    tenant_id, key = _hospital(client)
    kiosk = {"X-Kiosk-Key": key}
    state = client.app.state
    # A first visit online makes the patient's record.
    first = client.post("/api/sessions", json=SESSION, headers=kiosk).json()["id"]
    assert client.get("/api/config", headers=kiosk).status_code == 200  # the kiosk is remembered

    # The internet goes. The phone still reaches this server over the Wi-Fi.
    state.runtime.online = False
    code = client.post("/api/handoffs", json={"language": "en"}, headers=kiosk).json()["code"]
    assert code in state.offline.handoffs
    phone = client.get(f"/api/handoffs/{code}/phone").json()
    assert phone["status"] == "open" and phone["hospital"] == "City Hospital"
    assert client.post(f"/api/handoffs/{code}/phone/patients", json={"phone": "9876543210"}).json() == []
    intake = {k: v for k, v in SESSION.items() if k != "mode"} | {"allergies": "sulfa"}
    assert client.post(f"/api/handoffs/{code}/phone", json=intake).status_code == 204
    waiting = client.get(f"/api/handoffs/{code}", headers=kiosk).json()
    assert waiting["status"] == "submitted"
    sid = client.post("/api/sessions", json={**waiting["intake"], "mode": "phone"}, headers=kiosk).json()["id"]
    assert client.post(f"/api/handoffs/{code}/done", json={"sessionId": sid}, headers=kiosk).status_code == 204
    assert client.get(f"/api/handoffs/{code}/phone").json()["sessionId"] == sid
    with DbSession(state.engine) as db:
        assert db.get(IntakeSession, sid) is None  # held in memory

    # The internet is back: the visit is copied and joins the same person's record.
    state.runtime.online = True
    state.offline.flush(state.engine)
    with DbSession(state.engine) as db:
        again, before = db.get(IntakeSession, sid), db.get(IntakeSession, first)
        assert again.patient_id and again.patient_id == before.patient_id
        from app.patients.models import Patient

        assert "sulfa" in db.get(Patient, again.patient_id).allergies
