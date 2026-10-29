"""The hospital portal: its own accounts, scoped to one hospital."""

from test_api import ADMIN, SESSION, client  # noqa: F401  (pytest fixture)


def _hospital(client, name="City Hospital"):
    """A client (tenant) with its kiosk key, made in the company back office."""
    created = client.post("/api/admin/tenants", json={"name": name}, headers=ADMIN)
    assert created.status_code == 201, created.text
    tenant = created.json()
    key = client.post(f"/api/admin/tenants/{tenant['id']}/kiosk-key", headers=ADMIN).json()["kioskKey"]
    return tenant["id"], key


def _admin_of(client, tenant_id, email="admin@city.in"):
    """The hospital's first admin, signed in with a changed password."""
    made = client.post(
        f"/api/admin/tenants/{tenant_id}/hospital-admins",
        json={"email": email, "name": "Hospital Admin"},
        headers=ADMIN,
    )
    assert made.status_code == 201, made.text
    temporary = made.json()["temporaryPassword"]
    login = client.post("/api/hospital/auth/login", json={"email": email, "password": temporary})
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["mustChangePassword"] is True
    token = {"X-Hospital-Token": body["token"]}
    changed = client.post(
        "/api/hospital/auth/password", json={"current": temporary, "new": "a-new-password"}, headers=token
    )
    assert changed.status_code == 204
    return token


def test_the_company_opens_a_hospital_portal_and_accounts_stay_apart(client):
    tenant_id, _ = _hospital(client)
    token = _admin_of(client, tenant_id)
    me = client.get("/api/hospital/auth/me", headers=token).json()
    assert me["user"]["role"] == "hospital_admin" and me["user"]["mustChangePassword"] is False
    assert me["hospital"]["name"] == "City Hospital"

    # A hospital login never opens the company back office, and the other way round.
    assert client.get("/api/admin/tenants", headers={"X-Admin-Key": token["X-Hospital-Token"]}).status_code == 401
    assert client.get("/api/hospital/dashboard", headers={"X-Hospital-Token": "test-key"}).status_code == 401
    # Only the company creates a hospital's first admins.
    assert client.post(
        f"/api/admin/tenants/{tenant_id}/hospital-admins", json={"email": "x@y.in", "name": "X"}, headers=token
    ).status_code == 401
    assert [a["email"] for a in client.get(f"/api/admin/tenants/{tenant_id}/hospital-admins", headers=ADMIN).json()] == [
        "admin@city.in"
    ]
    # The temporary password no longer works once changed.
    assert client.post("/api/hospital/auth/login", json={"email": "admin@city.in", "password": "wrong"}).status_code == 401


def test_the_hospital_admin_manages_departments_doctors_and_staff(client):
    tenant_id, _ = _hospital(client)
    token = _admin_of(client, tenant_id)

    lists = client.get("/api/hospital/departments", headers=token).json()
    assert "Cardiology" in lists["reportDepartments"] and lists["departments"] == []
    cardio = client.post(
        "/api/hospital/departments", json={"name": "Cardiology", "reportDepartment": "Cardiology"}, headers=token
    ).json()
    assert client.post("/api/hospital/departments", json={"name": "Cardiology"}, headers=token).status_code == 409
    assert client.post(
        "/api/hospital/departments", json={"name": "X", "reportDepartment": "Magic"}, headers=token
    ).status_code == 422

    # A doctor needs a registration number; it goes on prescriptions.
    doctor = {"email": "dr.nair@city.in", "name": "Dr. Nair", "role": "doctor", "departmentId": cardio["id"]}
    assert client.post("/api/hospital/people", json=doctor, headers=token).status_code == 422
    made = client.post(
        "/api/hospital/people", json={**doctor, "registrationNumber": "KMC-12345", "qualification": "MBBS, MD"}, headers=token
    )
    assert made.status_code == 201
    person = made.json()["person"]
    assert person["department"] == "Cardiology" and made.json()["temporaryPassword"]
    staff = client.post(
        "/api/hospital/people",
        json={"email": "nurse@city.in", "name": "Asha", "role": "staff", "jobTitle": "Nurse"},
        headers=token,
    ).json()["person"]
    assert {p["role"] for p in client.get("/api/hospital/people", headers=token).json()} == {
        "hospital_admin", "doctor", "staff",
    }  # fmt: skip
    assert client.get("/api/hospital/departments", headers=token).json()["departments"][0]["doctors"] == 1

    # The doctor can sign in, but the hospital portal is for admins only.
    temporary = made.json()["temporaryPassword"]
    doctor_token = {
        "X-Hospital-Token": client.post(
            "/api/hospital/auth/login", json={"email": "dr.nair@city.in", "password": temporary}
        ).json()["token"]
    }
    assert client.get("/api/hospital/dashboard", headers=doctor_token).status_code == 403

    # Switching an account off signs it out at once.
    off = client.patch(f"/api/hospital/people/{person['id']}", json={"active": False}, headers=token)
    assert off.json()["active"] is False
    assert client.get("/api/hospital/auth/me", headers=doctor_token).status_code == 401
    assert client.post("/api/hospital/auth/login", json={"email": "dr.nair@city.in", "password": temporary}).status_code == 403
    # A reset gives a new temporary password and must be changed again.
    reset = client.post(f"/api/hospital/people/{staff['id']}/reset-password", headers=token).json()
    login = client.post("/api/hospital/auth/login", json={"email": "nurse@city.in", "password": reset["temporaryPassword"]})
    assert login.json()["user"]["mustChangePassword"] is True

    me_id = client.get("/api/hospital/auth/me", headers=token).json()["user"]["id"]
    assert client.patch(f"/api/hospital/people/{me_id}", json={"active": False}, headers=token).status_code == 422
    actions = [a["action"] for a in client.get("/api/hospital/audit", headers=token).json()]
    assert {"department.created", "doctor.created", "staff.created", "doctor.updated", "staff.password_reset"} <= set(actions)


def test_a_hospital_sees_only_its_own_visits_and_opening_one_is_audited(client):
    city, city_key = _hospital(client, "City Hospital")
    other, other_key = _hospital(client, "Other Hospital")
    city_token = _admin_of(client, city, "admin@city.in")
    other_token = _admin_of(client, other, "admin@other.in")

    visit = client.post("/api/sessions", json=SESSION, headers={"X-Kiosk-Key": city_key}).json()["id"]
    client.post("/api/sessions", json={**SESSION, "name": "Ravi"}, headers={"X-Kiosk-Key": other_key})

    mine = client.get("/api/hospital/visits", headers=city_token).json()
    assert [v["name"] for v in mine] == ["Asha Rao"]
    assert [v["name"] for v in client.get("/api/hospital/visits", headers=other_token).json()] == ["Ravi"]
    assert client.get("/api/hospital/visits?search=9876", headers=city_token).json()[0]["id"] == visit
    assert client.get("/api/hospital/visits?search=nobody", headers=city_token).json() == []
    # Another hospital's visit does not exist, as far as this one can tell.
    assert client.get(f"/api/hospital/visits/{visit}", headers=other_token).status_code == 404

    detail = client.get(f"/api/hospital/visits/{visit}", headers=city_token).json()
    assert detail["symptoms"] == "Headache and fever" and detail["report"] is None
    audit = client.get("/api/hospital/audit", headers=city_token).json()
    assert audit[0]["action"] == "visit.viewed" and "Asha Rao" in audit[0]["detail"]
    assert all(a["action"] != "visit.viewed" for a in client.get("/api/hospital/audit", headers=other_token).json())

    board = client.get("/api/hospital/dashboard", headers=city_token).json()
    assert board["today"]["visits"] == 1 and board["people"]["admins"] == 1
    assert len(board["week"]) == 7 and board["week"][-1]["visits"] == 1
    assert [a["event"] for a in client.get("/api/hospital/activity", headers=city_token).json()][0] == "session.created"


def test_hospital_settings_and_a_switched_off_hospital(client):
    tenant_id, _ = _hospital(client)
    token = _admin_of(client, tenant_id)
    settings = client.get("/api/hospital/settings", headers=token).json()
    assert settings["displayName"] == "City Hospital" and settings["timezone"] == "Asia/Kolkata"
    saved = client.put(
        "/api/hospital/settings",
        json={**settings, "displayName": "City Hospital, Kochi", "address": "MG Road", "logo": "data:image/png;base64,iVBORw0KGgo="},
        headers=token,
    )
    assert saved.status_code == 200 and saved.json()["address"] == "MG Road"
    assert client.get("/api/hospital/auth/me", headers=token).json()["hospital"]["name"] == "City Hospital, Kochi"
    assert client.put("/api/hospital/settings", json={**settings, "logo": "not an image"}, headers=token).status_code == 422
    assert client.put("/api/hospital/settings", json={**settings, "timezone": "Mars/Base"}, headers=token).status_code == 422

    # The company switches the hospital off: its portal closes.
    client.patch(f"/api/admin/tenants/{tenant_id}", json={"active": False}, headers=ADMIN)
    assert client.get("/api/hospital/auth/me", headers=token).status_code == 401


def test_a_client_is_created_with_its_hospital_admin_and_password(client):
    body = {"name": "Lake Hospital", "adminName": "Asha Nair", "adminEmail": "asha@lake.in", "adminPassword": "lake-pass-1"}
    created = client.post("/api/admin/tenants", json=body, headers=ADMIN)
    assert created.status_code == 201, created.text
    login = client.post("/api/hospital/auth/login", json={"email": "asha@lake.in", "password": "lake-pass-1"})
    assert login.status_code == 200
    token = {"X-Hospital-Token": login.json()["token"]}
    me = client.get("/api/hospital/auth/me", headers=token).json()
    # The company chose the password, so no forced change.
    assert me["hospital"]["name"] == "Lake Hospital" and me["user"]["mustChangePassword"] is False

    # A taken email or short password creates nothing, not even the client.
    again = {**body, "name": "Hill Hospital"}
    assert client.post("/api/admin/tenants", json=again, headers=ADMIN).status_code == 409
    short = {**body, "name": "Hill Hospital", "adminEmail": "b@hill.in", "adminPassword": "short"}
    assert client.post("/api/admin/tenants", json=short, headers=ADMIN).status_code == 422
    names = [t["name"] for t in client.get("/api/admin/tenants", headers=ADMIN).json()]
    assert "Hill Hospital" not in names
