from __future__ import annotations

from pathlib import Path

from app.shared.infra.tools import get_tool_registry
from app.shared.infra.tools.tool_loader import load_external_toolpacks, load_toolpack_manifests

_FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def test_toolpack_manifests_use_later_directory_priority() -> None:
    project_root = _FIXTURE_ROOT / "toolpacks_project"
    user_root = _FIXTURE_ROOT / "toolpacks_user"

    manifests = load_toolpack_manifests([project_root, user_root], include_default_dirs=False)

    assert len(manifests) == 1
    assert manifests[0]["name"] == "shared_pack"
    assert manifests[0]["description"] == "user"


def test_external_toolpacks_register_real_tools() -> None:
    registry = get_tool_registry()
    registry._tools.clear()
    toolpacks_root = _FIXTURE_ROOT / "toolpacks_runtime"

    loaded = load_external_toolpacks([toolpacks_root], include_default_dirs=False, registry=registry)

    definition = registry.get("summarize_question")
    assert "exam_helpers" in loaded
    assert definition is not None
    assert definition.description == "toolpack tool"
    assert definition.source == "toolpack:exam_helpers"


def test_disabled_or_broken_toolpacks_do_not_crash_loading() -> None:
    registry = get_tool_registry()
    registry._tools.clear()
    root = _FIXTURE_ROOT / "toolpacks_runtime"

    loaded = load_external_toolpacks([root], include_default_dirs=False, registry=registry)

    assert "disabled_pack" not in loaded
    assert "broken_pack" not in loaded
    assert registry.get("ignored_tool") is None
