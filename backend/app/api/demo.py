import json
import os

import redis
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tasks.fast_forward import FAST_FORWARD_KEY, run_fast_forward

router = APIRouter(prefix="/demo", tags=["demo"])
log = structlog.get_logger()

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class FastForwardStatus(BaseModel):
    running: bool
    day: int = 0
    total_days: int = 0
    claims_created: int = 0


@router.post("/fast-forward", status_code=202)
def start_fast_forward():
    raw = _redis.get(FAST_FORWARD_KEY)
    if raw:
        status = json.loads(raw)
        if status.get("running"):
            raise HTTPException(status_code=409, detail="Fast-forward already running")

    run_fast_forward.delay()
    log.info("fast_forward_triggered")
    return {"message": "Fast-forward started"}


@router.get("/fast-forward/status", response_model=FastForwardStatus)
def get_fast_forward_status():
    raw = _redis.get(FAST_FORWARD_KEY)
    if not raw:
        return FastForwardStatus(running=False)
    return FastForwardStatus(**json.loads(raw))
