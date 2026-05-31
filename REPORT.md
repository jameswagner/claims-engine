# Grow Therapy Billing Ops Platform — Technical Report

## What This Is

An internal billing operations platform modeled on the kind of system that handles claims processing at network scale — not a solo therapist tracker. Users are ops staff monitoring thousands of therapists' claims across dozens of payers. Every claim transition is validated against a database-driven rules engine, every state change writes an immutable audit event, duplicate submissions are rejected at both the application and database level, and a Celery task queue handles asynchronous clearinghouse and remittance work.

---

## Architecture

Seven Docker services:

| Service | Image | Purpose |
|---------|-------|---------|
| `db` | postgres:16-alpine | Primary datastore |
| `redis` | redis:7-alpine | Celery broker + result backend + fast-forward state |
| `backend` | ./backend | FastAPI API server (uvicorn) |
| `worker` | ./backend | Celery worker — clearinghouse submission, remittance batch |
| `beat` | ./backend | Celery Beat — fires remittance batch every 10s |
| `flower` | mher/flower:2.0 | Task monitoring UI at :5555 |
| `frontend` | ./frontend | React + Vite dev server |

**Claim lifecycle:**

```
CREATED → VALIDATED → SUBMITTING → SUBMITTED → ADJUDICATED → PAID
                              └→ CLEARINGHOUSE_REJECTED      └→ DENIED → SUBMITTING (resubmit)
```

---

## Backend Structure

```
backend/app/
├── main.py              # app factory — middleware, router mounts, CORS
├── core/logging.py      # structlog config (console dev / JSON prod)
├── db/session.py        # engine, SessionLocal, Base, get_db()
├── models/              # SQLAlchemy ORM models
│   ├── claim.py
│   ├── claim_event.py
│   ├── remit.py / remit_code.py
│   ├── payor_rule.py
│   └── enums.py
├── schemas/             # Pydantic request/response schemas
├── api/                 # Route handlers
│   ├── claims.py        # full lifecycle endpoints
│   ├── remits.py        # EOB submission and retrieval
│   ├── analytics.py     # denial rate by payer/CPT, aging, adjudication timing
│   └── demo.py          # fast-forward trigger and status polling
├── claims/
│   ├── state_machine.py # transition() — validates, locks, writes event
│   └── exceptions.py
├── rules/
│   └── validator.py     # DB-driven rules engine
└── tasks/               # Celery task modules
    ├── generators.py    # _create_one_claim() utility — used by fast_forward
    ├── submission.py    # clearinghouse EDI handshake, 80/20 success/reject
    ├── remittance.py    # 835 batch processor, payer-specific denial rates
    └── fast_forward.py  # demo firehose: creates claims, enqueues submissions
```

---

## Key Technical Decisions

### State Machine + Pessimistic Locking

All write-path claim fetches use `SELECT ... FOR UPDATE`. Two concurrent workers that both read the same `claim.status`, both pass the transition check, but only one commits — the second hits a stale row and gets an `InvalidTransitionError`. A second layer of protection: the idempotency key's unique index on `claim_events` means even if two workers with different keys both pass the state check, only one INSERT succeeds.

### Idempotency

Every transition endpoint requires an `Idempotency-Key` header — a UUID the caller generates per *operation*. The key is stored on `ClaimEvent` with a unique index. A retry with the same key replays the original 200 response. A different key for the same claim is a new operation, not a duplicate — so a claim can be denied and resubmitted without the check blocking the second submission. The idempotency check runs before the rules engine so retries bail immediately without re-hitting the DB. This is the Stripe pattern.

### Celery + Redis over FastAPI BackgroundTasks

`BackgroundTasks` has no durability, no retry, no monitoring — a restart drops everything in flight. Celery adds retry logic, dead-letter queues, and Flower observability. The API transitions a claim to SUBMITTING synchronously and enqueues the actual clearinghouse work — the caller gets an immediate response, the EDI handshake happens in the background. Flower at `:5555` gives an on-call engineer full visibility into what workers are doing.

### Fast-forward Architecture

`POST /demo/fast-forward` triggers a Celery task that compresses 3 days of billing activity into ~2 minutes — a dumb firehose that creates claims in bursts and enqueues submission tasks. The independent submission worker processes the queue (80% SUBMITTED, 20% CLEARINGHOUSE_REJECTED), and the Beat-scheduled remittance worker adjudicates SUBMITTED claims on its own 10-second cadence. No orchestration between them. Progress is tracked in Redis (`demo:fast_forward:status`) and polled by the frontend every 3 seconds for a live progress banner.

### Historical Seed vs Live Workers

The seed script (`seed.py`) writes 300 historically resolved claims directly to the DB with Aetna denial rates at ~15% — unremarkable. The live remittance worker uses Aetna's real-world 35% denial rate on 90837. During a fast-forward, the analytics charts update in real time as the Aetna bar climbs above the others. The anomaly emerges rather than being pre-baked.

### Immutable Event Ledger

Every status transition writes a `ClaimEvent` with `from_status`, `to_status`, `reason`, `idempotency_key`, and `triggered_at`. The events are never updated or deleted. The analytics endpoint (`GET /analytics/claims`) aggregates from the event ledger rather than the claims table — `avg_days_to_adjudication_by_payer` uses SUBMITTED→ADJUDICATED event pairs, aging counts use how long a claim has been in SUBMITTED state, throughput is counts of events in the last 24 hours.

### `native_enum=False` for Status Columns

`ClaimStatus` is stored as VARCHAR rather than a PostgreSQL native ENUM. Adding a new status (`SUBMITTING`, `CLEARINGHOUSE_REJECTED`) requires no `ALTER TYPE` — just a Python enum value and an Alembic migration that updates the check constraint. Native ENUMs are harder to alter and can lock the table in older Postgres versions.

### Sync `def` for Submission Endpoints

Submit and resubmit simulate clearinghouse latency with `time.sleep`. Making them `async def` while using a synchronous SQLAlchemy session would block the event loop during every DB call. FastAPI offloads sync `def` handlers to a thread pool automatically — the sleep and DB calls block only that thread, not the event loop.

### Cursor-Based Pagination

`GET /claims` paginates using a cursor encoding `(created_at, id)` as base64 JSON. The WHERE clause uses `(created_at, id) < (cursor_created_at, cursor_id)` with stable ORDER BY. Cost is constant regardless of page depth — offset pagination degrades as page number grows because the DB must scan and discard all prior rows.

### DB-Driven Rules Engine

Validation rules live in `payor_rules` rather than in code. Each row has a `payer` (or `*` for all payers), a `rule_type` (`ALLOWED_CPT`, `EXCLUDED_CPT`, `REQUIRE_DIAGNOSIS_PREFIX`), and the relevant value. Adding a new payer exclusion is an INSERT, not a deployment. At scale this ruleset would be cached in Redis on startup to avoid a DB hit on every validation request.

### Structured Logging

Every request gets a UUID `request_id` generated at the middleware layer (or propagated from an upstream `X-Request-ID` header), bound via `structlog.contextvars` so every log line within that request carries it automatically. Development is pretty console output; `ENVIRONMENT=production` switches to JSON with `EventRenamer(to="message")` so the message key matches what Datadog and CloudWatch expect. Uvicorn's access log is suppressed to avoid duplicate request logging.

---

## Database Schema (current)

| Table | Purpose |
|-------|---------|
| `claims` | Core entity — status, financial fields, payer, provider, patient |
| `claim_events` | Immutable audit trail — every transition with from/to status, reason, idempotency key |
| `remits` | EOB record — raw 835 response, totals, idempotency key |
| `remit_codes` | Adjustment codes from remit (CO-97, PR-1, etc.) with description and action_required |
| `payor_rules` | DB-driven validation rules — payer, rule_type, CPT code/value |

Financial fields on `Claim`: `billed_amount` (at creation), `allowed_amount` + `patient_responsibility` (at adjudication), `paid_amount` (at payment or remit). All `Numeric(10,2)` — no float rounding.

---

## Build Status

| Component | Status |
|-----------|--------|
| Claims lifecycle API (all transitions) | ✅ Complete |
| State machine + pessimistic locking | ✅ Complete |
| Idempotency on all transitions + remit | ✅ Complete |
| Rules engine (DB-driven) | ✅ Complete |
| Remit (EOB) processing | ✅ Complete |
| Structured logging + request tracing | ✅ Complete |
| Celery + Redis + Flower infrastructure | ✅ Complete |
| Historical seed (300 claims, 6 months) | ✅ Complete |
| Task modules (submission, remittance, fast-forward) | ✅ Complete |
| Fast-forward mode (demo endpoint) | ✅ Complete |
| Analytics endpoint | ✅ Complete |
| Cursor pagination + filtering on GET /claims | ✅ Complete |
| Dashboard (fast-forward banner, charts, metrics) | ✅ Complete |
| Worklist (tabs, filters, request badge) | ✅ Complete |