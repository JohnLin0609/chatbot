"""The web_search tool: live web results via the Brave Search API.

Registered only when `brave_api_key` is set (see the `requires` gate), so the
model never sees a tool it can't use.
"""

import logging

from core.tools.registry import tool
from core.tools.schemas import ToolContext

log = logging.getLogger("web.search_tool")

_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The web search query.",
        },
        "count": {
            "type": "integer",
            "description": "Max number of results to return.",
            "minimum": 1,
            "maximum": 10,
        },
        "freshness": {
            "type": "string",
            "description": (
                "Restrict results by recency: 'pd' past day, 'pw' past week, "
                "'pm' past month, 'py' past year. Omit for no time limit."
            ),
            "enum": ["pd", "pw", "pm", "py"],
        },
    },
    "required": ["query"],
}


@tool(
    name="web_search",
    description=(
        "Search the live web for current information (news, recent events, "
        "facts that may have changed, anything not in the conversation or the "
        "curated knowledge base). Returns titles, URLs, and snippets."
    ),
    parameters=_SCHEMA,
    requires=lambda s: bool(s.brave_api_key),
)
async def web_search(args: dict, ctx: ToolContext) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "error: 'query' is required"
    if ctx.web_search_service is None:  # defensive: should be gated at registration
        return "Web search is temporarily unavailable."

    count = args.get("count") or ctx.settings.brave_search_count
    freshness = args.get("freshness")

    try:
        results = await ctx.web_search_service.search(query, count, freshness)
    except Exception:  # noqa: BLE001 — degrade gracefully, don't break the reply
        log.exception("web_search failed")
        return "Web search is temporarily unavailable."

    if not results:
        return "No web results found."

    lines = []
    for i, r in enumerate(results, start=1):
        title = r.title or "untitled"
        lines.append(f"[{i}] {title} — {r.url}\n    {r.description}")
    return "\n".join(lines)
