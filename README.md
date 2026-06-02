# InsightLog

A fast, async, AI-powered incident triage microservice built with FastAPI and Google Gemini 2.5 Flash. It ingests application logs, intelligently categorizes them, extracts root causes and remediation steps, and automatically alerts your team on Slack for CRITICAL issues.

## 🌟 Features

- **Asynchronous Ingestion:** Fast API endpoints utilizing FastAPI `BackgroundTasks` to unblock the client immediately.
- **AI-Powered Triage:** Uses Gemini 2.5 Flash to accurately classify severity, category, root cause, and remediation steps.
- **Resilient Architecture:** Implements exponential backoff retries for LLM API calls to gracefully handle network volatility and rate limiting.
- **Automated Slack Alerts:** Safely isolated alerting service that pings a Slack webhook specifically for `CRITICAL` incidents.
- **Persistent Storage:** SQLite + SQLAlchemy backend mapping the full incident lifecycle (`RECEIVED` → `PROCESSING` → `COMPLETED` / `FAILED`).

## 🏗️ Architecture

Following Domain-Driven Design principles, the codebase is separated into clean layers:
- **API (`app/api/`):** Thin routes focusing only on HTTP requests/responses.
- **Services (`app/services/`):** Core business logic (`log_service`, `triage_service`, `llm_service`, `alert_service`) fully isolated from each other.
- **Models & Schemas:** SQLAlchemy ORM models (`app/models/`) and strict Pydantic v2 validation schemas (`app/schemas/`).

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Google Gemini API Key

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/manavsoni05/InsightLog.git
   cd InsightLog
   ```

2. **Set up virtual environment:**
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # On Windows
   # source venv/bin/activate    # On Linux/Mac
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Copy `.env.example` to `.env` and configure your API keys.
   ```bash
   cp .env.example .env
   ```

5. **Run the server:**
   ```bash
   uvicorn app.main:app --reload
   ```
   The API will be available at `http://127.0.0.1:8000`. You can explore the interactive Swagger documentation at `http://127.0.0.1:8000/docs`.

## 📌 Usage

**Ingest a Log (POST `/api/v1/logs`)**
```json
{
  "message": "Database connection timeout after 30 seconds on primary replica"
}
```

**Check Status (GET `/api/v1/logs/{receipt_id}`)**
Retrieves the full triage result, updating dynamically as the background task completes.
