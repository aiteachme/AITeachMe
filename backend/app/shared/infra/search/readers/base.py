"""Reader and scraper abstractions with URL-based factory registration.

`BaseReader` is the generic internal abstraction for "load content from a URL".
`BaseScraper` is the common specialization used by HTML/PDF fetchers.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.shared.infra.search.types import ScrapedPage
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace

_REGISTERED_READER_TYPES: dict[str, type["BaseReader"]] = {}


def _normalize_registry_name(value: str) -> str:
    return str(value or "").strip().lower()


def _dedupe_names(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for value in values:
        normalized = _normalize_registry_name(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return names


def register_reader_type(reader_type: type["BaseReader"]) -> type["BaseReader"]:
    for name in reader_type.factory_names():
        current = _REGISTERED_READER_TYPES.get(name)
        if current is not None and current is not reader_type:
            raise ValueError(f"Reader name `{name}` is already registered for `{current.__name__}`.")
        _REGISTERED_READER_TYPES[name] = reader_type
    return reader_type


def get_registered_reader_types() -> dict[str, type["BaseReader"]]:
    return dict(_REGISTERED_READER_TYPES)


def get_registered_reader_names() -> list[str]:
    return sorted(_REGISTERED_READER_TYPES)


class BaseReader(ABC):
    """Generic URL content reader."""

    canonical_name: str = ""
    aliases: tuple[str, ...] = ()
    auto_register: bool = True
    priority: int = 0

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls) or not getattr(cls, "auto_register", True):
            return
        register_reader_type(cls)

    @classmethod
    def factory_names(cls) -> list[str]:
        names = [getattr(cls, "canonical_name", "")]
        try:
            names.append(cls().name)
        except TypeError as exc:  # pragma: no cover - guard rail for future readers
            if not any(_normalize_registry_name(name) for name in names):
                raise TypeError(
                    f"{cls.__name__} must define `canonical_name` or support zero-argument construction "
                    "for auto registration."
                ) from exc
        names.extend(getattr(cls, "aliases", ()) or ())
        return _dedupe_names(names)

    @property
    def name(self) -> str:
        canonical = _normalize_registry_name(getattr(self, "canonical_name", ""))
        if canonical:
            return canonical
        return self.__class__.factory_names()[0]

    @classmethod
    def supports_url(cls, url: str) -> bool:
        return bool(str(url or "").strip())

    @classmethod
    def match_priority(cls, url: str) -> int | None:
        if not cls.supports_url(url):
            return None
        return int(getattr(cls, "priority", 0))

    @abstractmethod
    async def read(self, url: str) -> ScrapedPage:
        raise NotImplementedError

    async def scrape(self, url: str) -> ScrapedPage:
        return await self.read(url)

    async def traced_read(self, url: str) -> ScrapedPage:
        trace = get_llm_trace_context()
        with langsmith_trace(
            name=f"reader.{self.name}",
            run_type="tool",
            inputs={"url": url},
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata={"reader_name": self.name, "scraper_name": self.name},
            extra_tags=[f"reader:{self.name}", f"scraper:{self.name}"],
        ) as run:
            result = await self.read(url)
            result.reader_name = result.reader_name or self.name
            if run is not None:
                run.end(
                    outputs={
                        "success": result.success,
                        "content_length": len(result.content),
                        "content_type": result.content_type,
                        "reader_name": result.reader_name,
                        "error": result.error or "",
                    }
                )
            return result

    async def traced_scrape(self, url: str) -> ScrapedPage:
        return await self.traced_read(url)


class BaseScraper(BaseReader):
    """URL scraper specialization kept for clearer caller semantics."""

    @abstractmethod
    async def scrape(self, url: str) -> ScrapedPage:
        raise NotImplementedError

    async def read(self, url: str) -> ScrapedPage:
        return await self.scrape(url)


__all__ = [
    "BaseReader",
    "BaseScraper",
    "get_registered_reader_names",
    "get_registered_reader_types",
    "register_reader_type",
]



