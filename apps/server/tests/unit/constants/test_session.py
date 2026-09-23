"""Specify the shared cookie name and the seven-day session lifetime."""

from datetime import timedelta


def test_session_cookie_and_lifetime_are_shared_constants() -> None:
    """The cookie uses sid and expires after exactly seven days."""
    from app.constants.session import SESSION_COOKIE_NAME, SESSION_TTL  # noqa: PLC0415

    assert SESSION_COOKIE_NAME == "sid"
    assert SESSION_TTL == timedelta(days=7)
