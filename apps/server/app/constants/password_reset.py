"""How long a password-reset link works, and the path on the web client it opens.

The lifetime is written into `expires_at` when a reset is issued and is the only thing that
decides whether a token is still good, so it lives here rather than beside either caller. The
path is the web client's page, which the email links to; the API only ever sees the token.
"""

from datetime import timedelta

PASSWORD_RESET_TTL = timedelta(hours=1)
RESET_PAGE_PATH = "/reset-password"
