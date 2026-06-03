"""Tool registry + a decorator to make adding new tools a one-liner.

A new tool is defined with @tool(...) on an async handler; it's appended to a
module-level factory list. runtime calls register_default_tools(registry) to
instantiate them into a ToolRegistry. Tools can also be registered explicitly.
"""

from core.tools.schemas import Tool, ToolHandler

# Factories registered via @tool, instantiated by register_default_tools().
_DEFAULT_TOOL_FACTORIES: list[Tool] = []


def tool(*, name: str, description: str, parameters: dict):
    """Decorator: register an async handler as a default tool."""

    def decorator(handler: ToolHandler) -> ToolHandler:
        _DEFAULT_TOOL_FACTORIES.append(
            Tool(name=name, description=description, parameters=parameters, handler=handler)
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


def register_default_tools(registry: ToolRegistry) -> None:
    """Register every @tool-decorated tool into the given registry."""
    # Import for side effects so the decorators run and populate the factory list.
    import core.rag.search_tool  # noqa: F401

    for tool_obj in _DEFAULT_TOOL_FACTORIES:
        if registry.get(tool_obj.name) is None:
            registry.register(tool_obj)
