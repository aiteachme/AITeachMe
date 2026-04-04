"""同步调用桥接层。

在 FastAPI 异步上下文中部分调用方仍是同步函数（例如 docgen_store、
publish 流程中的辅助函数），此模块提供统一的同步→异步桥接，
避免在每个调用点重复编写 ThreadPoolExecutor 样板代码。

用法示例::

    from app.shared.infra.storage.sync_bridge import run_store_sync

    data: bytes | None = run_store_sync(store.read_bytes, "key", default=None)
    run_store_sync(store.write_bytes, "key", b"content")
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_MISSING = object()


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
            # 已在异步上下文中（FastAPI handler 等），
            # 在新线程中创建一个独立事件循环来执行。
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)
    except Exception:
        if default is not _MISSING:
            return default  # type: ignore[return-value]
        raise
