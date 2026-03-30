"""工具定义 YAML 加载器。

从 ``backend/tools/`` 目录加载工具定义 YAML 文件。
YAML 文件描述工具的元信息（名称、描述、参数 schema），
实际执行逻辑在 ``core/tools/builtin/`` 的 Python 文件中。

扫描路径：
1. ``backend/tools/`` — 项目内置工具定义
2. ``~/.atm/tools/`` — 用户自定义工具定义
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger()


def _get_project_tools_dir() -> Path:
    """项目内置 tools 目录: backend/tools/"""
    return Path(__file__).parent.parent.parent.parent / "tools"


def _get_user_tools_dir() -> Path:
    """用户自定义 tools 目录: ~/.atm/tools/"""
    return Path.home() / ".atm" / "tools"


def load_tool_definitions(
    extra_dirs: list[Path] | None = None,
) -> list[dict]:
    """扫描所有路径，加载工具定义 YAML 文件。

    Returns:
        工具定义列表（name, description, parameters 等）。
    """

    dirs = [_get_project_tools_dir(), _get_user_tools_dir()]
    if extra_dirs:
        dirs.extend(extra_dirs)

    loaded: dict[str, dict] = {}

    for tool_dir in dirs:
        if not tool_dir.exists():
            continue

        for yaml_file in sorted(tool_dir.glob("*.yaml")):
            try:
                parsed = _parse_tool_yaml(yaml_file)
                if parsed and "name" in parsed:
                    loaded[parsed["name"]] = parsed
                    logger.debug("tool_definition_loaded",
                                name=parsed["name"],
                                source=str(yaml_file))
            except Exception as exc:
                logger.warning("tool_yaml_parse_failed",
                              file=str(yaml_file),
                              error=str(exc))

    return list(loaded.values())


def _parse_tool_yaml(path: Path) -> dict | None:
    """解析工具定义 YAML 文件。"""

    text = path.read_text(encoding="utf-8")

    # 优先使用 pyyaml
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # 回退到简单解析
    result: dict = {}
    current_key = None
    current_dict: dict | None = None

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
                if value.lower() == "true":
                    result[key] = True
                elif value.lower() == "false":
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

        elif indent > 0 and current_key:
            if ":" in stripped:
                if current_dict is None:
                    current_dict = {}
                sub_key, _, sub_val = stripped.partition(":")
                sub_val = sub_val.strip()
                if sub_val.startswith('"') and sub_val.endswith('"'):
                    sub_val = sub_val[1:-1]
                if sub_val.lower() == "true":
                    sub_val = True
                elif sub_val.lower() == "false":
                    sub_val = False
                current_dict[sub_key.strip()] = sub_val

    if current_key and current_dict is not None:
        result[current_key] = current_dict

    return result
