"""B-43: the 413 the body-size guard answers with carries the registry's code, not a local literal.

The four existing body-limit test files under this directory assert the same 413 against a string
literal they each declare themselves, and they are deliberately left untouched: their passing
unchanged is the evidence that re-homing `PAYLOAD_TOO_LARGE_CODE` onto `ErrorCode` and the shared
envelope builder preserved the middleware's behavior. This file adds the one assertion that reads
the expected code from `app/constants/error_codes.py` instead, so the middleware and the registry
cannot drift apart without a test failing.
"""

import httpx

from app.constants.error_codes import ErrorCode

OVERSIZED_BODY_BYTES = 101 * 1024


async def test_b43_oversized_body_answers_the_registry_input_payload_too_large_code(
    api_client: httpx.AsyncClient,
) -> None:
    """B-43: a 101 KB body answers 413 whose code is ErrorCode.INPUT_PAYLOAD_TOO_LARGE."""
    response = await api_client.post("/health", content=b"x" * OVERSIZED_BODY_BYTES)

    assert response.status_code == 413, response.text
    response_body = response.json()
    assert set(response_body) == {"code", "error"}, response_body
    assert response_body["code"] == ErrorCode.INPUT_PAYLOAD_TOO_LARGE, response_body
    assert response_body["error"].strip(), response_body
