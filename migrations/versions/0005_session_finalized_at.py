"""sessions.finalized_at (idle-sweeper finalization marker) + index

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_last_active_at", "sessions", ["last_active_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_last_active_at", table_name="sessions")
    op.drop_column("sessions", "finalized_at")
