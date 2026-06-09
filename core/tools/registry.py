"""Tool registry + a decorator to make adding new tools a one-liner.

A new tool is defined with @tool(...) on an async handler; it's appended to a
module-level factory list. runtime calls register_default_tools(registry) to
instantiate them into a ToolRegistry. Tools can also be registered explicitly.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.tools.schemas import Tool, ToolHandler

if TYPE_CHECKING:
    from core.config import Settings

# Factories registered via @tool, instantiated by register_default_tools().
_DEFAULT_TOOL_FACTORIES: list[Tool] = []


def tool(
    *,
    name: str,
    description: str,
    parameters: dict,
    requires: "Callable[[Settings], bool] | None" = None,
):
    """Decorator: register an async handler as a default tool.

    `requires` is an optional gate: the tool is registered only when
    requires(settings) is truthy (e.g. a needed API key is set).
    """

    def decorator(handler: ToolHandler) -> ToolHandler:
        _DEFAULT_TOOL_FACTORIES.append(
            Tool(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
                requires=requires,
            )
        )
        return handler

    return decorator


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool_obj: Tool) -> None:
        if tool_obj.name in self._tools:
            raise ValueError(f"tool '{tool_obj.name}' already registered")
        self._tools[tool_obj.name] = tool_obj

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_schema(self) -> list[dict]:
        return [t.to_openai() for t in self._tools.values()]


def register_default_tools(registry: ToolRegistry, settings: "Settings") -> None:
    """Register every @tool-decorated tool whose `requires` gate passes."""
    # Import for side effects so the decorators run and populate the factory list.
    # (Knowledge RAG is no longer a tool — it's classifier-routed in the pipeline.)
    import core.tools.datetime_tool  # noqa: F401
    import core.web.search_tool  # noqa: F401

    for tool_obj in _DEFAULT_TOOL_FACTORIES:
        if tool_obj.requires is not None and not tool_obj.requires(settings):
            continue
        if registry.get(tool_obj.name) is None:
            registry.register(tool_obj)
