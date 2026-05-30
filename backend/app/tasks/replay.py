import json
import os
import random
import time
import uuid

import redis
import structlog
from sqlalchemy import select

from app.celery_app import celery
from app.claims.state_machine import transition
from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.enums import ClaimStatus
from app.tasks.generators import _create_one_claim
from app.tasks.remittance import process_remittance_batch
from app.tasks.submission import process_submission

log = structlog.get_logger()

REPLAY_KEY = "demo:replay:status"

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _set_progress(day: int, total_days: int, claims_created: int, events_processed: int) -> None:
    _redis.set(
        REPLAY_KEY,
        json.dumps({
            "running": True,
            "day": day,
            "total_days": total_days,
            "claims_created": claims_created,
            "events_processed": events_processed,
        }),
        ex=600,  # expire after 10 minutes if something goes wrong
    )


def _set_done(claims_created: int, events_processed: int) -> None:
    _redis.set(
        REPLAY_KEY,
        json.dumps({
            "running": False,
            "day": 0,
            "total_days": 0,
            "claims_created": claims_created,
            "events_processed": events_processed,
        }),
        ex=3600,
    )


@celery.task(name="app.tasks.replay.run_billing_replay")
def run_billing_replay(days: int = 3, compress_seconds: int = 120) -> dict:
    """
    Compress `days` days of billing activity into `compress_seconds` real seconds.
    Fires session completion bursts, clearinghouse submissions, and remittance batches
    at realistic ratios. Tracks progress in Redis for the frontend banner.
    """
    day_seconds = compress_seconds / days
    # Target ~50 claims per day, arrived in bursts of 3-8
    target_per_day = 50
    remittance_interval = 8  # seconds between remittance runs

    total_created = 0
    total_events = 0

    log.info("replay_started", days=days, compress_seconds=compress_seconds)
    _set_progress(1, days, 0, 0)

    for day in range(1, days + 1):
        day_start = time.monotonic()
        day_end = day_start + day_seconds
        day_created = 0
        next_remittance = day_start + remittance_interval

        _set_progress(day, days, total_created, total_events)

        while time.monotonic() < day_end and day_created < target_per_day:
            # --- Session completion burst ---
            burst = random.randint(3, 8)
            db = SessionLocal()
            try:
                new_ids = []
                for _ in range(burst):
                    if day_created >= target_per_day:
                        break
                    cid = _create_one_claim(db)
                    if cid:
                        new_ids.append(cid)
                        day_created += 1

                # Transition each to SUBMITTING before enqueueing
                submission_pairs = []
                for cid_str in new_ids:
                    claim = db.scalar(
                        select(Claim)
                        .where(Claim.id == uuid.UUID(cid_str))
                        .with_for_update()
                    )
                    if claim and claim.status == ClaimStatus.VALIDATED:
                        sub_key = str(uuid.uuid4())
                        transition(claim, ClaimStatus.SUBMITTING, db, idempotency_key=sub_key)
                        submission_pairs.append((cid_str, sub_key))

                db.commit()
                total_created += len(new_ids)
                # Each claim: CREATED→VALIDATED + VALIDATED→SUBMITTING = 2 events
                total_events += len(new_ids) * 2

                for cid_str, sub_key in submission_pairs:
                    process_submission.delay(cid_str, sub_key)

            except Exception as exc:
                db.rollback()
                log.error("replay_burst_failed", day=day, error=str(exc))
            finally:
                db.close()

            _set_progress(day, days, total_created, total_events)

            # --- Remittance run (if interval elapsed) ---
            if time.monotonic() >= next_remittance:
                result = process_remittance_batch(limit=15)
                resolved = result.get("paid", 0) + result.get("denied", 0)
                total_events += resolved * 2  # ADJUDICATED + PAID/DENIED per claim
                next_remittance = time.monotonic() + remittance_interval
                _set_progress(day, days, total_created, total_events)

            time.sleep(random.uniform(1.5, 2.5))

        # Final remittance sweep at end of each day
        result = process_remittance_batch(limit=25)
        resolved = result.get("paid", 0) + result.get("denied", 0)
        total_events += resolved * 2
        _set_progress(day, days, total_created, total_events)

        log.info("replay_day_done", day=day, day_created=day_created, total_created=total_created)

    _set_done(total_created, total_events)
    log.info("replay_complete", total_created=total_created, total_events=total_events)
    return {"claims_created": total_created, "events_processed": total_events}
