"""The password-reset email: its subject and the HTML carrying the one-hour link.

A template is a function that returns the message, and the client only sends it, so the wording
can change without touching the provider and the provider without touching the wording. The link
is built from `client_url` because it opens the web client's page, which then posts the token to
the API; the API's own origin never appears in an email.
"""

import html
from dataclasses import dataclass
from urllib.parse import urlencode

from app.constants.password_reset import RESET_PAGE_PATH

RESET_EMAIL_SUBJECT = "Reset your password"


@dataclass(slots=True, frozen=True)
class EmailMessage:
    """What a template produces and an email client sends."""

    subject: str
    html: str


def build_password_reset_link(client_url: str, raw_token: str) -> str:
    """Return the web client's reset page with the token in its query string."""
    query = urlencode({"token": raw_token})
    return f"{client_url.rstrip('/')}{RESET_PAGE_PATH}?{query}"


def build_password_reset_email(client_url: str, raw_token: str) -> EmailMessage:
    """Return the subject and HTML of the email that carries the reset link."""
    link = html.escape(build_password_reset_link(client_url, raw_token), quote=True)
    body = (
        "<p>Someone asked to reset the password for this account.</p>"
        f'<p><a href="{link}">Choose a new password</a></p>'
        "<p>The link works once and expires in one hour. If you did not ask for it, you can "
        "ignore this email and your password will not change.</p>"
    )
    return EmailMessage(subject=RESET_EMAIL_SUBJECT, html=body)
