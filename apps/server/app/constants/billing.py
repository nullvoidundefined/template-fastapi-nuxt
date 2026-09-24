"""The billing vocabulary: subscription statuses, ledger states, and the handled Stripe events.

`UserSubscriptionStatus` mirrors Stripe's subscription statuses, which are the Express template's
`subscription_status` values, so a status Stripe sends is stored as the same word. The ledger
states are the three a delivery moves through: claimed while a handler runs, then processed or
failed; a claim's outcome tells the delivery which of the three it met. The allowlist names the
five Stripe events the Express template handles; every other verified event is acknowledged and
ignored.
"""

import re
from enum import StrEnum

USER_SUBSCRIPTION_STATUS_ENUM_NAME = "user_subscription_status"
BILLING_WEBHOOK_EVENT_STATUS_ENUM_NAME = "billing_webhook_event_status"
# A claim older than this was left by a handler that crashed, and a redelivery takes it over.
STALE_CLAIM_MINUTES = 10
PRICE_ID_PATTERN = re.compile(r"^price_[A-Za-z0-9]+$")
STRIPE_SIGNATURE_HEADER = "stripe-signature"


class UserSubscriptionStatus(StrEnum):
    """Every status the `user_subscription_status` enum holds, in its declared order."""

    ACTIVE = "active"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class BillingWebhookEventStatus(StrEnum):
    """Where one Stripe delivery is in the ledger."""

    CLAIMED = "claimed"
    PROCESSED = "processed"
    FAILED = "failed"


class WebhookClaimOutcome(StrEnum):
    """What a delivery's claim found: its own claim, a finished event, or another live claim."""

    CLAIMED = "claimed"
    ALREADY_PROCESSED = "already_processed"
    IN_PROGRESS = "in_progress"


class StripeEventType(StrEnum):
    """The five Stripe event types the webhook handles; the allowlist is this enum."""

    CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"
    CUSTOMER_SUBSCRIPTION_CREATED = "customer.subscription.created"
    CUSTOMER_SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"


HANDLED_STRIPE_EVENT_TYPES = frozenset(event_type.value for event_type in StripeEventType)
