"""Base retriever abstraction with auto-registration helpers."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.shared.infra.search.cache import get_retriever_runtime_cache
from app.shared.infra.search.types import SearchResult
from app.shared.infra.observability import (
    get_llm_trace_context,
    langsmith_trace,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)

_REGISTERED_RETRIEVER_TYPES: dict[str, type["BaseRetriever"]] = {}


def _search_result_preview(results: list[SearchResult], *, limit: int = 3) -> list[dict[str, object]]:
    preview: list[dict[str, object]] = []
    for item in results[: max(1, limit)]:
        preview.append(
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "source": item.source,
            }
        )
    return preview


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


def register_retriever_type(retriever_type: type["BaseRetriever"]) -> type["BaseRetriever"]:
    for name in retriever_type.factory_names():
        current = _REGISTERED_RETRIEVER_TYPES.get(name)
        if current is not None and current is not retriever_type:
            raise ValueError(f"Retriever name `{name}` is already registered for `{current.__name__}`.")
        _REGISTERED_RETRIEVER_TYPES[name] = retriever_type
    return retriever_type


def get_registered_retriever_types() -> dict[str, type["BaseRetriever"]]:
    return dict(_REGISTERED_RETRIEVER_TYPES)


def get_registered_retriever_names() -> list[str]:
    return sorted(_REGISTERED_RETRIEVER_TYPES)


class BaseRetriever(ABC):
    canonical_name: str = ""
    aliases: tuple[str, ...] = ()
    auto_register: bool = True
    cacheable: bool = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls) or not getattr(cls, "auto_register", True):
            return
        register_retriever_type(cls)

    @classmethod
    def factory_names(cls) -> list[str]:
        names = [getattr(cls, "canonical_name", "")]
        try:
            names.append(cls().name)
        except TypeError as exc:  # pragma: no cover - guard rail for future retrievers
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

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError

    async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        trace = get_llm_trace_context()
        with langsmith_trace(
            name=f"retriever.{self.name}",
            run_type="retriever",
            inputs={
                "query": sanitize_langsmith_input(query, field_name="query"),
                "max_results": int(max_results),
            },
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata={"retriever_name": self.name},
            extra_tags=[f"retriever:{self.name}"],
        ) as run:
            if self.cacheable:
                results, cache_status = await get_retriever_runtime_cache().get_or_compute(
                    payload={
                        "retriever_name": self.name,
                        "query": query,
                        "max_results": int(max_results),
                    },
                    loader=lambda: self.search(query, max_results=max_results),
                )
            else:
                results = await self.search(query, max_results=max_results)
                cache_status = "disabled"
            if run is not None:
                run.end(
                    outputs={
                        "result_count": len(results),
                        "unique_url_count": len({item.url for item in results if item.url}),
                        "local_result_count": sum(1 for item in results if item.url.startswith("local://")),
                        "cache_status": cache_status,
                        "cache_hit": cache_status in {"hit", "shared"},
                        "results_preview": sanitize_langsmith_output(
                            _search_result_preview(results, limit=2),
                            field_name="results_preview",
                        ),
                    }
                )
            return results


__all__ = [
    "BaseRetriever",
    "get_registered_retriever_names",
    "get_registered_retriever_types",
    "register_retriever_type",
]
