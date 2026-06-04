"""eval logging: llm_calls, eval_traces, eval_retrieved_chunks + golden-set tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

BigIntPK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JsonDoc = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("call_type", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("session_key", sa.String(), nullable=True),
        sa.Column("user_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_calls_created", "llm_calls", ["created_at"])

    op.create_table(
        "eval_traces",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("llm_call_id", sa.BigInteger(), sa.ForeignKey("llm_calls.id"), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("session_db_id", sa.BigInteger(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("session_key", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("rag_tier", sa.String(), nullable=True),
        sa.Column("reranked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("knowledge_text", sa.Text(), nullable=True),
        sa.Column("messages", JsonDoc, nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("reply_message_id", sa.BigInteger(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=True),
        sa.Column("generation_latency_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_traces_created", "eval_traces", ["created_at"])
    op.create_index("ix_eval_traces_session_key", "eval_traces", ["session_key"])

    op.create_table(
        "eval_retrieved_chunks",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("eval_traces.id"), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("point_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=True),
        sa.Column("fused_score", sa.Float(), nullable=True),
        sa.Column("fused_rank", sa.Integer(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_chunks_trace", "eval_retrieved_chunks", ["trace_id"])
    op.create_index("ix_eval_chunks_doc", "eval_retrieved_chunks", ["doc_id", "chunk_index"])

    op.create_table(
        "eval_golden_queries",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "eval_golden_relevant_chunks",
        sa.Column("id", BigIntPK, primary_key=True),
        sa.Column("golden_query_id", sa.BigInteger(),
                  sa.ForeignKey("eval_golden_queries.id"), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_golden_rel_query", "eval_golden_relevant_chunks", ["golden_query_id"])


def downgrade() -> None:
    op.drop_table("eval_golden_relevant_chunks")
    op.drop_table("eval_golden_queries")
    op.drop_table("eval_retrieved_chunks")
    op.drop_table("eval_traces")
    op.drop_table("llm_calls")
