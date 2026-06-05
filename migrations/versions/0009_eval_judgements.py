"""eval judgements: eval_judgements + eval_chunk_labels (LLM-as-judge, Phase B)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

BigIntPK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "eval_judgements",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("eval_traces.id"), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("judge_provider", sa.String(), nullable=True),
        sa.Column("judge_model", sa.String(), nullable=True),
        sa.Column("judge_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_judgements_trace_metric", "eval_judgements", ["trace_id", "metric"])
    op.create_index("ix_eval_judgements_run", "eval_judgements", ["judge_run_id"])

    op.create_table(
        "eval_chunk_labels",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("eval_traces.id"), nullable=False),
        sa.Column("chunk_ref_id", sa.BigInteger(),
                  sa.ForeignKey("eval_retrieved_chunks.id"), nullable=True),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("judge_provider", sa.String(), nullable=True),
        sa.Column("judge_model", sa.String(), nullable=True),
        sa.Column("judge_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_chunk_labels_trace", "eval_chunk_labels", ["trace_id"])
    op.create_index("ix_eval_chunk_labels_chunk", "eval_chunk_labels", ["chunk_ref_id"])


def downgrade() -> None:
    op.drop_table("eval_chunk_labels")
    op.drop_table("eval_judgements")
