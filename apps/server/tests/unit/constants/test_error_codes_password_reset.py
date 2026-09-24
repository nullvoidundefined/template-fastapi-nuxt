"""B-15: the invalid-reset-token code is in the registry, not a literal at the call site."""

INVALID_RESET_CODE = "AUTH_RESET_TOKEN_INVALID"


def test_b15_the_registry_carries_the_invalid_reset_token_code() -> None:
    """The code a spent, expired, or unknown reset token answers with is a registered member."""
    from app.constants.error_codes import ErrorCode  # noqa: PLC0415

    registered_values = {code.value for code in ErrorCode}

    assert INVALID_RESET_CODE in registered_values
    assert ErrorCode(INVALID_RESET_CODE).name == INVALID_RESET_CODE
