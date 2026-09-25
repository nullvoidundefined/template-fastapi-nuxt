"""IAN-344 unit tests: the server's Sentry scrubber redacts tokens and emails inside free text.

`scrub_sentry_event` already drops whole fields (cookies, bodies, query strings). Free text is the
remaining path: a breadcrumb's `message`, an exception's `value`, and a log event's message can
each quote an address or a reset token. The scrubber redacts email addresses, bearer values,
`name=value` secrets, and long opaque tokens in all of them, and leaves request IDs, which are
UUIDs, readable so the event still joins its logs.

Every secret-shaped value is built at run time, so no credential-shaped literal sits here (R-108).
"""

import secrets
import uuid

from sentry_sdk.types import Event

EMAIL_ADDRESS = "@".join(("person", "example.test"))


def build_raw_token() -> str:
    """Return a value shaped like a reset or session token: 43 URL-safe characters."""
    return secrets.token_urlsafe(32)


def test_ian344_breadcrumb_messages_lose_emails_and_tokens() -> None:
    """A log breadcrumb quoting an address and a reset link keeps its words but not the values."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    raw_token = build_raw_token()
    event: Event = {
        "breadcrumbs": {
            "values": [
                {"category": "log", "message": f"reset requested for {EMAIL_ADDRESS}"},
                {"category": "log", "message": f"link sent: /reset-password?token={raw_token}"},
                {"category": "log", "message": f"issued {raw_token} to the user"},
            ]
        }
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    breadcrumbs = scrubbed["breadcrumbs"]
    assert isinstance(breadcrumbs, dict)
    messages = [crumb["message"] for crumb in breadcrumbs["values"]]
    assert EMAIL_ADDRESS not in repr(scrubbed)
    assert raw_token not in repr(scrubbed)
    assert messages[0].startswith("reset requested for ")
    assert messages[2].startswith("issued ")


def test_ian344_exception_values_lose_emails_bearer_values_and_named_secrets() -> None:
    """An exception message quoting credentials reaches Sentry with them redacted."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    bearer_value = build_raw_token()
    password_value = secrets.token_hex(6)
    event: Event = {
        "exception": {
            "values": [
                {"type": "ValueError", "value": f"no account for {EMAIL_ADDRESS}"},
                {"type": "RuntimeError", "value": f"upstream refused Bearer {bearer_value}"},
                {"type": "RuntimeError", "value": f"bad login password={password_value}"},
            ]
        }
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    assert EMAIL_ADDRESS not in repr(scrubbed)
    assert bearer_value not in repr(scrubbed)
    assert password_value not in repr(scrubbed)
    assert [value["type"] for value in scrubbed["exception"]["values"]] == [
        "ValueError",
        "RuntimeError",
        "RuntimeError",
    ]


def test_ian344_log_event_messages_and_params_lose_emails_and_tokens() -> None:
    """An event raised from a log record carries its message and parameters scrubbed."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    raw_token = build_raw_token()
    event: Event = {
        "message": f"failed for {EMAIL_ADDRESS}",
        "logentry": {
            "message": "failed for %s with %s",
            "formatted": f"failed for {EMAIL_ADDRESS} with {raw_token}",
            "params": [EMAIL_ADDRESS, raw_token],
        },
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    assert EMAIL_ADDRESS not in repr(scrubbed)
    assert raw_token not in repr(scrubbed)
    logentry = scrubbed["logentry"]
    assert logentry is not None
    assert logentry["message"] == "failed for %s with %s"


def test_ian344_a_request_id_in_free_text_stays_readable() -> None:
    """UUIDs are identifiers, not secrets, so the event can still be joined to its logs."""
    from app.clients.sentry import scrub_sentry_event  # noqa: PLC0415

    request_id = str(uuid.uuid4())
    raw_token = build_raw_token()
    event: Event = {
        "breadcrumbs": {
            "values": [{"category": "log", "message": f"request {request_id} used {raw_token}"}]
        }
    }

    scrubbed = scrub_sentry_event(event, {})

    assert scrubbed is not None
    breadcrumbs = scrubbed["breadcrumbs"]
    assert isinstance(breadcrumbs, dict)
    [breadcrumb] = breadcrumbs["values"]
    assert request_id in breadcrumb["message"]
    assert raw_token not in breadcrumb["message"]
