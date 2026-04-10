"""Base retriever abstraction with auto-registration helpers."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.shared.infra.search.types import SearchResult
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace

_REGISTERED_RETRIEVER_TYPES: dict[str, type["BaseRetriever"]] = {}


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


class BaseRetriever(ABC):
    canonical_name: str = ""
    aliases: tuple[str, ...] = ()
    auto_register: bool = True

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
            inputs={"query": query, "max_results": max_results},
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata={"retriever_name": self.name},
            extra_tags=[f"retriever:{self.name}"],
        ) as run:
            results = await self.search(query, max_results=max_results)
            if run is not None:
                run.end(
                    outputs={
                        "result_count": len(results),
                        "unique_url_count": len({item.url for item in results if item.url}),
                        "local_result_count": sum(1 for item in results if item.url.startswith("local://")),
                    }
                )
            return results


__all__ = [
    "BaseRetriever",
    "get_registered_retriever_types",
    "register_retriever_type",
]
