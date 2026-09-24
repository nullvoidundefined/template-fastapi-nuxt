"""The email client the worker uses when RESEND_API_KEY is unset: it logs and sends nothing.

Development and the test suites run without the provider, and a worker that raised on every send
would retry the job three times for nothing. The only email the application sends is the
password-reset email, so the line names it.

The line carries neither the body nor the recipient. The body holds the reset link, and a link
in a log is a working password reset for anyone who can read the logs; the recipient is personal
data (R-104).
"""

import structlog

logger = structlog.get_logger(__name__)


class DisabledEmailClient:
    """Stands in for Resend when no key is configured, logging each send instead of making it."""

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Log that the message was not sent, without the link, the token, or the address."""
        logger.warning("password_reset_email_not_sent", reason="resend_api_key_unset")

    async def close(self) -> None:
        """Release nothing, so the worker can close either client the same way."""
