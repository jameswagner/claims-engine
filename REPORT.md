# Claims Lifecycle Tracker — Project Report

## What This Is

A monorepo for a healthcare claims processing system. The goal is to track the full lifecycle of an insurance claim — from creation through validation, submission, adjudication, payment or denial — with a full audit trail of every status change.

---

## Repository Structure

```
ClaimsProcessing/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── e4384232efa6_initial.py
│   └── app/
│       ├── main.py
│       ├── api/
│       │   └── health.py
│       ├── db/
│       │   └── session.py
│       ├── models/
│       │   ├── enums.py
│       │   ├── claim.py
│       │   └── claim_event.py
│       ├── schemas/       ← empty, Pydantic schemas go here
│       └── rules/         ← empty, business logic goes here
└── frontend/
    ├── Dockerfile
    ├── index.html
    ├── package.json
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        └── vite-env.d.ts
```

---

## Infrastructure — `docker-compose.yml`

Three services:

**db** — `postgres:16-alpine`. Runs with a named volume `pgdata` so data survives container restarts. Has a healthcheck using `pg_isready` that polls every 5 seconds. The `backend` service declares `depends_on: db: condition: service_healthy`, meaning Docker will not start the backend until Postgres passes the healthcheck. Credentials default to `claims/claims/claims` and can be overridden via `.env`.

**backend** — Built from `./backend/Dockerfile`. Port 8000. Mounts `./backend:/app` as a volume so source changes are live without rebuilding. The `DATABASE_URL` in the container uses `db` as the hostname (the Docker service name), not `localhost`.

**frontend** — Built from `./frontend/Dockerfile`. Port 5173. Has two volume mounts: `./frontend:/app` for live source, and `/app/node_modules` as an anonymous volume to prevent the host mount from wiping out the container's installed packages — a common Docker + Node gotcha.

---

## Backend

### `Dockerfile` + `entrypoint.sh`

The image is `python:3.12-slim`. At build time it installs all Python dependencies from `requirements.txt`. At runtime it calls `sh entrypoint.sh`, which does two things in sequence:

```sh
#!/bin/sh
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The `exec` replaces the shell process with uvicorn so uvicorn becomes PID 1 and receives signals (like SIGTERM on `docker stop`) correctly. `set -e` means if the migration fails, the container exits immediately rather than starting a broken server.

### `requirements.txt`

| Package | Version | Purpose |
|---|---|---|
| fastapi | 0.115.12 | Web framework |
| uvicorn[standard] | 0.34.3 | ASGI server |
| sqlalchemy | 2.0.41 | ORM |
| psycopg2-binary | 2.9.10 | PostgreSQL driver |
| python-dotenv | 1.1.0 | `.env` loading |
| alembic | 1.16.1 | Migrations |
| structlog | 24.4.0 | Structured logging |

All versions are pinned. `uvicorn[standard]` includes `websockets` and `httptools` for production-grade performance. `psycopg2-binary` bundles native libs so no C compiler is needed at build time. SQLAlchemy 2.0 is a major revision from 1.x with proper type annotation support via `Mapped`.

### `app/main.py` — Entry Point

`main.py` creates the app, configures logging and middleware, and mounts routers. No routes are defined here directly.

```python
configure_logging()   # reads LOG_LEVEL and ENVIRONMENT env vars

@app.middleware("http")
async def request_logging_middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    # logs request_started, calls handler, logs request_finished with duration_ms
    response.headers["X-Request-ID"] = request_id
    return response
```

`configure_logging()` is called at import time so logging is configured before any route handler runs. The middleware uses `structlog.contextvars` to bind `request_id` for the duration of the request — every log call downstream (validator, state machine) automatically includes it without being passed explicitly.

### `app/db/session.py` — Database Layer

Three exports used throughout the app:

- **`engine`** — the SQLAlchemy connection pool, created once at module load from `DATABASE_URL`
- **`SessionLocal`** — a factory that produces database sessions. `autocommit=False` means you have to explicitly commit; `autoflush=False` means SQLAlchemy won't automatically sync state before queries
- **`Base`** — all SQLAlchemy models inherit from this. It holds `metadata`, which is what Alembic inspects to detect schema changes
- **`get_db()`** — a FastAPI dependency. Routes declare `db: Session = Depends(get_db)` and get a session that is automatically closed when the request finishes, even if it raises an exception

### `app/models/enums.py`

```python
class ClaimStatus(str, enum.Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    DENIED = "DENIED"
```

`ClaimStatus` inherits from both `str` and `enum.Enum`. The `str` base means instances serialize directly to their string value in JSON — no custom serializer needed. Kept in its own file to avoid circular imports between `claim.py` and `claim_event.py`, both of which need it.

### `app/models/claim.py` — The Core Entity

```python
class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    cpt_code: Mapped[str] = mapped_column(String, nullable=False)
    diagnosis_code: Mapped[str] = mapped_column(String, nullable=False)
    insurance_payer: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claimstatus", native_enum=False), nullable=False, default=ClaimStatus.CREATED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    events = relationship("ClaimEvent", back_populates="claim", cascade="all, delete-orphan")
```

Key decisions:

- **UUID primary key** instead of integer — avoids leaking sequential IDs in the API, harder to enumerate records
- **`native_enum=False`** — stores status as a VARCHAR with a check constraint rather than a PostgreSQL native ENUM type. Native enums in Postgres are harder to alter (adding a value requires a DDL statement that can lock the table and is difficult to roll back via Alembic)
- **`cascade="all, delete-orphan"`** — deleting a Claim automatically deletes all its ClaimEvents at the ORM level
- **`server_default=func.now()`** on timestamps — the default is set at the database level, not in Python, so it's accurate even if records are inserted bypassing the ORM

### `app/models/claim_event.py` — The Audit Trail

```python
class ClaimEvent(Base):
    __tablename__ = "claim_events"
    id: Mapped[uuid.UUID] = ...
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ClaimStatus] = ...
    to_status: Mapped[ClaimStatus] = ...
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    triggered_at: Mapped[datetime] = ...
```

Every status change on a claim writes a ClaimEvent row capturing where it came from, where it went, and optionally why. `reason` is nullable because most transitions don't need explanation — denial does. `idempotency_key` stores the client-supplied key so duplicate submissions can be detected and replayed. The `ondelete="CASCADE"` on the foreign key ensures the database enforces deletion even on raw SQL bypassing the ORM.

### Alembic — Migration System

`alembic/env.py` has two key customizations over the default:

```python
from app.db.session import Base
import app.models  # ensures all models are registered with Base.metadata

database_url = os.getenv("DATABASE_URL", "postgresql://claims:claims@localhost:5432/claims")
config.set_main_option("sqlalchemy.url", database_url)
```

Importing `app.models` is critical — Alembic uses `Base.metadata` to detect schema changes, and models only register themselves with `Base.metadata` when their module is imported. Without this import, autogenerate would see an empty schema and generate a migration that drops all your tables.

The generated migration (`e4384232efa6_initial.py`) creates both tables. `claimstatus` is stored as a VARCHAR enum (not a native PG ENUM), so the migration doesn't need to create a type before the table.

---

## Frontend

Vite + React + TypeScript + Tailwind CSS v4. Two pages, full API wiring.

### Structure

```
src/
├── api/claims.ts         # all fetch calls, error parsing
├── types/claim.ts        # TypeScript types mirroring API schemas
├── components/
│   └── StatusBadge.tsx   # color-coded pill for each ClaimStatus
├── pages/
│   ├── ClaimsList.tsx    # card grid + "Create Test Claim" button
│   └── ClaimDetail.tsx   # claim info, advance button, event timeline
├── App.tsx               # BrowserRouter + Routes
├── main.tsx              # React root mount
└── index.css             # @import "tailwindcss"
```

### `src/api/claims.ts`

Single `request<T>()` helper that sets `Content-Type`, checks `res.ok`, and throws a typed `ApiError` on failure. All route functions (`fetchClaims`, `fetchClaim`, `createClaim`, `advanceClaim`) call through it. `parseApiError()` normalizes the two error shapes the backend returns — plain string `detail` vs `{ errors: string[] }` — into a single display string.

### `src/components/StatusBadge.tsx`

A `Record<ClaimStatus, string>` maps each status to Tailwind classes. Full class strings (not dynamic concatenation) so Tailwind's scanner picks them up:

| Status | Color |
|---|---|
| CREATED | Gray |
| VALIDATED | Blue |
| SUBMITTED | Yellow |
| ADJUDICATED | Purple |
| PAID | Green |
| DENIED | Red |

### `src/pages/ClaimsList.tsx`

Fetches all claims on mount. Renders a responsive card grid. "Create Test Claim" posts a hardcoded sample claim (CPT 90837, F32.1, Aetna) and navigates to the detail page. Cards are `<button>` elements for keyboard/accessibility.

### `src/pages/ClaimDetail.tsx`

Fetches claim by ID from `useParams`. Shows claim metadata in a definition list. "Advance Claim" button calls `POST /claims/{id}/advance`, updates local state with the response, and shows inline validation errors from the API. Button is disabled with a message when the claim is in a terminal state (PAID or DENIED). Event timeline renders each `ClaimEvent` as a vertical list with connecting lines and a `StatusBadge` on each transition.

---

## Runtime State

| Service | Status | URL |
|---|---|---|
| PostgreSQL 16 | Running | localhost:5432 |
| FastAPI | Running | http://localhost:8000 |
| React/Vite | Running | http://localhost:5173 |

Tables confirmed in the database:
- `alembic_version` — tracks current migration revision
- `claims` — core entity table
- `claim_events` — audit trail table

---

## Structured Logging

### `app/core/logging.py`

Configures structlog once at startup. Reads `LOG_LEVEL` (default `INFO`) and `ENVIRONMENT` from env vars.

- **Development** (`ENVIRONMENT != "production"`): `ConsoleRenderer` with colored output for human readability.
- **Production**: `JSONRenderer` — one JSON object per log line, compatible with Datadog, CloudWatch, Loki, etc.

Every log line includes: `timestamp` (ISO 8601), `level`, `service: "claims-backend"`, `request_id` (from contextvars).

### `app/middleware` — Request Tracing

The HTTP middleware generates or propagates a `request_id` (UUID4) per request:

1. Checks `X-Request-ID` header first — upstream load balancers and API gateways often set this.
2. Falls back to a freshly generated UUID4.
3. Calls `structlog.contextvars.bind_contextvars(request_id=...)` so every log call for the rest of the request automatically carries it, without needing to pass it through function arguments.
4. Echoes the `request_id` back in the response as `X-Request-ID` so clients can correlate errors with server logs.

### Log Lines in Business Logic

**State machine** — logs on every transition attempt:
- `transition_applied` — claim_id, payer, from_status, to_status, duration_ms
- `transition_rejected` — claim_id, from_status, to_status, reason (one of `invalid_transition`, `validation_failed`, `duplicate_transition`)

**Validator** — logs after every `validate_claim()` call:
- `claim_validated` — payer, cpt_code, is_valid, errors list, duration_ms

---

## Interview Questions

### Docker / Infrastructure

**Q: Why does `depends_on` with a healthcheck matter here?**
Without it, Docker starts the backend container as soon as the Postgres container *starts* — not when Postgres is actually ready to accept connections. The backend would crash on startup trying to connect to a Postgres that's still initializing. The healthcheck (`pg_isready`) makes Docker wait until the database is actually accepting connections.

**Q: Why are there two volume mounts on the frontend container?**
`./frontend:/app` gives the container live access to your source files. But it also overwrites `/app/node_modules` with your (empty) host directory, breaking all imports. The second mount `/app/node_modules` is an anonymous Docker volume that sits on top of the host mount specifically for that directory, preserving the packages installed during `docker build`.

**Q: What does `exec` do in the entrypoint script and why does it matter?**
`exec` replaces the shell process with uvicorn rather than spawning it as a child. Without `exec`, the shell is PID 1 and uvicorn is a child. When Docker sends SIGTERM to stop the container, the shell may not forward it to uvicorn, causing the container to hang until a SIGKILL timeout. With `exec`, uvicorn is PID 1 and receives the signal directly.

### SQLAlchemy / Database

**Q: What's the difference between `server_default` and `default` in SQLAlchemy?**
`default` is applied by Python/SQLAlchemy before the INSERT — it generates the value in application code. `server_default` is a SQL expression sent as part of the column definition (e.g., `DEFAULT now()`) and applied by the database itself. `server_default` is more reliable because it works even on raw SQL inserts that bypass the ORM.

**Q: Why use `native_enum=False` for `ClaimStatus`?**
PostgreSQL native ENUMs are a DDL type — adding a new value requires `ALTER TYPE`. In Alembic, this is awkward to express and can't be cleanly rolled back. `native_enum=False` stores the value as VARCHAR with a check constraint. Adding a new status is then just adding it to the Python enum and running a migration that updates the check constraint, which is straightforward.

**Q: Why is `app.models` imported in `alembic/env.py`?**
SQLAlchemy models register themselves with `Base.metadata` only when their module is imported. Alembic autogenerate works by comparing `Base.metadata` (what your code says the schema should be) against the live database. If the models aren't imported, `metadata` is empty and autogenerate would produce a migration that drops all your tables.

**Q: What is `get_db()` and why is it a generator?**
It's a FastAPI dependency that yields a database session. Being a generator (using `yield`) allows code after the `yield` to run as cleanup after the request finishes — the `finally: db.close()` block runs whether the request succeeded or raised an exception. This guarantees sessions are always returned to the connection pool.

**Q: Why use UUID primary keys instead of integers?**
Integer keys are sequential and guessable — a user who sees `/claims/42` knows `/claims/43` probably exists and can try to access it. UUIDs are not enumerable. They also make it easier to merge data from multiple sources without key collisions, and to generate IDs client-side before hitting the database.

### FastAPI

**Q: Why are routes defined in separate files rather than in `main.py`?**
Separation of concerns and scalability. `main.py` as an entry point that only mounts routers means you can add an entire new feature area (e.g., `app/api/claims.py`) with one line in `main.py`. It also makes testing easier — you can test a router in isolation without spinning up the full application.

**Q: What does `ClaimStatus(str, enum.Enum)` give you over a plain `enum.Enum`?**
The `str` mixin makes each enum member a real string subclass. FastAPI serializes it directly as a JSON string without a custom encoder. It also means you can compare `status == "DENIED"` without having to call `.value`. Without the `str` mixin, FastAPI would serialize it as `{"status": "DENIED"}` in some contexts and plain `"DENIED"` in others depending on how it's accessed.

---

### Project Structure — FastAPI Backend

**Q: What does a well-structured FastAPI project look like and why?**
A mature FastAPI project separates concerns into distinct layers:

```
app/
├── main.py          # app factory only — middleware, router mounts
├── api/             # one file per feature: claims.py, users.py, etc.
├── models/          # SQLAlchemy ORM models (database shape)
├── schemas/         # Pydantic models (API request/response shape)
├── db/              # session factory, Base, get_db dependency
├── rules/           # pure business logic, no framework dependencies
└── dependencies/    # shared FastAPI dependencies (auth, pagination)
```

The key insight is that `models/` and `schemas/` are intentionally separate. Your ORM model is what the database looks like. Your Pydantic schema is what the API looks like. They are rarely identical — you don't want to expose `created_at` on a create request, or expose a password hash on a response. Keeping them separate means you control exactly what enters and exits the API boundary.

**Q: What goes in `schemas/` vs `models/`?**
`models/` contains SQLAlchemy classes that map to database tables — they define columns, relationships, and constraints. `schemas/` contains Pydantic classes that define what the API accepts and returns. For a claim you'd typically have:
- `ClaimCreate` — what the client sends to create one (no `id`, no `status`, no timestamps)
- `ClaimRead` — what the API returns (everything including computed fields)
- `ClaimUpdate` — what the client sends to update one (all fields optional)

FastAPI uses the schema for validation, serialization, and generating the OpenAPI docs at `/docs`.

**Q: What is a FastAPI dependency and when would you use one?**
A dependency is a function declared with `Depends()` that FastAPI calls automatically before your route handler. `get_db()` is a dependency — the route declares it needs a database session and FastAPI provides one. Common uses: database sessions, current authenticated user, pagination parameters, permission checks. Dependencies can depend on other dependencies, forming a tree that FastAPI resolves before calling the handler.

**Q: What's the difference between a router and the main app?**
`APIRouter` is a mini-application that groups related routes. You define routes on it exactly like you would on `app`, but it has no middleware or lifecycle of its own. `app.include_router(claims_router, prefix="/claims", tags=["claims"])` mounts it, automatically prefixing all its routes and grouping them in `/docs`. The main app (`FastAPI()`) is only created once in `main.py`; everything else is a router.

---

### Project Structure — React Frontend

**Q: What does a well-structured React + TypeScript frontend look like?**
A maintainable structure separates concerns by type and by feature:

```
src/
├── main.tsx              # mounts React, wraps with providers
├── App.tsx               # router definition only
├── pages/                # one component per route: ClaimsList, ClaimDetail
├── components/           # shared UI: Button, Badge, StatusPill
├── hooks/                # custom hooks: useClaimsAPI, useClaimStatus
├── api/                  # typed fetch functions for each endpoint
├── types/                # TypeScript interfaces matching API schemas
└── lib/                  # pure utilities: formatDate, formatCurrency
```

`pages/` are route-level components — they own data fetching and layout. `components/` are presentational and reusable — they receive props and render UI. The `api/` layer centralizes all `fetch` calls so if the API URL or auth header changes, it changes in one place.

**Q: What is `vite-env.d.ts` doing?**
It extends the global `ImportMeta` interface to tell TypeScript that `import.meta.env.VITE_API_URL` exists and is a string. Without it, TypeScript would error on any `import.meta.env` access because those are Vite-specific additions not in the standard TypeScript DOM types. Only variables prefixed with `VITE_` are exposed to the browser bundle — other env vars are stripped at build time.

**Q: What is `tsconfig.node.json` for?**
Vite has two runtime contexts: the browser bundle and the Node.js build tooling (`vite.config.ts` runs in Node, not the browser). They need different compiler settings — for example, `vite.config.ts` uses Node module resolution, not the browser bundler resolution. `tsconfig.node.json` applies only to `vite.config.ts`, while `tsconfig.json` applies to `src/`. The `references` field in `tsconfig.json` links them together so `tsc` knows about both.

**Q: Why `react-router-dom` v7 specifically?**
v7 is a full rewrite that merges React Router with Remix's data layer. It ships its own TypeScript types (no `@types/react-router-dom` needed). It introduces loader functions for route-level data fetching, replacing the pattern of fetching inside `useEffect` in a component. For this project it means claims data can load at the route level before the component renders, eliminating loading spinners for the initial page load.

---

### Schema Decisions

**Q: Why does `ClaimEvent` record `from_status` and `to_status` rather than just `to_status`?**
Recording both sides makes the audit log self-contained. You can answer questions like "how many claims went directly from SUBMITTED to DENIED without being ADJUDICATED?" with a single query. If you only stored `to_status`, you'd have to reconstruct the previous state by looking at the prior event, which breaks if events are ever missing or out of order.

**Q: Why is `reason` on `ClaimEvent` rather than on `Claim`?**
`reason` is a property of a specific transition, not of the claim itself. A claim might be denied, then resubmitted, then paid — each transition can have its own reason. If `reason` were on `Claim`, you'd only have the most recent one and would lose the history of why it was denied the first time.

**Q: Why are both `created_at` and `updated_at` on `Claim` but only `triggered_at` on `ClaimEvent`?**
`ClaimEvent` rows are immutable — they're written once when a transition happens and never changed. So `updated_at` doesn't make sense on them. `triggered_at` is the single timestamp of when that specific event occurred. `Claim` has both because the claim itself is mutable — its status, and potentially other fields, can be updated after creation.

**Q: Why use a client-supplied idempotency key instead of a server-computed one?**
The original design used `MD5(claim_id + to_status)` as a server-computed key. This works for a strictly linear pipeline but breaks any workflow where a claim legitimately visits the same state more than once — deny → correct → resubmit → deny again is realistic in behavioral health billing. With a server-computed key, the second DENIED transition would collide with the first and be rejected as a duplicate. A client-supplied key (a UUID the caller generates per *operation*, not per *state*) separates "this is a retry of the same operation" from "this is a new operation that happens to target the same state." On a duplicate key, the server replays the original 200 response rather than returning 409 — the caller can't tell the difference, which is the point. This is the pattern Stripe uses for all payment mutations.

**Q: What's missing from the schema that a production system would need?**
Several things: an `amount` or `billed_amount` field on `Claim` for the dollar value, an `adjudicated_amount` for what the insurer agreed to pay, a `user_id` or `submitted_by` foreign key to track who created the claim, an index on `claims.status` for efficiently querying claims in a given state, and an index on `claim_events.claim_id` for efficiently fetching the event history of a specific claim.

---

### Structured Logging

**Q: Why structlog over the standard library `logging` module?**
The stdlib `logging` module is line-oriented — it produces human-readable strings that are hard to parse programmatically. `structlog` treats log events as dictionaries first, then renders them at the end of a processor chain. In development the chain ends with `ConsoleRenderer` for readability; in production it ends with `JSONRenderer` for machine ingestion. You get the same call site (`log.info("claim_validated", payer=..., is_valid=...)`) regardless of environment — the output format is purely a configuration concern.

**Q: How does `request_id` propagate to the validator and state machine without being passed as a parameter?**
Via `structlog.contextvars`. The middleware calls `structlog.contextvars.bind_contextvars(request_id=...)` at the start of every request. `merge_contextvars` is the first processor in the structlog chain, so it merges whatever is in the context into every log event dict before rendering. This is Python's `contextvars` module under the hood — context is per-async-task, so concurrent requests don't bleed into each other.

**Q: Why check for `X-Request-ID` before generating one?**
In a real deployment, the load balancer or API gateway upstream of the backend usually generates a request ID and passes it forward. Propagating that ID means a single request can be traced through the load balancer logs, the backend logs, and any downstream service logs using the same ID. Generating a new ID only when one isn't provided means the system works standalone (local dev, direct curl) without breaking tracing in the full stack.

**Q: What's `cache_logger_on_first_use` and when would you turn it off?**
It's a structlog optimization that freezes the processor chain on the first use of a given logger. Subsequent calls skip the chain-building step. The tradeoff is that if you call `structlog.configure()` after the first log call, the new config doesn't apply to cached loggers. For production this is always the right choice — configure once at startup, then cache. You'd turn it off in tests that need to reconfigure structlog between test cases.

### Rules Engine

**Q: What is a database-driven rules engine and why use one over hardcoded logic?**
A DB-driven rules engine stores validation rules as rows in a table rather than `if` statements in code. Adding a new payer exclusion (e.g., "Cigna doesn't cover 90847") is an `INSERT`, not a code change and deployment. The `PayorRule` table has three rule types: `ALLOWED_CPT` (CPT must be in this set), `EXCLUDED_CPT` (this CPT is blocked for this payer), and `REQUIRE_DIAGNOSIS_PREFIX` (diagnosis must start with this string). A `payer` of `"*"` means the rule applies to all payers.

**Q: How does the validator query rules efficiently?**
It issues a single query filtering on `payer = claim.payer OR payer = "*"`. This pulls back both payer-specific and wildcard rules in one round trip. An index on `payor_rules.payer` makes this fast. The results are then partitioned in Python by `rule_type` to apply each category of check.

**Q: Why does `EXCLUDED_CPT` use the rule's `description` field as the error message?**
The description is written by whoever inserts the rule and carries human-readable context — "CPT 90853 (group therapy) is not covered by Medicare" is more useful to a user than a generic "code excluded." By surfacing the description directly, the validator avoids having to know anything about why a rule exists.

**Q: How are the tests structured without a live database?**
Using `unittest.mock.Mock` to fake the SQLAlchemy session. `make_db(*rules)` returns a Mock whose `.scalars(...).all()` returns whatever list of `PayorRule` instances you pass in. This means tests run in milliseconds, have no external dependencies, and can precisely control which rules the validator sees — impossible to do reliably with a real DB.

**Q: Why normalize input fields at the start of `validate_claim` rather than at the API boundary?**
The validator is the authoritative place for claim correctness — normalizing there means the rules always operate on clean data regardless of how the validator is called (HTTP, internal, tests). A leading space in a CPT code like `" 90837"` would silently fail an `ALLOWED_CPT` check without normalization, because the string comparison is exact. Normalizing all five fields with `.strip()` at the top of the function eliminates this class of silent failure. The API layer handles structural validation (Pydantic schema); the validator handles semantic/business-rule validation.

**Q: What's the seed script for and how is it idempotent?**
`seed_rules.py` populates the baseline ruleset on first run. It checks `db.query(PayorRule).count() == 0` before inserting, so running it twice doesn't duplicate rows. It's invoked manually via `docker exec ... python -m app.db.seed_rules`. A production system might replace this with a proper data migration in Alembic so seeding is automatic and versioned.

---

### Next Steps

**Q: What would you build next on the backend?**
The immediate next layer is:
1. **Pydantic schemas** in `app/schemas/` — `ClaimCreate`, `ClaimRead`, `ClaimEventRead`
2. **CRUD routes** in `app/api/claims.py` — `POST /claims`, `GET /claims`, `GET /claims/{id}`, `GET /claims/{id}/events`
3. **Status transition endpoint** — `POST /claims/{id}/transition` with validation that the requested transition is legal (e.g., you can't go from PAID back to CREATED)
4. **Transition rules** in `app/rules/` — a pure function that takes `(current_status, requested_status)` and returns whether it's allowed

**Q: What would you build next on the frontend?**
1. **API client** in `src/api/` — typed `fetchClaims()`, `fetchClaim(id)`, `createClaim()` functions using `VITE_API_URL`
2. **Route structure** in `App.tsx` — `/claims` list view, `/claims/:id` detail view
3. **ClaimsList page** — table of claims with status badges
4. **ClaimDetail page** — claim fields plus timeline of ClaimEvents

**Q: What would a status transition rule system look like?**
A state machine — a dictionary mapping each status to the set of statuses it's allowed to transition to:

```python
ALLOWED_TRANSITIONS = {
    ClaimStatus.CREATED:     {ClaimStatus.VALIDATED, ClaimStatus.DENIED},
    ClaimStatus.VALIDATED:   {ClaimStatus.SUBMITTED, ClaimStatus.DENIED},
    ClaimStatus.SUBMITTED:   {ClaimStatus.ADJUDICATED, ClaimStatus.DENIED},
    ClaimStatus.ADJUDICATED: {ClaimStatus.PAID, ClaimStatus.DENIED},
    ClaimStatus.PAID:        set(),
    ClaimStatus.DENIED:      {ClaimStatus.SUBMITTED},  # allow resubmission
}
```

A route calls `is_transition_allowed(current, requested)`, which looks up the set and returns a boolean. The `rules/` directory is the right home for this — it's pure logic with no database or framework dependencies, which makes it trivially testable.
