"""Configures structlog once per process: JSON in deployed environments, console locally."""

import logging

import structlog

from app.core.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Install the processor chain, merging per-request context before the renderer."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            select_renderer(settings),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )


def select_renderer(settings: Settings) -> structlog.typing.Processor:
    """Render readable lines in development and JSON everywhere else."""
    if settings.environment == "development":
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()
