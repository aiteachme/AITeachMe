"""提示词变量填充工具。

推荐用法：

```python
from app.shared.infra.prompt_loader import populate_prompt

SYSTEM_PROMPT = "你好，{{ subject }}。{% if weak_points %}薄弱点：...{% endif %}"

prompt = populate_prompt(
    SYSTEM_PROMPT,
    subject="高等数学",
    weak_points=["极限", "导数"],
)
```

模板支持标准 Jinja2 语法：

1. 单个变量
   `{{ subject }}`

2. 条件分支
   `{% if weak_points %}...{% endif %}`

3. 列表循环
   `{% for point in weak_points %}- {{ point }}{% endfor %}`

注意：
- 第一个参数必须是提示词字符串常量，而不是模板名。
- 未传入模板中使用到的变量时，会直接报错，避免静默渲染错误。
"""

from __future__ import annotations

from functools import lru_cache

from jinja2 import Environment, StrictUndefined


@lru_cache(maxsize=1)
def _get_environment() -> Environment:
    """创建共享的 Jinja2 渲染环境。"""

    return Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def populate_prompt(prompt_template: str, **kwargs) -> str:
    """将提示词模板中的变量填充为最终字符串。"""

    if not isinstance(prompt_template, str):
        raise TypeError("prompt_template 必须是字符串模板。")

    template = _get_environment().from_string(prompt_template)
    return template.render(**kwargs).strip()
