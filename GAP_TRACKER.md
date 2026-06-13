# Gap Tracker

This file tracks concrete implementation gaps discovered during review and "vibe coding" that required explicit human catch-up.

## 1. Initial claim creation is not idempotent
- Location: `backend/app/api/claims.py` → `create_claim()`
- Problem: `POST /claims` does not accept or use `Idempotency-Key`.
- Effect: network retry after a timeout can create duplicate claims.
- Why it was missed: idempotency was only applied to lifecycle transitions, not initial object creation.
- Fix direction: add an idempotency key to create, or require a stable request-level identifier for claim creation.

## 2. Multi-step transition side effects are not replay-safe
- Location: `backend/app/api/claims.py` → `adjudicate_claim()` and `pay_claim()`
- Problem: the route performs transition and then applies financial mutations after `_transition()` returns.
- Effect: a duplicate transition replay can leave the transaction in an inconsistent state and may cause a bad commit/500.
- Why it was missed: the transition layer returns a simple boolean replay signal, but the route still carries out a second logical phase.
- Fix direction: make the state machine layer return an explicit replay-safe result, then only apply side effects on a fresh transition.

## 3. No audit event for initial creation
- Location: `backend/app/api/claims.py` + `backend/app/claims/state_machine.py`
- Problem: `ClaimEvent` ledger is only written for state transitions, not for `CREATED`.
- Effect: the event timeline is incomplete for full lifecycle auditing.
- Why it was missed: the transition system was built around lifecycle moves, while initial creation was treated as plain CRUD.
- Fix direction: optionally create a `CREATED` event on `POST /claims` or move create into the transition/audit model.

## 4. DuplicateTransitionError handling is fragile
- Location: `backend/app/api/claims.py` → `_transition()` and `backend/app/claims/state_machine.py` → `transition()`
- Problem: duplicate transition detection is implemented with an exception that may cross transaction boundaries.
- Effect: replay semantics are fragile, and error handling is mixed with DB transaction state.
- Why it was missed: the existing code implicitly assumed `DuplicateTransitionError` was safe to catch and continue.
- Fix direction: centralize duplicate detection in the state machine as a returned result and avoid using exceptions for normal replay behavior.

## 5. Inconsistent idempotency scope
- Location: backend API routes
- Problem: some write paths use idempotency, others do not.
- Effect: partial protection gives false confidence.
- Why it was missed: the concept was implemented only where it was immediately needed for retries, not universally.
- Fix direction: define a consistent policy for write operations and apply it uniformly across create/transition/retry paths.

## Notes
This tracker is intentionally focused on gaps that were not obvious until review. It is not an exhaustive design doc, but a “things humans had to catch” list.
