"""tier-3 user_memory table + messages(user_id) index

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_memory",
        sa.Column("user_key", sa.String(), primary_key=True),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("last_extracted_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_messages_user_id", "messages", ["user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_messages_user_id", table_name="messages")
    op.drop_table("user_memory")
