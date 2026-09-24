"""The password-reset email job: issue a reset for the address, then mail its link.

The forgot-password route enqueues this for every address it is given, known or not, and this is
where the difference is found out: an unknown address issues nothing and sends nothing.

The reset is committed before the email is sent. Sending first could deliver a link whose row a
failed commit then discarded, and a link that never works is worse than a retry. A send that
raises is not caught, so arq retries the job (up to `max_tries`); each retry issues a fresh reset,
which retires the one the failed attempt stored, so only the link actually delivered works.

Like every job, it binds its arq job ID into the log context for the length of the run (R-341).
"""

import structlog

from app.core.settings import get_settings
from app.services.auth.issue_password_reset import issue_password_reset
from app.services.email.build_password_reset_email import build_password_reset_email
from app.workers.context import WorkerContext

logger = structlog.get_logger(__name__)


async def send_password_reset_email(ctx: WorkerContext, email: str) -> None:
    """Issue a reset and email its link, or do nothing when no account uses the address."""
    with structlog.contextvars.bound_contextvars(job_id=ctx["job_id"]):
        async with ctx["engine"].begin() as connection:
            issued = await issue_password_reset(connection, email)
        if issued is None:
            logger.info("password_reset_email_skipped")
            return
        message = build_password_reset_email(get_settings().client_url, issued.raw_token)
        await ctx["email_client"].send_email(issued.email, message.subject, message.html)
        logger.info("password_reset_email_sent", user_id=str(issued.user_id))
