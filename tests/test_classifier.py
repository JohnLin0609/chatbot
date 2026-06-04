"""QueryClassifier tier routing with a scripted ChatService."""

from core.rag.classifier import COMPLEX, MEDIUM, SIMPLE, QueryClassifier
from tests.conftest import make_settings


class ScriptedChat:
    def __init__(self, reply):
        self._reply = reply

    async def generate_reply(self, key, messages):
        return self._reply


async def test_returns_each_tier():
    for word, expect in [("simple", SIMPLE), ("medium", MEDIUM), ("complex", COMPLEX)]:
        c = QueryClassifier(ScriptedChat(word), make_settings())
        assert await c.classify("q") == expect


async def test_extracts_tier_from_verbose_output():
    c = QueryClassifier(ScriptedChat("I think this is Complex."), make_settings())
    assert await c.classify("q") == COMPLEX


async def test_bad_output_defaults_medium():
    c = QueryClassifier(ScriptedChat("banana"), make_settings())
    assert await c.classify("q") == MEDIUM


async def test_disabled_returns_medium():
    c = QueryClassifier(
        ScriptedChat("simple"), make_settings(adaptive_classifier_enabled=False)
    )
    assert await c.classify("q") == MEDIUM


async def test_error_defaults_medium():
    class Boom:
        async def generate_reply(self, key, messages):
            raise RuntimeError("down")

    assert await QueryClassifier(Boom(), make_settings()).classify("q") == MEDIUM
