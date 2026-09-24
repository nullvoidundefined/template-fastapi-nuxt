"""The one method a job needs from an email client, so the worker can hold either kind.

The worker stores Resend when a key is configured and the logging stand-in when not, and a job
sends through whichever it finds without knowing which. Tests hand a job a recording fake through
the same shape.
"""

from typing import Protocol


class EmailSender(Protocol):
    """Anything that can send one HTML email to one address."""

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Send the message, raising when the provider refuses it."""
        ...
