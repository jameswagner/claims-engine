# LOOM SCRIPT — Grow Therapy Billing Ops Platform
_Update this after each build prompt._

**Target runtime: ~5 minutes**
**Framing: Grow Therapy's internal billing operations platform, not a solo tracker**

---

## BEFORE YOU HIT RECORD

**Option A — Live AWS demo (recommended for showing cloud architecture)**

1. Open the CloudFront URL (production dashboard)
2. Confirm dashboard shows 8-day flat baseline — all payer denial rates below 20% threshold
3. If fast-forward has already been advanced: `POST /demo/fast-forward/reset` first
4. If data looks stale or reset is needed: invoke the seed Lambda via AWS Console or CLI
5. Open tabs: CloudFront dashboard, API Gateway URL + `/docs`

**Option B — Local Docker demo (for Flower/worker observability segment)**

1. `docker compose up` — all 7 services healthy (db, redis, backend, worker, beat, flower, frontend)
2. Run seed: `docker exec -w /app claimsprocessing-backend-1 python seed.py`
3. If rerunning: `TRUNCATE claims CASCADE;` first, then seed again; also `POST /demo/fast-forward/reset`
4. Open tabs: `localhost:5173` (dashboard), `localhost:5555` (Flower), `localhost:8000/docs` (API)
5. Dashboard should show 8-day denial rate trend chart — all payer lines flat, all below the 20% alert threshold.

---

## COLD OPEN (20 seconds)

> "This is Grow Therapy's internal billing operations platform. 6,400 claims,
> 8 days of history. Every payer denial rate is flat — normal operating baseline.
> I've paused the dashboard 3 days in the past. I'm going to advance it one day
> at a time and show you an anomaly emerging in real time."

**Action:** Point at the trend chart — flat lines, all well below the orange 20% threshold.
Point at the header: "Showing data through [date]".

---

## SEGMENT 1 — THE WORKER ARCHITECTURE (60 seconds)

> "The backend is FastAPI, deployed as a Lambda container behind API Gateway. But the
> interesting part is the async worker layer. Two independent workers replace what would
> traditionally be a Celery + Redis setup.
>
> A clearinghouse submission worker — a separate Lambda triggered directly by SQS.
> When a claim moves to SUBMITTING, the API enqueues a message; the SQS trigger fires
> the Lambda with batchSize=1, handles the EDI round-trip — 80% go to SUBMITTED, 20%
> get clearinghouse rejected — and the message is deleted on success. Three DLQ retries
> on failure.
>
> A remittance batch processor — another Lambda on an EventBridge Scheduler, firing
> every minute. It finds SUBMITTED claims and adjudicates them with payer-specific
> denial rates.
>
> In a real Grow Therapy system these workers consume events from session completion
> webhooks from the EHR, 835 file drops from the clearinghouse, and payer API polling.
> The queue decouples receiving an event from processing it — the API acknowledges
> immediately, the actual work happens in the background. Workers scale to zero between
> invocations."

**Show:** AWS Console — Lambda functions list, or locally: Flower at `localhost:5555`
- If local: connected workers, active tasks, task history firing
- If AWS: Lambda invocation metrics, SQS queue depth

> "The entire infrastructure is defined in CDK TypeScript across five stacks —
> network, data, API, workers, frontend. Cross-stack references are TypeScript object
> properties, not string lookups. IAM policies are scoped to least privilege per Lambda."

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

## SEGMENT 4 — THE AETNA ANOMALY (60 seconds)

> "The denial rate trend chart pulls from the event ledger — every ADJUDICATED to
> PAID or DENIED event, grouped by day and payer. Right now: 8 flat days, all payers
> 8 to 15%, nothing crosses the 20% alert threshold."

**Show:** Trend chart — flat lines, Aetna indistinguishable from others.

> "Let me advance one day."

**Action:** Click "⏩ Advance one day" — button shows "Writing day 1…" for ~5 seconds, then chart updates.

> "Day t-minus-2 just landed. Aetna has crossed the 20% alert threshold —
> every other payer is unchanged."

**Show:** Aetna line clearly above the orange dashed 20% line. Other lines flat.

> "One more."

**Action:** Click again → chart updates.

> "Two days in a row, Aetna climbing. This is what a real billing anomaly looks like —
> it doesn't appear all at once, it builds."

**Action:** Click once more → full spike.

> "Three days of escalating denials. Flip to the CPT breakdown — 90837 is the outlier,
> 90834 and 90832 are flat. That's Aetna's real-world denial rate on CPT 90837 in
> behavioral health — a 45% denial rate on the most common therapy session code.
> The dashboard tells you exactly which payer, which procedure code, and when it started.
> A billing manager seeing this would open a denial review on Aetna 90837 that afternoon."

**Show:** CPT denial rate bar chart — 90837 clearly elevated.

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
> one line per event, ready for CloudWatch or Datadog."

**Show:** Lambda CloudWatch logs (production) or `docker compose logs worker` (local)

> "The infrastructure is live on AWS — Lambda, RDS, SQS, EventBridge, CloudFront,
> DynamoDB, all defined in CDK TypeScript. What I'd add next: a GitHub Actions CI/CD
> pipeline so every merge deploys automatically. OpenTelemetry tracing via X-Ray to
> stitch together the full invocation chain. RDS Proxy to cap connection count at scale —
> right now each Lambda cold start opens a fresh connection, which is fine at low
> concurrency but doesn't scale. And a denial classification service that turns
> CO-97 and PR-1 codes into structured action items with priority routing for billing teams."

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
