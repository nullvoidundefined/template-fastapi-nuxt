"""Provides the application's Stripe client to a billing route, or refuses when there is none.

The client is built once in the lifespan and kept on the application's state, so every request
shares one connection pool. Without `STRIPE_SECRET_KEY` there is no client, and a billing route
answers 503 `BILLING_NOT_CONFIGURED` rather than failing on its first Stripe call. Routes declare
`RequestStripeBillingClient`, which is what lets a test substitute a client whose Stripe calls a
recorder answers.
"""

from typing import Annotated, cast

from fastapi import Depends
from starlette.requests import Request

from app.clients.stripe import StripeBillingClient
from app.constants.error_codes import ErrorCode
from app.errors import AppError

BILLING_NOT_CONFIGURED_MESSAGE = "Billing is not configured"


class BillingNotConfiguredError(AppError):
    """The deployment has no Stripe key, so no billing call can be made."""

    def __init__(self) -> None:
        """Answer 503 with the registry's not-configured code."""
        super().__init__(503, ErrorCode.BILLING_NOT_CONFIGURED, BILLING_NOT_CONFIGURED_MESSAGE)


def get_stripe_billing_client(request: Request) -> StripeBillingClient:
    """Return the client the lifespan stored, raising when billing is not configured."""
    client = cast("StripeBillingClient | None", request.app.state.stripe_billing_client)
    if client is None:
        raise BillingNotConfiguredError
    return client


RequestStripeBillingClient = Annotated[StripeBillingClient, Depends(get_stripe_billing_client)]
