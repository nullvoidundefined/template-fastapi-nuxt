"""Create user_subscriptions, its status enum, and its set_updated_at trigger.

One row per user, holding the user's Stripe billing state as the webhook last wrote it. The
Stripe customer and subscription ids are each unique, because the webhook finds a row by either
one, and both are nullable, because a row can exist before Stripe has named both. `ON DELETE
CASCADE` removes a deleted account's row with it; the unique constraint on `user_id` is also the
index the portal's lookup uses.

The status enum holds the Express template's `subscription_status` values, which are Stripe's own,
and defaults to `incomplete`, which is what Stripe calls a subscription that has not yet been paid.

Revision ID: 20260924_0006
Revises: 20260924_0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0006"
down_revision = "20260924_0005"
branch_labels = None
depends_on = None

SUBSCRIPTIONS_TABLE_NAME = "user_subscriptions"
SUBSCRIPTIONS_TRIGGER_NAME = "user_subscriptions_set_updated_at"
# The function itself was created by the first revision and is shared by every table.
CREATE_SUBSCRIPTIONS_TRIGGER = f"""
CREATE TRIGGER {SUBSCRIPTIONS_TRIGGER_NAME}
BEFORE UPDATE ON {SUBSCRIPTIONS_TABLE_NAME}
FOR EACH ROW EXECUTE FUNCTION set_updated_at()
"""

subscription_status = postgresql.ENUM(
    "active",
    "canceled",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "paused",
    "trialing",
    "unpaid",
    name="user_subscription_status",
    create_type=False,
)


def upgrade() -> None:
    """Create the enum, then the table with its unique ids, then the updated_at trigger."""
    subscription_status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        SUBSCRIPTIONS_TABLE_NAME,
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column("plan_id", sa.Text(), nullable=True),
        sa.Column("status", subscription_status, nullable=False, server_default="incomplete"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_canceling_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", name="uq_user_subscriptions_user_id"),
        sa.UniqueConstraint("stripe_customer_id", name="uq_user_subscriptions_stripe_customer_id"),
        sa.UniqueConstraint(
            "stripe_subscription_id", name="uq_user_subscriptions_stripe_subscription_id"
        ),
    )
    op.execute(CREATE_SUBSCRIPTIONS_TRIGGER)


def downgrade() -> None:
    """Drop the table, which takes its trigger and constraints with it, then the enum."""
    op.drop_table(SUBSCRIPTIONS_TABLE_NAME)
    subscription_status.drop(op.get_bind(), checkfirst=False)
