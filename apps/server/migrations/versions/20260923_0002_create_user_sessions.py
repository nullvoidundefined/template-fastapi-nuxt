"""Create the user_sessions table, its unique token hash, and the expiry index.

The table stores the SHA-256 of the cookie's token rather than the token, so a database leak hands
over no live session. `ON DELETE CASCADE` on the user makes deleting an account sign it out
everywhere without a second statement, and the index on `expires_at` is what lets slice 08's
hourly cleanup find expired rows without scanning.

No `set_updated_at` trigger: a session has no `updated_at`. `last_seen_at` is written explicitly,
and at most once every five minutes, by `app/repositories/user_sessions.py`.

Revision ID: 20260923_0002
Revises: 20260923_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0002"
down_revision = "20260923_0001"
branch_labels = None
depends_on = None

USER_SESSIONS_TABLE_NAME = "user_sessions"
EXPIRES_AT_INDEX_NAME = "ix_user_sessions_expires_at"
UNIQUE_HASH_CONSTRAINT_NAME = "uq_user_sessions_token_hash"


def upgrade() -> None:
    """Create the table, the unique constraint on the token hash, and the expiry index."""
    op.create_table(
        USER_SESSIONS_TABLE_NAME,
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        UNIQUE_HASH_CONSTRAINT_NAME, USER_SESSIONS_TABLE_NAME, ["token_hash"]
    )
    op.create_index(EXPIRES_AT_INDEX_NAME, USER_SESSIONS_TABLE_NAME, ["expires_at"])


def downgrade() -> None:
    """Drop the table, which takes its index and constraints with it."""
    op.drop_table(USER_SESSIONS_TABLE_NAME)
