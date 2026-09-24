"""Request and response models for the billing routes, and the Stripe objects the webhook reads.

The checkout body carries only the price. Its pattern is the spec's `^price_[A-Za-z0-9]+$`, so a
product id, an injection string, or anything else Stripe would reject answers 400
`INPUT_VALIDATION_ERROR` before a Stripe call is made, and the length bound keeps an oversized
value from reaching the pattern at all.

The Stripe models name only the fields a webhook handler reads and ignore the rest, so a field
Stripe adds later changes nothing here, while a field the handler needs arriving in the wrong
shape fails validation, which fails the handler and leaves the event for Stripe to retry.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.constants.billing import PRICE_ID_PATTERN, UserSubscriptionStatus

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


class WebhookReceivedData(BaseModel):
    """The acknowledgement Stripe needs: any 2xx stops its retries."""

    received: bool


class WebhookReceivedResponse(BaseModel):
    """The `{ data }` envelope around the webhook's acknowledgement."""

    data: WebhookReceivedData


class StripeCheckoutSession(BaseModel):
    """The fields of a completed Checkout session the webhook reads; Stripe sends many more."""

    model_config = ConfigDict(extra="ignore")

    id: str
    customer: str | None = None
    subscription: str | None = None
    metadata: dict[str, str] | None = None


class StripePrice(BaseModel):
    """The price a subscription item is for; its id is stored as the plan."""

    model_config = ConfigDict(extra="ignore")

    id: str


class StripeSubscriptionItem(BaseModel):
    """One line of a subscription, carrying the period in API versions from 2025-03-31."""

    model_config = ConfigDict(extra="ignore")

    price: StripePrice
    current_period_start: int | None = None
    current_period_end: int | None = None


class StripeSubscriptionItemList(BaseModel):
    """The list wrapper Stripe puts around a subscription's items."""

    model_config = ConfigDict(extra="ignore")

    data: list[StripeSubscriptionItem] = Field(default_factory=list)


class StripeSubscription(BaseModel):
    """The fields of a subscription the three subscription events write.

    `status` is validated against the stored enum, so a status Stripe has never sent fails the
    handler rather than reaching the database. The period is read from the first item when the
    account's API version puts it there, and from the subscription itself otherwise.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    customer: str
    status: UserSubscriptionStatus
    cancel_at_period_end: bool = False
    current_period_start: int | None = None
    current_period_end: int | None = None
    items: StripeSubscriptionItemList = Field(default_factory=StripeSubscriptionItemList)
    metadata: dict[str, str] = Field(default_factory=dict)


class StripeInvoiceSubscriptionDetails(BaseModel):
    """Where API versions from 2025-03-31 name the subscription an invoice bills."""

    model_config = ConfigDict(extra="ignore")

    subscription: str | None = None


class StripeInvoiceParent(BaseModel):
    """What an invoice was issued for, in API versions from 2025-03-31."""

    model_config = ConfigDict(extra="ignore")

    subscription_details: StripeInvoiceSubscriptionDetails | None = None


class StripeInvoice(BaseModel):
    """The fields of an invoice that `invoice.payment_failed` reads, in either API shape."""

    model_config = ConfigDict(extra="ignore")

    id: str
    subscription: str | None = None
    parent: StripeInvoiceParent | None = None
