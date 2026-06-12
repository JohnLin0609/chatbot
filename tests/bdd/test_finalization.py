import pytest
from pytest_bdd import scenarios

from tests.bdd.world import World
from tests.conftest import make_settings
from tests.test_pipeline import FactAwareChat

scenarios("session_finalization.feature")


@pytest.fixture
def world():
    # Finalization runs the summarizer + forced fact extraction — FactAwareChat
    # answers those prompts with valid summary text / fact JSON.
    w = World(chat=FactAwareChat(make_settings()))
    yield w
    w.close()
