"""Brave Search API client. The first tool that calls an external third-party
HTTP service, so it owns one shared httpx.AsyncClient (injected via ToolContext),
mirroring how the embedding/vector services are wired."""

from dataclasses import dataclass

import httpx

from core.config import Settings


class WebSearchError(Exception):
    """Raised when the Brave Search backend fails or returns an unusable body."""


@dataclass
class BraveResult:
    title: str
    url: str
    description: str


class BraveSearchService:
    """Thin async wrapper over Brave's web-search endpoint.

    Holds a single AsyncClient for connection reuse. `search` returns parsed
    results; any transport/parse failure is wrapped in WebSearchError so the
    tool handler can degrade gracefully.
    """

    def __init__(self, settings: Settings) -> None:
        self._url = settings.brave_search_url
        self._count = settings.brave_search_count
        self._country = settings.brave_search_country
        self._lang = settings.brave_search_lang
        self._client = httpx.AsyncClient(
            timeout=settings.brave_search_timeout,
            headers={
                "X-Subscription-Token": settings.brave_api_key,
                "Accept": "application/json",
            },
        )

    async def search(
        self,
        query: str,
        count: int | None = None,
        freshness: str | None = None,
    ) -> list[BraveResult]:
        params: dict[str, str | int] = {
            "q": query,
            "count": count or self._count,
        }
        if freshness:
            params["freshness"] = freshness
        if self._country:
            params["country"] = self._country
        if self._lang:
            params["search_lang"] = self._lang

        try:
            resp = await self._client.get(self._url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchError(str(exc)) from exc

        results = (data.get("web") or {}).get("results") or []
        return [
            BraveResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                description=r.get("description") or "",
            )
            for r in results
        ]

    async def aclose(self) -> None:
        await self._client.aclose()


def build_web_search_service(settings: Settings) -> BraveSearchService | None:
    """Build the Brave client, or None when no key is configured (the tool is
    then never registered — the model won't see it)."""
    if not settings.brave_api_key:
        return None
    return BraveSearchService(settings)
