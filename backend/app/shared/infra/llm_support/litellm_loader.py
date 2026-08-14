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

import asyncio
import os
from functools import lru_cache

import structlog

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def load_litellm():
    """Import LiteLLM without request-time environment or network discovery."""

    os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    return litellm


async def warm_litellm() -> None:
    """Move the blocking LiteLLM import off the first user request."""

    try:
        await asyncio.to_thread(load_litellm)
    except Exception:
        logger.warning("litellm_warmup_failed", exc_info=True)
    else:
        logger.info("litellm_warmup_complete")


__all__ = ["load_litellm", "warm_litellm"]
