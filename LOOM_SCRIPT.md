# LOOM SCRIPT — Grow Therapy Billing Ops Platform
_Update this after each build prompt._

**Target runtime: ~5 minutes**
**Framing: Grow Therapy's internal billing operations platform, not a solo tracker**

---

## BEFORE YOU HIT RECORD

1. `docker compose up` — all 6 services healthy (db, redis, backend, worker, beat, flower)
2. Run seed: `docker exec -w /app claimsprocessing-backend-1 python seed.py`
3. Open tabs: `localhost:5173` (dashboard), `localhost:5555` (Flower), `localhost:8000/docs` (API)
4. Dashboard should show ~300 historical claims, charts populated, all Aetna denial rates ~15%

---

## COLD OPEN (15 seconds)

> "This is Grow Therapy's internal billing operations platform. Every time a therapist
> completes a session, a claim enters this pipeline. I'm going to start by kicking off
> a simulation that compresses 3 days of billing activity into about 2 minutes — and
> then walk through what's actually happening while it runs."

**Action:** Click "⏩ Fast-forward" button on dashboard → amber progress banner appears.
Banner reads: "Fast-forwarding billing activity — Day 1 of 3 · 0 claims submitted"

---

## SEGMENT 1 — THE QUEUE ARCHITECTURE (60 seconds)

> "The backend is FastAPI with a Celery task queue backed by Redis. Two independent
> workers: a clearinghouse submission worker that picks up SUBMITTING claims from the
> queue and handles the EDI round-trip — 80% go to SUBMITTED, 20% get clearinghouse
> rejected. And a remittance batch processor on a Beat schedule that fires every 10
> seconds, finds SUBMITTED claims, and adjudicates them with payer-specific denial rates.
>
> In a real Grow Therapy system these workers consume events from session completion
> webhooks from the EHR, 835 file drops from the clearinghouse, and payer API polling.
> The queue decouples receiving an event from processing it — the API acknowledges
> immediately, the actual work happens in the background."

**Show:** Flower at `localhost:5555`
- Connected workers, active tasks
- Task history — submission and remittance tasks firing
- Throughput chart ticking up

> "This is Flower — the Celery monitoring UI. An on-call engineer watching this at
> 2am can see exactly what the workers are doing, which tasks are failing, and why.
> That observability matters when you have 22,000 clinicians submitting claims."

**Watch banner:** "Day 1 of 3 · 47 claims submitted"

---

## SEGMENT 2 — RULES ENGINE + STATE MACHINE (60 seconds)

> "Before a claim can move from CREATED to VALIDATED it runs through a rules engine.
> The rules aren't hardcoded — they live in Postgres as data. Adding a new payer
> exclusion is an INSERT, not a deployment."

**Show:** `payor_rules` table via Swagger UI or quick SQL in the DB

> "The state machine enforces valid transitions. VALIDATED can go to SUBMITTED, not
> directly to PAID. Every transition writes an immutable ClaimEvent — not an
> updated_at timestamp, a full record of where it came from, where it went, why,
> and when. That event log answers questions a single status column never can:
> how many claims went SUBMITTED directly to DENIED this month? What was the
> denial reason on this claim six months ago?"

**Show:** ClaimDetail page — event timeline with from/to status and triggered_at timestamps

> "All write-path endpoints use SELECT FOR UPDATE — pessimistic locking. If two
> workers race to transition the same claim, only one commit succeeds."

---

## SEGMENT 3 — IDEMPOTENCY (30 seconds)

> "Every transition requires an Idempotency-Key header — a UUID the caller generates.
> The key is stored on the ClaimEvent with a unique index. A retry with the same key
> replays the original response. A different key for the same claim-plus-status is a
> fresh attempt, not a duplicate — so a claim can be denied and resubmitted without
> the idempotency check blocking the second submission.
>
> The check runs before the rules engine so retries bail immediately without
> re-hitting the database."

**Show:** The idempotency_key column on a ClaimEvent in the timeline (first 8 chars monospace)

---

## SEGMENT 4 — THE AETNA PATTERN (45 seconds)

> "The dashboard is pulling aggregations from the claim event ledger, not the
> claims table. Let's look at the denial rate by payer chart."

**Show:** Dashboard BarChart — currently all payers near 12-15%, Aetna unremarkable

> "Historically, Aetna's denial rate on 90837 is about 15% — nothing alarming.
> But the remittance batch worker I started at the beginning of this recording has
> been adjudicating live claims at Aetna's real-world rate for 90837."

**Show:** Watch Aetna's bar climb as fast-forward continues — now showing 25-30%. Switch to the CPT code denial rate chart — 90837 is the outlier, 90834 and 90832 are flat.

> "That's not pre-baked into the historical data. The workers introduced it. By
> the time the fast-forward finishes, you'll see Aetna's 90837 denial rate sitting at
> 35% — roughly where it sits in the real behavioral health billing market. The CPT
> code chart tells you exactly which procedure code is the problem. A billing manager
> looking at this dashboard would know to investigate Aetna 90837 claims."

---

## SEGMENT 5 — WORKLIST + PAGINATION (45 seconds)

> "The worklist is built for billing ops, not developers."

**Show:** Navigate to `/claims` — worklist page

> "Three tabs: all claims, the exceptions queue — denied claims needing action —
> and an aging queue for submissions past the 30-day SLA."

**Show:** Click "Exceptions" tab — denied claims filtered automatically

> "Cursor-based pagination. Watch the request badge."

**Show:** Hit Next — bottom right shows "↩ 11ms · req-a3f2b1c4"

> "That 11ms is constant regardless of how deep you are in the result set. Offset
> pagination degrades as you page deeper — cursor pagination doesn't. The cursor
> encodes a (created_at, id) pair as base64 so it's stable even as new claims
> arrive between page loads."

---

## SEGMENT 6 — OBSERVABILITY + SCALE (30 seconds)

> "Every request gets a UUID request_id generated at the middleware layer — or
> propagated from an upstream X-Request-ID header. It's bound via structlog
> contextvars so every log line within that request carries it automatically.
> Development is pretty console output; ENVIRONMENT=production switches to JSON,
> one line per event, ready for Datadog."

**Show:** `docker compose logs worker` — structured log lines from the remittance processor

> "What I'd add at production scale: replace Redis/Celery with SQS and Lambda so
> workers scale to zero and the DLQ is a first-class infrastructure primitive rather
> than configuration. OpenTelemetry tracing via X-Ray to stitch together the full
> lifecycle across services. A denial classification service that turns CO-97 and PR-1
> codes into structured action items for billing teams. And per-payer circuit breakers
> to handle payer API instability without cascading failures."

---

## COLD CLOSE (10 seconds)

> "Code on GitHub. Happy to walk through any of it."

---

## TOTAL TARGET: ~5 minutes

---

## Build Status

| Segment | Status |
|---------|--------|
| Cold open + fast-forward trigger | ✅ Ready |
| Flower / queue architecture | ✅ Ready |
| Rules engine + state machine | ✅ Ready |
| Idempotency | ✅ Ready |
| Aetna pattern / analytics charts | ✅ Ready |
| Worklist + pagination | ✅ Ready |
| Observability | ✅ Ready |
| Cold close | ✅ Ready |
