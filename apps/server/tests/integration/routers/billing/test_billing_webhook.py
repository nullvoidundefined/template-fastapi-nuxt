"""B-6, B-7, B-20, B-21, B-34, B-41, B-42, B-51: `POST /v1/billing/webhook` through the real app.

Every delivery is signed the way Stripe signs it and sent without `X-Requested-With`, as Stripe
sends it, so each test also exercises the CSRF exemption. The assertions read the two tables
directly: the ledger row a delivery claimed, and the `user_subscriptions` columns a handler wrote.
A delivery that must change nothing is checked against the whole row, `updated_at` included,
which the shared trigger advances on any UPDATE, so even a write of unchanged values would show.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.integration.routers.billing.conftest import (
    WEBHOOK_SIGNING_VALUE,
    WRONG_SIGNING_VALUE,
    build_stripe_event,
    make_stripe_id,
    sign_stripe_payload,
)

RECEIVED_BODY = {"data": {"received": True}}
PERIOD_START = 1767225600
PERIOD_END = 1769904000
PERIOD_START_AT = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END_AT = datetime(2026, 2, 1, tzinfo=UTC)
STALE_SIGNATURE_AGE_SECONDS = 3600
GLOBAL_RATE_LIMIT = 100
EARLIER_EVENT_SECONDS = 60
STALE_CLAIM_MINUTES_AGO = 11
FRESH_CLAIM_MINUTES_AGO = 2


def build_checkout_session(user_id: object, customer_id: str, subscription_id: str) -> dict:
    """Return a completed subscription-mode Checkout session naming the user in its metadata."""
    return {
        "id": make_stripe_id("cs"),
        "object": "checkout.session",
        "mode": "subscription",
        "customer": customer_id,
        "subscription": subscription_id,
        "metadata": {"user_id": str(user_id)},
    }


def build_subscription(
    subscription_id: str,
    customer_id: str,
    status: str,
    *,
    is_canceling: bool = False,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a Stripe subscription on price_Pro1 with its period on its one item.

    The period is on the item because Stripe moved it there in the 2025-03-31 API version;
    `move_period_to_top_level` builds the shape an account pinned to an older version receives.
    """
    item: dict[str, Any] = {
        "id": make_stripe_id("si"),
        "object": "subscription_item",
        "price": {"id": "price_Pro1", "object": "price"},
        "quantity": 1,
    }
    subscription: dict[str, Any] = {
        "id": subscription_id,
        "object": "subscription",
        "customer": customer_id,
        "status": status,
        "cancel_at_period_end": is_canceling,
        "items": {"object": "list", "data": [item]},
        "metadata": metadata or {},
    }
    item["current_period_start"] = PERIOD_START
    item["current_period_end"] = PERIOD_END
    return subscription


def move_period_to_top_level(subscription: dict[str, Any]) -> dict[str, Any]:
    """Move the period from the subscription's item to the subscription, as older APIs send it."""
    [item] = subscription["items"]["data"]
    subscription["current_period_start"] = item.pop("current_period_start")
    subscription["current_period_end"] = item.pop("current_period_end")
    return subscription


def build_payment_failed_event(subscription_id: str) -> dict[str, Any]:
    """Return an `invoice.payment_failed` event naming the subscription at the top level."""
    return build_stripe_event(
        "invoice.payment_failed",
        {"id": make_stripe_id("in"), "object": "invoice", "subscription": subscription_id},
    )


async def seed_linked_user(billing_db, auth_emails, label: str) -> tuple[uuid.UUID, str, str]:
    """Commit a user whose subscription row already names a customer and a subscription."""
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails(label))
    customer_id = make_stripe_id("cus")
    subscription_id = make_stripe_id("sub")
    await billing_db.seed_subscription(user_id, customer_id, subscription_id)
    return user_id, customer_id, subscription_id


async def build_unlinked_checkout(billing_db, auth_emails, label: str) -> tuple[uuid.UUID, dict]:
    """Commit a user with no subscription row and return a checkout event naming that user."""
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails(label))
    event = build_stripe_event(
        "checkout.session.completed",
        build_checkout_session(user_id, make_stripe_id("cus"), make_stripe_id("sub")),
    )
    return user_id, event


@pytest.mark.integration
async def test_b20_a_signature_under_the_wrong_key_answers_400_and_writes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """An event signed with any other key is INVALID_SIGNATURE, with no ledger row and no link."""
    user_id, event = await build_unlinked_checkout(billing_db, auth_emails, "wrong-key")

    response = await webhook_sender.deliver(event, signing_value=WRONG_SIGNING_VALUE)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_INVALID_SIGNATURE"
    assert await webhook_sender.read_ledger(event["id"]) == []
    assert await billing_db.read_subscription(user_id) is None


@pytest.mark.integration
@pytest.mark.parametrize("defect", ["other-bytes", "stale", "garbage"])
async def test_b20_a_tampered_stale_or_garbled_signature_is_invalid(
    webhook_sender, billing_db, auth_emails, defect
) -> None:
    """The right key over other bytes, the right signature an hour old, or no v1 scheme at all."""
    user_id, event = await build_unlinked_checkout(billing_db, auth_emails, f"sig-{defect}")
    payload = json.dumps(event).encode()
    signed_an_hour_ago = int(datetime.now(UTC).timestamp()) - STALE_SIGNATURE_AGE_SECONDS
    signatures = {
        "other-bytes": sign_stripe_payload(b'{"id": "evt_other"}', WEBHOOK_SIGNING_VALUE),
        "stale": sign_stripe_payload(payload, WEBHOOK_SIGNING_VALUE, signed_an_hour_ago),
        "garbage": "not-a-stripe-signature",
    }

    response = await webhook_sender.deliver(event, signature=signatures[defect])

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_INVALID_SIGNATURE"
    assert await webhook_sender.read_ledger(event["id"]) == []
    assert await billing_db.read_subscription(user_id) is None


@pytest.mark.integration
async def test_b42_a_delivery_without_a_stripe_signature_header_answers_misconfigured(
    webhook_sender, billing_db, auth_emails
) -> None:
    """No Stripe-Signature header at all is MISCONFIGURED, and nothing is written."""
    user_id, event = await build_unlinked_checkout(billing_db, auth_emails, "no-header")

    response = await webhook_sender.deliver(event, is_signed=False)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_MISCONFIGURED"
    assert await webhook_sender.read_ledger(event["id"]) == []
    assert await billing_db.read_subscription(user_id) is None


@pytest.mark.integration
async def test_b42_a_webhook_without_a_configured_signing_value_answers_misconfigured(
    unconfigured_webhook_sender, billing_db, auth_emails
) -> None:
    """A signed delivery to a deployment without STRIPE_WEBHOOK_SECRET is refused, writing none."""
    user_id, event = await build_unlinked_checkout(billing_db, auth_emails, "no-config")

    response = await unconfigured_webhook_sender.deliver(event)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_MISCONFIGURED"
    assert await unconfigured_webhook_sender.read_ledger(event["id"]) == []
    assert await billing_db.read_subscription(user_id) is None


@pytest.mark.integration
async def test_b34_a_verified_event_outside_the_allowlist_answers_200_and_changes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """An unhandled type is acknowledged; no ledger row is written and no subscription moves."""
    user_id, customer_id, _subscription_id = await seed_linked_user(
        billing_db, auth_emails, "unknown-type"
    )
    before = await billing_db.read_subscription(user_id)
    event = build_stripe_event("customer.updated", {"id": customer_id, "object": "customer"})

    response = await webhook_sender.deliver(event)

    assert response.status_code == 200, response.text
    assert response.json() == RECEIVED_BODY
    assert await webhook_sender.read_ledger(event["id"]) == []
    assert await billing_db.read_subscription(user_id) == before


@pytest.mark.integration
async def test_b21_b51_checkout_links_the_user_once_however_often_it_is_delivered(
    webhook_sender, billing_db, auth_emails
) -> None:
    """The first delivery links customer and subscription by metadata; the second writes nothing."""
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails("checkout-once"))
    customer_id = make_stripe_id("cus")
    subscription_id = make_stripe_id("sub")
    event = build_stripe_event(
        "checkout.session.completed",
        build_checkout_session(user_id, customer_id, subscription_id),
    )

    first = await webhook_sender.deliver(event)
    linked = await billing_db.read_subscription(user_id)
    second = await webhook_sender.deliver(event)
    after_duplicate = await billing_db.read_subscription(user_id)

    assert first.status_code == 200, first.text
    assert first.json() == RECEIVED_BODY
    assert linked is not None
    assert linked.stripe_customer_id == customer_id
    assert linked.stripe_subscription_id == subscription_id
    assert second.status_code == 200, second.text
    assert second.json() == RECEIVED_BODY
    assert after_duplicate == linked
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "processed"
    assert ledger_row.event_type == "checkout.session.completed"
    assert ledger_row.processed_at is not None


@pytest.mark.integration
@pytest.mark.parametrize(
    ("event_type", "status", "is_canceling", "is_period_on_item"),
    [
        ("customer.subscription.created", "trialing", False, True),
        ("customer.subscription.updated", "active", True, True),
        ("customer.subscription.updated", "past_due", False, False),
        ("customer.subscription.deleted", "canceled", False, True),
    ],
)
async def test_b51_each_subscription_event_writes_status_plan_period_and_cancel_flag(  # noqa: PLR0913, PLR0917
    webhook_sender, billing_db, auth_emails, event_type, status, is_canceling, is_period_on_item
) -> None:
    """The row found by subscription id takes the event's status, price, period, and flag."""
    user_id, customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "subscription-event"
    )
    subscription = build_subscription(
        subscription_id, customer_id, status, is_canceling=is_canceling
    )
    if not is_period_on_item:
        subscription = move_period_to_top_level(subscription)

    response = await webhook_sender.deliver(build_stripe_event(event_type, subscription))

    assert response.status_code == 200, response.text
    stored = await billing_db.read_subscription(user_id)
    assert stored.status == status
    assert stored.plan_id == "price_Pro1"
    assert stored.current_period_start == PERIOD_START_AT
    assert stored.current_period_end == PERIOD_END_AT
    assert stored.is_canceling_at_period_end is is_canceling
    assert stored.stripe_customer_id == customer_id
    assert stored.stripe_subscription_id == subscription_id


@pytest.mark.integration
async def test_b51_a_subscription_event_arriving_before_checkout_creates_the_users_row(
    webhook_sender, billing_db, auth_emails
) -> None:
    """Stripe does not order deliveries, so the subscription's own metadata links a new row."""
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails("early-subscription"))
    customer_id = make_stripe_id("cus")
    subscription_id = make_stripe_id("sub")
    subscription = build_subscription(
        subscription_id, customer_id, "active", metadata={"user_id": str(user_id)}
    )

    response = await webhook_sender.deliver(
        build_stripe_event("customer.subscription.created", subscription)
    )

    assert response.status_code == 200, response.text
    stored = await billing_db.read_subscription(user_id)
    assert stored is not None
    assert stored.status == "active"
    assert stored.plan_id == "price_Pro1"
    assert stored.stripe_customer_id == customer_id
    assert stored.stripe_subscription_id == subscription_id
    assert stored.current_period_end == PERIOD_END_AT


@pytest.mark.integration
async def test_b51_a_subscription_event_for_an_unknown_subscription_changes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """No row names the subscription and no metadata names a user, so nothing is written."""
    user_id, _customer_id, _subscription_id = await seed_linked_user(
        billing_db, auth_emails, "unknown-subscription"
    )
    before = await billing_db.read_subscription(user_id)
    subscription = build_subscription(make_stripe_id("sub"), make_stripe_id("cus"), "active")
    event = build_stripe_event("customer.subscription.updated", subscription)

    response = await webhook_sender.deliver(event)

    assert response.status_code == 200, response.text
    assert await billing_db.read_subscription(user_id) == before
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "processed"


@pytest.mark.integration
async def test_b51_a_late_event_for_a_replaced_subscription_leaves_the_newer_one_alone(
    webhook_sender, billing_db, auth_emails
) -> None:
    """The user moved from S1 to S2; S1's late event, metadata and all, must not repoint the row.

    No row names S1 any more, so the handler reaches the `metadata.user_id` fallback, and the
    user's row names a different subscription, which the fallback may never overwrite.
    """
    user_id, customer_id, _current_subscription_id = await seed_linked_user(
        billing_db, auth_emails, "replaced-subscription"
    )
    before = await billing_db.read_subscription(user_id)
    replaced_subscription = build_subscription(
        make_stripe_id("sub"), customer_id, "canceled", metadata={"user_id": str(user_id)}
    )
    event = build_stripe_event("customer.subscription.updated", replaced_subscription)

    response = await webhook_sender.deliver(event)

    assert response.status_code == 200, response.text
    assert await billing_db.read_subscription(user_id) == before
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "processed"


@pytest.mark.integration
async def test_b51_a_subscription_event_fills_a_row_that_names_no_subscription_yet(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A row holding only the customer takes the subscription its metadata links to the user."""
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails("customer-only"))
    customer_id = make_stripe_id("cus")
    await billing_db.seed_subscription(user_id, customer_id)
    subscription_id = make_stripe_id("sub")
    subscription = build_subscription(
        subscription_id, customer_id, "active", metadata={"user_id": str(user_id)}
    )

    response = await webhook_sender.deliver(
        build_stripe_event("customer.subscription.created", subscription)
    )

    assert response.status_code == 200, response.text
    stored = await billing_db.read_subscription(user_id)
    assert stored.stripe_subscription_id == subscription_id
    assert stored.status == "active"


@pytest.mark.integration
async def test_b51_an_update_created_before_the_deletion_but_delivered_after_it_changes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """Stripe does not order deliveries, so an older `updated` must not revive a canceled row.

    The late update carries the user's metadata too, so neither the update by subscription id nor
    the metadata fallback may apply it.
    """
    user_id, customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "out-of-order"
    )
    metadata = {"user_id": str(user_id)}
    deleted_at = int(time.time())
    deletion = build_stripe_event(
        "customer.subscription.deleted",
        build_subscription(subscription_id, customer_id, "canceled", metadata=metadata),
        created=deleted_at,
    )
    late_update = build_stripe_event(
        "customer.subscription.updated",
        build_subscription(subscription_id, customer_id, "active", metadata=metadata),
        created=deleted_at - EARLIER_EVENT_SECONDS,
    )

    deleted = await webhook_sender.deliver(deletion)
    canceled = await billing_db.read_subscription(user_id)
    updated = await webhook_sender.deliver(late_update)

    assert deleted.status_code == 200, deleted.text
    assert canceled.status == "canceled"
    assert updated.status_code == 200, updated.text
    assert await billing_db.read_subscription(user_id) == canceled
    [ledger_row] = await webhook_sender.read_ledger(late_update["id"])
    assert ledger_row.status == "processed"


@pytest.mark.integration
async def test_b51_a_subscription_event_created_in_the_same_second_as_the_last_is_applied(
    webhook_sender, billing_db, auth_emails
) -> None:
    """Stripe stamps whole seconds, so an event as old as the stored one is still applied."""
    user_id, customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "same-second"
    )
    created_at = int(time.time())
    for status in ("trialing", "active"):
        response = await webhook_sender.deliver(
            build_stripe_event(
                "customer.subscription.updated",
                build_subscription(subscription_id, customer_id, status),
                created=created_at,
            )
        )
        assert response.status_code == 200, response.text

    assert (await billing_db.read_subscription(user_id)).status == "active"


@pytest.mark.integration
@pytest.mark.parametrize("is_parent_shape", [True, False])
async def test_b51_invoice_payment_failed_sets_past_due(
    webhook_sender, billing_db, auth_emails, is_parent_shape
) -> None:
    """The invoice's subscription, in either API version's shape, is marked past_due."""
    user_id, customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "payment-failed"
    )
    invoice: dict[str, Any] = {
        "id": make_stripe_id("in"),
        "object": "invoice",
        "customer": customer_id,
    }
    if is_parent_shape:
        invoice["parent"] = {
            "type": "subscription_details",
            "subscription_details": {"subscription": subscription_id},
        }
    else:
        invoice["subscription"] = subscription_id

    response = await webhook_sender.deliver(build_stripe_event("invoice.payment_failed", invoice))

    assert response.status_code == 200, response.text
    stored = await billing_db.read_subscription(user_id)
    assert stored.status == "past_due"
    assert stored.stripe_subscription_id == subscription_id


@pytest.mark.integration
async def test_b41_b42_a_failed_event_is_marked_failed_then_processed_on_redelivery(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A handler that raises marks the event failed and answers 500; Stripe's retry processes it.

    The checkout names a user who does not exist yet, so linking the row violates the foreign
    key. Once the user exists, the same event delivered again is claimed again and applied.
    """
    missing_user_id = uuid.uuid4()
    customer_id = make_stripe_id("cus")
    subscription_id = make_stripe_id("sub")
    event = build_stripe_event(
        "checkout.session.completed",
        build_checkout_session(missing_user_id, customer_id, subscription_id),
    )

    failed = await webhook_sender.deliver(event)
    failed_rows = await webhook_sender.read_ledger(event["id"])
    await webhook_sender.seed_user_with_id(missing_user_id, auth_emails("late-user"))
    redelivered = await webhook_sender.deliver(event)
    processed_rows = await webhook_sender.read_ledger(event["id"])

    assert failed.status_code == 500, failed.text
    assert failed.json()["code"] == "BILLING_WEBHOOK_PROCESSING_FAILED"
    assert [row.status for row in failed_rows] == ["failed"]
    assert failed_rows[0].processed_at is None
    assert redelivered.status_code == 200, redelivered.text
    assert [row.status for row in processed_rows] == ["processed"]
    assert processed_rows[0].attempted_at > failed_rows[0].attempted_at
    stored = await billing_db.read_subscription(missing_user_id)
    assert stored.stripe_customer_id == customer_id
    assert stored.stripe_subscription_id == subscription_id


@pytest.mark.integration
async def test_b41_a_claim_older_than_ten_minutes_is_taken_over_on_redelivery(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A claim a crashed handler left behind is claimed again, applied, and marked processed."""
    user_id, _customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "stale-claim"
    )
    event = build_payment_failed_event(subscription_id)
    await webhook_sender.seed_ledger(event["id"], event["type"], "claimed", STALE_CLAIM_MINUTES_AGO)

    response = await webhook_sender.deliver(event)

    assert response.status_code == 200, response.text
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "processed"
    assert (await billing_db.read_subscription(user_id)).status == "past_due"


@pytest.mark.integration
async def test_b41_a_fresh_claim_held_by_another_delivery_answers_409_so_stripe_retries(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A claim younger than ten minutes may still crash, so the delivery is refused, not acked.

    Answering 200 here would end Stripe's retries while the event's only other delivery might yet
    fail, losing the event; a 409 leaves Stripe to deliver it again after the holder finishes.
    """
    user_id, _customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "fresh-claim"
    )
    before = await billing_db.read_subscription(user_id)
    event = build_payment_failed_event(subscription_id)
    await webhook_sender.seed_ledger(event["id"], event["type"], "claimed", FRESH_CLAIM_MINUTES_AGO)

    response = await webhook_sender.deliver(event)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_IN_PROGRESS"
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "claimed"
    assert await billing_db.read_subscription(user_id) == before


@pytest.mark.integration
async def test_b21_an_event_already_processed_answers_200_and_changes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A redelivery of a processed event is acknowledged, and neither table moves."""
    user_id, _customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "already-processed"
    )
    before = await billing_db.read_subscription(user_id)
    event = build_payment_failed_event(subscription_id)
    await webhook_sender.seed_ledger(
        event["id"], event["type"], "processed", FRESH_CLAIM_MINUTES_AGO
    )
    [seeded_row] = await webhook_sender.read_ledger(event["id"])

    response = await webhook_sender.deliver(event)

    assert response.status_code == 200, response.text
    assert response.json() == RECEIVED_BODY
    assert await webhook_sender.read_ledger(event["id"]) == [seeded_row]
    assert await billing_db.read_subscription(user_id) == before


@pytest.mark.integration
async def test_b42_an_unparseable_event_object_is_marked_failed_and_changes_nothing(
    webhook_sender, billing_db, auth_emails
) -> None:
    """A subscription whose status Stripe never sends fails its handler and is left to retry."""
    user_id, customer_id, subscription_id = await seed_linked_user(
        billing_db, auth_emails, "bad-status"
    )
    before = await billing_db.read_subscription(user_id)
    event = build_stripe_event(
        "customer.subscription.updated",
        build_subscription(subscription_id, customer_id, "not_a_status"),
    )

    response = await webhook_sender.deliver(event)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_PROCESSING_FAILED"
    assert [row.status for row in await webhook_sender.read_ledger(event["id"])] == ["failed"]
    assert await billing_db.read_subscription(user_id) == before


@pytest.mark.integration
async def test_b6_b7_the_webhook_is_exempt_from_csrf_and_both_rate_limit_buckets(
    webhook_sender,
) -> None:
    """More deliveries than the global limit, none carrying the CSRF header, are all accepted."""
    statuses = []
    for _ in range(GLOBAL_RATE_LIMIT + 5):
        event = build_stripe_event("customer.updated", {"id": make_stripe_id("cus")})
        response = await webhook_sender.deliver(event)
        statuses.append(response.status_code)

    assert set(statuses) == {200}
