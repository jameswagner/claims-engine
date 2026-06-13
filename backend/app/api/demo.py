import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tasks.fast_forward import (
    advance_one_day,
    get_cursor,
    get_ff_status,
    reset_cursor,
)

router = APIRouter(prefix="/demo", tags=["demo"])
log = structlog.get_logger()


class FastForwardStatus(BaseModel):
    running: bool
    day: int = 0
    total_days: int = 3
    claims_created: int = 0


class FastForwardResult(BaseModel):
    day_index: int
    date_written: str | None
    complete: bool


@router.post("/fast-forward", response_model=FastForwardResult, status_code=202)
def step_fast_forward():
    """Advance the demo by one day. Call up to 3 times to reveal the Aetna anomaly."""
    cursor = get_cursor()
    if cursor >= 3:
        raise HTTPException(status_code=409, detail="Fast-forward complete — reset first")

    result = advance_one_day()
    log.info("fast_forward_step", **result)
    return FastForwardResult(**result)


@router.get("/fast-forward/status", response_model=FastForwardStatus)
def get_fast_forward_status():
    status = get_ff_status()
    if not status:
        return FastForwardStatus(running=False)
    return FastForwardStatus(**status)


@router.post("/fast-forward/reset", status_code=200)
def reset_fast_forward():
    """Reset the demo cursor so fast-forward can be replayed from scratch."""
    reset_cursor()
    log.info("fast_forward_reset")
    return {"message": "Fast-forward reset"}
