"""Sends email through Resend's HTTP API with httpx, one instrumented call per message.

A thin client over the one endpoint the application uses, rather than the Resend SDK: the SDK is
synchronous, and a POST with a bearer key is all it would add. The HTTP client is built once per
worker process and reused, so each send reuses the connection pool.

A non-2xx answer raises. The email job turns that into arq's `Retry` until its last try, and on
the last try lets it escape and logs it, because a send that failed quietly would lose the reset
email with nobody told (spec, failure modes).
"""

from collections.abc import Mapping

import httpx
from pydantic import SecretStr

from app.clients.telemetry import with_client_telemetry

RESEND_EMAILS_URL = "https://api.resend.com/emails"
RESEND_PROVIDER = "resend"
SEND_EMAIL_OPERATION = "send_email"
# httpx bounds each phase of the request with this, and the telemetry wrapper bounds the whole
# call with the same value, so neither a slow connect nor a slow body can hold a job open.
RESEND_TIMEOUT_SECONDS = 10.0


class ResendEmailClient:
    """Sends one HTML email per call from the configured sender address."""

    def __init__(
        self,
        sending_key: SecretStr,
        sender: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Record the key and sender, and build the HTTP client unless one is supplied."""
        self.sending_key = sending_key
        self.sender = sender
        self.http_client = http_client or httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS)

    async def send_email(self, to: str, subject: str, html: str) -> None:
        """Send the message, raising `httpx.HTTPStatusError` when Resend refuses it."""

        async def post_message(forwarded_headers: Mapping[str, str]) -> None:
            await self.post_email(forwarded_headers, to, subject, html)

        await with_client_telemetry(
            RESEND_PROVIDER, SEND_EMAIL_OPERATION, post_message, RESEND_TIMEOUT_SECONDS
        )

    async def post_email(
        self, forwarded_headers: Mapping[str, str], to: str, subject: str, html: str
    ) -> None:
        """POST one message to Resend and raise on any answer outside 2xx."""
        response = await self.http_client.post(
            RESEND_EMAILS_URL,
            json={"from": self.sender, "to": [to], "subject": subject, "html": html},
            headers={**forwarded_headers, "Authorization": self.build_authorization()},
            timeout=RESEND_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def build_authorization(self) -> str:
        """Return the bearer header value, reading the key only at the moment it is sent."""
        return "Bearer " + self.sending_key.get_secret_value()

    async def close(self) -> None:
        """Close the HTTP client's connection pool when the worker shuts down."""
        await self.http_client.aclose()
