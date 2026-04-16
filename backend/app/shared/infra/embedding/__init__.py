"""Stable package exports for embedding helpers and adapters."""

from app.shared.infra.embedding.api import aembed_texts


def __getattr__(name: str):
    if name == "ATMEmbedding":
        from app.shared.infra.embedding.llamaindex import ATMEmbedding

        return ATMEmbedding
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["ATMEmbedding", "aembed_texts"]
