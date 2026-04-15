"""Bridge existing LiteLLM embedding calls to LlamaIndex BaseEmbedding.

This adapter allows LlamaIndex components (VectorStoreIndex, retrievers,
etc.) to use the same embedding model and API configuration already
defined in ``config.yaml`` and the ``aembed_texts()`` helper.

No new embedding dependencies are introduced — all calls go through
``app.shared.infra.embedding.aembed_texts``.
"""

from __future__ import annotations

from typing import Any

from llama_index.core.embeddings import BaseEmbedding
from pydantic import Field, PrivateAttr

from app.shared.infra.config import get_settings


class ATMEmbedding(BaseEmbedding):
    """LlamaIndex embedding adapter backed by the existing LiteLLM pipeline."""

    _model_name: str = PrivateAttr(default="")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._model_name = get_settings().normalized_embedding_model or ""

    @classmethod
    def class_name(cls) -> str:
        return "ATMEmbedding"

    # ------------------------------------------------------------------
    # Async methods (preferred – FastAPI backend is fully async)
    # ------------------------------------------------------------------

    async def _aget_text_embedding(self, text: str) -> list[float]:
        from app.shared.infra.embedding import aembed_texts

        result = await aembed_texts([text])
        return result[0]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        from app.shared.infra.embedding import aembed_texts

        return await aembed_texts(texts)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self._aget_text_embedding(query)

    # ------------------------------------------------------------------
    # Sync fallbacks (required by the BaseEmbedding ABC)
    # ------------------------------------------------------------------

    def _run_coroutine(self, coro):
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(coro)

        return asyncio.get_event_loop().run_until_complete(coro)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._run_coroutine(self._aget_text_embedding(text))

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._run_coroutine(self._aget_text_embeddings(texts))

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)


__all__ = ["ATMEmbedding"]
