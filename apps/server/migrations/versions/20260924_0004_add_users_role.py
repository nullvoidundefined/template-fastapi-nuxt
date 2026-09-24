"""Add the user_role enum and the users.role column, backfilling every existing user as a member.

The column is added NOT NULL with a constant default in one statement. Postgres fills every
existing row with the default as part of the ALTER, so the backfill the data model asks for needs
no separate UPDATE and there is no moment at which a user has no role.

The enum is created and dropped explicitly, because autogenerate does not manage an enum's
lifecycle and the column type is declared with `create_type=False`.

Revision ID: 20260924_0004
Revises: 20260924_0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0004"
down_revision = "20260924_0003"
branch_labels = None
depends_on = None

USERS_TABLE_NAME = "users"
ROLE_COLUMN_NAME = "role"

user_role = postgresql.ENUM("member", "admin", name="user_role", create_type=False)


def upgrade() -> None:
    """Create the enum, then add the column, which backfills every existing row to member."""
    user_role.create(op.get_bind(), checkfirst=False)
    op.add_column(
        USERS_TABLE_NAME,
        sa.Column(ROLE_COLUMN_NAME, user_role, nullable=False, server_default="member"),
    )


def downgrade() -> None:
    """Drop the column, then the enum it used."""
    op.drop_column(USERS_TABLE_NAME, ROLE_COLUMN_NAME)
    user_role.drop(op.get_bind(), checkfirst=False)
