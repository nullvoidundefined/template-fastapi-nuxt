"""Add the raw response columns to request_idempotency_keys: body bytes, content type, headers.

This is the expand half of an expand/contract change. Revision 0005 stored a completed response
as a JSONB body alone, which cannot hold a plain-text or binary body and has nowhere to keep the
handler's headers. The three new columns are nullable, so the statement is a catalog change that
rewrites no rows, and `response_body` stays: a row completed before the deploy still replays from
it, and a replica still running the previous release still reads the column it knows. The
contract step, dropping `response_body`, can run once every row written before this revision has
aged past the twenty-four hour replay window and no replica reads it.

`response_headers` holds the allowlisted headers as a JSON array of `[name, value]` pairs rather
than an object, because a header may repeat and order is part of what is replayed.

Revision ID: 20260924_0008
Revises: 20260924_0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0008"
down_revision = "20260924_0007"
branch_labels = None
depends_on = None

KEYS_TABLE_NAME = "request_idempotency_keys"


def upgrade() -> None:
    """Add the three nullable response columns beside the JSONB body."""
    op.add_column(
        KEYS_TABLE_NAME, sa.Column("response_body_bytes", sa.LargeBinary(), nullable=True)
    )
    op.add_column(KEYS_TABLE_NAME, sa.Column("response_content_type", sa.Text(), nullable=True))
    op.add_column(KEYS_TABLE_NAME, sa.Column("response_headers", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the three columns, leaving the JSONB body revision 0005 created."""
    op.drop_column(KEYS_TABLE_NAME, "response_headers")
    op.drop_column(KEYS_TABLE_NAME, "response_content_type")
    op.drop_column(KEYS_TABLE_NAME, "response_body_bytes")
