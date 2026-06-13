# Grow Therapy Billing Ops Platform — Technical Report

## What This Is

An internal billing operations platform modeled on the kind of system that handles claims processing at network scale — not a solo therapist tracker. Users are ops staff monitoring thousands of therapists' claims across dozens of payers. Every claim transition is validated against a database-driven rules engine, every state change writes an immutable audit event, duplicate submissions are rejected at both the application and database level, and a Celery task queue handles asynchronous clearinghouse and remittance work.

---

## Architecture

**Local development — 7 Docker services:**

| Service | Image | Purpose |
|---------|-------|---------|
| `db` | postgres:16-alpine | Primary datastore |
| `redis` | redis:7-alpine | Celery broker + result backend |
| `backend` | ./backend | FastAPI API server (uvicorn) |
| `worker` | ./backend | Celery worker — clearinghouse submission, remittance batch |
| `beat` | ./backend | Celery Beat — fires remittance batch every 10s |
| `flower` | mher/flower:2.0 | Task monitoring UI at :5555 |
| `frontend` | ./frontend | React + Vite dev server |

**Production — AWS (5 CDK stacks):**

| Stack | Contents |
|-------|----------|
| `claims-network` | VPC, Lambda + RDS security groups, VPC interface endpoints (Secrets Manager, SQS), Gateway endpoint (DynamoDB) |
| `claims-data` | RDS Postgres 15, SQS submission queue + DLQ, DynamoDB (FF cursor), Secrets Manager, IAM policies, RDS auto-stop/start |
| `claims-api` | FastAPI Lambda (Docker/Mangum, 512 MB, 5-min timeout), HTTP API Gateway v2, SSM parameter |
| `claims-workers` | Submission Lambda (SQS event source, batchSize=1), Remittance Lambda (EventBridge Scheduler, 1 min) |
| `claims-frontend` | S3 bucket, CloudFront distribution, Vite bundle with baked API URL |

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

### Fast-forward as a Rolling Demo Clock

The dashboard maintains a `demoCutoff` date in React state, initially set to today − 3. The time-series chart renders an 8-day window ending at `demoCutoff`. Each `POST /demo/fast-forward` call writes 800 backdated adjudicated claims directly to the database for the next pending day (t-2, t-1, or today) — no Celery, no pipeline, returns in ~5 seconds. The frontend increments `demoCutoff` by one day and re-fetches the time-series: the chart slides right (oldest day drops off, new day with escalating Aetna rates appears). Three clicks reveal the full anomaly. A `POST /demo/fast-forward/reset` clears the DynamoDB cursor for replay. The demo cursor position is persisted in DynamoDB so a page refresh or Lambda cold start doesn't lose the current state — the frontend fetches cursor state on mount and syncs its local day index accordingly.

### Seed: 8-Day Flat Baseline

`seed.py` writes 800 claims/day for t-10 through t-3 (6,400 claims total) at flat, normal denial rates — Aetna 90837 at 15%, other payers at 8–12%. Days t-2, t-1, and today are intentionally left empty. The fast-forward fills them one click at a time with Aetna 90837 denial rates escalating 22% → 36% → 45%, so the anomaly emerges in real time rather than being pre-baked. All seed claims have their `ADJUDICATED→{PAID,DENIED}` event timestamped to the target day so they appear in the correct bucket on the time-series chart.

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
| Celery + Redis + Flower (local dev) | ✅ Complete |
| Seed (6,400 claims, 8-day flat baseline t-10→t-3) | ✅ Complete |
| Task modules (submission, remittance) | ✅ Complete |
| Fast-forward demo (click-by-click, t-2/t-1/today, escalating Aetna rates) | ✅ Complete |
| Analytics endpoint + denial-rate-timeseries | ✅ Complete |
| Cursor pagination + filtering on GET /claims | ✅ Complete |
| Dashboard (8-day line chart, 20% alert threshold, demoCutoff clock, metrics) | ✅ Complete |
| Worklist (tabs, filters, request badge) | ✅ Complete |
| **AWS deployment — CDK TypeScript, 5 stacks** | ✅ Complete |
| VPC + security groups + VPC endpoints (no NAT gateway) | ✅ Complete |
| RDS Postgres 15 + Secrets Manager + auto-stop/start | ✅ Complete |
| FastAPI Lambda (Docker/Mangum) + HTTP API Gateway v2 | ✅ Complete |
| SQS submission queue + Lambda worker + DLQ | ✅ Complete |
| EventBridge Scheduler → Remittance Lambda (1 min) | ✅ Complete |
| S3 + CloudFront frontend + SSM API URL baking | ✅ Complete |
| DynamoDB FF cursor (survives cold starts + page refreshes) | ✅ Complete |
| CI/CD pipeline (GitHub Actions) | ⬜ Not started |