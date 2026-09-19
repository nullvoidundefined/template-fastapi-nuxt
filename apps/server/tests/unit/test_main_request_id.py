"""B-2 unit tests for request IDs as the app factory wires them.

Covers the response header (a valid inbound X-Request-Id echoed, an invalid or missing one
replaced by a new UUID, on every response including rejections) and the structlog binding (every
log line emitted during a request carries that request's ID, and no ID outlives its request).
A log-probe route is mounted on the app by the test itself, so the log assertions do not depend
on any route the implementation defines.
"""

import asyncio
import uuid
from typing import Any

import httpx
import pytest
import structlog
from fastapi import FastAPI

REQUEST_ID_HEADER = "X-Request-Id"
LOG_PROBE_PATH = "/test-only/log-probe"
LOG_PROBE_EVENT = "request_id_probe"
OVERSIZED_BODY_BYTES = 101 * 1024

VALID_REQUEST_IDS = [
    "req-abc.123_XYZ",
    "a",
    "A" * 64,
]

INVALID_REQUEST_IDS = [
    "A" * 65,
    "bad id!",
    "abc/def",
    "<script>alert(1)</script>",
    "abc;DROP TABLE users",
]


def mount_log_probe_route(application: FastAPI) -> None:
    """Add a test-only GET route that logs one probe event carrying its marker."""
    probe_logger = structlog.get_logger()

    async def emit_probe_log(marker: str) -> dict[str, str]:
        await asyncio.sleep(0.01)
        probe_logger.info(LOG_PROBE_EVENT, marker=marker)
        return {"marker": marker}

    application.add_api_route(LOG_PROBE_PATH, emit_probe_log, methods=["GET"])


def assert_is_new_uuid(header_value: str, inbound_value: str | None) -> None:
    """Assert the header parses as a UUID and is not the inbound value."""
    assert header_value != inbound_value
    parsed_uuid = uuid.UUID(header_value)
    assert parsed_uuid.int != 0


def find_probe_events(events: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    """Return the captured probe events emitted for one marker."""
    return [
        event
        for event in events
        if event.get("event") == LOG_PROBE_EVENT and event.get("marker") == marker
    ]


@pytest.mark.parametrize("inbound_request_id", VALID_REQUEST_IDS)
async def test_b2_valid_inbound_request_id_is_echoed(
    api_client: httpx.AsyncClient, inbound_request_id: str
) -> None:
    """B-2: an inbound X-Request-Id matching ^[A-Za-z0-9._-]{1,64}$ is echoed unchanged."""
    response = await api_client.get("/health", headers={REQUEST_ID_HEADER: inbound_request_id})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == inbound_request_id


@pytest.mark.parametrize("inbound_request_id", INVALID_REQUEST_IDS)
async def test_b2_invalid_inbound_request_id_is_replaced_by_new_uuid(
    api_client: httpx.AsyncClient, inbound_request_id: str
) -> None:
    """B-2: an inbound X-Request-Id failing the pattern is replaced by a new UUID."""
    response = await api_client.get("/health", headers={REQUEST_ID_HEADER: inbound_request_id})

    assert response.status_code == 200
    assert_is_new_uuid(response.headers[REQUEST_ID_HEADER], inbound_request_id)


async def test_b2_missing_request_id_is_replaced_by_a_new_uuid_per_request(
    api_client: httpx.AsyncClient,
) -> None:
    """B-2: a request without X-Request-Id gets a new UUID, different on each request."""
    first_response = await api_client.get("/health")
    second_response = await api_client.get("/health")

    first_request_id = first_response.headers[REQUEST_ID_HEADER]
    second_request_id = second_response.headers[REQUEST_ID_HEADER]
    assert_is_new_uuid(first_request_id, None)
    assert_is_new_uuid(second_request_id, None)
    assert first_request_id != second_request_id


@pytest.mark.parametrize(
    ("method", "path", "body", "expected_status"),
    [
        ("GET", "/health", None, 200),
        ("GET", "/health/ready", None, 503),
        ("GET", "/test-only/no-such-route", None, 404),
        ("POST", "/health", b"x" * OVERSIZED_BODY_BYTES, 413),
    ],
)
async def test_b2_every_response_carries_the_request_id_including_rejections(
    api_client: httpx.AsyncClient,
    method: str,
    path: str,
    body: bytes | None,
    expected_status: int,
) -> None:
    """B-2: every response, including 404, 413, and 503, echoes the valid inbound ID."""
    inbound_request_id = "every-response.check_1"

    response = await api_client.request(
        method, path, content=body, headers={REQUEST_ID_HEADER: inbound_request_id}
    )

    assert response.status_code == expected_status
    assert response.headers[REQUEST_ID_HEADER] == inbound_request_id


@pytest.mark.parametrize(
    "inbound_headers",
    [
        {REQUEST_ID_HEADER: "log-line.check_1"},
        {REQUEST_ID_HEADER: "bad id!"},
        {},
    ],
    ids=["valid", "invalid", "missing"],
)
async def test_b2_every_log_line_during_the_request_carries_the_response_request_id(
    server_app: FastAPI,
    api_client: httpx.AsyncClient,
    captured_log_events: list[dict[str, Any]],
    inbound_headers: dict[str, str],
) -> None:
    """B-2: each log line emitted during a request carries the ID the response returns."""
    mount_log_probe_route(server_app)
    captured_log_events.clear()

    response = await api_client.get(
        LOG_PROBE_PATH, params={"marker": "single"}, headers=inbound_headers
    )

    assert response.status_code == 200
    response_request_id = response.headers[REQUEST_ID_HEADER]
    assert find_probe_events(captured_log_events, "single"), "the probe log line was not captured"
    for event in captured_log_events:
        assert event.get("request_id") == response_request_id, event


async def test_b2_concurrent_requests_log_their_own_request_ids(
    server_app: FastAPI,
    api_client: httpx.AsyncClient,
    captured_log_events: list[dict[str, Any]],
) -> None:
    """B-2: two overlapping requests each log their own ID, never the other's."""
    mount_log_probe_route(server_app)
    request_ids_by_marker = {"first": "concurrent-first.1", "second": "concurrent-second.2"}

    responses = await asyncio.gather(
        *(
            api_client.get(
                LOG_PROBE_PATH, params={"marker": marker}, headers={REQUEST_ID_HEADER: request_id}
            )
            for marker, request_id in request_ids_by_marker.items()
        )
    )

    assert [response.status_code for response in responses] == [200, 200]
    for marker, request_id in request_ids_by_marker.items():
        probe_events = find_probe_events(captured_log_events, marker)
        assert probe_events, f"no probe log line captured for {marker}"
        assert [event.get("request_id") for event in probe_events] == [request_id]


async def test_b2_request_id_does_not_leak_into_logs_after_the_request_ends(
    server_app: FastAPI,
    api_client: httpx.AsyncClient,
    captured_log_events: list[dict[str, Any]],
) -> None:
    """B-2: a log line after a request ends carries no ID, and the next request logs its own."""
    mount_log_probe_route(server_app)
    first_request_id = "sequential-first.1"
    second_request_id = "sequential-second.2"

    await api_client.get(
        LOG_PROBE_PATH, params={"marker": "first"}, headers={REQUEST_ID_HEADER: first_request_id}
    )
    structlog.get_logger().info("after_request_probe")
    await api_client.get(
        LOG_PROBE_PATH, params={"marker": "second"}, headers={REQUEST_ID_HEADER: second_request_id}
    )

    after_request_events = [
        event for event in captured_log_events if event.get("event") == "after_request_probe"
    ]
    assert len(after_request_events) == 1
    assert after_request_events[0].get("request_id") is None
    second_probe_events = find_probe_events(captured_log_events, "second")
    assert [event.get("request_id") for event in second_probe_events] == [second_request_id]
