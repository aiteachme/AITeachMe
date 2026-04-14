"""Shared workflow type aliases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

StateT = TypeVar("StateT")

AsyncNode = Callable[[StateT], Awaitable[StateT]]
GraphBuilder = Callable[[], Any]
