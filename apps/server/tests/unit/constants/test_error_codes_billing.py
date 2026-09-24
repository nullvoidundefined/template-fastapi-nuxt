"""Slice 06: every code the billing routes and the webhook answer with is in the registry."""

import pytest

BILLING_CODES = [
    "BILLING_NO_ACCOUNT",
    "BILLING_NOT_CONFIGURED",
    "BILLING_WEBHOOK_MISCONFIGURED",
    "BILLING_WEBHOOK_INVALID_SIGNATURE",
    "BILLING_WEBHOOK_PROCESSING_FAILED",
    "BILLING_WEBHOOK_IN_PROGRESS",
]


@pytest.mark.parametrize("code", BILLING_CODES)
def test_the_registry_carries_each_billing_code(code: str) -> None:
    """Each billing code is a registered member whose value is its own name."""
    from app.constants.error_codes import ErrorCode  # noqa: PLC0415

    registered_values = {member.value for member in ErrorCode}

    assert code in registered_values
    assert ErrorCode(code).name == code
