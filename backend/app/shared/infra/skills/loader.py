"""Skill 加载器 — 支持多路径扫描 + OpenClaw 风格 SKILL.md 文件。

扫描路径（按优先级）：
1. 项目内置: ``backend/skills/``
2. 用户自定义: ``~/.atm/skills/``

OpenClaw 规范：
- 每个 Skill 是一个目录，包含 SKILL.md 文件
- SKILL.md 使用 YAML frontmatter 定义元信息
- Markdown 正文是具体的执行指令

目录结构::

    backend/skills/               ← 项目内置
    ├── find_resources/
    │   └── SKILL.md
    ├── explain_with_analogy/
    │   └── SKILL.md
    └── review_mistakes/
        └── SKILL.md

    ~/.atm/skills/                ← 用户自定义
    └── my_custom_skill/
        └── SKILL.md
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ── 默认扫描路径 ──────────────────────────────────────────────

def _get_project_skills_dir() -> Path:
    """项目内置 skills 目录: backend/skills/"""
    # 从 core/skills/loader.py 往上走到 backend/
    return Path(__file__).parent.parent.parent.parent / "skills"


def _get_user_skills_dir() -> Path:
    """用户自定义 skills 目录: ~/.atm/skills/"""
    return Path.home() / ".atm" / "skills"


def get_all_skill_dirs() -> list[Path]:
    """返回所有 skill 扫描路径（按优先级）。

    Returns:
        [项目内置目录, 用户自定义目录]
        只返回实际存在的目录。
    """
    dirs = [
        _get_project_skills_dir(),
        _get_user_skills_dir(),
    ]
    return [d for d in dirs if d.exists()]


# ── SKILL.md 解析 ─────────────────────────────────────────────


def _parse_skill_md(path: Path) -> dict | None:
    """解析 SKILL.md 文件，提取 YAML frontmatter 和 markdown 正文。"""

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("skill_md_read_failed", path=str(path), error=str(exc))
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        frontmatter = _parse_yaml(parts[1].strip())
    except Exception as exc:
        logger.warning("skill_md_frontmatter_invalid", path=str(path), error=str(exc))
        return None

    body = parts[2].strip()
    frontmatter["instructions"] = body
    frontmatter["_source_path"] = str(path)
    return frontmatter


def _parse_yaml(text: str) -> dict:
    """解析 YAML — 优先用 pyyaml，回退到简单解析器。"""

    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # 简单回退解析器
    result: dict = {}
    current_key = None
    current_list: list | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and ":" in stripped:
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                result[key] = value
                current_key = None
            else:
                current_key = key
                current_list = None

        elif stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
            current_list.append(stripped[2:].strip())

        elif indent > 0 and ":" in stripped and current_key:
            if current_key not in result:
                result[current_key] = {}
            sub_key, _, sub_value = stripped.partition(":")
            sub = sub_key.strip()
            val = sub_value.strip()
            if isinstance(result[current_key], dict):
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.lower() == "true":
                    val = True
                elif val.lower() == "false":
                    val = False
                result[current_key][sub] = val

    if current_key and current_list is not None:
        result[current_key] = current_list

    return result


# ── 扫描加载 ──────────────────────────────────────────────────


def load_all_skill_definitions(
    extra_dirs: list[Path] | None = None,
) -> list[dict]:
    """扫描所有路径，加载全部 SKILL.md 文件。

    扫描顺序：
    1. ``backend/skills/``（项目内置）
    2. ``~/.atm/skills/``（用户自定义）
    3. ``extra_dirs``（额外指定路径）

    同名 Skill 后加载的覆盖先加载的（用户 > 项目）。

    Returns:
        解析后的 Skill 定义列表（去重后）。
    """

    all_dirs = get_all_skill_dirs()
    if extra_dirs:
        all_dirs.extend(d for d in extra_dirs if d.exists())

    loaded: dict[str, dict] = {}  # name → definition（后加载覆盖）

    for skill_dir in all_dirs:
        for subdir in sorted(skill_dir.iterdir()):
            if not subdir.is_dir():
                continue
            skill_md = subdir / "SKILL.md"
            if not skill_md.exists():
                continue

            parsed = _parse_skill_md(skill_md)
            if parsed and "name" in parsed:
                loaded[parsed["name"]] = parsed
                logger.info("skill_md_loaded",
                            name=parsed["name"],
                            source=str(skill_md))

    return list(loaded.values())


def auto_discover_python_skills() -> None:
    """扫描 builtin/ 目录，自动 import Python skill 模块。"""

    builtin_package = "app.shared.infra.skills.builtin"
    try:
        package = importlib.import_module(builtin_package)
    except ImportError:
        return

    for _, name, _ in pkgutil.iter_modules(package.__path__):
        try:
            importlib.import_module(f"{builtin_package}.{name}")
            logger.debug("python_skill_imported", module=name)
        except Exception as exc:
            logger.warning("python_skill_import_failed", module=name, error=str(exc))
