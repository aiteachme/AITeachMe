"""Shared config entrypoint.

This module currently proxies the legacy config implementation.
"""

from __future__ import annotations

from app.infra.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]

