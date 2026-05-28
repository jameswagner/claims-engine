# Claims Lifecycle Tracker

A healthcare insurance claims processing system that tracks the full lifecycle of a claim — from creation through validation, submission, adjudication, and payment or denial. Built to demonstrate the kind of stateful, rule-heavy, auditable backend work that exists in real behavioral health billing infrastructure: every transition is validated against a database-driven rules engine, every state change writes an immutable audit event, and duplicate submissions are rejected at both the application and database level.

---

## Architecture

```
┌──────────────────┐         ┌───────────────────────────────┐         ┌─────────────────┐
│                  │         │  FastAPI  :8000                │         │                 │
│  React + Vite    │ ──────▶ │                               │ ──────▶ │   PostgreSQL     │
│  :5173           │         │  ┌─────────────┐              │         │   :5432         │
│                  │         │  │ State       │              │         │                 │
│  /               │         │  │ Machine     │              │         │  claims         │
│  /claims/:id     │         │  └──────┬──────┘              │         │  claim_events   │
│                  │         │         │                      │         │  payor_rules    │
└──────────────────┘         │  ┌──────▼──────┐              │         │                 │
                             │  │ Rules       │              │         └─────────────────┘
                             │  │ Engine      │              │
                             │  └─────────────┘              │
                             └───────────────────────────────┘
```

**Claim lifecycle:**

```
CREATED ──▶ VALIDATED ──▶ SUBMITTED ──▶ ADJUDICATED ──▶ PAID
                                                    └──▶ DENIED
```

---

## Running Locally

**Prerequisites:** Docker Desktop

```bash
git clone <repo-url>
cd ClaimsProcessing
cp .env.example .env
docker compose up --build
```

Then seed the database:

```bash
# Seed payor rules (allowlists, exclusions, diagnosis requirements)
docker exec -w /app claimsprocessing-backend-1 python -m app.db.seed_rules

# Seed sample claims in various states
docker exec -w /app claimsprocessing-backend-1 python seed.py
```

| Service  | URL                          |
|----------|------------------------------|
| Frontend | http://localhost:5173        |
| API      | http://localhost:8000        |
| API docs | http://localhost:8000/docs   |

**Run tests:**

```bash
cd backend
.venv/bin/pytest tests/ -v
```

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/claims` | Create a new claim |
| `GET` | `/claims` | List all claims |
| `GET` | `/claims/{id}` | Get claim with full event history |
| `POST` | `/claims/{id}/advance` | Advance to the next state |

---

## Engineering Decisions

- **Client-supplied idempotency keys.** `POST /claims/{id}/advance` requires an `Idempotency-Key` header (a UUID the caller generates). The key is stored on the `ClaimEvent` with a unique index — a duplicate key returns the original response (200 replay) rather than a 409, matching the Stripe pattern. This is intentionally caller-controlled rather than server-computed: a server-computed key based on `(claim_id, to_status)` would silently block legitimate resubmissions in workflows where a claim visits the same state more than once (e.g. deny → correct → resubmit → deny again).

- **Financial fields with lifecycle semantics.** `Claim` carries `billed_amount` (always set at creation), `allowed_amount` and `patient_responsibility` (set at adjudication), and `paid_amount` (auto-computed as `allowed - patient_responsibility` on the PAID transition). `adjustment_reason` carries the remit code explanation (e.g. `CO-45: charge exceeds fee schedule`). All stored as `Numeric(10,2)` — no float rounding — and serialized to JSON as numbers via a Pydantic field serializer.

- **Database-driven rules engine.** Validation rules live in a `payor_rules` table rather than in code. Each row has a `payer` (or `*` for all payers), a `rule_type` (`ALLOWED_CPT`, `EXCLUDED_CPT`, `REQUIRE_DIAGNOSIS_PREFIX`), and the relevant value. Adding a new payer exclusion is an `INSERT`, not a deployment. At scale this ruleset would be cached in Redis on startup to avoid a DB hit on every validation request.

- **Immutable event log over `updated_at`.** Every status transition writes a `ClaimEvent` with `from_status`, `to_status`, `reason`, and `triggered_at`. This is not an audit log bolted on afterward — it is the source of truth for claim history. It answers questions like "how many claims went from SUBMITTED directly to DENIED?" or "what was the denial reason for this claim six months ago?" that a single `updated_at` timestamp cannot. Events are never updated or deleted.

- **Structured logging with per-request tracing.** Every request gets a UUID `request_id` generated at the middleware layer (or propagated from an upstream `X-Request-ID` header) and bound via `structlog.contextvars` so every log line within that request — validation, state machine, DB flush — carries it automatically. Output is pretty console in development, JSON in production. The state machine logs every transition attempt with `claim_id`, `from_status`, `to_status`, and `duration_ms`; the validator logs `payer`, `cpt_code`, `is_valid`, and any errors.

- **What I'd add at scale.** Async claim submission via a message queue (Kafka or SQS) so the backend acknowledges receipt immediately and processes in the background — important for payers with slow adjudication APIs. OpenTelemetry tracing to map the full lifecycle of every claim across services. A dedicated denial classification service that parses raw remit codes (CO-97, PR-1, etc.) into structured action items for billing teams. Rate limiting and per-payer circuit breakers to handle payer API instability without cascading failures.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite 6, Tailwind CSS v4 |
| Backend | FastAPI, SQLAlchemy 2.0, Alembic, structlog, Python 3.12 |
| Database | PostgreSQL 16 |
| Infrastructure | Docker Compose |
| Testing | pytest (69 unit tests) |

---

## AI Tooling

This project was built using **Claude Code** (Anthropic's CLI coding agent) and **Claude** (chat) as primary development tools throughout — for scaffolding, architecture decisions, test generation, and iteration. This reflects the role's expectations around AI-assisted development workflows.
