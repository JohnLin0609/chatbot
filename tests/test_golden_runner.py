"""GoldenRunner: retrieval metrics + correctness over the golden set."""

from sqlalchemy import select

from core.eval.golden_runner import GoldenRunner
from core.eval.golden_store import GoldenStore
from core.eval.judge import MetricScore
from core.persistence.models import EvalGoldenResult, EvalGoldenRun
from core.rag.vector_store import Hit
from tests.conftest import make_settings


def _hit(doc_id, idx, text="t"):
    return Hit(text=text, score=1.0, title="T",
               payload={"doc_id": doc_id, "chunk_index": idx})


class FakeRetriever:
    def __init__(self, hits):
        self._hits = hits

    async def retrieve(self, query, *, top_k):
        return self._hits[:top_k]


class FakeChat:
    async def generate_reply(self, sid, messages):
        return "generated answer"


class CapturingChat:
    def __init__(self):
        self.messages = None

    async def generate_reply(self, sid, messages):
        self.messages = messages
        return "answer"


class FakePairStore:
    def __init__(self, code_hits):
        self._code = code_hits

    async def fetch_paired(self, content_type, lecture, *, limit=5):
        return list(self._code)[:limit]


class FakeJudge:
    async def judge_correctness(self, query, answer, reference):
        return MetricScore("correctness", 0.9, "matches reference")


def _runner(sessionmaker, hits):
    s = make_settings(golden_eval_k_values=[1, 3], golden_eval_candidates=10,
                      rag_complex_top_k=3)
    return GoldenRunner(sessionmaker, FakeRetriever(hits), None, FakeChat(),
                        FakeJudge(), s)


async def test_run_computes_metrics_and_correctness(sessionmaker):
    store = GoldenStore(sessionmaker)
    await store.create(query="how long for a refund?", reference_answer="14 days",
                       relevant_chunks=[{"doc_id": "d1", "chunk_index": 0, "relevance": 1}])
    # retrieval surfaces the relevant chunk at rank 0, an irrelevant one at rank 1
    runner = _runner(sessionmaker, [_hit("d1", 0), _hit("d2", 1)])

    summary = await runner.run()
    assert summary["num_queries"] == 1
    assert summary["aggregate"]["recall"]["1"] == 1.0   # relevant at top-1
    assert summary["aggregate"]["mrr"] == 1.0
    assert summary["aggregate"]["correctness"] == 0.9

    async with sessionmaker() as db:
        run = (await db.execute(select(EvalGoldenRun))).scalar_one()
        res = (await db.execute(select(EvalGoldenResult))).scalar_one()
    assert run.num_queries == 1 and run.aggregate["correctness"] == 0.9
    assert res.correctness == 0.9 and res.generated_answer == "generated answer"
    assert res.metrics["recall"]["1"] == 1.0
    assert res.retrieved[0]["relevant"] is True and res.retrieved[1]["relevant"] is False


async def test_no_reference_skips_correctness(sessionmaker):
    store = GoldenStore(sessionmaker)
    await store.create(query="q", relevant_chunks=[{"doc_id": "d1", "chunk_index": 0}])
    runner = _runner(sessionmaker, [_hit("d1", 0)])
    summary = await runner.run()
    assert summary["aggregate"]["correctness"] is None  # no reference -> not judged
    async with sessionmaker() as db:
        res = (await db.execute(select(EvalGoldenResult))).scalar_one()
    assert res.correctness is None and res.generated_answer is None
    assert res.metrics["recall"]["1"] == 1.0


async def test_pairing_injects_code_into_generation(sessionmaker):
    store = GoldenStore(sessionmaker)
    await store.create(query="show me the W05 conditionals code",
                       reference_answer="def pass_or_fail(s): ...",
                       relevant_chunks=[{"doc_id": "s5", "chunk_index": 0}])
    slide = Hit(text="slide body", score=1.0, title="W05_條件判斷.pptx",
                payload={"doc_id": "s5", "chunk_index": 0,
                         "content_type": "slide", "lecture": 5})
    code = Hit(text="def pass_or_fail(score):\n    return score >= 60",
               score=0.0, title="W05_條件判斷.py",
               payload={"doc_id": "c5", "chunk_index": 0, "content_type": "code",
                        "lecture": 5, "source_file": "W05_條件判斷.py"})
    chat = CapturingChat()
    s = make_settings(golden_eval_k_values=[1, 3], golden_eval_candidates=10,
                      rag_complex_top_k=3, rag_pair_code_enabled=True)
    runner = GoldenRunner(sessionmaker, FakeRetriever([slide]), None, chat,
                          FakeJudge(), s, vector_store=FakePairStore([code]))
    await runner.run()
    blob = " ".join(m["content"] for m in chat.messages)
    # the slide's paired code was injected into the generation prompt
    assert "def pass_or_fail" in blob and "code: W05_條件判斷.py" in blob


async def test_pairing_off_when_no_store(sessionmaker):
    store = GoldenStore(sessionmaker)
    await store.create(query="q", reference_answer="r",
                       relevant_chunks=[{"doc_id": "s5", "chunk_index": 0}])
    slide = Hit(text="slide", score=1.0, title="W05.pptx",
                payload={"doc_id": "s5", "chunk_index": 0,
                         "content_type": "slide", "lecture": 5})
    chat = CapturingChat()
    runner = GoldenRunner(sessionmaker, FakeRetriever([slide]), None, chat, FakeJudge(),
                          make_settings(rag_complex_top_k=3), vector_store=None)
    await runner.run()
    assert chat.messages is not None and "code:" not in \
        " ".join(m["content"] for m in chat.messages)


async def test_latest_run(sessionmaker):
    store = GoldenStore(sessionmaker)
    await store.create(query="q", reference_answer="r",
                       relevant_chunks=[{"doc_id": "d1", "chunk_index": 0}])
    runner = _runner(sessionmaker, [_hit("d1", 0)])
    await runner.run()
    latest = await runner.latest_run()
    assert latest["num_queries"] == 1 and len(latest["results"]) == 1
    assert latest["results"][0]["correctness"] == 0.9
