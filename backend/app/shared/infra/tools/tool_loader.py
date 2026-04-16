"""Tool loader for executable external toolpacks."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import structlog

from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry, get_tool_registry

logger = structlog.get_logger(__name__)


def _get_project_toolpacks_dir() -> Path:
    return Path(__file__).parent.parent.parent.parent.parent / "toolpacks"


def _get_user_toolpacks_dir() -> Path:
    return Path.home() / ".atm" / "toolpacks"


def _parse_yaml(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")

    try:
        import yaml

        parsed = yaml.safe_load(text) or {}
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        pass

    result: dict[str, Any] = {}
    current_key: str | None = None
    current_dict: dict[str, Any] | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in stripped:
            if current_key and current_dict is not None:
                result[current_key] = current_dict
                current_dict = None

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                lowered = value.lower()
                if lowered == "true":
                    result[key] = True
                elif lowered == "false":
                    result[key] = False
                else:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        try:
                            result[key] = float(value)
                        except ValueError:
                            result[key] = value
                current_key = None
            else:
                current_key = key
        elif indent > 0 and current_key and ":" in stripped:
            if current_dict is None:
                current_dict = {}
            sub_key, _, sub_val = stripped.partition(":")
            sub_val = sub_val.strip()
            if sub_val.startswith('"') and sub_val.endswith('"'):
                sub_val = sub_val[1:-1]
            lowered = sub_val.lower()
            if lowered == "true":
                current_dict[sub_key.strip()] = True
            elif lowered == "false":
                current_dict[sub_key.strip()] = False
            else:
                current_dict[sub_key.strip()] = sub_val

    if current_key and current_dict is not None:
        result[current_key] = current_dict
    return result


def _iter_toolpack_dirs(
    extra_dirs: list[Path] | None = None,
    *,
    include_default_dirs: bool = True,
) -> list[Path]:
    dirs: list[Path] = []
    if include_default_dirs:
        dirs.extend([_get_project_toolpacks_dir(), _get_user_toolpacks_dir()])
    if extra_dirs:
        dirs.extend(extra_dirs)
    return [directory for directory in dirs if directory.exists()]


def load_toolpack_manifests(
    extra_dirs: list[Path] | None = None,
    *,
    include_default_dirs: bool = True,
) -> list[dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for root_dir in _iter_toolpack_dirs(extra_dirs, include_default_dirs=include_default_dirs):
        for subdir in sorted(root_dir.iterdir()):
            if not subdir.is_dir():
                continue
            manifest_path = subdir / "manifest.yaml"
            if not manifest_path.exists():
                manifest_path = subdir / "manifest.yml"
            if not manifest_path.exists():
                continue
            try:
                parsed = _parse_yaml(manifest_path) or {}
            except Exception as exc:
                logger.warning("toolpack_manifest_parse_failed", manifest=str(manifest_path), error=str(exc))
                continue
            name = str(parsed.get("name") or subdir.name).strip()
            if not name:
                continue
            loaded[name] = {
                **parsed,
                "name": name,
                "directory": str(subdir),
                "manifest_path": str(manifest_path),
                "entrypoint": str(parsed.get("entrypoint") or "handler.py:register_toolpack").strip(),
                "enabled": bool(parsed.get("enabled", True)),
                "source_label": f"toolpack:{name}",
            }
    return list(loaded.values())


def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 构建 import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _register_toolpack_result(
    result: Any,
    *,
    registry: ToolRegistry,
    source_label: str,
) -> None:
    if result is None:
        return
    if isinstance(result, ToolDefinition):
        if result.source in ("", "python"):
            result.source = source_label
        registry.register(result)
        return
    if isinstance(result, Mapping):
        definition = ToolDefinition(
            name=str(result.get("name") or "").strip(),
            description=str(result.get("description") or "").strip(),
            parameters=dict(result.get("parameters") or {}),
            handler=result["handler"],
            is_async=bool(result.get("is_async", False)),
            tags=list(result.get("tags") or []),
            source=str(result.get("source") or source_label),
            risk_level=str(result.get("risk_level") or "low"),
            scopes=list(result.get("scopes") or []),
            timeout_s=result.get("timeout_s"),
            requires_subject=bool(result.get("requires_subject", False)),
            requires_approval=bool(result.get("requires_approval", False)),
            cache_policy=str(result.get("cache_policy") or "none"),
        )
        registry.register(definition)
        return
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
        for item in result:
            _register_toolpack_result(item, registry=registry, source_label=source_label)
        return
    raise TypeError(f"不支持的 toolpack 注册返回值类型：{type(result)!r}")


def load_external_toolpacks(
    extra_dirs: list[Path] | None = None,
    *,
    registry: ToolRegistry | None = None,
    include_default_dirs: bool = True,
) -> list[str]:
    resolved_registry = registry or get_tool_registry()
    loaded_names: list[str] = []
    for manifest in load_toolpack_manifests(extra_dirs, include_default_dirs=include_default_dirs):
        if not bool(manifest.get("enabled", True)):
            continue
        directory = Path(str(manifest["directory"]))
        entrypoint = str(manifest.get("entrypoint") or "handler.py:register_toolpack").strip()
        handler_file, _, callable_name = entrypoint.partition(":")
        callable_name = callable_name or "register_toolpack"
        handler_path = directory / (handler_file or "handler.py")
        if not handler_path.exists():
            logger.warning(
                "toolpack_handler_missing",
                name=manifest["name"],
                handler_path=str(handler_path),
            )
            continue
        module_name = "atm_toolpack_" + hashlib.md5(str(handler_path).encode("utf-8")).hexdigest()
        try:
            module = _load_module_from_path(module_name, handler_path)
            handler = getattr(module, callable_name)
            signature = inspect.signature(handler)
            if len(signature.parameters) == 0:
                result = handler()
            else:
                result = handler(resolved_registry)
            if inspect.isawaitable(result):
                raise TypeError("toolpack 注册函数必须是同步的")
            _register_toolpack_result(
                result,
                registry=resolved_registry,
                source_label=str(manifest["source_label"]),
            )
            loaded_names.append(str(manifest["name"]))
            logger.info(
                "toolpack_loaded",
                name=manifest["name"],
                manifest_path=manifest["manifest_path"],
            )
        except Exception as exc:
            logger.warning(
                "toolpack_load_failed",
                name=manifest["name"],
                manifest_path=manifest["manifest_path"],
                error=str(exc),
            )
    return loaded_names


__all__ = [
    "load_external_toolpacks",
    "load_toolpack_manifests",
]
