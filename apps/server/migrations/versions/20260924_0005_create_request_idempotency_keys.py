"""Create request_idempotency_keys, its state enum, and the created_at index the cleanup uses.

One row per `(key, user_id)`, which is the primary key and the conflict target of the claim
insert. The row also stores the method, path, and body hash of the request that claimed it, so a
key reused for a different request is refused rather than replayed. `ON DELETE CASCADE` on the
user removes an account's claims with it, and the index on `created_at` is what lets slice 08's
hourly cleanup find rows older than twenty-four hours without scanning.

No `set_updated_at` trigger: a claim has no `updated_at`. Its changes of state are written by the
single statements that take it over, complete it, or release it.

Revision ID: 20260924_0005
Revises: 20260924_0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0005"
down_revision = "20260924_0004"
branch_labels = None
depends_on = None

KEYS_TABLE_NAME = "request_idempotency_keys"
CREATED_AT_INDEX_NAME = "ix_request_idempotency_keys_created_at"

key_state = postgresql.ENUM(
    "in_progress", "completed", name="request_idempotency_key_state", create_type=False
)


def upgrade() -> None:
    """Create the enum, then the table keyed on key and user, then the created_at index."""
    key_state.create(op.get_bind(), checkfirst=False)
    op.create_table(
        KEYS_TABLE_NAME,
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_method", sa.Text(), nullable=False),
        sa.Column("request_path", sa.Text(), nullable=False),
        sa.Column("request_body_hash", sa.Text(), nullable=False),
        sa.Column("state", key_state, nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("key", "user_id", name="pk_request_idempotency_keys"),
    )
    op.create_index(CREATED_AT_INDEX_NAME, KEYS_TABLE_NAME, ["created_at"])


def downgrade() -> None:
    """Drop the table, which takes its index with it, then the enum."""
    op.drop_table(KEYS_TABLE_NAME)
    key_state.drop(op.get_bind(), checkfirst=False)
