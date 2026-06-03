"""Pure-helper tests for the Discord adapter (no gateway needed)."""

from interfaces.discord_helpers import (
    build_inbound,
    chunk_message,
    clean_content,
    emoji_for_progress,
    parse_allowed_guilds,
    reaction_for,
    should_handle,
)
from shared.progress import THINKING, TOOL_END, TOOL_START


# --- should_handle ------------------------------------------------------------
def test_dm_always_handled():
    assert should_handle(is_dm=True, is_bot=False, mentioned=False,
                         guild_id=None, allowed_guilds=set())


def test_guild_requires_mention():
    assert not should_handle(is_dm=False, is_bot=False, mentioned=False,
                            guild_id="g1", allowed_guilds=set())
    assert should_handle(is_dm=False, is_bot=False, mentioned=True,
                        guild_id="g1", allowed_guilds=set())


def test_bots_ignored():
    assert not should_handle(is_dm=True, is_bot=True, mentioned=True,
                            guild_id=None, allowed_guilds=set())


def test_guild_allowlist():
    assert should_handle(is_dm=False, is_bot=False, mentioned=True,
                        guild_id="g1", allowed_guilds={"g1"})
    assert not should_handle(is_dm=False, is_bot=False, mentioned=True,
                            guild_id="g2", allowed_guilds={"g1"})


def test_parse_allowed_guilds():
    assert parse_allowed_guilds("") == set()
    assert parse_allowed_guilds("a, b ,c") == {"a", "b", "c"}


# --- clean_content ------------------------------------------------------------
def test_clean_content_strips_mention():
    assert clean_content("<@123> hello there", 123) == "hello there"
    assert clean_content("<@!123> hi", 123) == "hi"
    assert clean_content("no mention", 123) == "no mention"


# --- reaction UX --------------------------------------------------------------
def test_reaction_for_phases():
    assert reaction_for("received") == "👀"
    assert reaction_for("thinking") == "🧠"
    assert reaction_for("done") == "✅"
    assert reaction_for("error") == "❌"


def test_reaction_for_tools():
    assert reaction_for("tool", "web_search") == "🌐"
    assert reaction_for("tool", "search_knowledge") == "🔎"
    assert reaction_for("tool", "something_new") == "🛠️"


def test_emoji_for_progress_lifecycle():
    # tool_start shows the tool emoji; thinking/tool_end revert to the brain.
    assert emoji_for_progress(THINKING) == "🧠"
    assert emoji_for_progress(TOOL_START, "web_search") == "🌐"
    assert emoji_for_progress(TOOL_END, "web_search") == "🧠"
    # A full web-search turn ends on done -> only ✅ remains (set by on_message).
    assert reaction_for("done") == "✅"


# --- chunk_message ------------------------------------------------------------
def test_chunk_message():
    assert chunk_message("") == []
    assert chunk_message("short") == ["short"]
    big = "x" * 4500
    chunks = chunk_message(big)
    assert len(chunks) == 3
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == big


# --- build_inbound ------------------------------------------------------------
def test_build_inbound_fields():
    ev = build_inbound(text="hello", channel_id="chan1", user_id="user1",
                       message_id="msg1", correlation_id="cid1")
    assert ev.platform == "discord"
    assert ev.channel_id == "chan1"
    assert ev.session_id == "discord:chan1"
    assert ev.user_id == "user1"
    assert ev.message_id == "msg1"
    assert ev.reply_token == "msg1"
    assert ev.correlation_id == "cid1"
    assert ev.text == "hello"
