# Running Medora on your machine

Medora has two parts. Run both, each in its own terminal:

- **backend/**: the API (Python). It listens on `http://localhost:8100`.
- **frontend/**: the web app (Flutter). It opens in Chrome.

The database is the team's **Supabase** database, on the internet. You don't install a database: the backend connects to it by itself using the settings in `backend/.env`.

## 1. Install these first

| What | Version | Check with |
| :--- | :--- | :--- |
| Python | **3.12** (3.13 may fail on some packages) | `python --version` |
| Flutter | 3.44 or newer (Dart 3.12 or newer) | `flutter --version` |
| Google Chrome | any recent one | |

Optional: **Ollama** (https://ollama.com). It is only needed for offline reports and for symptom matching by meaning. Without it, everything online still works. To use it, run:

```bash
ollama pull all-minilm
ollama pull medgemma:4b
ollama pull qwen2.5:3b
```

## 2. Get the settings file

Get `backend/.env` from Maheswar privately. It is not in the zip because it holds the database password and the Gemini key. Put it in the `backend/` folder, next to `requirements.txt`.

## 3. Start the backend (terminal 1)

```bash
cd backend
python -m venv .venv
```

Activate the environment:

- Windows: `.venv\Scripts\activate`
- macOS / Linux: `source .venv/bin/activate`

Then install and start it:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

The install takes a few minutes. When the server is ready, it prints `Application startup complete`. Check that it works by opening http://localhost:8100/docs.

Next time, you only need to activate the environment and run the `uvicorn` line.

## 4. Start the frontend (terminal 2)

```bash
cd frontend
flutter pub get
flutter run -d chrome
```

Chrome opens on the **company back office**. Create an account on the sign-in screen, or use the shared one.

If you are on Linux, run this inside a VS Code terminal, and Chrome does not open, use `./run_dev.sh` instead of `flutter run -d chrome`.

## 5. Where everything is

| Address (after the port Chrome shows) | What |
| :--- | :--- |
| `/#/` | Company back office: clients (hospitals), keys, sessions, logs, knowledge |
| `/#/kiosk` | The patient kiosk |
| `/#/hospital` | Hospital portal (the email and password set in "Add client (hospital)") |
| `/#/doctor` | Doctor portal (doctors are added in the hospital portal) |
| `/#/r/<visit number>` | The patient's own report page |

A full test run goes like this:

1. In the back office, open Clients & keys and click **Add client (hospital)**, with an admin email and password.
2. Sign in to the hospital portal, then add a department and a doctor.
3. Do a visit on the kiosk.
4. In the doctor portal, take the patient and sign.
5. Open the patient page.

## Good to know

- **Same database as the rest of the team.** Every client, visit and account you create is visible to everyone. Don't delete other people's data.
- **The Gemini key is a free-tier key shared by the team.** If reports become slow or fail with "429 / quota", someone else is using it at the same time. Wait a minute and try again.
- **Smart band:** the band **simulator** is on (sliders on the vitals screen), so you don't need a real band.
- **Voice** needs a microphone and internet. Allow microphone access when Chrome asks.
- **"Use my phone" QR codes** only open on the same computer, because they point to `localhost`.

## Tests (optional)

```bash
cd backend
pip install pytest
pytest -q

cd frontend
flutter test
```

## If something goes wrong

| Problem | Fix |
| :--- | :--- |
| `backend/.env is missing`, or database errors at start | Check that `.env` is in `backend/`. The backend needs internet at start-up and retries if Supabase is unreachable. |
| `Address already in use` on 8100 | Another backend is still running. Close it, or stop the program that is using port 8100. |
| The app says it cannot reach the server | The backend is not running, or not on port 8100. |
| `pip install` fails on a package | Make sure the environment uses Python **3.12**. Delete `.venv` and create it again with Python 3.12. |
