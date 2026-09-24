"""Every analytics event the server sends, named `object_action` in the past tense (R-343).

A call site passes a member of this registry and never a string, so an event cannot be renamed at
one call site and drift from the dashboards built on it. The two password-reset events join this
registry with the reset routes.
"""

from enum import StrEnum


class AnalyticsEvent(StrEnum):
    """The server-side events PostHog receives, each keyed by the user's ID only."""

    USER_REGISTERED = "user_registered"
    USER_SIGNED_IN = "user_signed_in"
    USER_SIGNED_OUT = "user_signed_out"
    # An event name, not a secret; ruff's S105 matches the word "password" in the member name.
    USER_PASSWORD_CHANGED = "user_password_changed"  # noqa: S105
