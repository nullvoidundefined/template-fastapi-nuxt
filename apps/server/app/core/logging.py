"""Configures structlog once per process: JSON in deployed environments, console locally.

Records from the standard library (uvicorn, asgi-correlation-id, arq, SQLAlchemy) are routed
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
    "arq",
)


def configure_logging(settings: Settings) -> None:
    """Install the structlog chain and route standard-library records through the same renderer."""
    shared_processors = build_shared_processors(settings)
    structlog.configure(
        processors=[*shared_processors, select_renderer(settings)],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    route_stdlib_records(settings, shared_processors)


def build_shared_processors(settings: Settings) -> list[structlog.typing.Processor]:
    """Return the processors both structlog and standard-library records pass through.

    `ExceptionRenderer` turns `exc_info` into a list of frame dictionaries, which is what the JSON
    renderer needs and what `ConsoleRenderer` cannot accept: handed a list where it expects a
    rendered string, it raises `TypeError` and takes the whole log call with it, so a handler that
    logs an exception in development would answer an empty 500 instead of its response. Console
    output therefore keeps `exc_info` intact and lets `ConsoleRenderer` format the traceback
    itself, which also shows no frame locals and so keeps R-104.
    """
    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if settings.environment != "development":
        processors.append(
            structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False))
        )
    return processors


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
