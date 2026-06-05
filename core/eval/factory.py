"""Build the JudgeRunner with a (possibly overridden) judge model."""

from core.eval.instrument import InstrumentedChatService
from core.eval.judge import Judge
from core.eval.logger import EvalLogger, NullEvalLogger
from core.eval.runner import JudgeRunner
from core.llm.factory import build_chat_service
from core.tokens.counter import TokenCounter


def build_judge_runner(settings, sessionmaker) -> JudgeRunner:
    # Judge model: override provider/model when configured, else the main service.
    judge_settings = settings
    update = {}
    if settings.judge_provider:
        update["provider"] = settings.judge_provider
    if settings.judge_model:
        update["model"] = settings.judge_model
    if update:
        judge_settings = settings.model_copy(update=update)

    chat = build_chat_service(judge_settings)
    counter = TokenCounter(settings.tiktoken_encoding)
    logger = (
        EvalLogger(sessionmaker, counter, judge_settings)
        if settings.eval_logging_enabled
        else NullEvalLogger()
    )
    instrumented = InstrumentedChatService(chat, logger, "judge")
    judge = Judge(instrumented, judge_settings)
    return JudgeRunner(sessionmaker, judge, settings)
