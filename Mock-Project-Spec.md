# Take-Home Engineering Assessment: Autonomous Incident Triaging & Remediation Service

## Overview
We want to build a lightweight Python-based microservice that ingests server and application logs, triages them using a Large Language Model (LLM), and forwards critical incidents to a Microsoft Teams (preferred) or Slack channel. 

As a modern engineer in our organization, you are encouraged to use AI coding assistants (e.g., Claude Code, Gemini, ChatGPT) to plan, write, and debug your implementation. We want to see how you leverage these tools to build a high-quality system quickly without sacrificing engineering rigor.

---

## Core Requirements

Your microservice should be built in **Python** (using **FastAPI**) and support the following capabilities:

### 1. Log Ingestion Endpoint
* Expose a `POST /api/v1/logs` endpoint that receives raw log payloads.
* The API should validate incoming payloads using Pydantic models to ensure correctness.

### 2. LLM Triaging & Structured Extraction
* Process the log message using an LLM API (you can use Claude/Gemini APIs directly or mock the client calls).
* Extract the following structured fields from the log:
  * **Severity:** `LOW`, `MEDIUM`, or `CRITICAL` (Enum).
  * **Category:** `DATABASE`, `NETWORK`, `APPLICATION`, or `SECURITY` (Enum).
  * **Root-Cause Hypothesis:** A brief (1-2 sentence) explanation of what went wrong.
  * **Suggested Remediation:** Clear steps to resolve the incident.
* Ensure the LLM output is validated against your Pydantic schema (e.g., JSON mode/structured outputs).

### 3. Background Processing & Performance
* Evaluating the LLM and sending notifications should not block the main API response.
* Ingestion should return a tracking receipt ID immediately, while the classification and alerting run asynchronously.

### 4. Incident Alerting (Microsoft Teams or Slack)
* If the log severity is determined to be `CRITICAL`, format a rich card/message and send it to a webhook. You can implement either of the following (Teams is preferred):
  * **Microsoft Teams (Preferred):** Send a card payload (Adaptive Cards or MessageCards format) to a Teams incoming webhook.
  * **Slack:** Send a block kit/markdown payload to a Slack webhook.
  * *Note: You can mock the webhook endpoint in tests or use a personal test channel.*

### 5. Persistence
* Save all ingested logs along with their extracted LLM metadata and triaging status into a database (SQLAlchemy with SQLite is recommended).

---

## Deliverables

Please package and return the following items before the technical review session:

1. **Working Codebase:**
   * A clean ZIP file or link to a private Git repository containing the complete implementation.
   * A working test suite (using `pytest` or standard unittest) verifying core endpoints and utility logic.
   * Clear running instructions (e.g., a setup script, `requirements.txt`, or environment variable template).
2. **System Architecture & Documentation (`README.md`):**
   * Explain your architecture design and why you selected specific libraries/patterns (e.g., database, worker concurrency model).
   * Document how the service handles API rate limits, LLM failures, and malformed LLM responses.
   * Describe how the system's design would change if log ingestion scaled to 10,000 alerts per minute.
3. **AI Chat History (`ai_chat_history.md` or links):**
   * Exported chat logs (Markdown, PDF, or shareable web links) showing the full conversation history with your AI coding assistants (Claude, Gemini, ChatGPT) during design and implementation.
   * **Note:** We are looking at *how* you prompted the AI, how you handled bugs, and how you iteratively refined the codebase.

