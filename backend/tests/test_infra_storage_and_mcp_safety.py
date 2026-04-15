from __future__ import annotations

import asyncio

import pytest

from app.shared.infra.mcp.manager import MCPManager, MCPServer, MCPTool
from app.shared.infra.storage import local_store
from app.shared.infra.storage.local_store import LocalArtifactStore
from app.shared.infra.tools import registry as registry_module
from app.shared.infra.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def reset_tool_registry():
    original = registry_module._registry
    registry_module._registry = ToolRegistry()
    yield
    registry_module._registry = original


def test_local_artifact_store_rejects_path_escape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(local_store, "get_runtime_data_dir", lambda: tmp_path)
    store = LocalArtifactStore()

    with pytest.raises(ValueError, match="escapes runtime data dir"):
        asyncio.run(store.write_bytes("../escape.txt", b"nope"))

    asyncio.run(store.write_bytes("subject/raw_markdowns/1.md", "内容".encode("utf-8")))
    assert asyncio.run(store.read_bytes("subject/raw_markdowns/1.md")).decode("utf-8") == "内容"


def test_local_artifact_store_allows_absolute_paths_under_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(local_store, "get_runtime_data_dir", lambda: tmp_path)
    store = LocalArtifactStore()
    path = tmp_path / "subject" / "raw.txt"

    asyncio.run(store.write_bytes(str(path), b"ok"))

    assert asyncio.run(store.read_bytes(str(path))) == b"ok"


def test_mcp_tools_require_explicit_allowlist_before_registry_exposure() -> None:
    manager = MCPManager()
    server = MCPServer(
        name="demo",
        transport="stdio",
        config={},
        connected=True,
        tools=[
            MCPTool(
                name="search",
                description="search",
                parameters={"type": "object"},
                server_name="demo",
            )
        ],
    )

    manager._register_to_tools(server)

    assert registry_module.get_tool_registry().get("mcp.demo.search") is None

    server.config = {"allowed_tools": ["search"], "requires_approval": False}
    manager._register_to_tools(server)

    registered = registry_module.get_tool_registry().get("mcp.demo.search")
    assert registered is not None
    assert registered.source == "mcp:demo"
    assert registered.scopes == ["mcp"]
