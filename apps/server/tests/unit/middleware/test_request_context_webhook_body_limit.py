"""The Stripe webhook's own body ceiling: 1 MB rather than the 100 KB every other route gets.

Stripe's event payloads can exceed 100 KB (a subscription with many items, an invoice with many
lines), and a delivery refused with 413 is retried by Stripe until it gives up, so the webhook
path gets a larger ceiling. It is still a ceiling: a body past 1 MB answers 413 before the route
runs, whether it declares its length or streams without one. The path is matched exactly, so a
path that merely begins with the webhook's keeps the 100 KB limit.

The deliveries carry no `Stripe-Signature`, so a body inside the ceiling reaches the route and is
refused there with 400 `BILLING_WEBHOOK_MISCONFIGURED`, which shows the middleware let it through
without needing a database or a signing secret.
"""

from collections.abc import AsyncIterator

import httpx
import pytest

WEBHOOK_PATH = "/v1/billing/webhook"
SPOOFED_WEBHOOK_PATH = "/v1/billing/webhook-spoof"
WEBHOOK_MAX_BODY_BYTES = 1024 * 1024
DEFAULT_OVERSIZED_BODY_BYTES = 200 * 1024
STREAM_CHUNK_BYTES = 64 * 1024


async def stream_body_chunks(total_bytes: int) -> AsyncIterator[bytes]:
    """Yield a body of total_bytes in fixed chunks, so httpx sends it without Content-Length."""
    remaining_bytes = total_bytes
    while remaining_bytes > 0:
        chunk_bytes = min(STREAM_CHUNK_BYTES, remaining_bytes)
        remaining_bytes -= chunk_bytes
        yield b"x" * chunk_bytes


def build_request_body(total_bytes: int, is_streamed: bool) -> bytes | AsyncIterator[bytes]:
    """Return a body of total_bytes, streamed without Content-Length or sent with one."""
    if is_streamed:
        return stream_body_chunks(total_bytes)
    return b"x" * total_bytes


@pytest.mark.parametrize("is_streamed", [False, True], ids=["declared", "streamed"])
async def test_a_webhook_body_of_exactly_1_mb_reaches_the_route(
    api_client: httpx.AsyncClient, is_streamed: bool
) -> None:
    """1 MB is inside the webhook's ceiling, so the route itself answers."""
    response = await api_client.post(
        WEBHOOK_PATH, content=build_request_body(WEBHOOK_MAX_BODY_BYTES, is_streamed)
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_MISCONFIGURED"


@pytest.mark.parametrize("is_streamed", [False, True], ids=["declared", "streamed"])
async def test_a_webhook_body_one_byte_over_1_mb_answers_413(
    api_client: httpx.AsyncClient, is_streamed: bool
) -> None:
    """The webhook's ceiling is a ceiling: one byte past 1 MB is refused before the route runs."""
    response = await api_client.post(
        WEBHOOK_PATH, content=build_request_body(WEBHOOK_MAX_BODY_BYTES + 1, is_streamed)
    )

    assert response.status_code == 413, response.text
    assert response.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"


async def test_a_path_that_only_begins_with_the_webhooks_keeps_the_100_kb_limit(
    api_client: httpx.AsyncClient,
) -> None:
    """The larger ceiling is matched by exact path, never by prefix."""
    response = await api_client.post(
        SPOOFED_WEBHOOK_PATH,
        content=b"x" * DEFAULT_OVERSIZED_BODY_BYTES,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 413, response.text
    assert response.json()["code"] == "INPUT_PAYLOAD_TOO_LARGE"
