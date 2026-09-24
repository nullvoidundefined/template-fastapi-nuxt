"""Create billing_webhook_events, the idempotent ledger of Stripe webhook deliveries.

One row per Stripe event id, which is the conflict target of the claim upsert: a delivery claims
its event, and a redelivery reclaims it only when the earlier attempt failed or its claim is more
than ten minutes old. `attempted_at` records the latest claim and `processed_at` the success. The
index on `attempted_at` serves the slice 08 cleanup of rows older than thirty days.

The ledger has no foreign key to a user: it records deliveries, and a delivery outlives any one
account. No `set_updated_at` trigger, because every change of state is written with its own time.

Revision ID: 20260924_0007
Revises: 20260924_0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0007"
down_revision = "20260924_0006"
branch_labels = None
depends_on = None

EVENTS_TABLE_NAME = "billing_webhook_events"
ATTEMPTED_AT_INDEX_NAME = "ix_billing_webhook_events_attempted_at"

event_status = postgresql.ENUM(
    "claimed", "processed", "failed", name="billing_webhook_event_status", create_type=False
)


def upgrade() -> None:
    """Create the enum, then the ledger keyed on the Stripe event id, then its cleanup index."""
    event_status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        EVENTS_TABLE_NAME,
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("stripe_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", event_status, nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("stripe_event_id", name="uq_billing_webhook_events_stripe_event_id"),
    )
    op.create_index(ATTEMPTED_AT_INDEX_NAME, EVENTS_TABLE_NAME, ["attempted_at"])


def downgrade() -> None:
    """Drop the table, which takes its index with it, then the enum."""
    op.drop_table(EVENTS_TABLE_NAME)
    event_status.drop(op.get_bind(), checkfirst=False)
