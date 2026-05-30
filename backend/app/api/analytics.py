import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus

router = APIRouter(prefix="/analytics", tags=["analytics"])
log = structlog.get_logger()


class PayerDenialRate(BaseModel):
    payer: str
    total: int
    denied: int
    denial_rate_pct: float


class PayerAdjDays(BaseModel):
    payer: str
    avg_days: float


class AgingSummary(BaseModel):
    over_14_days: int
    over_30_days: int


class ResubmissionRate(BaseModel):
    resubmitted: int
    eventually_paid: int
    rate_pct: float


class Throughput24h(BaseModel):
    created: int
    submitted: int
    paid: int
    denied: int


class ClaimsAnalytics(BaseModel):
    claims_by_status: dict[str, int]
    denial_rate_by_payer: list[PayerDenialRate]
    avg_days_to_adjudication_by_payer: list[PayerAdjDays]
    aging_summary: AgingSummary
    resubmission_success_rate: ResubmissionRate
    throughput_last_24h: Throughput24h


@router.get("/claims", response_model=ClaimsAnalytics)
def get_claims_analytics(db: Session = Depends(get_db)) -> Any:
    start = time.perf_counter()

    # --- Claims by status ---
    rows = db.execute(
        select(Claim.status, func.count().label("n"))
        .group_by(Claim.status)
    ).all()
    claims_by_status = {r.status.value: r.n for r in rows}

    # --- Denial rate by payer ---
    # Count ADJUDICATED→DENIED and ADJUDICATED→PAID events per payer
    adj_events = db.execute(
        select(
            Claim.insurance_payer,
            ClaimEvent.to_status,
            func.count().label("n"),
        )
        .join(Claim, Claim.id == ClaimEvent.claim_id)
        .where(ClaimEvent.from_status == ClaimStatus.ADJUDICATED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.PAID, ClaimStatus.DENIED]))
        .group_by(Claim.insurance_payer, ClaimEvent.to_status)
    ).all()

    payer_totals: dict[str, dict[str, int]] = {}
    for row in adj_events:
        p = row.insurance_payer
        if p not in payer_totals:
            payer_totals[p] = {"total": 0, "denied": 0}
        payer_totals[p]["total"] += row.n
        if row.to_status == ClaimStatus.DENIED:
            payer_totals[p]["denied"] += row.n

    denial_rate_by_payer = [
        PayerDenialRate(
            payer=p,
            total=v["total"],
            denied=v["denied"],
            denial_rate_pct=round(v["denied"] / v["total"] * 100, 1) if v["total"] else 0.0,
        )
        for p, v in sorted(payer_totals.items())
    ]

    # --- Avg days to adjudication by payer ---
    # Join SUBMITTED events with ADJUDICATED events for the same claim
    e_sub = ClaimEvent.__table__.alias("e_sub")
    e_adj = ClaimEvent.__table__.alias("e_adj")

    adj_days_rows = db.execute(
        select(
            Claim.insurance_payer,
            func.avg(
                func.extract("epoch", e_adj.c.triggered_at - e_sub.c.triggered_at) / 86400
            ).label("avg_days"),
        )
        .select_from(e_sub)
        .join(e_adj, e_sub.c.claim_id == e_adj.c.claim_id)
        .join(Claim, Claim.id == e_sub.c.claim_id)
        .where(e_sub.c.to_status == ClaimStatus.SUBMITTED.value)
        .where(e_adj.c.to_status == ClaimStatus.ADJUDICATED.value)
        .group_by(Claim.insurance_payer)
    ).all()

    avg_days_by_payer = [
        PayerAdjDays(payer=r.insurance_payer, avg_days=round(float(r.avg_days or 0), 1))
        for r in sorted(adj_days_rows, key=lambda r: r.insurance_payer)
    ]

    # --- Aging summary ---
    now = datetime.now(timezone.utc)
    threshold_14 = now - timedelta(days=14)
    threshold_30 = now - timedelta(days=30)

    # Claims currently SUBMITTED with their most recent SUBMITTED event
    aging_sub = (
        select(
            ClaimEvent.claim_id,
            func.max(ClaimEvent.triggered_at).label("submitted_at"),
        )
        .where(ClaimEvent.to_status == ClaimStatus.SUBMITTED)
        .group_by(ClaimEvent.claim_id)
        .subquery()
    )

    over_14 = db.scalar(
        select(func.count())
        .select_from(aging_sub)
        .join(Claim, Claim.id == aging_sub.c.claim_id)
        .where(Claim.status == ClaimStatus.SUBMITTED)
        .where(aging_sub.c.submitted_at < threshold_14)
    ) or 0

    over_30 = db.scalar(
        select(func.count())
        .select_from(aging_sub)
        .join(Claim, Claim.id == aging_sub.c.claim_id)
        .where(Claim.status == ClaimStatus.SUBMITTED)
        .where(aging_sub.c.submitted_at < threshold_30)
    ) or 0

    aging_summary = AgingSummary(over_14_days=over_14, over_30_days=over_30)

    # --- Resubmission success rate ---
    # Claims that have a DENIED→SUBMITTED or DENIED→SUBMITTING event
    resubmitted = db.scalar(
        select(func.count(func.distinct(ClaimEvent.claim_id)))
        .where(ClaimEvent.from_status == ClaimStatus.DENIED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.SUBMITTED, ClaimStatus.SUBMITTING]))
    ) or 0

    eventually_paid = db.scalar(
        select(func.count(func.distinct(ClaimEvent.claim_id)))
        .where(ClaimEvent.from_status == ClaimStatus.DENIED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.SUBMITTED, ClaimStatus.SUBMITTING]))
        .where(
            ClaimEvent.claim_id.in_(
                select(Claim.id).where(Claim.status == ClaimStatus.PAID)
            )
        )
    ) or 0

    resubmission_rate = ResubmissionRate(
        resubmitted=resubmitted,
        eventually_paid=eventually_paid,
        rate_pct=round(eventually_paid / resubmitted * 100, 1) if resubmitted else 0.0,
    )

    # --- Throughput last 24h ---
    since = now - timedelta(hours=24)

    def _count_events(to_status: ClaimStatus) -> int:
        return db.scalar(
            select(func.count())
            .where(ClaimEvent.to_status == to_status)
            .where(ClaimEvent.triggered_at >= since)
        ) or 0

    throughput = Throughput24h(
        created=_count_events(ClaimStatus.VALIDATED),
        submitted=_count_events(ClaimStatus.SUBMITTED),
        paid=_count_events(ClaimStatus.PAID),
        denied=_count_events(ClaimStatus.DENIED),
    )

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info("analytics_computed", duration_ms=duration_ms)

    return ClaimsAnalytics(
        claims_by_status=claims_by_status,
        denial_rate_by_payer=denial_rate_by_payer,
        avg_days_to_adjudication_by_payer=avg_days_by_payer,
        aging_summary=aging_summary,
        resubmission_success_rate=resubmission_rate,
        throughput_last_24h=throughput,
    )
