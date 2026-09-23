"""B-10: the duplicate-registration code is in the registry, not a literal at the call site.

An unregistered code is a type error rather than a string: the registry is what the exception
handler, the exported document, and the frontend's generated types all read, so a 409 answered
with a bare string would be invisible to every one of them.
"""

DUPLICATE_EMAIL_CODE = "AUTH_EMAIL_ALREADY_REGISTERED"


def test_b10_the_registry_carries_the_duplicate_registration_code() -> None:
    """The code registration answers a duplicate with is a member whose value is its own name."""
    from app.constants.error_codes import ErrorCode  # noqa: PLC0415

    registered_values = {code.value for code in ErrorCode}

    assert DUPLICATE_EMAIL_CODE in registered_values
    assert ErrorCode(DUPLICATE_EMAIL_CODE).name == DUPLICATE_EMAIL_CODE
