"""Canonical exception entrypoint for shared kernel.

For now, this module proxies the existing legacy exception definitions.
"""

from __future__ import annotations

from app.shared.infra import exceptions as _legacy


def __getattr__(name: str):
    return getattr(_legacy, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_legacy)))

