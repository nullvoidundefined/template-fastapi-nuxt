"""Every analytics event the server sends, named `object_action` in the past tense (R-343).

A call site passes a member of this registry and never a string, so an event cannot be renamed at
one call site and drift from the dashboards built on it.
"""

from enum import StrEnum


class AnalyticsEvent(StrEnum):
    """The server-side events PostHog receives, each keyed by the user's ID only."""

    USER_REGISTERED = "user_registered"
    USER_SIGNED_IN = "user_signed_in"
    USER_SIGNED_OUT = "user_signed_out"
    # An event name, not a secret; ruff's S105 matches the word "password" in the member name.
    USER_PASSWORD_CHANGED = "user_password_changed"  # noqa: S105
    # Sent by the reset-email job, the first point that knows which user asked (B-24).
    USER_PASSWORD_RESET_REQUESTED = "user_password_reset_requested"  # noqa: S105
    # Sent by the reset route, which learns the user from the token it consumed.
    USER_PASSWORD_RESET_COMPLETED = "user_password_reset_completed"  # noqa: S105
