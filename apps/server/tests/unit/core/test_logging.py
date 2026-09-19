"""Unit tests for the structlog configuration in app/core/logging.py (B-1, B-2).

Two review defects are pinned here. First, an exception logged with `exc_info` must never carry
frame locals into the output, because the asyncpg connect frames hold the database password
(defect 1, B-1 readiness). Second, a record logged through the standard library, as uvicorn does,
must pass through the same structlog chain and reach stdout as one JSON line in deployed
environments (defect 5, B-2 structured logs).

The database URL for the secret test is assembled at run time from parts, so no
credential-shaped literal appears in the source.
"""

import json
import logging
import logging.config
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import structlog
from arq.logs import default_log_config
from fastapi import FastAPI

DSN_SCHEME = "postgresql+asyncpg"
DSN_USER = "probe_user"
DSN_UNREACHABLE_HOST_AND_DATABASE = "127.0.0.1:1/none"
PASSWORD_MARKER = "pw-marker-" + uuid.uuid4().hex
STDLIB_PROBE_MESSAGE = "probe-message"
ARQ_PROBE_MESSAGE = "arq-probe-message"


def build_database_url_with_password(password: str) -> str:
    """Join a DSN for a closed local port whose password is the given marker."""
    return "".join(
        [DSN_SCHEME, "://", DSN_USER, ":", password, "@", DSN_UNREACHABLE_HOST_AND_DATABASE]
    )


def parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Return every line of text that parses as a JSON object."""
    parsed_objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            parsed_objects.append(candidate)
    return parsed_objects


@pytest.fixture
def restored_stdlib_logging() -> Iterator[None]:
    """Snapshot the root, uvicorn, and arq loggers and restore them, so no test's config leaks."""
    logger_names = ["", "uvicorn", "uvicorn.error", "uvicorn.access", "arq", "arq.worker"]
    snapshots = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in logger_names
    }
    yield
    for name, (handlers, level, propagate) in snapshots.items():
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers[:] = handlers
        stdlib_logger.setLevel(level)
        stdlib_logger.propagate = propagate


@pytest.mark.parametrize(
    "database_url",
    [build_database_url_with_password(PASSWORD_MARKER)],
    ids=["password-marker-dsn"],
)
async def test_defect1_b1_readiness_failure_log_never_contains_the_database_password(
    api_client: httpx.AsyncClient,
    captured_log_events: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Defect 1, B-1: the readiness_db_failed log line renders no frame locals, so no password."""
    captured_log_events.clear()

    response = await api_client.get("/health/ready")
    captured_output = capsys.readouterr()

    assert response.status_code == 503
    readiness_events = [
        event for event in captured_log_events if event.get("event") == "readiness_db_failed"
    ]
    assert readiness_events, "the readiness failure was not logged"
    leaking_event_names = [
        str(event.get("event"))
        for event in captured_log_events
        if PASSWORD_MARKER in json.dumps(event, default=str)
    ]
    assert leaking_event_names == [], "these log events carry the DB password"
    is_password_on_stdout = PASSWORD_MARKER in captured_output.out
    is_password_on_stderr = PASSWORD_MARKER in captured_output.err
    assert not is_password_on_stdout, "stdout carries the DB password"
    assert not is_password_on_stderr, "stderr carries the DB password"


def test_defect5_b2_stdlib_log_record_is_rendered_as_one_json_line_in_production(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_stdlib_logging: None,
) -> None:
    """Defect 5, B-2: a uvicorn stdlib record reaches stdout as one JSON line with level, time."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.core.settings import get_settings  # noqa: PLC0415 (read after the env is patched)
    from app.main import create_app  # noqa: PLC0415 (read after the env is patched)

    get_settings.cache_clear()
    try:
        production_app: FastAPI = create_app()
        assert production_app is not None
        capsys.readouterr()

        logging.getLogger("uvicorn.error").warning(STDLIB_PROBE_MESSAGE)

        captured_output = capsys.readouterr()
    finally:
        get_settings.cache_clear()

    probe_lines = [
        line_object
        for line_object in parse_json_lines(captured_output.out)
        if STDLIB_PROBE_MESSAGE in (line_object.get("event"), line_object.get("message"))
    ]
    assert len(probe_lines) == 1, (
        f"expected one JSON line on stdout; stdout={captured_output.out!r} "
        f"stderr={captured_output.err!r}"
    )
    probe_line = probe_lines[0]
    assert str(probe_line.get("level", "")).lower() == "warning"
    assert probe_line.get("timestamp"), "the JSON line has no timestamp"


def test_review1_arq_log_record_is_rendered_once_as_json_after_arq_installs_its_handler(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_stdlib_logging: None,
) -> None:
    """Review item 1: arq's own plain-text handler is removed, so its records go through structlog.

    arq's CLI runs logging.config.dictConfig(default_log_config(...)) before the worker's startup
    hook, which leaves a plain-text StreamHandler on the `arq` logger. configure_logging() must
    strip that handler and let `arq` and its children propagate to root, so an `arq.worker` record
    reaches stdout exactly once, as JSON, and nothing reaches stderr.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.core.logging import configure_logging  # noqa: PLC0415 (read after the env is patched)
    from app.core.settings import get_settings  # noqa: PLC0415 (read after the env is patched)

    original_structlog_config = structlog.get_config()
    get_settings.cache_clear()
    try:
        logging.config.dictConfig(default_log_config(verbose=False))
        assert logging.getLogger("arq").handlers, "arq's dictConfig should install a handler"

        configure_logging(get_settings())
        capsys.readouterr()
        logging.getLogger("arq.worker").info(ARQ_PROBE_MESSAGE)
        captured_output = capsys.readouterr()
    finally:
        get_settings.cache_clear()
        structlog.configure(**original_structlog_config)

    arq_logger = logging.getLogger("arq")
    arq_worker_logger = logging.getLogger("arq.worker")
    assert arq_logger.handlers == [], "the arq logger keeps a handler of its own"
    assert arq_logger.propagate is True
    assert arq_worker_logger.handlers == []
    assert arq_worker_logger.propagate is True
    probe_lines = [
        line_object
        for line_object in parse_json_lines(captured_output.out)
        if ARQ_PROBE_MESSAGE in (line_object.get("event"), line_object.get("message"))
    ]
    assert len(probe_lines) == 1, (
        f"expected one JSON line on stdout; stdout={captured_output.out!r} "
        f"stderr={captured_output.err!r}"
    )
    assert captured_output.out.count(ARQ_PROBE_MESSAGE) == 1, "the arq record is rendered twice"
    assert ARQ_PROBE_MESSAGE not in captured_output.err, "arq's plain-text handler still writes"
    assert str(probe_lines[0].get("level", "")).lower() == "info"
