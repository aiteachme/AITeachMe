"""Jinja2 提示词模板加载器。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


@lru_cache(maxsize=1)
def _get_environment() -> Environment:
    """创建共享的 Jinja2 环境。"""

    prompt_root = Path(__file__).resolve().parents[1] / "agents"
    return Environment(
        loader=FileSystemLoader(str(prompt_root)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt(template_path: str, **kwargs) -> str:
    """渲染提示词模板。"""

    template = _get_environment().get_template(template_path)
    return template.render(**kwargs).strip()
