# AI Incident Triage Service - Development Instructions

## Project Goal

Build a Python FastAPI microservice that receives application/server logs, classifies them using an LLM, stores the results in a database, and sends alerts for critical incidents.

This is an MVP implementation focused on clean architecture, maintainability, testing, and production-minded design decisions.

---

# Core Functional Requirements

## 1. Log Ingestion API

Create:

POST /api/v1/logs

Request:

{
"message": "Database connection timeout after 30 seconds"
}

Response:

{
"receipt_id": "uuid"
}

The endpoint must:

* Validate requests using Pydantic
* Persist logs immediately
* Return a receipt ID instantly
* Trigger asynchronous processing

---

## 2. LLM Triaging

Analyze log messages and extract:

Severity:

* LOW
* MEDIUM
* CRITICAL

Category:

* DATABASE
* NETWORK
* APPLICATION
* SECURITY

Root Cause:

* Short explanation

Remediation:

* Suggested action steps

All outputs must be validated through Pydantic models.

---

## 3. Asynchronous Processing

The API response must not wait for:

* LLM execution
* Alert delivery

Use FastAPI BackgroundTasks.

Workflow:

Receive Log
→ Save Log
→ Return Receipt
→ Background Processing
→ LLM Analysis
→ Update Database
→ Alert If Critical

---

## 4. Incident Alerting

If severity == CRITICAL

Send Slack webhook notification.

Slack was chosen because the assignment allows Slack or Teams and Slack provides simpler setup.

---

## 5. Persistence

Use:

* SQLite
* SQLAlchemy ORM

Store:

* Original log
* Severity
* Category
* Root cause
* Remediation
* Processing status
* Created timestamp

---

# Technical Decisions

## Database

SQLite + SQLAlchemy

Reason:
Simple local setup while preserving ORM abstraction for future PostgreSQL migration.

---

## Async Strategy

FastAPI BackgroundTasks

Reason:
Suitable for MVP.
Can later be replaced with Celery, Redis, Kafka, or worker queues.

---

## AI Provider

Google Gemini 2.5 Flash

Reason:
Free tier available.
Fast response times.
Supports structured output.

---

## Alert Provider

Slack Incoming Webhook

Reason:
Faster setup and easier testing.

---

# Status Lifecycle

Each incident must track:

RECEIVED
PROCESSING
COMPLETED
FAILED

Reason:
Improves observability and debugging.

---

# Failure Handling

LLM failures:

Attempt up to 3 retries.

If all retries fail:

Status = FAILED

Store error details if possible.

---

# Folder Structure

app/

api/
database/
models/
schemas/
services/
tests/

README.md

requirements.txt

.env

---

# Code Quality Rules

Follow:

* Type hints
* Clean architecture
* Separation of concerns
* Service layer pattern
* Dependency injection where appropriate
* No business logic inside routes
* Meaningful naming
* Small focused functions

---

# Do Not Use

* LangChain
* RAG
* Vector databases
* Celery
* Kafka
* Redis
* Agent frameworks
* React frontend

Keep the implementation simple and production-minded.

---

# Testing Requirements

Implement tests for:

* API endpoint
* Schema validation
* LLM service
* Alert service

Use pytest.

---

# Deliverables

* Working FastAPI application
* SQLite persistence
* Gemini integration
* Slack integration
* Tests
* README documentation
* Architecture explanation
* Scalability discussion
