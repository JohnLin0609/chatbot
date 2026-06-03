"""Assemble the provider-agnostic message list fed to an LLM.

The canonical format is an OpenAI-style list of {"role", "content"} dicts with
roles in {"system", "user", "assistant"}. Each provider translates this to its
own SDK shape (Anthropic extracts the system messages into its `system` field,
Gemini into `system_instruction`, OpenAI/Ollama use the roles inline).
"""


Turn = dict  # {"role": "user"|"assistant", "content": str, ...}


def build_messages(
    system_prompt: str,
    running_summary: str | None,
    recent_turns: list[Turn],
    user_text: str,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if running_summary:
        messages.append(
            {
                "role": "system",
                "content": f"Conversation summary so far:\n{running_summary}",
            }
        )

    for turn in recent_turns:
        messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": user_text})
    return messages


def split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split a canonical message list into (joined system text, non-system turns).

    Used by providers (Anthropic/Gemini) that take the system prompt separately.
    """
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    turns = [m for m in messages if m["role"] != "system"]
    return "\n\n".join(system_parts), turns
