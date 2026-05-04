"""Community entry support helpers."""

from __future__ import annotations

import asyncio
import structlog
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.shared.infra.env_support import get_env

_DEFAULT_COMMUNITY_QR_URL = (
    "https://raw.githubusercontent.com/aiteachme/assets/main/wechat-qr.jpg"
)
_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS = 8
_COMMUNITY_QR_MAX_BYTES = 2 * 1024 * 1024
logger = structlog.get_logger(__name__)


def _get_community_wechat_qr_url() -> str | None:
    url = (
        (get_env("COMMUNITY_WECHAT_QR_URL") or "").strip()
        or _DEFAULT_COMMUNITY_QR_URL
    )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.warning("community_wechat_qr_invalid_url", url=url)
        return None
    return url


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
    """Read the latest community WeChat QR image from the configured remote URL."""

    url = _get_community_wechat_qr_url()
    if not url:
        return None

    try:
        return await asyncio.to_thread(_read_remote_community_wechat_qr_sync, url)
    except Exception as exc:
        logger.warning(
            "community_wechat_qr_fetch_failed",
            url=url,
            error=str(exc),
        )
        return None


__all__ = ["read_community_wechat_qr_bytes"]
