"""Small async concurrency helpers for workflow fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def gather_with_concurrency(
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    limit: int,
) -> list[R]:
    """Run an async worker over items with a bounded local fan-out."""

    normalized_items = list(items)
    if not normalized_items:
        return []

    semaphore = asyncio.Semaphore(max(1, min(int(limit or 1), len(normalized_items))))

    async def _run_one(item: T) -> R:
        async with semaphore:
            return await worker(item)

    return list(await asyncio.gather(*(_run_one(item) for item in normalized_items)))


__all__ = ["gather_with_concurrency"]
