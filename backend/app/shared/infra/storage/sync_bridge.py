"""同步调用桥接层。

在 FastAPI 异步上下文中部分调用方仍是同步函数（例如 build_store、
publish 流程中的辅助函数），此模块提供统一的同步→异步桥接，
避免在每个调用点重复编写 ThreadPoolExecutor 样板代码。

用法示例::

    from app.shared.infra.storage.sync_bridge import run_store_sync

    data: bytes | None = run_store_sync(store.read_bytes, "key", default=None)
    run_store_sync(store.write_bytes, "key", b"content")
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import threading
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_MISSING = object()

_BACKGROUND_LOOP: asyncio.AbstractEventLoop | None = None
_BACKGROUND_THREAD: threading.Thread | None = None
_BACKGROUND_LOCK = threading.Lock()
_BACKGROUND_READY: threading.Event | None = None


def _run_background_loop(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
    asyncio.set_event_loop(loop)
    ready.set()
    loop.run_forever()


def _get_background_loop() -> asyncio.AbstractEventLoop:
    global _BACKGROUND_LOOP, _BACKGROUND_THREAD, _BACKGROUND_READY

    with _BACKGROUND_LOCK:
        if _BACKGROUND_LOOP is not None and _BACKGROUND_LOOP.is_running():
            return _BACKGROUND_LOOP

        loop = asyncio.new_event_loop()
        ready = threading.Event()
        thread = threading.Thread(
            target=_run_background_loop,
            args=(loop, ready),
            name="storage-sync-bridge",
            daemon=True,
        )
        thread.start()
        ready.wait(timeout=2)
        _BACKGROUND_LOOP = loop
        _BACKGROUND_THREAD = thread
        _BACKGROUND_READY = ready
        return loop


def _shutdown_background_loop() -> None:
    global _BACKGROUND_LOOP, _BACKGROUND_THREAD, _BACKGROUND_READY

    with _BACKGROUND_LOCK:
        loop = _BACKGROUND_LOOP
        thread = _BACKGROUND_THREAD
        _BACKGROUND_LOOP = None
        _BACKGROUND_THREAD = None
        _BACKGROUND_READY = None

    if loop is None or not loop.is_running():
        return
    loop.call_soon_threadsafe(loop.stop)
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
    if not loop.is_closed():
        loop.close()


atexit.register(_shutdown_background_loop)


def run_store_sync(
    coro_fn: Callable[..., Awaitable[T]],
    *args: Any,
    default: Any = _MISSING,
    **kwargs: Any,
) -> T:
    """同步调用一个 async 存储方法，安全处理事件循环嵌套。

    Parameters
    ----------
    coro_fn:
        一个返回 awaitable 的 callable，例如 ``store.read_bytes``。
    *args, **kwargs:
        透传给 ``coro_fn`` 的位置参数与关键字参数。
    default:
        如果调用抛出异常且指定了 default，返回该默认值而非抛出。
        未指定 default 时异常会正常传播。
    """

    coro = coro_fn(*args, **kwargs)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop is not None and loop.is_running():
            # 已在异步上下文中（FastAPI / LangGraph node 等）时，不能嵌套
            # asyncio.run。复用后台事件循环，避免每次同步桥调用都创建
            # Windows socketpair，长流程频繁写进度时会触发 WinError 10055。
            future = asyncio.run_coroutine_threadsafe(coro, _get_background_loop())
            return future.result()
        else:
            return asyncio.run(coro)
    except concurrent.futures.CancelledError:
        coro.close()
        if default is not _MISSING:
            return default  # type: ignore[return-value]
        raise
    except Exception:
        if default is not _MISSING:
            return default  # type: ignore[return-value]
        raise

