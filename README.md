# InsightLog (v2)

![InsightLog Architecture Diagram](https://via.placeholder.com/1200x600.png?text=InsightLog+Architecture+Diagram)

**InsightLog** is a fast, asynchronous, AI-powered AIOps microservice built for modern SRE teams. It ingests raw application and system logs, intelligently categorizes them using Google Gemini, extracts root causes and remediation steps, and automatically alerts your team on Slack for critical issues.

---

## 🏗️ Architecture Overview

Following Domain-Driven Design (DDD) principles, the v2 architecture strictly separates internal business logic from external API integrations.

- **API Layer (`app/api/`):** Thin FastApi routers handling HTTP validation and rate limiting.
- **Service Layer (`app/services/`):** Core business logic handling the lifecycle of incidents (RECEIVED → PROCESSING → COMPLETED/FAILED).
- **Integrations Layer (`app/integrations/`):** Safely isolated wrappers for blocking external I/O (Gemini API, Slack Webhooks).
- **Data Layer (`app/database/`, `app/models/`):** SQLAlchemy ORM models mapped to an asynchronous-ready interface (currently backed by SQLite).

---

## 🛠️ Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **Database:** SQLite with SQLAlchemy ORM
- **AI/LLM:** Google Gemini 2.5 Flash SDK (with structured JSON outputs)
- **Validation:** Pydantic v2
- **Rate Limiting:** `slowapi`
- **Testing:** `pytest` (100% Core coverage)

---

## 🚀 Setup & Run Instructions

### 1. Prerequisites
- Python 3.10+
- Google Gemini API Key

### 2. Installation
Clone the repository and set up the virtual environment:
```bash
git clone https://github.com/manavsoni05/InsightLog.git
cd InsightLog
python -m venv venv

# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3. Dependencies & Config
Install requirements and prepare the environment file:
```bash
pip install -r requirements.txt
cp .env.example .env
```
*(Make sure to open `.env` and add your real `GEMINI_API_KEY`, `SLACK_WEBHOOK_URL`, and secure `API_KEY`!)*

### 4. Run the Server
```bash
uvicorn app.main:app --reload
```
The API is now running at `http://127.0.0.1:8000`. 
Interactive Swagger docs are available at `http://127.0.0.1:8000/docs`.

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| **POST** | `/api/v1/logs` | Ingests a new log and returns an immediate tracking `receipt_id`. |
| **GET**  | `/api/v1/logs/{receipt_id}` | Poll the triage result using the returned tracking ID. |

*(All endpoints require the `X-API-Key` header for authentication).*

---

## 🧪 Real-world Sample Test Cases (Curl)

You can test the system locally using these `curl` commands:

### 1. LOW Severity (Security)
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs" \
  -H "X-API-Key: insightlog-dev-secret-changeme" \
  -H "Content-Type: application/json" \
  -d '{"message": "INFO: Admin user manav@example.com successfully changed their password from IP 192.168.1.50."}'
```

### 2. MEDIUM Severity (Application)
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs" \
  -H "X-API-Key: insightlog-dev-secret-changeme" \
  -H "Content-Type: application/json" \
  -d '{"message": "WARN: Memory usage spiked to 85% in the image processing microservice during batch upload."}'
```

### 3. HIGH / CRITICAL Severity (Database Outage)
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs" \
  -H "X-API-Key: insightlog-dev-secret-changeme" \
  -H "Content-Type: application/json" \
  -d '{"message": "FATAL: Postgres replica sync failed. Write-ahead log corruption detected. Halting all database transactions immediately to prevent data loss."}'
```

### 4. Invalid Payload (Semantic Validation Failure)
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs" \
  -H "X-API-Key: insightlog-dev-secret-changeme" \
  -H "Content-Type: application/json" \
  -d '{"message": "123 !@# %%%"}'
```
*(Returns 422 Unprocessable Entity - log rejected as junk data)*

### 5. Authentication Failure
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs" \
  -H "X-API-Key: WRONG_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test log message"}'
```
*(Returns 401 Unauthorized)*

---

## ✨ Improvements over V1

| Feature | V1 | V2 |
|---------|----|----|
| **Security** | None | HMAC timing-safe API Key Authentication |
| **Stability** | Dropped connections on failure | 3-attempt Exponential Backoff on Gemini API |
| **Rate Limiting** | None | `slowapi` 30 req/min limits |
| **Folder Structure**| Mixed external & internal logic | Clean `integrations/` vs `services/` separation |
| **Testing** | Non-existent | 80+ Pytest Suite (Coverage for LLM Mocks, Schemas, Auth) |
| **Database** | Missing critical indexes | Created indexes for `status` and `created_at` polling |

---

## 🚧 Current Limitations

- **Asynchronous Execution:** Currently, the system leverages FastAPI's built-in `BackgroundTasks` via thread pools. It does **not** yet use Celery or Redis for distributed worker queues. While perfectly stable for moderate traffic, heavy parallel I/O blocking from Gemini can saturate the application backend.
- **Database Backend:** SQLite file locking on Windows can cause slight concurrency delays at very high request volumes.

---

## 🔮 Future Enhancements

- **Celery + Redis Worker Queue:** Decouple the HTTP API layer from the background LLM processing by implementing a true distributed message broker.
- **PostgreSQL Migration:** Move to a robust relational database with `PgBouncer` connection pooling to handle 10,000+ alerts per minute safely.
- **Observability Metrics:** Add Prometheus metric scraping and a Grafana dashboard to track Gemini token usage, average latency, and API HTTP error rates.
- **Advanced LLM Fallbacks:** Implement routing to Claude 3.5 or OpenAI GPT-4o if the Gemini API goes down or exhausts daily quota.
