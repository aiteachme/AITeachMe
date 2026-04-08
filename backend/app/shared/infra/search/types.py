"""Typed search results used by planner and docgen tooling."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float = 0.0
    source: str = ""

    def to_text(self) -> str:
        title = self.title.strip() or self.url.strip() or "Untitled source"
        snippet = self.snippet.strip()
        if snippet:
            return f"[{title}]({self.url})\n{snippet}"
        return f"[{title}]({self.url})"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ScrapedPage:
    url: str
    title: str = ""
    content: str = ""
    content_type: str = "text/html"
    success: bool = True
    error: str | None = None


WebSearchResult = SearchResult

__all__ = ["ScrapedPage", "SearchResult", "WebSearchResult"]
