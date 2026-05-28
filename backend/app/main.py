import os
import time
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.claims import router as claims_router
from app.api.health import router as health_router
from app.api.remits import router as remits_router
from app.core.logging import configure_logging

configure_logging()

log = structlog.get_logger()

app = FastAPI(title="Claims Lifecycle Tracker")

_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    log.info("request_started", method=request.method, path=request.url.path)

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info(
        "request_finished",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(health_router)
app.include_router(claims_router)
app.include_router(remits_router)
