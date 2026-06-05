"""SQLAlchemy ORM models for durable conversation history."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BigInteger doesn't autoincrement on SQLite (used in tests); fall back to
# INTEGER there so primary keys auto-populate. Postgres keeps BIGINT/BIGSERIAL.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
# JSONB on Postgres, plain JSON on SQLite (tests).
JsonDoc = JSONB().with_variant(JSON, "sqlite")


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    session_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set by the idle-sweeper when the session is finalised into durable memory.
    # Re-eligible if last_active_at later exceeds this (session resumed).
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    summaries: Mapped[list["Summary"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        Index("ix_messages_session_created", "session_id", "created_at"),
        # Supports load_messages_after(user_id, after_id) for fact extraction.
        Index("ix_messages_user_id", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    platform_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="messages")


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = (
        Index("ix_summaries_session_created", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id"), nullable=False
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    covers_through_message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=True
    )
    turn_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="summaries")


class User(Base):
    """Console account. The first account created is promoted to `admin`."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Document(Base):
    """Registry of curated RAG documents. Source of truth for the doc list / UI;
    chunks live in Qdrant. `enabled` gates retrieval (mirrored to Qdrant payload)."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_type: Mapped[str] = mapped_column(String, nullable=False, default="prose")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AppSetting(Base):
    """Generic key-value store for admin-editable runtime settings.
    Currently holds key "system_prompt" (the global agent persona override)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MessageFeedback(Base):
    """A user's 👍/👎 on an assistant reply. One rating per (message, user)."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
        CheckConstraint("rating IN (-1, 1)", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 👍 / -1 👎
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserMemory(Base):
    """Per-user durable memory document (tier-3), keyed platform:user_id."""

    __tablename__ = "user_memory"

    user_key: Mapped[str] = mapped_column(String, primary_key=True)
    document: Mapped[dict] = mapped_column(JsonDoc, nullable=False)
    # Cursor: highest message id already considered for fact extraction.
    last_extracted_message_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------- eval logging
class LlmCall(Base):
    """Lightweight telemetry for every LLM call (cost / latency / usage).
    The main reply additionally gets a rich EvalTrace; internal calls
    (classifier/summarizer/fact_extract/judge) only land here."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_created", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    call_type: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[bool] = mapped_column(default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_key: Mapped[str | None] = mapped_column(String, nullable=True)
    user_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalTrace(Base):
    """Rich record of one main-reply turn: the full assembled context, the reply,
    routing tier, token/latency telemetry. Parent of EvalRetrievedChunk."""

    __tablename__ = "eval_traces"
    __table_args__ = (
        Index("ix_eval_traces_created", "created_at"),
        Index("ix_eval_traces_session_key", "session_key"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    llm_call_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("llm_calls.id"), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_db_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sessions.id"), nullable=True
    )
    session_key: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    reranked: Mapped[bool] = mapped_column(default=False, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    messages: Mapped[dict | None] = mapped_column(JsonDoc, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=True
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list["EvalRetrievedChunk"]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )


class EvalRetrievedChunk(Base):
    """One retrieved candidate for a trace, with its scores/ranks and whether it
    made the final top-k injected into the prompt. Judge labels + golden-set
    relevance join here on (doc_id, chunk_index)."""

    __tablename__ = "eval_retrieved_chunks"
    __table_args__ = (
        Index("ix_eval_chunks_trace", "trace_id"),
        Index("ix_eval_chunks_doc", "doc_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_traces.id"), nullable=False
    )
    doc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fused_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fused_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    included: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trace: Mapped[EvalTrace] = relationship(back_populates="chunks")


class EvalGoldenQuery(Base):
    """Reserved for offline eval: a query with an optional reference answer.
    Populated later; enables true Recall@k / Correctness."""

    __tablename__ = "eval_golden_queries"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    relevant_chunks: Mapped[list["EvalGoldenRelevantChunk"]] = relationship(
        back_populates="golden_query", cascade="all, delete-orphan"
    )


class EvalGoldenRelevantChunk(Base):
    """Reserved: a chunk known to be relevant to a golden query, with a graded
    relevance label (e.g. 0–3) for NDCG / Recall@k."""

    __tablename__ = "eval_golden_relevant_chunks"
    __table_args__ = (
        Index("ix_golden_rel_query", "golden_query_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    golden_query_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_golden_queries.id"), nullable=False
    )
    doc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    golden_query: Mapped[EvalGoldenQuery] = relationship(
        back_populates="relevant_chunks"
    )


# ----------------------------------------------- eval judgements (Phase B: judge)
class EvalJudgement(Base):
    """One LLM-as-judge score for a trace+metric. Tall + re-judgeable: a re-run
    appends new rows (latest-wins by created_at), tagged with model + run id."""

    __tablename__ = "eval_judgements"
    __table_args__ = (
        Index("ix_eval_judgements_trace_metric", "trace_id", "metric"),
        Index("ix_eval_judgements_run", "judge_run_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_traces.id"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0–1, null=N/A
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String, nullable=True)
    judge_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalChunkLabel(Base):
    """Judge's relevance label for one retrieved chunk (enables Precision@k / MRR /
    NDCG / Hit Rate over the retrieved set)."""

    __tablename__ = "eval_chunk_labels"
    __table_args__ = (
        Index("ix_eval_chunk_labels_trace", "trace_id"),
        Index("ix_eval_chunk_labels_chunk", "chunk_ref_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_traces.id"), nullable=False
    )
    chunk_ref_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("eval_retrieved_chunks.id"), nullable=True
    )
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0–1
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String, nullable=True)
    judge_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
