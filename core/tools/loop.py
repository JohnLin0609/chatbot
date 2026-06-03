"""ToolRunner: drive the tool-calling loop for a single reply.

complete() -> if the model wants tools, execute them, stack the results back,
call again — until the model returns plain text or we hit max_iterations.
Falls back to a single completion when tools are disabled/unsupported.
"""

import logging

from core.config import Settings
from core.llm.base import ChatService
from core.tools.registry import ToolRegistry
from core.tools.schemas import ToolCall, ToolContext

log = logging.getLogger("tools")


class ToolRunner:
    def __init__(
        self, chat_service: ChatService, registry: ToolRegistry, settings: Settings
    ) -> None:
        self._chat = chat_service
        self._registry = registry
        self._settings = settings

    async def run(
        self, session_id: str, messages: list[dict], ctx: ToolContext
    ) -> str:
        if not (self._settings.enable_tools and self._chat.supports_tools):
            result = await self._chat.complete(session_id, messages, tools=None)
            return result.text or ""

        tools = self._registry.openai_schema()
        working = list(messages)

        for _ in range(self._settings.tool_max_iterations):
            result = await self._chat.complete(session_id, working, tools=tools)
            if not result.tool_calls:
                return result.text or ""
            # Stack the assistant message (with tool_calls) verbatim, then a
            # tool result for each call — OpenAI requires both on the next turn.
            working.append(result.raw_assistant_message)
            for call in result.tool_calls:
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": await self._dispatch(call, ctx),
                    }
                )

        # Hit the iteration cap — make one final tool-free pass to converge.
        final = await self._chat.complete(session_id, working, tools=None)
        return final.text or ""

    async def _dispatch(self, call: ToolCall, ctx: ToolContext) -> str:
        tool = self._registry.get(call.name)
        if tool is None:
            return f"error: unknown tool '{call.name}'"
        log.info("tool call: %s args=%s", call.name, call.arguments)
        try:
            return await tool.handler(call.arguments, ctx)
        except Exception as exc:  # noqa: BLE001 — surface to the model, keep looping
            log.exception("tool '%s' failed", call.name)
            return f"error: {exc}"
