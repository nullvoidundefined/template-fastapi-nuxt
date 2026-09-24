"""The password-reset email job: issue a reset for the address, then mail its link.

The forgot-password route enqueues this for every address it is given, known or not, and this is
where the difference is found out: an unknown address issues nothing and sends nothing.

The reset is committed before the email is sent. Sending first could deliver a link whose row a
failed commit then discarded, and a link that never works is worse than a retry. A send that
raises is turned into `arq.worker.Retry` when arq is running the job, because arq retries nothing
else. Each retry issues a fresh reset, which
retires the one the failed attempt stored, so only the link actually delivered works.

Like every job, it binds its arq job ID into the log context for the length of the run, and the
ID of the request that enqueued it, so its log lines and its Resend call carry that ID (R-341).
"""

import structlog
from arq.worker import Retry

from app.constants.password_reset import RESET_EMAIL_MAX_TRIES
from app.core.settings import get_settings
from app.services.auth.issue_password_reset import issue_password_reset
from app.services.email.build_password_reset_email import build_password_reset_email
from app.workers.context import WorkerContext

logger = structlog.get_logger(__name__)

# The delay before a retry, multiplied by the try number, so a provider outage is given longer
# on each attempt rather than being hammered.
RESET_EMAIL_RETRY_DELAY_SECONDS = 5.0


async def send_password_reset_email(
    ctx: WorkerContext, email: str, request_id: str | None = None
) -> None:
    """Send the reset email; under arq, turn a failure into the `Retry` arq needs to run it again.

    arq supplies `job_try` on every run and retries only a job that raises `Retry`, so a failure
    is converted exactly when arq is the caller. A direct call, which has no `job_try`, gets the
    underlying error, which is what a caller outside the worker can act on.
    """
    try:
        await issue_and_send_reset_email(ctx, email, request_id)
    except Exception as err:
        if "job_try" not in ctx:
            raise
        job_try = ctx["job_try"]
        if job_try >= RESET_EMAIL_MAX_TRIES:
            # The last try: raise the provider's own error, so the lost email is logged with its
            # cause rather than as one more "retrying" warning arq then drops.
            logger.error("password_reset_email_failed", job_try=job_try, err=err)
            raise
        logger.warning("password_reset_email_retrying", job_try=job_try, err=err)
        raise Retry(defer=RESET_EMAIL_RETRY_DELAY_SECONDS * job_try) from err


async def issue_and_send_reset_email(
    ctx: WorkerContext, email: str, request_id: str | None
) -> None:
    """Issue a reset and email its link, or do nothing when no account uses the address."""
    bound_ids = {"job_id": ctx.get("job_id")}
    if request_id:
        bound_ids["request_id"] = request_id
    with structlog.contextvars.bound_contextvars(**bound_ids):
        async with ctx["engine"].begin() as connection:
            issued = await issue_password_reset(connection, email)
        if issued is None:
            logger.info("password_reset_email_skipped")
            return
        message = build_password_reset_email(get_settings().client_url, issued.raw_token)
        await ctx["email_client"].send_email(issued.email, message.subject, message.html)
        logger.info("password_reset_email_sent", user_id=str(issued.user_id))
