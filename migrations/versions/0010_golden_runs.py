"""golden eval runs: eval_golden_runs + eval_golden_results (Phase C)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

BigIntPK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JsonDoc = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "eval_golden_runs",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("k_values", JsonDoc, nullable=True),
        sa.Column("num_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("judge_model", sa.String(), nullable=True),
        sa.Column("aggregate", JsonDoc, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "eval_golden_results",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("eval_golden_runs.id"), nullable=False),
        sa.Column("golden_query_id", sa.BigInteger(),
                  sa.ForeignKey("eval_golden_queries.id"), nullable=True),
        sa.Column("retrieved", JsonDoc, nullable=True),
        sa.Column("metrics", JsonDoc, nullable=True),
        sa.Column("generated_answer", sa.Text(), nullable=True),
        sa.Column("correctness", sa.Float(), nullable=True),
        sa.Column("correctness_reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_golden_results_run", "eval_golden_results", ["run_id"])
    op.create_index("ix_golden_results_query", "eval_golden_results", ["golden_query_id"])


def downgrade() -> None:
    op.drop_table("eval_golden_results")
    op.drop_table("eval_golden_runs")
