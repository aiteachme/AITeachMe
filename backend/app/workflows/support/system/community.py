"""Community entry support helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import structlog
import time
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

_COMMUNITY_QR_FETCH_TIMEOUT_SECONDS = 8
_COMMUNITY_QR_CACHE_TTL_SECONDS = 10 * 60
_COMMUNITY_QR_STALE_RETRY_SECONDS = 60
_COMMUNITY_QR_MAX_BYTES = 2 * 1024 * 1024
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CommunityQrChannel:
    channel_id: str
    image_url: str
    media_type: str = "image/jpeg"


@dataclass
class CommunityQrCacheEntry:
    image_bytes: bytes | None = None
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_COMMUNITY_QR_CHANNELS: dict[str, CommunityQrChannel] = {
    "wechat": CommunityQrChannel(
        channel_id="wechat",
        image_url="https://raw.githubusercontent.com/aiteachme/assets/main/community/wechat-qr.jpg",
    ),
    "feishu": CommunityQrChannel(
        channel_id="feishu",
        image_url="https://raw.githubusercontent.com/aiteachme/assets/main/community/feishu-qr.png",
        media_type="image/png",
    ),
}
_community_qr_cache: dict[str, CommunityQrCacheEntry] = {
    channel_id: CommunityQrCacheEntry()
    for channel_id in _COMMUNITY_QR_CHANNELS
}


def _with_cache_buster(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "t"
    ]
    query.append(("t", str(int(time.time()))))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _read_remote_community_qr_sync(url: str) -> bytes:
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


async def read_community_qr_bytes(channel_id: str) -> bytes | None:
    """Read the latest community QR image for one configured channel."""

    channel = _COMMUNITY_QR_CHANNELS[channel_id]
    cache_entry = _community_qr_cache[channel_id]

    now = time.monotonic()
    if cache_entry.image_bytes is not None and now < cache_entry.expires_at:
        return cache_entry.image_bytes

    async with cache_entry.lock:
        now = time.monotonic()
        if cache_entry.image_bytes is not None and now < cache_entry.expires_at:
            return cache_entry.image_bytes

        try:
            image_bytes = await asyncio.to_thread(_read_remote_community_qr_sync, channel.image_url)
        except Exception as exc:
            logger.warning(
                "community_qr_fetch_failed",
                channel_id=channel.channel_id,
                url=channel.image_url,
                error=str(exc),
            )
            if cache_entry.image_bytes is not None:
                cache_entry.expires_at = time.monotonic() + _COMMUNITY_QR_STALE_RETRY_SECONDS
            return cache_entry.image_bytes

        cache_entry.image_bytes = image_bytes
        cache_entry.expires_at = time.monotonic() + _COMMUNITY_QR_CACHE_TTL_SECONDS
        return image_bytes


async def read_community_wechat_qr_bytes() -> bytes | None:
    """Read the latest community WeChat QR image from the project assets repo."""

    return await read_community_qr_bytes("wechat")


async def read_community_feishu_qr_bytes() -> bytes | None:
    """Read the latest community Feishu QR image from the project assets repo."""

    return await read_community_qr_bytes("feishu")


async def refresh_community_qr_cache(channel_ids: Iterable[str] | None = None) -> None:
    """Best-effort warmup for configured community QR caches."""

    for channel_id in channel_ids or _COMMUNITY_QR_CHANNELS:
        try:
            await read_community_qr_bytes(channel_id)
        except Exception:
            logger.debug("community_qr_cache_warmup_failed", channel_id=channel_id, exc_info=True)


async def refresh_community_wechat_qr_cache() -> None:
    """Best-effort warmup for the community WeChat QR cache."""

    await refresh_community_qr_cache(["wechat"])


__all__ = [
    "read_community_feishu_qr_bytes",
    "read_community_qr_bytes",
    "read_community_wechat_qr_bytes",
    "refresh_community_qr_cache",
    "refresh_community_wechat_qr_cache",
]
