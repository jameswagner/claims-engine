import time
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text, cast, Date
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.claim import Claim
from app.models.claim_event import ClaimEvent
from app.models.enums import ClaimStatus
from app.tasks.fast_forward import get_demo_now

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


class CptDenialRate(BaseModel):
    cpt_code: str
    total: int
    denied: int
    denial_rate_pct: float


class DenialRateDailyPoint(BaseModel):
    date: str
    payer: str
    total: int
    denied: int
    denial_rate_pct: float


class PosDenialRate(BaseModel):
    payer: str
    place_of_service: str
    total: int
    denied: int
    denial_rate_pct: float


class ClaimsAnalytics(BaseModel):
    claims_by_status: dict[str, int]
    denial_rate_by_payer: list[PayerDenialRate]
    denial_rate_by_cpt: list[CptDenialRate]
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

    # --- Denial rate by CPT code ---
    cpt_events = db.execute(
        select(
            Claim.cpt_code,
            ClaimEvent.to_status,
            func.count().label("n"),
        )
        .join(Claim, Claim.id == ClaimEvent.claim_id)
        .where(ClaimEvent.from_status == ClaimStatus.ADJUDICATED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.PAID, ClaimStatus.DENIED]))
        .group_by(Claim.cpt_code, ClaimEvent.to_status)
    ).all()

    cpt_totals: dict[str, dict[str, int]] = {}
    for row in cpt_events:
        c = row.cpt_code
        if c not in cpt_totals:
            cpt_totals[c] = {"total": 0, "denied": 0}
        cpt_totals[c]["total"] += row.n
        if row.to_status == ClaimStatus.DENIED:
            cpt_totals[c]["denied"] += row.n

    denial_rate_by_cpt = [
        CptDenialRate(
            cpt_code=c,
            total=v["total"],
            denied=v["denied"],
            denial_rate_pct=round(v["denied"] / v["total"] * 100, 1) if v["total"] else 0.0,
        )
        for c, v in sorted(cpt_totals.items())
    ]

    # --- Avg days to adjudication by payer ---
    # Scoped to the current demo day so the number reflects today's batch, not the
    # all-time average (which is locked by the deterministic seed and never moves).
    e_sub = ClaimEvent.__table__.alias("e_sub")
    e_adj = ClaimEvent.__table__.alias("e_adj")
    demo_day_start = get_demo_now().replace(hour=0, minute=0, second=0, microsecond=0)

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
        .where(e_adj.c.triggered_at >= demo_day_start)
        .group_by(Claim.insurance_payer)
    ).all()

    avg_days_by_payer = [
        PayerAdjDays(payer=r.insurance_payer, avg_days=round(float(r.avg_days or 0), 1))
        for r in sorted(adj_days_rows, key=lambda r: r.insurance_payer)
    ]

    # --- Aging summary ---
    now = get_demo_now()
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
    # Use start of the current demo day so the window = "today" not a rolling 24h that spans two batch days.
    since = get_demo_now().replace(hour=0, minute=0, second=0, microsecond=0)

    def _count_events(to_status: ClaimStatus) -> int:
        return db.scalar(
            select(func.count())
            .where(ClaimEvent.to_status == to_status)
            .where(ClaimEvent.triggered_at >= since)
        ) or 0

    resolved_today = db.scalar(
        select(func.count(func.distinct(ClaimEvent.claim_id)))
        .where(ClaimEvent.to_status.in_([ClaimStatus.PAID, ClaimStatus.DENIED]))
        .where(ClaimEvent.triggered_at >= since)
    ) or 0

    throughput = Throughput24h(
        created=resolved_today,
        submitted=_count_events(ClaimStatus.SUBMITTED),
        paid=_count_events(ClaimStatus.PAID),
        denied=_count_events(ClaimStatus.DENIED),
    )

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info("analytics_computed", duration_ms=duration_ms)

    return ClaimsAnalytics(
        claims_by_status=claims_by_status,
        denial_rate_by_payer=denial_rate_by_payer,
        denial_rate_by_cpt=denial_rate_by_cpt,
        avg_days_to_adjudication_by_payer=avg_days_by_payer,
        aging_summary=aging_summary,
        resubmission_success_rate=resubmission_rate,
        throughput_last_24h=throughput,
    )


@router.get("/denial-rate-timeseries", response_model=list[DenialRateDailyPoint])
def get_denial_rate_timeseries(db: Session = Depends(get_db)) -> Any:
    since = get_demo_now() - timedelta(days=14)

    date_expr = func.date_trunc("day", ClaimEvent.triggered_at)

    rows = db.execute(
        select(
            date_expr.label("event_day"),
            Claim.insurance_payer,
            ClaimEvent.to_status,
            func.count().label("n"),
        )
        .join(Claim, Claim.id == ClaimEvent.claim_id)
        .where(ClaimEvent.from_status == ClaimStatus.ADJUDICATED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.PAID, ClaimStatus.DENIED]))
        .where(ClaimEvent.triggered_at >= since)
        .group_by(date_expr, Claim.insurance_payer, ClaimEvent.to_status)
        .order_by(date_expr, Claim.insurance_payer)
    ).all()

    points: dict[tuple[str, str], dict] = {}
    for row in rows:
        date_str = row.event_day.strftime("%Y-%m-%d")
        key = (date_str, row.insurance_payer)
        if key not in points:
            points[key] = {"total": 0, "denied": 0}
        points[key]["total"] += row.n
        if row.to_status == ClaimStatus.DENIED:
            points[key]["denied"] += row.n

    return [
        DenialRateDailyPoint(
            date=k[0],
            payer=k[1],
            total=v["total"],
            denied=v["denied"],
            denial_rate_pct=round(v["denied"] / v["total"] * 100, 1) if v["total"] else 0.0,
        )
        for k, v in sorted(points.items())
    ]


@router.get("/denial-rate-by-pos", response_model=list[PosDenialRate])
def get_denial_rate_by_pos(db: Session = Depends(get_db)) -> Any:
    rows = db.execute(
        select(
            Claim.insurance_payer,
            Claim.place_of_service,
            ClaimEvent.to_status,
            func.count().label("n"),
        )
        .join(Claim, Claim.id == ClaimEvent.claim_id)
        .where(ClaimEvent.from_status == ClaimStatus.ADJUDICATED)
        .where(ClaimEvent.to_status.in_([ClaimStatus.PAID, ClaimStatus.DENIED]))
        .where(Claim.place_of_service.isnot(None))
        .group_by(Claim.insurance_payer, Claim.place_of_service, ClaimEvent.to_status)
        .order_by(Claim.insurance_payer, Claim.place_of_service)
    ).all()

    buckets: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.insurance_payer, row.place_of_service)
        if key not in buckets:
            buckets[key] = {"total": 0, "denied": 0}
        buckets[key]["total"] += row.n
        if row.to_status == ClaimStatus.DENIED:
            buckets[key]["denied"] += row.n

    return [
        PosDenialRate(
            payer=k[0],
            place_of_service=k[1],
            total=v["total"],
            denied=v["denied"],
            denial_rate_pct=round(v["denied"] / v["total"] * 100, 1) if v["total"] else 0.0,
        )
        for k, v in sorted(buckets.items())
    ]
