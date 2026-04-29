"""Safe LiteLLM import helpers.

LangGraph dev will flag synchronous blocking calls like ``os.getcwd()`` when
they happen lazily on the event loop. LiteLLM imports ``python-dotenv`` in DEV
mode, and that code path may call ``find_dotenv() -> os.getcwd()`` during the
first request.

This project already loads repo-local environment variables via
``app.shared.infra.env_support``, so we explicitly disable python-dotenv's
auto-discovery before importing LiteLLM.
"""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def load_litellm():
    """Import LiteLLM after disabling python-dotenv auto-discovery."""

    os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
    import litellm

    return litellm


__all__ = ["load_litellm"]
