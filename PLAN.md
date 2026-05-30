# Build Plan: Claims Engine → Grow Therapy Billing Ops Platform

**Target:** Loom recorded Tuesday, application sent Wednesday
**Framing:** Internal Grow Therapy billing operations platform — not a solo therapist
tracker. Users are Grow Therapy's own ops staff monitoring thousands of therapists'
claims across dozens of payers.

**Core demo approach:** At the start of the Loom, trigger `POST /demo/replay` which
compresses 3 days of billing activity (session completions, clearinghouse submissions,
payer remittance batches) into ~2 minutes. The dashboard updates in real time while
you narrate the architecture. By the time you finish explaining, the system has
meaningful live volume. After replay completes, Beat generators continue at normal
intervals so the system keeps breathing.

---

## Outstanding Bug — DONE ✓

Remit `idempotency_key` column and migration committed and pushed.

---

## Phase 1 — Backend Infrastructure (Saturday AM)

### 1. Celery + Redis + Flower Setup (2 hrs)

Foundation everything else builds on. Get infrastructure running before writing tasks.

**docker-compose additions:**
- `redis:7-alpine` — broker
- `worker` — same backend image, Celery worker, concurrency 4
- `beat` — same backend image, Celery Beat scheduler
- `flower` — `mher/flower`, task monitoring UI at `:5555`

**Prompt:**
> Set up Celery + Redis + Flower in the project:
> 1. Add four services to `docker-compose.yml`:
>    - `redis`: image `redis:7-alpine`, port 6379
>    - `worker`: build `./backend`, command
>      `celery -A app.celery_app worker --loglevel=info --concurrency=4`,
>      depends on `db` and `redis`, same env vars as backend service
>    - `beat`: build `./backend`, command
>      `celery -A app.celery_app beat --loglevel=info`,
>      depends on `redis`
>    - `flower`: image `mher/flower:2.0`, command
>      `celery --broker=redis://redis:6379/0 flower --port=5555`,
>      port `5555:5555`, depends on `redis`
> 2. Add `REDIS_URL=redis://redis:6379/0` to `.env.example` and to backend service
>    env in docker-compose
> 3. Add `celery==5.3.6` and `redis==5.0.1` to `backend/requirements.txt`
> 4. Create `backend/app/celery_app.py`: Celery instance named `claims`, broker and
>    result backend from env var `REDIS_URL`, `beat_schedule` empty for now
> 5. Create `backend/app/tasks/__init__.py` (empty)
> Verify: `docker compose up --build`, Flower reachable at localhost:5555 with
> connected workers shown.

---

### 2. Historical Seed — Baseline Only (1-2 hrs)

Six months of already-resolved claims so analytics charts have historical context.
The replay generates all in-flight and recent activity — seed is purely backstory.

**Demo narrative:** Historical data shows a *normal* baseline — Aetna denial rate
~15%, unremarkable. Then when live workers spin up during the Loom, the Aetna rate
climbs to 35-40% in real time. The viewer watches the anomaly emerge rather than
seeing a pre-baked spike. "Watch what happens when I start the simulation workers...
there it is."

**What the seed needs:**
- 300 resolved claims (PAID or DENIED only — nothing in-flight)
- 6 therapist providers, 5 payers (Aetna, Cigna, BCBS, UnitedHealthcare, Humana)
- CPT codes: 90837, 90834, 90791
- Historical payer patterns (intentionally unremarkable — the spike comes from live workers):
  - Aetna: ~15% denial rate on 90837 (normal, not alarming)
  - UnitedHealthcare: avg 45 days SUBMITTED→ADJUDICATED (others ~20 days)
  - BCBS: lowest denial rate (~8%)
  - All payers: 10-15% denial rate overall
- ~40 DENIED claims that were resubmitted and eventually PAID
- Realistic financials: $150-$300 billed, $100-$200 allowed
- ClaimEvents with accurate triggered_at timestamps throughout

**Prompt:**
> Write `seed.py` in the project root to generate 300 historically resolved claims
> (status PAID or DENIED only) spread across the last 6 months. Use 6 provider
> names, 5 payers (Aetna, Cigna, BCBS, UnitedHealthcare, Humana), CPT codes
> 90837/90834/90791. Historical denial rates should be unremarkable (Aetna ~15% on
> 90837, BCBS ~8%, others ~12%) — the live workers will introduce the spike.
> UnitedHealthcare takes avg 45 days to adjudicate vs 20 for others. For each claim
> write ClaimEvents for every transition with realistic triggered_at timestamps —
> VALIDATED 1-2 days after CREATED, SUBMITTED 1-3 days later, ADJUDICATED 20-45
> days after SUBMITTED (payer-dependent), PAID/DENIED same day as adjudication.
> Include ~40 DENIED claims resubmitted and eventually PAID.
> Write directly to DB via SQLAlchemy session, not the API. Run payor rule seeding
> first if rules table is empty.

---

## Phase 2 — Task Architecture (Saturday PM)

### 3. Core Task Modules (1.5 hrs)

The three worker functions that both the replay and the Beat schedule call.
Build these first as pure functions, then wire into replay and Beat separately.

**New files:**
- `backend/app/tasks/generators.py` — session completion logic
- `backend/app/tasks/submission.py` — clearinghouse worker
- `backend/app/tasks/remittance.py` — 835 batch processor

**Add to ClaimStatus + ALLOWED_TRANSITIONS + migration:**
- `SUBMITTING` — claim handed to clearinghouse worker, in flight
- `CLEARINGHOUSE_REJECTED` — EDI validation failed, needs correction

**Prompt:**
> Create three Celery task modules. Also add SUBMITTING and CLEARINGHOUSE_REJECTED
> to ClaimStatus enum and ALLOWED_TRANSITIONS, and write a migration for them.
>
> `backend/app/tasks/generators.py` — task `generate_session_completions(count=2)`:
> Creates `count` claims with random (provider, payer, cpt_code), validates each
> via validate_claim directly, transitions to VALIDATED, returns list of claim IDs.
> Opens and closes its own DB session.
>
> `backend/app/tasks/submission.py` — task `process_submission(claim_id, idempotency_key, reason=None)`:
> Opens own DB session, fetches claim, verifies SUBMITTING status, sleeps 0.5-2s
> (random), then 80% → SUBMITTED, 20% → CLEARINGHOUSE_REJECTED with reason
> "EDI validation failed: invalid NPI format". Commits and closes session.
>
> `backend/app/tasks/remittance.py` — task `process_remittance_batch(limit=10)`:
> Opens own DB session, finds up to `limit` SUBMITTED claims oldest-first.
> Payer-specific adjudication: Aetna+90837 → 35% DENIED, UHC → 20% DENIED (skip
> if submitted < 2 min ago), others → 12% DENIED. ADJUDICATED claims get
> allowed_amount (85-95% of billed), patient_responsibility (20% of allowed), then
> immediately PAID. DENIED claims get realistic reason codes (CO-97, CO-45, CO-50).
> Uses generated idempotency keys. Commits per claim (partial success is correct).
>
> ALLOWED_TRANSITIONS additions:
> VALIDATED → SUBMITTING, DENIED → SUBMITTING (resubmit path),
> SUBMITTING → SUBMITTED, SUBMITTING → CLEARINGHOUSE_REJECTED,
> CLEARINGHOUSE_REJECTED → SUBMITTING (retry)

---

### 4. Replay Mode (2 hrs)

The demo centrepiece. Triggered once at the start of the Loom, compresses 3 days
of network activity into ~2 minutes. Progress tracked in Redis so the UI can
show a live banner.

**New files:**
- `backend/app/tasks/replay.py` — replay orchestrator task
- `backend/app/api/demo.py` — `/demo/replay` and `/demo/replay/status` endpoints

**How replay works:**
- 3 "days" × ~50 session completions per day = 150 claims generated
- Each day takes ~40 seconds of real time (3 days = ~2 min total)
- Within each simulated day: fires session completions in bursts, runs remittance
  batches every 8 seconds, mimicking morning sessions + evening EOB processing
- Progress stored in Redis: `{day: 2, total_days: 3, claims_created: 87, events_processed: 312}`
- After replay: Beat schedule kicks in at normal intervals for ongoing activity

**Prompt:**
> Create `backend/app/tasks/replay.py` with Celery task `run_billing_replay`:
> Takes `days=3`, `compress_seconds=120`. Divides compress_seconds evenly across
> days. Within each day:
>   - Fire generate_session_completions(count=random(3,8)) every 2-3 seconds
>     until ~50 claims created for that day
>   - Fire process_remittance_batch(limit=15) every 8 seconds
>   - After each session burst, enqueue process_submission for each new VALIDATED
>     claim (transition to SUBMITTING first, then enqueue)
> Track progress in Redis key `demo:replay:status` as JSON:
>   `{running: true, day: N, total_days: 3, claims_created: N, events_processed: N}`
> Set `running: false` when complete.
>
> Create `backend/app/api/demo.py` with two endpoints registered in main.py:
>   - `POST /demo/replay` — enqueues run_billing_replay, returns 202
>   - `GET /demo/replay/status` — reads Redis key, returns progress JSON
>     (returns `{running: false}` if key missing)
>
> Register `run_billing_replay` in celery_app beat_schedule to NOT run automatically
> — only triggered manually via the endpoint.
>
> Also add a low-frequency Beat task `run_background_generators` that fires every
> 30 seconds after startup: generates 1-2 session completions and runs a small
> remittance batch (limit=3) to keep the system alive post-replay.

---

### 5. Manual Submit Wiring (1 hr)

Wire the UI submit/resubmit buttons into the same submission worker.

**Prompt:**
> Update `POST /claims/{id}/submit` and `POST /claims/{id}/resubmit` in
> `backend/app/api/claims.py`:
> - Transition claim to SUBMITTING synchronously (committed immediately)
> - Enqueue process_submission via Celery
> - Return 202 with the claim in SUBMITTING state
>
> Update frontend `api/claims.ts`: submitClaim and resubmitClaim handle 202,
> return claim body. Update `ClaimDetail.tsx`: SUBMITTING status shows disabled
> "Processing…" button and polls GET /claims/{id} every 2s until status changes.
> CLEARINGHOUSE_REJECTED shows red alert with rejection reason and
> "Retry Submission →" button. Add SUBMITTING (amber) and CLEARINGHOUSE_REJECTED
> (orange-red) to StatusBadge color map.

---

## Phase 3 — Analytics + Data Layer (Saturday Eve)

### 6. Analytics Endpoint (2 hrs)

**Prompt:**
> Add `GET /analytics/claims` in new file `backend/app/api/analytics.py`,
> registered in `main.py`. Pydantic response schema. structlog timing. Return:
> - `claims_by_status`: dict of ClaimStatus → count
> - `denial_rate_by_payer`: list of {payer, total, denied, denial_rate_pct}
> - `avg_days_to_adjudication_by_payer`: list of {payer, avg_days} — use
>   claim_events pairs SUBMITTED→ADJUDICATED, compute day diff per payer
> - `aging_summary`: {over_14_days: int, over_30_days: int} — SUBMITTED claims
>   where SUBMITTED event triggered_at is older than threshold
> - `resubmission_success_rate`: {resubmitted: int, eventually_paid: int, rate_pct}
> - `throughput_last_24h`: {created: int, submitted: int, paid: int, denied: int}
>   — counts of claims with relevant events in the last 24 hours, shows live activity

---

### 7. Filtering + Cursor Pagination on GET /claims (1.5 hrs)

**Prompt:**
> Update `GET /claims` to support: `status`, `insurance_payer`, `date_from`,
> `date_to`, `is_aging` (bool), `cursor`, `page_size` (default 20, max 100).
> Cursor encodes `(created_at, id)` as base64 JSON. Use
> `WHERE (created_at, id) < (cursor_created_at, cursor_id)` ORDER BY created_at
> DESC, id DESC for stable pagination.
> Response schema: `{items: list[ClaimRead], next_cursor: str | None, total_count: int}`
> Also add `is_aging: bool = False` to Claim model + ClaimRead schema + migration.
> Add `expose_headers=["X-Request-ID"]` to CORSMiddleware in main.py.
> Update frontend types and fetchClaims signature accordingly.

---

## Phase 4 — Frontend (Sunday)

### 8. Install Recharts (15 min)

> `cd frontend && npm install recharts`

---

### 9. Dashboard — `/` (3-4 hrs)

**Prompt:**
> Create `frontend/src/pages/Dashboard.tsx` as new `/` route, move ClaimsList
> to `/claims`. Dashboard:
> 1. Nav bar: "Grow Therapy · Billing Ops" wordmark, Dashboard and Worklist links
> 2. Replay banner: on load, call GET /demo/replay/status every 3s. While
>    `running: true`, show a dismissable amber banner:
>    "Replaying billing activity across the network — Day {day} of {total_days} ·
>    {claims_created} claims · {events_processed} events processed" with progress bar.
>    Auto-dismiss when running becomes false.
> 3. Four metric cards (auto-refresh every 20s): Claims Last 24h, Network Denial
>    Rate %, Claims Past 30-Day SLA, Avg Days to Payment
> 4. Recharts BarChart: denial rate by payer — red gradient, higher = darker red
> 5. Recharts BarChart: avg days to adjudication by payer
> 6. Aging alert: if over_30_days > 0, show banner linking to /claims?tab=aging
> 7. Small "Updated Xs ago" ticker bottom-right

---

### 10. Worklist — `/claims` (3-4 hrs)

**Prompt:**
> Rewrite `frontend/src/pages/ClaimsList.tsx` as billing ops worklist:
> 1. Three tabs: "All Claims" | "Exceptions (Denied)" | "Aging (>30 days)"
>    Exceptions pre-filters status=DENIED. Aging pre-filters is_aging=true.
> 2. Filter bar: payer dropdown, status dropdown, date range
> 3. Table columns: Patient, Provider, Payer, CPT, Status badge, Billed,
>    Created, Age (days). Aging rows highlighted amber.
> 4. Cursor pagination: "Showing 1–20 of 312 claims" with Prev / Next
> 5. Request tracer badge bottom-right after each fetch:
>    "↩ 12ms · req-a3f2b1c4" — timing via performance.now() delta,
>    request ID from X-Request-ID response header
> 6. Auto-refresh every 20s (new claims from generators appear without reload)

---

### 11. Enhanced Claim Detail (1 hr)

**Prompt:**
> Update `frontend/src/pages/ClaimDetail.tsx`:
> 1. Idempotency key on each timeline event: first 8 chars monospace,
>    full value on hover
> 2. SUBMITTING: disabled "Processing…" button, poll every 2s
> 3. CLEARINGHOUSE_REJECTED: red alert box with reason, "Retry Submission →" button
> 4. X-Request-ID shown subtly at bottom of claim card

---

## Phase 5 — Polish + Docs (Monday)

### 12. MIGRATIONS.md

> Create `MIGRATIONS.md` explaining expand-contract zero-downtime strategy.
> Use idempotency_key addition to claim_events as the worked example.
> Show Alembic patterns: add nullable, backfill, NOT VALID constraint,
> VALIDATE CONSTRAINT separately.

### 13. Update README Engineering Decisions

Add: Celery/Redis queue with Beat scheduler, replay architecture and why
(demo compressibility as a design consideration), cursor pagination, analytics
endpoint, Flower observability.

### 14. Run full test suite, fix breaks

---

## Stretch Goals

- **Rules cache in Redis** — PayorRule table into Redis on startup, refreshed by
  Beat task. Zero DB hit on validation hot path. Show cache-hit rate in Flower.
- **Write-off state** — DENIED → WRITTEN_OFF transition with reason.
- **Bulk resubmit** — `POST /claims/bulk-resubmit` enqueues submission tasks for
  a list of claim IDs. Useful in the Exceptions tab.

---

## Loom Narrative (Draft)

"I'm going to kick off the replay now — this compresses 3 days of therapy session
completions and payer EDI events from across the country into about 2 minutes. You
can see the progress banner — Day 1 of 3, claims being created, submitted to the
clearinghouse, adjudicated in batch. While that runs, let me walk you through
what's actually happening.

This is Grow Therapy's internal billing operations platform. Every 15 seconds in
normal operation, session completion events fire as therapists finish appointments —
each one kicks off the claims pipeline automatically. No human touches the happy
path. The queue workers handle the clearinghouse handshake asynchronously, which
means the API returns immediately and the actual round-trip happens in the background.
About 20% of those submissions come back as clearinghouse rejections — EDI validation
errors — and the system routes them to a rejection state for correction.

The remittance processor simulates 835 batch files arriving from payers — Aetna,
Cigna, BCBS, UHC, Humana. Each batch adjudicates a cohort of submitted claims using
payer-specific rates. You can see Aetna running at 35% denial for 90837 — that
pattern is built into the processor and surfaces automatically on the dashboard.

Replay's done — let's look at the results. Dashboard is pulling live aggregations
from the claim event ledger, not the claims table. The aging alert is telling me
there are claims in SUBMITTED past 30 days SLA — let's jump to the worklist.

312 claims. Cursor-based pagination — watch the request badge. 11ms. That cost
is constant regardless of how deep you are in the result set, which offset
pagination can't guarantee.

Filter to the exception queue — 47 denied claims. Click one. Here's the immutable
event ledger — every transition stamped with an idempotency key. If any upstream
system retried this call, it gets the original response back, not a duplicate event.

Open Flower and you're looking at the actual task queue — workers, throughput,
task history. This is the observability layer that an on-call engineer would use
to understand what the system is doing at 2am.

The rules engine, state machine, event ledger, async workers, replay architecture —
these are the components Grow Therapy's billing infrastructure at network scale
actually needs."

---

## Timeline

| Day | Tasks |
|-----|-------|
| Saturday AM | Celery + Redis + Flower setup, historical seed |
| Saturday PM | Core task modules (generators, submission, remittance) + new states + migration |
| Saturday eve | Replay mode + demo endpoints, manual submit wiring, analytics endpoint |
| Sunday AM | Dashboard (replay banner, metrics, charts, auto-refresh) |
| Sunday PM | Worklist (tabs, filters, pagination, request badge, auto-refresh) |
| Sunday eve | Claim detail polish, CLEARINGHOUSE_REJECTED UX |
| Monday | MIGRATIONS.md, README, test suite, end-to-end smoke test |
| Tuesday | Loom recording |
| Wednesday | Application sent |
