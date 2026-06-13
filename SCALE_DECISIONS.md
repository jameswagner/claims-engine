# Scale Decisions

Architectural choices made for the current portfolio/demo scale, with explicit rationale and the trigger for revisiting each one. Referenced in interviews against Grow Therapy's published numbers: 22,000 clinicians, 1.4M clients, 10M sessions projected in 2026.

---

## Connection Pooling — Direct vs RDS Proxy

**Decision:** Direct Lambda → RDS connections. No RDS Proxy.

**Rationale:** At demo scale (< 10 concurrent Lambda invocations), direct connections are fine. `db.t3.micro` caps at ~60–80 total connections. The Lambda concurrency ceiling for a portfolio workload is well below that.

**At production scale:** A session-completion burst at Grow Therapy's volume could spin up 200+ concurrent Lambda invocations simultaneously. Each holds an open DB connection for the duration of its execution. RDS Proxy pools these at the proxy layer so 200 Lambdas share ~10–20 actual DB connections, preventing exhaustion without any application code change.

**Upgrade trigger:** Sustained Lambda concurrency > 20, or any `too many connections` errors in CloudWatch.

**Cost:** RDS Proxy is $0.015/vCPU-hour. Not free-tier eligible.

---

## Message Broker — SQS vs Redis/ElastiCache

**Decision:** SQS for the submission queue. No Redis in the AWS architecture.

**Rationale:** Redis on AWS requires either ElastiCache (~$11–13/month, not free tier) or a persistent compute host. SQS is always-free at demo scale (1M requests/month free), fully managed, and handles at-least-once delivery and retries natively. The SQS + DLQ pattern gives better failure isolation than Redis/Celery for a serverless architecture — a crashed Lambda doesn't lose the message.

**What's lost vs Redis/Celery:** Celery Beat (periodic tasks) and Flower monitoring. EventBridge Scheduler replaces Beat; CloudWatch + X-Ray replaces Flower.

**Upgrade trigger:** If task routing complexity grows (priority queues, rate limiting per payer, task chaining) Celery becomes worth the Redis cost. At current scope SQS covers it cleanly.

---

## DB-Driven Rules — In-Memory Cache vs DB Query Per Validation

**Decision:** DB query on every `validate_claim` call. No application-level cache.

**Rationale:** At 10M sessions/year with realistic claim batching, peak validation load is ~300–500 claims/hour — well within what a single RDS query handles. The `payor_rules` table has ~7 rows. Query cost is negligible.

**At production scale:** Rules change infrequently (quarterly payer contract updates). A module-level cache in Lambda is the zero-cost win — warm instances serve rules from memory, cold starts re-fetch. A Lambda env-var bump forces recycling of all warm instances, which is a 30-second CI step and serves as a cache invalidation mechanism.

**Cache staleness risk:** A rule change (e.g. payer drops coverage for a CPT code) would be served incorrectly by warm Lambdas until they recycle. For a billing system this can mean claims incorrectly accepted or denied. Cache TTL or explicit invalidation (env-var bump or Lambda function version update) must be part of the rule-change runbook.

**Upgrade trigger:** > 100 rules per payer, or validation latency becomes measurable in p99 analytics.

---

## Single-AZ RDS vs Multi-AZ

**Decision:** Single-AZ RDS.

**Rationale:** Multi-AZ doubles the RDS instance cost and is not free-tier eligible. For a portfolio project with no SLA, a ~20-minute failover window is acceptable. `us-west-1` only has two AZs anyway (`us-west-1a`, `us-west-1c`).

**Upgrade trigger:** Any production use. Multi-AZ is the first infra change before real data lives here.

---

## Secrets Manager vs SSM Parameter Store

**Decision:** Secrets Manager for the DB credentials (via CDK's `rds.DatabaseSecret`). SSM Parameter Store for the API URL (baked into the frontend at build time).

**Rationale:** CDK's `rds.DatabaseSecret` construct provisions a Secrets Manager secret automatically and rotates it on a schedule if configured — there's no equivalent CDK construct for SSM. The API Lambda reads `DB_SECRET_ARN` at cold start via `secretsmanager:GetSecretValue`. The API URL lives in SSM because CDK's `ssm.StringParameter.valueFromLookup()` resolves it at synth time, making it available to the frontend build without a circular stack dependency. SSM Standard tier is always free; Secrets Manager costs $0.40/secret/month — negligible for one secret.

**At production scale:** Add automatic rotation to the `DatabaseSecret` construct — CDK wires a rotation Lambda automatically. Move other credentials (payer API keys, clearinghouse tokens) into Secrets Manager with per-secret rotation policies.

**Upgrade trigger:** Any production use where DB credentials need automated rotation or a full audit trail for secret access.

---

## Cursor Pagination vs Offset Pagination

**Decision:** Cursor-based pagination encoding `(created_at, id)` as base64 JSON.

**Rationale:** At Grow Therapy's scale — 22,000 clinicians each submitting multiple claims — the claims table grows deep quickly. Offset pagination (`LIMIT n OFFSET k`) requires the DB to scan and discard all prior rows on every page request. Cost scales linearly with page depth. Cursor pagination uses `WHERE (created_at, id) < (cursor_created_at, cursor_id)` with a matching index — cost is constant regardless of depth.

**Tradeoff:** Cursors don't support random page access ("jump to page 47") or stable total counts. For a worklist UI (always starts at the top, scrolls forward) this is the right tradeoff.

---

## Pessimistic Locking vs Optimistic Locking

**Decision:** `SELECT ... FOR UPDATE` on all write-path claim fetches.

**Rationale:** Claims go through multi-step transitions (validate → submit → adjudicate → pay/deny) where the business cost of a lost update is high — double-paying a claim or recording the wrong final status has real financial consequences. Pessimistic locking blocks concurrent writers at the DB level, guaranteeing only one transition executes at a time per claim. Optimistic locking (version counter + retry) would allow two writers to proceed concurrently, detect the conflict on commit, and retry — acceptable for low-contention writes but adds retry logic and latency under contention.

**At Grow Therapy's scale:** With 22,000 clinicians and a remittance batch worker processing claims in parallel, contention on individual claim rows is low but real. Pessimistic locking's cost (held row lock during network I/O) is acceptable for claim transitions which are short operations.

---

## Immutable Event Ledger vs `updated_at` on Claims

**Decision:** Every state transition writes a `ClaimEvent` row. The `claims` table `status` column is updated but never the event history.

**Rationale:** `updated_at` on the claim tells you the current state and when it last changed — nothing else. The event ledger tells you the full lifecycle: every transition, who triggered it, when, with what idempotency key, and why. Analytics that matter for billing ops (avg days to adjudication, denial rate trends by day, aging SLA) require the event timestamps, not just the current status. The ledger is also the foundation for audit compliance — insurers can request a full transition history for any claim.

**Cost:** One extra write per transition. Worth it unconditionally for a billing system.

---

## Lambda Cold Starts vs Provisioned Concurrency

**Decision:** Standard Lambda with no provisioned concurrency.

**Rationale:** Cold start for this FastAPI + Mangum Lambda is ~500ms after idle. For a demo and internal ops tool this is acceptable — billing ops staff aren't running sub-100ms SLA workflows. Provisioned concurrency keeps instances warm at a fixed cost regardless of traffic.

**Upgrade trigger:** If the API is customer-facing or p99 latency SLAs are introduced. First step would be provisioned concurrency on the API Lambda only (not workers, which are async).
