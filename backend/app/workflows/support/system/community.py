"""Community entry support helpers."""

from __future__ import annotations

import asyncio
import structlog
import time
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.shared.infra.env_support import get_env
from app.shared.infra.storage import get_artifact_store

_COMMUNITY_QR_OBJECT_KEY = "community/wechat-qr.jpg"
_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS = 8
logger = structlog.get_logger(__name__)


async def _read_community_wechat_qr_from_store() -> bytes | None:
    """Read the community QR image from the configured artifact store."""

    try:
        return await get_artifact_store().read_bytes(_COMMUNITY_QR_OBJECT_KEY)
    except Exception as exc:
        logger.debug(
            "community_wechat_qr_read_failed",
            storage_key=_COMMUNITY_QR_OBJECT_KEY,
            error=str(exc),
        )
        return None


def _build_public_community_wechat_qr_url() -> str | None:
    public_base_url = (get_env("S3_PUBLIC_BASE_URL") or "").strip()
    if not public_base_url:
        return None
    url = urljoin(public_base_url.rstrip("/") + "/", _COMMUNITY_QR_OBJECT_KEY)
    return f"{url}{'&' if '?' in url else '?'}t={int(time.time())}"


def _read_public_community_wechat_qr_sync(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "AITeachMe/CommunityQR",
        },
        method="GET",
    )
    with urlopen(request, timeout=_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS) as response:
        return response.read()


async def _read_community_wechat_qr_from_public_url() -> bytes | None:
    """Fetch the community QR image from the public OSS/CDN URL as a desktop fallback."""

    url = _build_public_community_wechat_qr_url()
    if not url:
        return None

    try:
        return await asyncio.to_thread(_read_public_community_wechat_qr_sync, url)
    except Exception as exc:
        logger.warning(
            "community_wechat_qr_public_fetch_failed",
            url=url,
            error=str(exc),
        )
        return None


async def read_community_wechat_qr_bytes() -> bytes | None:
    """Read the latest community WeChat QR image from storage or public OSS."""

    return await _read_community_wechat_qr_from_store() or await _read_community_wechat_qr_from_public_url()


__all__ = ["read_community_wechat_qr_bytes"]
