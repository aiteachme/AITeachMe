"""Exercise the real provider HTTP transport against a local HTTP server."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app.shared.infra.llm_support import litellm_loader


@asynccontextmanager
async def _local_http_server():
    stalled = asyncio.Event()
    release = asyncio.Event()
    tasks = set()
    writers = set()

    async def handle(reader, writer):
        tasks.add(asyncio.current_task())
        writers.add(writer)
        try:
            while True:
                request = await reader.readuntil(b"\r\n\r\n")
                path = request.split(b" ")[1]
                if path == b"/slow":
                    stalled.set()
                    await release.wait()
                if path == b"/truncated":
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                        b"c\r\ndata: hello\n\r\n"
                    )
                    await writer.drain()
                    break  # Missing final chunk: this response must fail.
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: keep-alive\r\n\r\nok"
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            writers.discard(writer)
            tasks.discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", stalled, release
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        for writer in list(writers):
            writer.close()
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _provider_handler(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.delenv("DISABLE_AIOHTTP_TRANSPORT", raising=False)
    litellm_loader.load_litellm.cache_clear()
    litellm_loader.load_litellm()
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    return AsyncHTTPHandler(timeout=httpx.Timeout(1))


def test_provider_transport_rejects_truncated_stream_and_recovers(monkeypatch):
    async def scenario():
        async with _local_http_server() as (base, _stalled, _release):
            handler = _provider_handler(monkeypatch)
            try:
                with pytest.raises(httpx.RemoteProtocolError):
                    async with handler.client.stream("GET", base + "/truncated") as response:
                        async for _chunk in response.aiter_bytes():
                            pass
                assert (await handler.get(base + "/ok")).text == "ok"
            finally:
                await handler.close()

    asyncio.run(scenario())


def test_provider_transport_cancelled_request_does_not_poison_followup(monkeypatch):
    async def scenario():
        async with _local_http_server() as (base, stalled, release):
            handler = _provider_handler(monkeypatch)
            try:
                request = asyncio.create_task(handler.get(base + "/slow"))
                await asyncio.wait_for(stalled.wait(), timeout=2)
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
                release.set()
                assert (await handler.get(base + "/ok")).text == "ok"
            finally:
                await handler.close()

    asyncio.run(scenario())


def test_provider_transport_read_timeout_does_not_poison_followup(monkeypatch):
    async def scenario():
        async with _local_http_server() as (base, _stalled, release):
            handler = _provider_handler(monkeypatch)
            try:
                with pytest.raises(httpx.ReadTimeout):
                    await handler.get(base + "/slow", timeout=httpx.Timeout(0.05))
                release.set()
                assert (await handler.get(base + "/ok")).text == "ok"
            finally:
                await handler.close()

    asyncio.run(scenario())
