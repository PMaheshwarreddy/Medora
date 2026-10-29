# Medora: Comprehensive System Master Blueprint & Project Documentation

**Project Name**: Medora AI Healthcare Kiosk System  
**Document Type**: Complete Master Documentation & Roadmap  
**Status**: Architecture Finalized, Codebase Cleared for Clean Rebuild, Ingestion Guidelines Assigned  
**Primary Platform Target**: Web Application First (to be deployed and run on Touchscreen Kiosks)

---

## 1. Executive Summary & Vision

### **1.1 What is Medora?**
Medora is an **AI-driven, multimodal healthcare kiosk and clinical intake system** engineered to automate and optimize the preliminary medical triage process in hospitals, rural clinics, and outpatient centers.

Instead of waiting in long queues to fill out paper intake forms or repeating symptoms to triage nurses, patients interact with **Dr. Medora**—an empathetic, conversational AI agent that:
1. Conducts natural, multi-language conversational assessments.
2. Follows clinical reasoning to ask pertinent follow-up questions.
3. Guides patients to attach vital sensor hardware (Smart Bands / Smart Cuffs) for real-time telemetry (ECG, SpO2, Heart Rate, Temperature, Blood Pressure).
4. Summarizes collected information visually on an interactive board, allowing the patient to verify and correct any inaccuracies via voice or touch before clinical review.
5. Issues a printed or digital clinical summary slip with differential diagnosis indicators, precautions, and queue tokens.

---

## 2. Core End-to-End Patient Flow & Clinical Logic

The user flow is strictly defined across five sequential, interactive phases:

```
+-----------------------------------------------------------------------------------+
| 1. WELCOME & LANGUAGE SELECTION                                                  |
|    - Clean clinical interface (Option B: Ultra-Clean Clinical Theme).             |
|    - Patient taps "Start Assessment" and selects their native language.           |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. CONVERSATIONAL VOICE INTAKE (Dr. Medora AI Avatar)                             |
|    - Dr. Medora greets patient warmly and inquires about primary complaint.       |
|    - Active Follow-up questioning:                                               |
|      * Example: Patient says "I have a fever."                                    |
|      * Agent responds: "I'm sorry to hear that. Since when have you been having    |
|        this fever? Do you also experience chills, shivering, or body pain?"       |
|    - Real-Time Interruption Handling (Barge-In):                                  |
|      * If patient speaks while Dr. Medora is talking, the agent immediately stops |
|        output, listens, and redirects conversation dynamically.                  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. HARDWARE VITALS & TELEMETRY COLLECTION                                         |
|    - Agent prompts patient: "Please slip on the Smart Band on your wrist so I     |
|      can collect your vitals."                                                    |
|    - Smart Band streams telemetry over BLE/Serial to the system:                  |
|      * Real-time ECG waveform graph                                               |
|      * SpO2 (Oxygen Saturation)                                                   |
|      * Heart Rate (BPM) & Body Temperature (°C / °F)                              |
|      * Blood Pressure (Systolic / Diastolic)                                      |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. INTERACTIVE VISUAL SUMMARY BOARD (Rectification Step)                         |
|    - Displays patient demographics, reported symptoms, duration, and vitals.      |
|    - Patient examines the screen.                                                 |
|    - Rectification Loop:                                                         |
|      * Patient can state corrections (e.g., "Actually, my fever started 3 days    |
|        ago, not yesterday") or touch the screen to edit.                          |
|      * AI acknowledges and updates the record live on screen.                     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. TRIAGE REPORT & TICKET DISPENSING                                              |
|    - System runs Medical RAG against ICD-10 & clinical guidelines.                |
|    - Generates precautions, suggested department, and urgency flag.              |
|    - 80mm Thermal Printer dispenses receipt slip with QR code token for doctor.   |
+-----------------------------------------------------------------------------------+
```

---

## 3. UI/UX Design Direction: "Option B — Modern Ultra-Clean Clinical"

After reviewing initial iterations and removing legacy code, the project locked in **Option B**:
* **Aesthetic Philosophy**: Crisp, modern clinical aesthetic with maximum legibility and visual calm.
* **Palette Tokens**:
  * Backgrounds: Pure Slate White (`#F8FAFC`) with subtle neutral borders (`#E2E8F0`).
  * Primary Accents: Deep Clinical Royal Blue (`#0F52BA` / `#1E40AF`) representing clinical authority.
  * Secondary Accents: Soothing Emerald Teal (`#0D9488`) for health indicators.
  * Card Surfaces: High-contrast white surfaces (`#FFFFFF`) with soft drop shadows (`0 4px 12px rgba(0,0,0,0.05)`).
* **Target Interface**: First release is built as a **Web Application**, fully responsive and optimized for large 21.5" to 24" touch displays in kiosk environments.

---

## 4. Technical Architecture & Technology Stack

### **4.1 Frontend**
* **Framework**: Flutter Web / Flutter Desktop (clean, multi-platform, fast rendering).
* **State Management**: Provider / Riverpod.
* **Audio Engine**: Direct microphone chunk capture (`record` / Web Audio API) streaming raw PCM audio over WebSockets.

### **4.2 Backend & Orchestration**
* **Framework**: FastAPI (Python 3.11+).
* **Asynchronous Communication**: WebSockets (`/ws/voice`, `/ws/telemetry`).
* **Multi-Agent Architecture**: CrewAI / LangChain dividing clinical roles:
  * *Intake Agent*: Manages conversational dialogue and symptom extraction.
  * *Diagnostic & Reasoning Agent*: Matches symptoms against medical embeddings.
  * *Safety & Precautions Agent*: Validates contraindications, drug interactions, and red-flag symptoms.

### **4.3 Database: PostgreSQL 16 + `pgvector`**
* **Engine**: PostgreSQL 16 with native `pgvector` extension.
* **Why PostgreSQL + `pgvector`?**
  * **100% Free Open-Source License**.
  * Eliminates the need for expensive third-party vector databases (e.g. Pinecone/Milvus at $100+/mo).
  * Stores structured relational records (Patients, Sessions) and vector embeddings (SNOMED, ICD-10, Precautions) in a single database with high ACID reliability.

---

## 5. Database Sizing & Cost Estimation (Approved Final Specification)

### **5.1 Dataset Breakdown (Based on ~1 GB Raw Dataset Expansion)**

| Data Layer | Target Size | Explanation |
| :--- | :--- | :--- |
| **Primary Medical Knowledge Base** | **~1 GB** | 11,000+ Diseases, Precautions, Side Effects, Symptoms & Drug Index |
| **Vector Search Embeddings (`pgvector`)** | **~2.5 GB** | 1536-dimensional vector embeddings for AI RAG semantic search |
| **Patient Demographics & Transcripts** | **~2.0 GB** | Patient profiles, dialogue histories, session transcripts |
| **Telemetry Sensor Readings** | **~4.5 GB** | High-frequency continuous waveform points (ECG, SpO2, Pulse) |
| **Database Overheads & Indexes** | **~5.0 GB** | HNSW vector indexes, B-tree indexes, write-ahead logs |
| **TOTAL RECOMMENDED STORAGE** | **15 - 20 GB** | Total allocated database storage capacity |

### **5.2 Cost Matrix for Management**

| Component | Demo / PoC Phase | Production Phase | Notes |
| :--- | :--- | :--- | :--- |
| **Database (PostgreSQL + pgvector)** | **$0.00 / month** | **$10.00 – $15.00 / month** | Free locally; low-cost cloud for production |
| **Online AI Voice (Gemini 1.5 Flash)** | **$0.00 / month** | **$2.00 – $5.00 / month** | Free tier for testing; ultra-low token cost |
| **Offline AI Voice (Ollama + Whisper)**| **$0.00 / month** | **$0.00 / month** | 100% Free open-source local processing |
| **Kiosk Hardware Assembly** | **$0.00** | **~$500 – $700** | One-time CapEx per kiosk unit |
| **TOTAL ESTIMATED COST** | **$0.00 Total** | **~$500 - $700 (One-Time) + $12 - $20/month** | Minimum cost, maximum quality |

---

## 6. Offline Mode Architecture & Resilience

To guarantee the kiosk continues operating if hospital Wi-Fi or broadband drops:

```
+-------------------------------------------------------------------------+
| MEDORA KIOSK UNIT (Mini-PC)                                             |
+-------------------------------------------------------------------------+
        |                                                 |
  [ONLINE MODE]                                     [OFFLINE MODE]
        |                                                 |
  Google Gemini Live WebSocket API                  Local Faster-Whisper (STT)
  Cloud PostgreSQL + pgvector                       Local Piper TTS (Voice)
  Cloud Medical RAG                                 Local SQLite + sqlite-vec
                                                    Local Ollama (Phi-3 / Llama-3 8B)
```

1. **Local Speech Recognition (STT)**: Faster-Whisper runs locally on the kiosk CPU.
2. **Local Voice Synthesis (TTS)**: Piper Neural Voice TTS generates immediate local audio.
3. **Local Reasoning Model**: Ollama running lightweight models (Phi-3 Mini) for basic triage extraction.
4. **Local Data Buffering**: Sensor telemetry and patient records save into local SQLite and sync with central PostgreSQL once connectivity is restored.

---

## 7. Data Engineering & Ingestion Pipeline (Teammate Task Scope)

The raw collected data consists of files in diverse, non-standard formats (CSV, JSON, text) with varying columns. A teammate has been tasked with building an **AI-Assisted ETL Pipeline**:

1. **AI Column Auto-Mapping**: Uses an LLM prompt to automatically map disparate column names (e.g. `illness_title` vs `condition_name`) into standard schema keys.
2. **Data Cleansing & Balancing**:
   * Normalizes symptom strings into linked tables.
   * Synthesizes and validates balanced precautions for diseases with missing data.
3. **Target Schema**:
   * `diseases` (stores disease name, ICD-10, description, `vector(1536)` embedding).
   * `symptoms` & `disease_symptoms` (many-to-many relationship for granular symptom scoring).
   * `precautions` (linked to diseases with precaution types).
   * `medicines` (OpenFDA & SIDER drug index with side effects and contraindications).
4. **Vector Embedding Ingestion**: Computes embeddings via `text-embedding-004` and indexes them with HNSW for sub-second retrieval.

---

## 8. Current Workspace Status & Next Immediate Action

* **Workspace Cleaned**: All prior prototype code in `/home/turing/PROJECTS/Medora` was safely removed upon user confirmation to start fresh.
* **Architecture Locked**: Option B (Ultra-Clean Clinical), Web First target, PostgreSQL + `pgvector` database, Gemini Live / Ollama hybrid AI.
* **Next Step**: Begin implementing the fresh, clean Medora Web codebase step-by-step starting from the foundational theme and initial Kiosk Welcome Screen.
