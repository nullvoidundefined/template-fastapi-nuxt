"""Request and response models for the billing routes.

The checkout body carries only the price. Its pattern is the spec's `^price_[A-Za-z0-9]+$`, so a
product id, an injection string, or anything else Stripe would reject answers 400
`INPUT_VALIDATION_ERROR` before a Stripe call is made, and the length bound keeps an oversized
value from reaching the pattern at all.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.constants.billing import PRICE_ID_PATTERN

MAX_PRICE_ID_LENGTH = 255


class CheckoutCreate(BaseModel):
    """The body of `POST /v1/billing/checkout`: the Stripe price to subscribe to."""

    model_config = ConfigDict(extra="forbid", strict=True)

    price_id: str = Field(max_length=MAX_PRICE_ID_LENGTH, pattern=PRICE_ID_PATTERN.pattern)


class BillingRedirectData(BaseModel):
    """The hosted Stripe page the browser is sent to next."""

    url: str


class BillingRedirectResponse(BaseModel):
    """The `{ data }` envelope around a Checkout or portal URL."""

    data: BillingRedirectData
