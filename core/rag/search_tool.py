"""The search_knowledge tool: retrieve curated knowledge by similarity."""

import logging

from core.tools.registry import tool
from core.tools.schemas import ToolContext

log = logging.getLogger("rag.search_tool")

_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "What to look up in the curated knowledge base.",
        },
        "top_k": {
            "type": "integer",
            "description": "Max number of results to return.",
            "minimum": 1,
            "maximum": 10,
        },
    },
    "required": ["query"],
}


@tool(
    name="search_knowledge",
    description=(
        "Search the curated knowledge base (FAQs, cases, documentation) for "
        "information relevant to the user's question. Use it when the answer "
        "likely depends on stored knowledge rather than the conversation itself."
    ),
    parameters=_SCHEMA,
)
async def search_knowledge(args: dict, ctx: ToolContext) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "error: 'query' is required"
    top_k = args.get("top_k") or ctx.settings.rag_top_k

    try:
        vectors = await ctx.embedding_service.embed([query])
        hits = await ctx.vector_store.search(
            vectors[0],
            top_k,
            source="curated",
            score_threshold=ctx.settings.rag_score_threshold or None,
        )
    except Exception:  # noqa: BLE001 — degrade gracefully, don't break the reply
        log.exception("search_knowledge failed")
        return "Knowledge base is temporarily unavailable."

    if not hits:
        return "No relevant knowledge found."

    lines = []
    for i, hit in enumerate(hits, start=1):
        title = hit.title or "untitled"
        lines.append(f"[{i}] ({title} | score {hit.score:.2f}) {hit.text}")
    return "\n".join(lines)
