"""Configures structlog once per process: JSON in deployed environments, console locally.

Records from the standard library (uvicorn, asgi-correlation-id, SQLAlchemy) are routed
through the same processors, so every line in production is one JSON object. Tracebacks are
rendered without frame locals, because a frame's locals can hold secrets such as the database
password inside asyncpg's connect call (R-104).
"""

import logging
import sys

import structlog
from structlog.tracebacks import ExceptionDictTransformer

from app.core.settings import Settings

STDLIB_LOGGERS_ROUTED_TO_ROOT = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "asgi_correlation_id",
)


def configure_logging(settings: Settings) -> None:
    """Install the structlog chain and route standard-library records through the same renderer."""
    shared_processors = build_shared_processors()
    structlog.configure(
        processors=[*shared_processors, select_renderer(settings)],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    route_stdlib_records(settings, shared_processors)


def build_shared_processors() -> list[structlog.typing.Processor]:
    """Return the processors both structlog and standard-library records pass through."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)),
    ]


def select_renderer(settings: Settings) -> structlog.typing.Processor:
    """Render readable lines in development and JSON everywhere else."""
    if settings.environment == "development":
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


def route_stdlib_records(
    settings: Settings, shared_processors: list[structlog.typing.Processor]
) -> None:
    """Send every standard-library record to stdout through the structlog renderer."""
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            select_renderer(settings),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
    for logger_name in STDLIB_LOGGERS_ROUTED_TO_ROOT:
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers = []
        named_logger.propagate = True
