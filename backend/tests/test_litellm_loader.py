import builtins
import asyncio

from app.shared.infra.llm_support import litellm_loader


def test_load_litellm_forces_local_cost_map_before_import(monkeypatch) -> None:
    sentinel = object()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "litellm":
            assert litellm_loader.os.environ["PYTHON_DOTENV_DISABLED"] == "1"
            assert litellm_loader.os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
            return sentinel
        return real_import(name, globals, locals, fromlist, level)

    litellm_loader.load_litellm.cache_clear()
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert litellm_loader.load_litellm() is sentinel
    litellm_loader.load_litellm.cache_clear()


def test_warm_litellm_runs_import_off_event_loop(monkeypatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_load():
        calls.append(sentinel)
        return sentinel

    monkeypatch.setattr(litellm_loader, "load_litellm", fake_load)

    asyncio.run(litellm_loader.warm_litellm())

    assert calls == [sentinel]
