import logging
import os

import structlog

SERVICE_NAME = "claims-backend"


def _add_service(_logger, _method, event_dict):
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def configure_logging() -> None:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    is_dev = os.getenv("ENVIRONMENT", "development") != "production"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_service,
        structlog.processors.StackInfoRenderer(),
    ]

    if is_dev:
        processors = shared_processors + [structlog.dev.ConsoleRenderer()]
    else:
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer(to="message"),
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Suppress uvicorn's built-in access log — the request_logging_middleware
    # already logs every request through structlog, avoiding duplicate entries.
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.access").handlers = []
