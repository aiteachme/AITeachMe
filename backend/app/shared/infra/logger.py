"""Shared logger entrypoint.

This module currently proxies the legacy logger implementation.
"""

from __future__ import annotations

from app.infra.logger import configure_logging

__all__ = ["configure_logging"]

