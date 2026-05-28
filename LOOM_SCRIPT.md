# LOOM SCRIPT — Claims Lifecycle Tracker
_Update this after each build prompt._

---

## COLD OPEN (15 seconds)
> "Most backend portfolio projects are search APIs or todo apps.
> This is a healthcare insurance claims lifecycle tracker —
> the kind of system that determines whether a therapist
> actually gets paid. Let me show you how it works."

**STATUS: Ready to record.**

---

## SEGMENT 1 — THE PROBLEM (30 seconds)
> "Insurance claims are stateful, rule-heavy financial
> transactions. A claim moves through states — created,
> validated, submitted, adjudicated, paid or denied.
> Every transition needs to be auditable, every rule
> needs to be inspectable, and nothing can ever be
> submitted twice."

**Show:** Repo structure in VS Code, `docker compose up` spinning up all three services.

**STATUS: Ready to record.** Repo structure, models, and Docker Compose are all in place.

---

## SEGMENT 2 — THE RULES ENGINE + STATE MACHINE (90 seconds)
> "Before a claim can move from created to validated it
> runs through a rules engine. The rules aren't hardcoded
> — they live in Postgres as data. Adding a new payor
> rule is an INSERT, not a deployment."

**Show:**
- `payor_rules` table in DB — `SELECT payer, rule_type, cpt_code, value FROM payor_rules;`
- POST a valid claim → advances to VALIDATED
- POST a Medicare claim with CPT 90853 → rejected, error message returned

> "At scale you'd cache this ruleset in Redis on startup
> to avoid a DB hit on every validation. And for
> operational toggles — like temporarily suspending
> Medicare submissions — you'd layer in something like
> AWS AppConfig so ops teams can flip a switch without
> touching the database."

**STATUS: Ready to record.**
- ✅ `payor_rules` table seeded — show the DB query
- ✅ Rules engine + state machine fully wired to HTTP endpoints
- ✅ 69 passing unit tests (33 validator + 36 state machine)
- ✅ `POST /claims` + `POST /claims/{id}/advance` — demo via UI or curl

---

## SEGMENT 3 — IDEMPOTENCY (45 seconds)
> "Double submissions are a real problem in claims —
> network retries, user double-clicks, upstream system
> bugs. The frontend generates a UUID for every advance
> call and sends it as an Idempotency-Key header.
> The backend stores it on the ClaimEvent and detects
> duplicates on that key — not on a server-computed hash.
> That distinction matters: a server hash of claim_id
> plus status would silently block a second denial on
> the same claim. The client-supplied key separates
> retry from re-submission. This is the Stripe pattern."

**Show:**
- `idempotency_key` column in `claim_events`
- Show the unique index on `claim_events.idempotency_key` in the DB
- Hit "Advance Claim" twice rapidly — second call gets the same 200 response (replay, not 409)

**STATUS: Ready to record.** `idempotency_key` stored on every `ClaimEvent`, unique constraint enforced at DB level, duplicate key replays 200 response.

---

## SEGMENT 4 — THE AUDIT TRAIL + FINANCIALS (45 seconds)
> "Every state transition writes an immutable event —
> not just an updated_at timestamp but a full record
> of where it came from, where it went, and why.
> This is the foundation of any financial system."

**Show:**
- Event timeline on the claim detail page — CREATED→VALIDATED→SUBMITTED→ADJUDICATED→PAID
- Financial section on the claim card: Billed $200, Allowed $150, Patient Resp. $20, Paid $130
- Thomas Chen (DENIED) — adjustment_reason "CO-97: procedure bundled" visible on the card

**STATUS: Ready to record.** Financial fields set at adjudication, `paid_amount` auto-computed on PAID, all visible in the UI.

---

## SEGMENT 5 — THE FRONTEND (30 seconds)
> "The UI is deliberately simple — color coded status
> badges, a timeline of events, one button to advance
> the claim. The interesting engineering is in the
> backend. But a hiring manager should be able to
> click through it without a terminal."

**Show:**
- Claims list at `http://localhost:5173` — cards with color-coded status badges
- Hit "Create Test Claim" — lands on the detail page at CREATED
- Hit "Advance Claim" four times — watch status badges flip through the pipeline
- Show the event timeline filling in with each transition

**STATUS: Ready to record.** React + TypeScript + Tailwind. Two pages, full API wiring, live status updates.

---

## SEGMENT 5b — REMIT PROCESSING (30 seconds)
> "Once a claim is adjudicated, the payer sends back
> an Explanation of Benefits — a remit. Each remit
> contains adjustment codes: CO-97 means the procedure
> was bundled, PR-1 is patient deductible, OA-23 is
> a coordination of benefits adjustment. We store the
> raw remit, parse each code against a library that
> maps it to a human-readable action — 'bill patient',
> 'resubmit unbundled' — and update the claim's
> financial fields from the remit totals."

**Show:**
- `POST /claims/{id}/remit` via curl or Swagger UI — submit a remit with CO-45 and PR-1 codes
- `GET /claims/{id}/remit` — show the response with codes, descriptions, action_required

**STATUS: Ready to record.** Remit model, RemitCode model, code library, and API endpoints all in place.

---

## SEGMENT 6 — OBSERVABILITY + SCALE (45 seconds)
> "Before I talk about what I'd add at scale —
> the observability is already wired. Every request
> gets a UUID request_id. Every state transition
> logs claim_id, payer, from_status, to_status,
> duration in milliseconds. In development it's
> pretty console output; flip ENVIRONMENT=production
> and it's JSON — one line per event, ready for
> Datadog or CloudWatch."

**Show:**
- `docker compose logs backend` while clicking "Advance Claim" in the UI — show the structured log lines with request_id threading through validation and transition
- README engineering decisions section

> "At Grow's scale — 10 million sessions, 22,000
> clinicians — I'd layer in async claim submission
> via a queue so the backend acknowledges immediately
> and processes in the background, OpenTelemetry
> spans to stitch together the full trace across
> services, and a denial classification service
> that turns CO-97 and PR-1 remit codes into
> structured action items for billing teams."

**STATUS: Ready to record.** Structured logging live — `request_id`, `transition_applied`, `claim_validated` log events visible in Docker logs.

---

## COLD CLOSE (10 seconds)
> "Code is on GitHub, live demo at [URL].
> Happy to walk through any of it."

**STATUS: Ready once repo is public and demo is deployed.**

---

## TOTAL TARGET: ~4 minutes

---

## Build Progress Tracker

| Segment | Blocker |
|---|---|
| Cold open | — |
| Segment 1 — Problem | — |
| Segment 2 — Rules engine | Claims API endpoints (`POST /claims`, `POST /claims/{id}/transition`) |
| Segment 3 — Idempotency | Idempotency key on submission + duplicate detection |
| Segment 4 — Audit trail | Claims API + `GET /claims/{id}/events` |
| Segment 5 — Frontend | Claims list page, detail page, status transition UI |
| Segment 6 — Scale | — |
| Cold close | Public GitHub + deployed demo |
