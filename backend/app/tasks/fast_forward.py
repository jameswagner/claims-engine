import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import structlog
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus

log = structlog.get_logger()

_TABLE = os.getenv("FAST_FORWARD_TABLE")
_FF_PK = "ff_state"

PROVIDERS = [
    "Dr. Sarah Chen", "Dr. Marcus Williams", "Dr. Aisha Patel",
    "Dr. James Rodriguez", "Dr. Emily Nakamura", "Dr. David Okonkwo",
]
PAYERS = ["Aetna", "Cigna", "BCBS", "UnitedHealthcare", "Humana"]
CPT_CODES = ["90837", "90834", "90832"]
DIAGNOSES = ["F32.1", "F41.1", "F43.1", "F33.0", "F40.10", "F31.81", "F32.0", "F33.1"]
PATIENT_NAMES = [
    "Maria Santos", "David Kim", "Rebecca Johnson", "Thomas Chen",
    "Jennifer Walsh", "Michael Torres", "Angela Davis", "Robert Nguyen",
    "Christine Park", "James Mitchell", "Sandra Lee", "William Brown",
]

BILLED_RANGE = {"90837": (200, 280), "90834": (160, 220), "90832": (130, 175)}

DENIAL_REASONS = [
    "CO-97: procedure bundled, not separately payable",
    "CO-45: charge exceeds contracted fee schedule",
    "CO-50: service not deemed medically necessary",
    "PR-1: deductible amount not yet met",
    "CO-4: procedure inconsistent with modifier",
]

_DAY_RATES: list[dict[tuple[str | None, str | None], float]] = [
    {
        ("Aetna", "90837"): 0.22, ("Aetna", None): 0.14,
        ("BCBS", None): 0.08, ("UnitedHealthcare", None): 0.12,
        ("Cigna", None): 0.11, ("Humana", None): 0.12, (None, None): 0.12,
    },
    {
        ("Aetna", "90837"): 0.36, ("Aetna", None): 0.22,
        ("BCBS", None): 0.08, ("UnitedHealthcare", None): 0.12,
        ("Cigna", None): 0.11, ("Humana", None): 0.12, (None, None): 0.12,
    },
    {
        ("Aetna", "90837"): 0.45, ("Aetna", None): 0.28,
        ("BCBS", None): 0.08, ("UnitedHealthcare", None): 0.12,
        ("Cigna", None): 0.11, ("Humana", None): 0.12, (None, None): 0.12,
    },
]

_DAY_OFFSETS = [2, 1, 0]
CLAIMS_PER_FF_DAY_RANGE = (680, 920)

# In-memory fallback for local dev (no DynamoDB)
_local_cursor: int = 0
_local_ff_status: dict | None = None


def _ddb():
    return boto3.client("dynamodb", region_name=os.getenv("AWS_REGION", "us-west-1"))


def _read_state() -> tuple[int, dict | None]:
    if not _TABLE:
        return _local_cursor, _local_ff_status
    try:
        resp = _ddb().get_item(TableName=_TABLE, Key={"pk": {"S": _FF_PK}})
        item = resp.get("Item")
        if not item:
            return 0, None
        cursor = int(item["cursor"]["N"])
        status = None
        if "status_day" in item:
            status = {
                "running": False,
                "day": int(item["status_day"]["N"]),
                "total_days": 3,
                "claims_created": int(item["status_claims"]["N"]),
            }
        return cursor, status
    except Exception:
        return 0, None


def _write_state(cursor: int, claims_created: int) -> None:
    if not _TABLE:
        return
    _ddb().put_item(
        TableName=_TABLE,
        Item={
            "pk": {"S": _FF_PK},
            "cursor": {"N": str(cursor)},
            "status_day": {"N": str(cursor)},
            "status_claims": {"N": str(claims_created)},
        },
    )


def _delete_state() -> None:
    if not _TABLE:
        return
    try:
        _ddb().delete_item(TableName=_TABLE, Key={"pk": {"S": _FF_PK}})
    except Exception:
        pass


def get_cursor() -> int:
    cursor, _ = _read_state()
    return cursor


def get_ff_status() -> dict | None:
    _, status = _read_state()
    return status


def get_demo_now() -> datetime:
    days_back = max(0, len(_DAY_OFFSETS) - get_cursor())
    return datetime.now(timezone.utc) - timedelta(days=days_back)


def reset_cursor() -> None:
    global _local_cursor, _local_ff_status
    _local_cursor = 0
    _local_ff_status = None
    _delete_state()
    ff_cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db = SessionLocal()
    try:
        db.execute(delete(Claim).where(Claim.updated_at >= ff_cutoff))
        db.commit()
    finally:
        db.close()


def _denial_rate(payer: str, cpt_code: str, rates: dict) -> float:
    return (
        rates.get((payer, cpt_code))
        or rates.get((payer, None))
        or rates[(None, None)]
    )


def _adj_days(payer: str) -> int:
    if payer == "UnitedHealthcare":
        return random.randint(35, 55)
    return random.randint(15, 25)


def _event(claim_id, from_status, to_status, triggered_at, reason=None):
    return ClaimEvent(
        id=uuid.uuid4(),
        claim_id=claim_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        idempotency_key=str(uuid.uuid4()),
        triggered_at=triggered_at,
    )


def advance_one_day() -> dict:
    global _local_cursor, _local_ff_status
    cursor, _ = _read_state()

    if cursor >= len(_DAY_OFFSETS):
        return {"day_index": cursor, "date_written": None, "complete": True}

    now = datetime.now(timezone.utc)
    day_date = (now - timedelta(days=_DAY_OFFSETS[cursor])).date()
    rates = _DAY_RATES[cursor]

    log.info("ff_day_started", cursor=cursor, date=str(day_date))

    db = SessionLocal()
    written = 0
    try:
        for i in range(random.randint(*CLAIMS_PER_FF_DAY_RANGE)):
            payer = random.choice(PAYERS)
            cpt_code = random.choice(CPT_CODES)

            resolved_at = datetime(
                day_date.year, day_date.month, day_date.day,
                random.randint(6, 22), random.randint(0, 59), random.randint(0, 59),
                tzinfo=timezone.utc,
            )
            adjudicated_at = resolved_at - timedelta(hours=random.randint(1, 4))
            submitted_at = adjudicated_at - timedelta(days=_adj_days(payer), hours=random.randint(0, 12))
            validated_at = submitted_at - timedelta(days=random.randint(1, 2), hours=random.randint(1, 6))
            created_at = validated_at - timedelta(days=random.randint(1, 2), hours=random.randint(1, 6))

            lo, hi = BILLED_RANGE[cpt_code]
            billed = Decimal(str(round(random.uniform(lo, hi), 2))).quantize(Decimal("0.01"))
            is_denied = random.random() < _denial_rate(payer, cpt_code, rates)
            denial_reason = random.choice(DENIAL_REASONS) if is_denied else None

            if is_denied:
                allowed, patient_resp, paid_amt = Decimal("0.00"), None, None
                final_status = ClaimStatus.DENIED
            else:
                allowed = (billed * Decimal(str(round(random.uniform(0.82, 0.95), 4)))).quantize(Decimal("0.01"))
                patient_resp = (allowed * Decimal("0.20")).quantize(Decimal("0.01"))
                paid_amt = allowed - patient_resp
                final_status = ClaimStatus.PAID

            claim = Claim(
                id=uuid.uuid4(),
                patient_name=random.choice(PATIENT_NAMES),
                provider_name=random.choice(PROVIDERS),
                cpt_code=cpt_code,
                diagnosis_code=random.choice(DIAGNOSES),
                insurance_payer=payer,
                billed_amount=billed,
                status=final_status,
                allowed_amount=allowed,
                patient_responsibility=patient_resp,
                paid_amount=paid_amt,
                adjustment_reason=denial_reason if is_denied else None,
                created_at=created_at,
                updated_at=resolved_at,
            )
            db.add(claim)
            db.flush()

            events = [
                _event(claim.id, ClaimStatus.CREATED,    ClaimStatus.VALIDATED,   validated_at),
                _event(claim.id, ClaimStatus.VALIDATED,  ClaimStatus.SUBMITTED,   submitted_at),
                _event(claim.id, ClaimStatus.SUBMITTED,  ClaimStatus.ADJUDICATED, adjudicated_at),
            ]
            if is_denied:
                events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.DENIED, resolved_at, reason=denial_reason))
            else:
                events.append(_event(claim.id, ClaimStatus.ADJUDICATED, ClaimStatus.PAID, resolved_at))
            db.add_all(events)

            if (i + 1) % 100 == 0:
                db.commit()
            written += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    new_cursor = cursor + 1
    _local_cursor = new_cursor
    _local_ff_status = {"running": False, "day": new_cursor, "total_days": 3, "claims_created": written}
    _write_state(new_cursor, written)

    complete = new_cursor >= len(_DAY_OFFSETS)
    log.info("ff_day_complete", cursor=cursor, date=str(day_date), written=written, complete=complete)
    return {"day_index": new_cursor, "date_written": str(day_date), "complete": complete}
