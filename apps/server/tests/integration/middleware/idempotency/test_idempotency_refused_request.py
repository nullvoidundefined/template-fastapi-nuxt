"""A keyed request a guard refuses writes no claim (IAN-339).

The unit test beside the middleware list proves the order through a closed database port; this
one reads the claim table itself. A signed-in user sends a keyed POST without the CSRF header, the
guard answers 403, and afterwards no row exists for that key and the handler never ran.
"""

import pytest

from tests.integration.middleware.idempotency.conftest import (
    ECHO_PATH,
    build_unique_key,
    encode_body,
)


@pytest.mark.integration
async def test_a_keyed_request_the_csrf_guard_refuses_leaves_no_claim_row(
    idempotency_app, idempotency_db, handler_probe
) -> None:
    """The 403 arrives, the claim table holds nothing for the key, and the handler never ran."""
    user = await idempotency_db.sign_in_user()
    key = build_unique_key()
    headers = {name: value for name, value in user.headers.items() if name != "X-Requested-With"}
    headers.update({"Content-Type": "application/json", "Idempotency-Key": key})

    async with idempotency_app as client:
        refused = await client.post(
            ECHO_PATH, content=encode_body({"item": "refused"}), headers=headers
        )

    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "CSRF_HEADER_MISSING"
    assert (await idempotency_db.read_claim(key, user.id)) is None
    assert handler_probe.calls == 0
