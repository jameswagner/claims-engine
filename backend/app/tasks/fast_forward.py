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
from app.tasks.submission import process_submission

log = structlog.get_logger()

FAST_FORWARD_KEY = "demo:fast_forward:status"

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _set_progress(day: int, total_days: int, claims_created: int) -> None:
    _redis.set(
        FAST_FORWARD_KEY,
        json.dumps({
            "running": True,
            "day": day,
            "total_days": total_days,
            "claims_created": claims_created,
        }),
        ex=600,
    )


def _set_done(claims_created: int) -> None:
    _redis.set(
        FAST_FORWARD_KEY,
        json.dumps({
            "running": False,
            "day": 0,
            "total_days": 0,
            "claims_created": claims_created,
        }),
        ex=3600,
    )


@celery.task(name="app.tasks.fast_forward.run_fast_forward")
def run_fast_forward(days: int = 3, compress_seconds: int = 120) -> dict:
    """
    Compress `days` days of claim submissions into `compress_seconds` real seconds.
    Creates claims and drops them into the submission queue. Workers handle the rest.
    """
    day_seconds = compress_seconds / days
    target_per_day = 400

    total_created = 0

    log.info("fast_forward_started", days=days, compress_seconds=compress_seconds)
    _set_progress(1, days, 0)

    for day in range(1, days + 1):
        day_start = time.monotonic()
        day_end = day_start + day_seconds
        day_created = 0

        _set_progress(day, days, total_created)

        while time.monotonic() < day_end and day_created < target_per_day:
            burst = random.randint(5, 12)
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

                submission_pairs = []
                for cid_str in new_ids:
                    claim = db.scalar(
                        select(Claim)
                        .where(Claim.id == uuid.UUID(cid_str))
                        .with_for_update()
                    )
                    if claim and claim.status == ClaimStatus.VALIDATED:
                        submitting_key = str(uuid.uuid4())
                        submitted_key = str(uuid.uuid4())
                        transition(claim, ClaimStatus.SUBMITTING, db, idempotency_key=submitting_key)
                        submission_pairs.append((cid_str, submitted_key))

                db.commit()
                total_created += len(new_ids)

                for cid_str, sub_key in submission_pairs:
                    process_submission.delay(cid_str, sub_key)

            except Exception as exc:
                db.rollback()
                log.error("fast_forward_burst_failed", day=day, error=str(exc))
            finally:
                db.close()

            _set_progress(day, days, total_created)
            time.sleep(random.uniform(0.2, 0.5))

        log.info("fast_forward_day_done", day=day, day_created=day_created)

    _set_done(total_created)
    log.info("fast_forward_complete", total_created=total_created)
    return {"claims_created": total_created}
