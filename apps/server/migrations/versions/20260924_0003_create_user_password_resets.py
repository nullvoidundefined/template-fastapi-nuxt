"""Create the user_password_resets table, its unique token hash, and its two indexes.

Like a session, a reset stores only the SHA-256 of the token the email carries, so a database
leak hands over no working link. `ON DELETE CASCADE` on the user removes an account's resets with
it. The index on `user_id` serves the delete that retires a user's earlier unused resets whenever
a new one is issued, and the index on `expires_at` is what lets slice 08's hourly cleanup find
expired rows without scanning.

No `set_updated_at` trigger: a reset has no `updated_at`. Its one change of state is `used_at`,
written by the single atomic statement that consumes it.

Revision ID: 20260924_0003
Revises: 20260923_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0003"
down_revision = "20260923_0002"
branch_labels = None
depends_on = None

RESETS_TABLE_NAME = "user_password_resets"
USER_ID_INDEX_NAME = "ix_user_password_resets_user_id"
EXPIRES_AT_INDEX_NAME = "ix_user_password_resets_expires_at"
UNIQUE_HASH_CONSTRAINT_NAME = "uq_user_password_resets_token_hash"


def upgrade() -> None:
    """Create the table, the unique constraint on the token hash, and both indexes."""
    op.create_table(
        RESETS_TABLE_NAME,
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(UNIQUE_HASH_CONSTRAINT_NAME, RESETS_TABLE_NAME, ["token_hash"])
    op.create_index(USER_ID_INDEX_NAME, RESETS_TABLE_NAME, ["user_id"])
    op.create_index(EXPIRES_AT_INDEX_NAME, RESETS_TABLE_NAME, ["expires_at"])


def downgrade() -> None:
    """Drop the table, which takes its indexes and constraints with it."""
    op.drop_table(RESETS_TABLE_NAME)
