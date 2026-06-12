import pytest

from tests.bdd.world import World


@pytest.fixture
def world():
    w = World()
    yield w
    w.close()
