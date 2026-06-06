"""Judge.judge_trace: parses generation metrics + per-chunk relevance labels."""

from types import SimpleNamespace

from core.eval.judge import Judge
from tests.conftest import make_settings


class FakeJudgeChat:
    """Returns canned JSON depending on which judge prompt it sees."""

    def __init__(self, raw=None):
        self._raw = raw

    async def generate_reply(self, session_id, messages):
        if self._raw is not None:
            return self._raw
        sys = messages[0]["content"]
        if "document chunk" in sys:  # chunk-relevance call
            return ('{"chunks":[{"index":0,"relevance":1.0,"reasoning":"hit"},'
                    '{"index":1,"relevance":0.0,"reasoning":"miss"}]}')
        if "NO retrieved context" in sys:  # no-context generation call
            return '{"answer_relevance":{"score":0.6,"reasoning":"ok"}}'
        return ('{"faithfulness":{"score":0.8,"reasoning":"grounded"},'
                '"answer_relevance":{"score":0.9,"reasoning":"on point"},'
                '"context_utilization":{"score":0.7,"reasoning":"uses ctx"}}')


def _trace(query="q?", reply="a", knowledge="ctx"):
    return SimpleNamespace(id=1, query=query, reply_text=reply, knowledge_text=knowledge)


def _chunks(n):
    return [SimpleNamespace(id=100 + i, chunk_text=f"chunk {i}") for i in range(n)]


async def test_judge_with_context_scores_all_and_labels_chunks():
    judge = Judge(FakeJudgeChat(), make_settings())
    res = await judge.judge_trace(_trace(), _chunks(2))
    scores = {m.metric: m.score for m in res.metrics}
    assert scores == {"faithfulness": 0.8, "answer_relevance": 0.9, "context_utilization": 0.7}
    # chunk labels mapped back to the eval_retrieved_chunk ids
    assert [(c.chunk_ref_id, c.relevance) for c in res.chunk_labels] == [(100, 1.0), (101, 0.0)]


async def test_judge_no_context_only_answer_relevance():
    judge = Judge(FakeJudgeChat(), make_settings())
    res = await judge.judge_trace(_trace(knowledge=""), chunks=[])
    scores = {m.metric: m.score for m in res.metrics}
    assert scores["answer_relevance"] == 0.6
    # context-dependent metrics are present but null
    assert scores["faithfulness"] is None and scores["context_utilization"] is None
    assert res.chunk_labels == []


async def test_judge_malformed_json_yields_null_scores_no_raise():
    judge = Judge(FakeJudgeChat(raw="not json at all"), make_settings())
    res = await judge.judge_trace(_trace(), _chunks(1))
    assert all(m.score is None for m in res.metrics)
    # chunk present but unlabelled (relevance None)
    assert res.chunk_labels[0].chunk_ref_id == 100
    assert res.chunk_labels[0].relevance is None


async def test_judge_correctness():
    judge = Judge(FakeJudgeChat(raw='{"score":0.75,"reasoning":"mostly right"}'),
                  make_settings())
    res = await judge.judge_correctness("q?", "an answer", "the reference")
    assert res.metric == "correctness" and res.score == 0.75
    assert res.reasoning == "mostly right"


async def test_scores_clamped_to_unit_interval():
    judge = Judge(FakeJudgeChat(
        raw='{"faithfulness":{"score":1.7},"answer_relevance":{"score":-3},'
            '"context_utilization":{"score":0.5}}'), make_settings())
    res = await judge.judge_trace(_trace(), chunks=[])
    scores = {m.metric: m.score for m in res.metrics}
    assert scores["faithfulness"] == 1.0 and scores["answer_relevance"] == 0.0
