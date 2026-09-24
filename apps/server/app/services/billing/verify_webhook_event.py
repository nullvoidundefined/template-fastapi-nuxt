"""Turns a raw webhook delivery into a verified Stripe event, or refuses it with 400.

Two refusals, told apart because they call for different fixes. A delivery with no
`Stripe-Signature` header, or one reaching a deployment with no signing secret configured, is
`BILLING_WEBHOOK_MISCONFIGURED`: the endpoint or the environment is set up wrong. A signature that
does not verify is `BILLING_WEBHOOK_INVALID_SIGNATURE`: the request did not come from Stripe, or
was altered or replayed on the way. Neither writes anything.
"""

import structlog
from pydantic import SecretStr

from app.clients.stripe import (
    InvalidWebhookSignatureError,
    StripeWebhookEvent,
    construct_webhook_event,
)
from app.constants.error_codes import ErrorCode
from app.errors import AppError

MISCONFIGURED_MESSAGE = "The webhook signature or its signing secret is missing"
INVALID_SIGNATURE_MESSAGE = "The webhook signature did not verify"

logger = structlog.get_logger(__name__)


class WebhookMisconfiguredError(AppError):
    """The delivery carried no signature, or no signing secret is configured to check it with."""

    def __init__(self) -> None:
        """Answer 400 with the registry's misconfigured code."""
        super().__init__(400, ErrorCode.BILLING_WEBHOOK_MISCONFIGURED, MISCONFIGURED_MESSAGE)


class WebhookInvalidSignatureError(AppError):
    """The delivery's signature did not verify against the signing secret."""

    def __init__(self) -> None:
        """Answer 400 with the registry's invalid-signature code."""
        super().__init__(
            400, ErrorCode.BILLING_WEBHOOK_INVALID_SIGNATURE, INVALID_SIGNATURE_MESSAGE
        )


def verify_webhook_event(
    payload: bytes, signature_header: str | None, signing_secret: SecretStr | None
) -> StripeWebhookEvent:
    """Return the verified event, raising the 400 that names why a delivery was refused."""
    if signing_secret is None or not signature_header:
        logger.warning(
            "billing_webhook_misconfigured",
            has_signature=bool(signature_header),
            has_signing_secret=signing_secret is not None,
        )
        raise WebhookMisconfiguredError
    try:
        return construct_webhook_event(payload, signature_header, signing_secret)
    except InvalidWebhookSignatureError as err:
        logger.warning("billing_webhook_signature_invalid", exc_info=err)
        raise WebhookInvalidSignatureError from err
