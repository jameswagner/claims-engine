# Grow Therapy Billing Ops Platform

[![CI / CD](https://github.com/jameswagner/claims-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/jameswagner/claims-engine/actions/workflows/ci.yml)

An internal billing operations platform for monitoring and processing insurance claims across a therapy network at scale. Users are ops staff tracking thousands of therapists' claims across dozens of payers — not individual clinicians submitting their own claims. Every transition is validated against a database-driven rules engine, every state change writes an immutable audit event, duplicate submissions are rejected at both the application and database level, and a Celery task queue handles asynchronous clearinghouse and remittance work.

---

## Architecture

**Local development (Docker Compose — 7 services):**

```
┌──────────────────┐    ┌────────────────────────────────────────────┐    ┌─────────────────┐
│                  │    │  FastAPI  :8000                             │    │                 │
│  React + Vite    │───▶│  State Machine · Rules Engine              │───▶│   PostgreSQL     │
│  :5173           │    │  Analytics · Cursor Pagination              │    │   :5432         │
│                  │    └──────────────────────┬─────────────────────┘    └─────────────────┘
└──────────────────┘                           │ enqueue
                         ┌─────────────────────▼──────────────────────┐
                         │  Redis  :6379  +  Celery Workers            │
                         │  ┌──────────────┐  ┌──────────────────┐   │
                         │  │  submission  │  │  remittance      │   │
                         │  │  (EDI round- │  │  (835 batch,     │   │
                         │  │   trip)      │  │   Beat 10s)      │   │
                         │  └──────────────┘  └──────────────────┘   │
                         └────────────────────────────────────────────┘
Flower task monitor: :5555
```

**Production (AWS — 5 CDK stacks):**

```
┌──────────────────────┐    ┌──────────────────────────────────────────────┐    ┌──────────────────┐
│                      │    │  Lambda  (Docker / Mangum)                    │    │                  │
│  S3 + CloudFront     │───▶│  API Gateway v2  (HTTP API)                   │───▶│  RDS Postgres 15 │
│  (Vite bundle)       │    │  State Machine · Rules Engine · Analytics     │    │  t3.micro · VPC  │
│                      │    └──────────────────────┬───────────────────────┘    └──────────────────┘
└──────────────────────┘                           │ SQS enqueue
                              ┌────────────────────▼─────────────────────────┐
                              │  Lambda Workers                               │
                              │  ┌───────────────────┐  ┌─────────────────┐  │
                              │  │  Submission        │  │  Remittance     │  │
                              │  │  SQS event source  │  │  EventBridge    │  │
                              │  │  batchSize=1 · DLQ │  │  Scheduler 1m  │  │
                              │  └───────────────────┘  └─────────────────┘  │
                              └──────────────────────────────────────────────┘
```

| CDK Stack | Contents |
|-----------|----------|
| `claims-network` | VPC, Lambda + RDS security groups, VPC interface endpoints (Secrets Manager, SQS), Gateway endpoint (DynamoDB) |
| `claims-data` | RDS Postgres 15, SQS submission queue + DLQ (3 retries, 14-day retention), DynamoDB (FF cursor), Secrets Manager, IAM policies, RDS auto-stop/start schedule |
| `claims-api` | FastAPI Lambda (Docker/Mangum, 512 MB, 5-min timeout), HTTP API Gateway v2, SSM parameter for frontend URL |
| `claims-workers` | Submission Lambda (SQS trigger, batchSize=1), Remittance Lambda (EventBridge Scheduler, every 1 min) |
| `claims-frontend` | S3 bucket, CloudFront distribution, Vite bundle with baked API URL (SSM lookup at synth time) |

**Claim lifecycle:**

```
CREATED ──▶ VALIDATED ──▶ SUBMITTING ──▶ SUBMITTED ──▶ ADJUDICATED ──▶ PAID
                                    └──▶ CLEARINGHOUSE_REJECTED        └──▶ DENIED ──▶ SUBMITTING (resubmit)
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

Then seed the database with 8 days of flat baseline history (t-10 through t-3):

```bash
docker exec -w /app claimsprocessing-backend-1 python seed.py
```

The fast-forward demo advances the dashboard one day at a time. Each click writes one day of backdated claims with escalating Aetna 90837 denial rates (22% → 36% → 45%), revealing the anomaly across 3 chart updates:

```bash
curl -X POST http://localhost:8000/demo/fast-forward   # day 1: t-2, Aetna 22%
curl -X POST http://localhost:8000/demo/fast-forward   # day 2: t-1, Aetna 29%
curl -X POST http://localhost:8000/demo/fast-forward   # day 3: today, Aetna 35%
curl -X POST http://localhost:8000/demo/fast-forward/reset  # replay from scratch
```

| Service      | URL                          |
|--------------|------------------------------|
| Frontend     | http://localhost:5173        |
| API          | http://localhost:8000        |
| API docs     | http://localhost:8000/docs   |
| Flower (tasks) | http://localhost:5555      |

**Run tests (no Docker required — tests mock the database):**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/ -v
```

**Run the backend directly (requires a local Postgres instance):**

```bash
cd backend
DATABASE_URL=postgresql://claims:claims@localhost:5432/claims .venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/claims` | Create a new claim |
| `GET` | `/claims` | List claims — filterable by status, payer, date; cursor-paginated |
| `GET` | `/claims/{id}` | Get claim with full event history |
| `POST` | `/claims/{id}/validate` | Run rules engine, CREATED → VALIDATED |
| `POST` | `/claims/{id}/submit` | Enqueue clearinghouse submission, VALIDATED → SUBMITTING |
| `POST` | `/claims/{id}/adjudicate` | Record adjudication with financial terms |
| `POST` | `/claims/{id}/pay` | Record payment, ADJUDICATED → PAID |
| `POST` | `/claims/{id}/deny` | Record denial with reason, ADJUDICATED → DENIED |
| `POST` | `/claims/{id}/resubmit` | Correction flow, DENIED → SUBMITTING |
| `POST` | `/claims/{id}/remit` | Submit remit (EOB) for an adjudicated claim |
| `GET` | `/claims/{id}/remit` | Get the remit with all adjustment codes |
| `GET` | `/analytics/claims` | Denial rates, adjudication timing, aging, throughput by payer |
| `GET` | `/analytics/denial-rate-timeseries` | Daily denial rate per payer over last 14 days |
| `POST` | `/demo/fast-forward` | Advance demo by one day (call up to 3×) |
| `GET` | `/demo/fast-forward/status` | Current demo cursor state from DynamoDB |
| `POST` | `/demo/fast-forward/reset` | Reset demo cursor for replay |

---

## Engineering Decisions

- **Client-supplied idempotency keys.** Every transition endpoint requires an `Idempotency-Key` header (a UUID the caller generates). The key is stored on the `ClaimEvent` with a unique index — a duplicate key returns the original response (200 replay) rather than a 409, matching the Stripe pattern. This is intentionally caller-controlled rather than server-computed: a server-computed key based on `(claim_id, to_status)` would silently block legitimate resubmissions in workflows where a claim visits the same state more than once (e.g. deny → correct → resubmit → deny again). The idempotency check runs before the rules engine so retries bail out immediately without re-hitting the database.

- **Pessimistic locking on transition endpoints.** All write-path fetches use `SELECT ... FOR UPDATE` to lock the claim row for the duration of the transaction. This closes the race where two concurrent callers both read the same `claim.status`, both pass the transition check, and both attempt to write — only one commit succeeds, the second hits a stale state and gets an `InvalidTransitionError`. The idempotency key's unique index provides a second layer: even if two workers with different keys both pass the state check, only one `INSERT INTO claim_events` succeeds. In production you'd more likely see queue partitioning by `claim_id` (so a single worker handles each claim serially) or application-level claim ownership with a `locked_by` field — the DB row lock is appropriate here because transitions are short-lived.

- **Sync `def` handlers over `async def` with sync SQLAlchemy.** Route handlers that do blocking work (DB calls, sleep) are plain `def`, which FastAPI offloads to a thread pool. Making them `async def` while using a synchronous SQLAlchemy session would block the event loop during every DB call — negating the benefit of async. The actual async work (clearinghouse handshake, remittance processing) lives in Celery workers, which is the right place for it.

- **`native_enum=False` for status columns.** SQLAlchemy stores `ClaimStatus` as `VARCHAR` rather than a PostgreSQL native `ENUM`. Native enums are slightly more compact and faster to compare, but adding a new status value requires `ALTER TYPE` which can lock the table. `VARCHAR` with an application-level check constraint makes migrations simpler — an `ALTER TABLE ADD COLUMN` or a new value in the Python enum is enough. For a financial ledger where the status enum changes rarely, either is defensible; the migration ergonomics tilted the choice here.

- **Remit (EOB) processing.** `POST /claims/{id}/remit` accepts a remit payload against an ADJUDICATED claim — raw response text, totals, and an array of adjustment codes (`CO-97`, `PR-1`, etc.). Each code is resolved against a library (`seed_remit_codes.py`) that maps code → category, description, and `action_required` (e.g. "Bill patient", "Resubmit unbundled or write off"). Unknown codes are accepted with a generic fallback rather than rejected, since real remits routinely include codes outside any static list. Posting a remit also updates `claim.allowed_amount` and `claim.paid_amount` from the remit totals, keeping the claim's financial state in sync.

- **Financial fields with lifecycle semantics.** `Claim` carries `billed_amount` (always set at creation), `allowed_amount` and `patient_responsibility` (set at adjudication), and `paid_amount` (set at payment). `adjustment_reason` carries the remit code explanation (e.g. `CO-45: charge exceeds fee schedule`). All stored as `Numeric(10,2)` — no float rounding — and serialized to JSON as numbers via a Pydantic field serializer.

- **Database-driven rules engine.** Validation rules live in a `payor_rules` table rather than in code. Each row has a `payer` (or `*` for all payers), a `rule_type` (`ALLOWED_CPT`, `EXCLUDED_CPT`, `REQUIRE_DIAGNOSIS_PREFIX`), and the relevant value. Adding a new payer exclusion is an `INSERT`, not a deployment. At scale this ruleset would be cached in memory on startup (or in Redis for multi-process deployments) to avoid a DB hit on every validation request — the table structure stays the same, only the read path changes.

- **Immutable event log over `updated_at`.** Every status transition writes a `ClaimEvent` with `from_status`, `to_status`, `reason`, and `triggered_at`. This is not an audit log bolted on afterward — it is the source of truth for claim history. It answers questions like "how many claims went from SUBMITTED directly to DENIED?" or "what was the denial reason for this claim six months ago?" that a single `updated_at` timestamp cannot. Events are never updated or deleted.

- **Structured logging with per-request tracing.** Every request gets a UUID `request_id` generated at the middleware layer (or propagated from an upstream `X-Request-ID` header) and bound via `structlog.contextvars` so every log line within that request — validation, state machine, DB flush — carries it automatically. Output is pretty console in development, JSON in production (with `EventRenamer` so the message key matches what Datadog and CloudWatch expect). The middleware wraps `call_next` in `try/finally` so request completion is always logged even when a route raises an unhandled exception.

- **SQS + Lambda workers (AWS) / Celery + Redis (local).** The API transitions a claim to SUBMITTING synchronously and enqueues the actual clearinghouse work asynchronously — the caller gets an immediate 202, the EDI handshake happens in the background. In production: the submission Lambda is triggered directly by SQS (batchSize=1, 3 DLQ retries) and the remittance Lambda fires on a one-minute EventBridge Scheduler. Locally: Celery workers consume from Redis with a Beat scheduler every 10 seconds. Flower provides real-time task monitoring at `:5555` in local dev.

- **Fast-forward as a rolling demo clock.** The dashboard maintains a `demoCutoff` date, initially set to today − 3, and renders an 8-day window ending there. Each `POST /demo/fast-forward` call writes one day of backdated adjudicated claims directly to the database and returns immediately (~5 seconds). The frontend advances `demoCutoff` by one day and re-fetches the time-series — the chart slides: a new day with higher Aetna denial rates appears on the right, the oldest day drops off the left. Three clicks reveal the full Aetna anomaly. A `POST /demo/fast-forward/reset` clears the DynamoDB cursor so the demo can be replayed. Aetna 90837 denial rates escalate: 22% → 36% → 45% across the three days.

- **Seed covers t-10 through t-3 at flat baseline.** The seed script writes 6,400 claims across 8 days (800/day), all at normal denial rates — Aetna 90837 at 15%, other payers 8–12%. Days t-2, t-1, and today are intentionally left empty. The fast-forward fills them one click at a time with escalating Aetna rates, so the anomaly emerges rather than being pre-loaded.

- **Cursor-based pagination on `GET /claims`.** Cursor encodes `(created_at, id)` as base64 JSON. The WHERE clause uses `(created_at, id) < (cursor_created_at, cursor_id)` with `ORDER BY created_at DESC, id DESC` — cost is constant regardless of how deep into the result set you page, unlike offset pagination which degrades as page number grows.

- **Analytics endpoint from the event ledger.** `GET /analytics/claims` aggregates directly from `claim_events` rather than the claims table. This gives accurate time-series metrics: denial rate by payer, denial rate by CPT code, avg days SUBMITTED→ADJUDICATED per payer (using event pairs), aging counts by how long claims have been in SUBMITTED state, throughput in the last 24 hours. The event ledger is the source of truth.

- **What's deployed on AWS.** The app is live on AWS: Lambda (Docker/Mangum) behind HTTP API Gateway v2 for the API, SQS-triggered Lambda for clearinghouse submissions, EventBridge Scheduler for remittance batches, RDS Postgres 15 for the database, S3 + CloudFront for the frontend, DynamoDB for demo cursor state, and Secrets Manager for credentials. All infrastructure is defined in CDK TypeScript across five stacks with cross-stack TypeScript references, IAM managed policies scoped to least privilege, and VPC endpoints routing AWS API calls within the VPC without a NAT gateway.

- **What I'd add next.** OpenTelemetry tracing via X-Ray to stitch together the full invocation chain across API Gateway → API Lambda → Worker Lambda. RDS Proxy to cap connection count at scale (each Lambda cold start opens a new connection — fine at low concurrency, breaks at high). A denial classification service that turns remit codes (CO-97, PR-1) into structured action items with priority routing for billing teams. Per-payer circuit breakers to isolate payer API instability. WAF on the API Gateway for production.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite 6, Tailwind CSS v4, Recharts |
| Backend | FastAPI, SQLAlchemy 2.0, Alembic, structlog, Python 3.12 |
| Task queue | SQS + Lambda + EventBridge Scheduler (AWS) / Celery 5 + Redis 7 + Beat (local) |
| Database | RDS PostgreSQL 15 (AWS) / PostgreSQL 16 Docker (local) |
| Demo state | DynamoDB (AWS) / in-memory (local) |
| Infrastructure | AWS CDK TypeScript — 5 stacks / Docker Compose — 7 services (local) |
| Testing | pytest |

---

## AI Tooling

This project was built using **Claude Code** (Anthropic's CLI coding agent) and **Claude** (chat) as primary development tools throughout — for scaffolding, architecture decisions, test generation, and iteration. This reflects the role's expectations around AI-assisted development workflows.
