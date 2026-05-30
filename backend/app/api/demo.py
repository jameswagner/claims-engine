import json
import os

import redis
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tasks.replay import REPLAY_KEY, run_billing_replay

router = APIRouter(prefix="/demo", tags=["demo"])
log = structlog.get_logger()

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class ReplayStatus(BaseModel):
    running: bool
    day: int = 0
    total_days: int = 0
    claims_created: int = 0
    events_processed: int = 0


@router.post("/replay", status_code=202)
def start_replay():
    raw = _redis.get(REPLAY_KEY)
    if raw:
        status = json.loads(raw)
        if status.get("running"):
            raise HTTPException(status_code=409, detail="Replay already running")

    run_billing_replay.delay()
    log.info("replay_triggered")
    return {"message": "Replay started"}


@router.get("/replay/status", response_model=ReplayStatus)
def get_replay_status():
    raw = _redis.get(REPLAY_KEY)
    if not raw:
        return ReplayStatus(running=False)
    return ReplayStatus(**json.loads(raw))
