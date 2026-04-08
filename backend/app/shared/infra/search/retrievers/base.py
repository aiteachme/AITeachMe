"""Base retriever abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.shared.infra.search.types import SearchResult
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace


class BaseRetriever(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

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


__all__ = ["BaseRetriever"]
