"""Shared cache entrypoint.

This module currently proxies the legacy cache implementation.
"""

from __future__ import annotations

from app.infra import cache as _legacy


def __getattr__(name: str):
    return getattr(_legacy, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_legacy)))

