from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="MEDORA_", extra="ignore"
    )

    # The database this server works from. For a kiosk site this is a local
    # database, so intake keeps working without internet.
    database_url: str = "postgresql+psycopg://medora:medora@localhost:5432/medora"
    # Optional central database. When set and reachable, clients, sessions,
    # reports and logs are mirrored to it in the background.
    cloud_database_url: str = ""
    # Separate database for the medical knowledge base and guideline RAG
    # (`app/kb`). Empty = not configured.
    knowledge_database_url: str = ""
    # Guideline sources still waiting for permission (ICMR STW, NFI, WHO list:
    # production_allowed = false) may be used in reports. For testing only.
    knowledge_testing_sources: bool = False
    # Community datasets (Hugging Face, tier 5) may be used in reports.
    knowledge_community_sources: bool = False
    # Watches internet reachability and runs the mirror. Off in tests.
    background_tasks: bool = True
    # Behave as if there were no internet (for rehearsing offline mode
    # without switching off the network). Copying back to Supabase waits too.
    force_offline: bool = False
    data_dir: Path = Path("data")
    cors_origins: list[str] = ["*"]
    max_upload_mb: int = 200

    # --- Gemini (online voice and reports). Empty = not configured. --------
    gemini_api_key: str = ""
    # Must be a model that supports the Live API with audio output.
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    # Prebuilt voice for Dr. Medora (for example Kore, Aoede, Puck, Charon).
    gemini_voice: str = "Kore"
    # Vitals are taken at every visit (the user's rule of 2026-10-29: "vitals
    # are a must"). False brings back the per-complaint decision
    # (vitals_need.py), which waived them for e.g. a sprain or a rash.
    vitals_always: bool = True
    gemini_text_model: str = "gemini-2.5-flash"
    # Model for the final report only: the writer (summary, medicines, doses),
    # the condition check and the pharmacist review. Empty = gemini_text_model.
    # A stronger model here (gemini-3.1-pro-preview) is more accurate but
    # slower and has tighter free-tier limits; when it fails or runs out, the
    # report falls back to gemini_text_model on its own.
    gemini_report_model: str = ""

    # --- Ollama (offline reports, symptom embeddings) ----------------------
    ollama_url: str = "http://localhost:11434"
    # Small general model: only the plain summary when Gemini fails online.
    ollama_model: str = "qwen2.5:3b"
    # Local medical model for the whole report when there is no internet
    # (panel, writer, review, precautions). Empty = offline reports carry
    # only the plain summary.
    offline_model: str = "medgemma:4b"
    # Specialists asked offline. Each is a model call of 2-3 minutes on a
    # laptop CPU, one after another, so by default none: the chair (a general
    # physician) concludes alone, then the same writer, check and review.
    offline_panel_size: int = 0
    # CPU threads for the local model (0 = Ollama's default). 10 on the
    # development laptop (i7-1355U) doubled its reading speed.
    ollama_threads: int = 10
    # Embeds symptom names for search by meaning. Empty = match by name only.
    ollama_embed_model: str = "all-minilm"

    # Whether anyone who can reach the back office may create a working
    # account. Set to false on any server reachable from outside the company.
    registration_open: bool = True

    # --- Specialist panel (CrewAI; Gemini online, offline_model offline) ---
    # How many specialists review each case, out of the 18 on the roster, at most. Each
    # one is a model call, so this sets the report's time and cost.
    panel_size: int = 5
    # Model for the specialists; empty = the same as the chair
    # (gemini_text_model). A faster model here shortens the report's wait.
    gemini_panel_model: str = "gemini-3.1-flash-lite"

    # --- Email delivery (SMTP). Empty host = not configured. ---------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- SMS delivery (Twilio). Empty SID = not configured. ----------------
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    # Prepended to patient numbers typed without a "+", e.g. "+91".
    sms_default_country_code: str = ""

    # Address patients can reach this server on; used for the report link in
    # SMS. Empty = the SMS carries the summary without a link.
    public_base_url: str = ""
