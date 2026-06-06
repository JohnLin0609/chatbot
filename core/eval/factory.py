"""Build the eval runners (judge + golden) with a (possibly overridden) judge model."""

from core.eval.instrument import InstrumentedChatService
from core.eval.judge import Judge
from core.eval.logger import EvalLogger, NullEvalLogger
from core.eval.runner import JudgeRunner
from core.llm.factory import build_chat_service
from core.tokens.counter import TokenCounter


def _eval_logger(settings, sessionmaker):
    counter = TokenCounter(settings.tiktoken_encoding)
    if settings.eval_logging_enabled:
        return EvalLogger(sessionmaker, counter, settings)
    return NullEvalLogger()


def _judge_settings(settings):
    update = {}
    if settings.judge_provider:
        update["provider"] = settings.judge_provider
    if settings.judge_model:
        update["model"] = settings.judge_model
    return settings.model_copy(update=update) if update else settings


def build_judge(settings, sessionmaker) -> Judge:
    """A Judge backed by the configured judge model, instrumented so its calls
    land in llm_calls."""
    js = _judge_settings(settings)
    logger = (EvalLogger(sessionmaker, TokenCounter(settings.tiktoken_encoding), js)
              if settings.eval_logging_enabled else NullEvalLogger())
    instrumented = InstrumentedChatService(build_chat_service(js), logger, "judge")
    return Judge(instrumented, js)


def build_judge_runner(settings, sessionmaker) -> JudgeRunner:
    return JudgeRunner(sessionmaker, build_judge(settings, sessionmaker), settings)


def build_golden_runner(settings, sessionmaker):
    """Assemble the retrieval stack + answer generator + correctness judge."""
    from core.eval.golden_runner import GoldenRunner
    from core.rag.embeddings import build_embedding_service
    from core.rag.reranker import build_reranker
    from core.rag.retriever import RagRetriever
    from core.rag.sparse import build_sparse_embedder
    from core.rag.vector_store import QdrantVectorStore

    store = QdrantVectorStore(
        settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim,
        settings.rag_sparse_vector_name,
    )
    retriever = RagRetriever(
        store, build_embedding_service(settings), build_sparse_embedder(settings), settings)
    reranker = build_reranker(settings)
    # answer generation uses the MAIN model (the system's real model), instrumented
    gen_chat = InstrumentedChatService(
        build_chat_service(settings), _eval_logger(settings, sessionmaker), "golden_gen")
    judge = build_judge(settings, sessionmaker)
    return GoldenRunner(sessionmaker, retriever, reranker, gen_chat, judge, settings)
