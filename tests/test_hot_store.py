"""HotStore tests against fakeredis."""

from core.memory.hot_store import HotStore


async def test_append_and_load(settings, redis):
    hot = HotStore(redis, settings)
    await hot.append_turn("cli:c1", "hello", "hi there", user_id="u1")

    summary, turns = await hot.load("cli:c1")
    assert summary is None
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "hello"
    assert turns[0]["user_id"] == "u1"
    assert turns[1]["user_id"] is None  # assistant has no author


async def test_backstop_caps_messages(settings, redis):
    hot = HotStore(redis, settings)
    hot._MAX_MESSAGES = 6  # shrink the safety valve for the test
    for i in range(10):
        await hot.append_turn("cli:c1", f"u{i}", f"a{i}", user_id="u1")
    _summary, turns = await hot.load("cli:c1")
    assert len(turns) == 6


async def test_ttl_set(settings, redis):
    hot = HotStore(redis, settings)
    await hot.append_turn("cli:c1", "u", "a")
    ttl = await redis.ttl(hot._turns_key("cli:c1"))
    assert 0 < ttl <= settings.hot_ttl_seconds


async def test_set_summary_and_replace_turns(settings, redis):
    hot = HotStore(redis, settings)
    await hot.append_turn("cli:c1", "u1", "a1")
    await hot.append_turn("cli:c1", "u2", "a2")
    await hot.set_summary("cli:c1", {"text": "S", "turn_count": 1})
    await hot.replace_turns("cli:c1", [{"role": "user", "content": "u2"}])

    summary, turns = await hot.load("cli:c1")
    assert summary["text"] == "S"
    assert len(turns) == 1


async def test_backfill_populates_cold_store(settings, redis):
    hot = HotStore(redis, settings)
    assert not await hot.exists("cli:c1")
    await hot.backfill(
        "cli:c1",
        {"text": "prior", "turn_count": 2},
        [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
    )
    summary, turns = await hot.load("cli:c1")
    assert summary["text"] == "prior"
    assert len(turns) == 2
