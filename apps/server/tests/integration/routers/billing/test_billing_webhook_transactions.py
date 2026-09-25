"""B-41, B-42: how the webhook's writes and its ledger marks share or survive a failed transaction.

The handler's writes and the `processed` mark commit in one transaction, so a failure of the mark
must roll the handler's writes back with it; the event is then marked `failed` for Stripe to
redeliver. Marking it failed is best effort: when that write fails too, the delivery still answers
500 `BILLING_WEBHOOK_PROCESSING_FAILED` and the claim is left for a redelivery to take over once
it is stale.

Each failure is a real Postgres error raised on the connection the service hands the ledger
function, by a stand-in that divides by zero in SQL, so the transaction is genuinely aborted
rather than an exception thrown beside it. Everything else is the application `create_app()`
assembles, delivering signed events as Stripe does.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.routers.billing.conftest import (
    BillingDatabase,
    WebhookSender,
    build_stripe_event,
    make_stripe_id,
)
from tests.integration.routers.conftest import EmailFactory

SERVICE_MODULE = "app.services.billing.process_webhook_event"
FAILING_STATEMENT = text("SELECT 1 / 0")


async def fail_in_database(connection: AsyncConnection, _stripe_event_id: str) -> None:
    """Stand in for a ledger mark by raising Postgres's own division-by-zero error."""
    await connection.execute(FAILING_STATEMENT)


@pytest.mark.integration
async def test_b41_a_failed_processed_mark_rolls_back_the_handlers_writes(
    webhook_sender: WebhookSender,
    billing_db: BillingDatabase,
    auth_emails: EmailFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The checkout's link and the mark are one transaction, so neither survives the other."""
    monkeypatch.setattr(f"{SERVICE_MODULE}.mark_webhook_event_processed", fail_in_database)
    user_id, _raw_token = await billing_db.seed_signed_in_user(auth_emails("mark-fails"))
    event = build_stripe_event(
        "checkout.session.completed",
        {
            "id": make_stripe_id("cs"),
            "object": "checkout.session",
            "mode": "subscription",
            "customer": make_stripe_id("cus"),
            "subscription": make_stripe_id("sub"),
            "metadata": {"user_id": str(user_id)},
        },
    )

    response = await webhook_sender.deliver(event)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_PROCESSING_FAILED"
    assert await billing_db.read_subscription(user_id) is None
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "failed"
    assert ledger_row.processed_at is None


@pytest.mark.integration
async def test_b42_a_failed_failure_mark_still_answers_500_and_leaves_the_claim(
    webhook_sender: WebhookSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any database error marking the event failed is logged, not raised over the 500 answer."""
    monkeypatch.setattr(f"{SERVICE_MODULE}.mark_webhook_event_failed", fail_in_database)
    unparseable_subscription = {
        "id": make_stripe_id("sub"),
        "object": "subscription",
        "customer": make_stripe_id("cus"),
        "status": "not_a_status",
        "cancel_at_period_end": False,
        "items": {"object": "list", "data": []},
        "metadata": {},
    }
    event = build_stripe_event("customer.subscription.updated", unparseable_subscription)

    response = await webhook_sender.deliver(event)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "BILLING_WEBHOOK_PROCESSING_FAILED"
    [ledger_row] = await webhook_sender.read_ledger(event["id"])
    assert ledger_row.status == "claimed"
