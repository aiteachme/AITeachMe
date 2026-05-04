"""Community entry support helpers."""

from __future__ import annotations

import asyncio
import structlog
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

_COMMUNITY_QR_URL = (
    "https://raw.githubusercontent.com/aiteachme/assets/main/community/wechat-qr.jpg"
)
_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS = 8
_COMMUNITY_QR_MAX_BYTES = 2 * 1024 * 1024
logger = structlog.get_logger(__name__)


def _with_cache_buster(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "t"
    ]
    query.append(("t", str(int(time.time()))))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _read_remote_community_wechat_qr_sync(url: str) -> bytes:
    request = Request(
        _with_cache_buster(url),
        headers={
            "Accept": "image/*,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "AITeachMe/CommunityQR",
        },
        method="GET",
    )
    with urlopen(request, timeout=_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS) as response:
        image_bytes = response.read(_COMMUNITY_QR_MAX_BYTES + 1)

    if len(image_bytes) > _COMMUNITY_QR_MAX_BYTES:
        raise ValueError("community QR image is too large")
    return image_bytes


async def read_community_wechat_qr_bytes() -> bytes | None:
    """Read the latest community WeChat QR image from the project assets repo."""

    try:
        return await asyncio.to_thread(_read_remote_community_wechat_qr_sync, _COMMUNITY_QR_URL)
    except Exception as exc:
        logger.warning(
            "community_wechat_qr_fetch_failed",
            url=_COMMUNITY_QR_URL,
            error=str(exc),
        )
        return None


__all__ = ["read_community_wechat_qr_bytes"]
