# 工具定义目录

> `backend/tools/*.yaml` 现在是过渡态，只保留工具说明与向后兼容元信息。
> 真正可执行的外部扩展入口已经切到 `backend/toolpacks/<name>/manifest.yaml + handler.py`。

## 结构

```
backend/tools/
├── README.md           ← 本文件
├── web_search.yaml     ← 工具定义（元信息）
├── search_kb.yaml
├── remember_info.yaml
└── ...
```

## 工具定义格式

```yaml
name: web_search
description: 搜索互联网获取最新相关信息
version: "1.0"
category: 检索
enabled: true
parameters:
  query:
    type: string
    description: 搜索查询
    required: true
  top_k:
    type: integer
    description: 返回结果数量
    default: 5
```

## 当前状态

- `backend/tools/*.yaml`：只描述工具元信息，不再宣称自己能独立完成运行时注册。
- `backend/toolpacks/<name>/manifest.yaml + handler.py`：真实可接入的外部工具扩展点。
- `app.shared.infra.tools`：唯一 canonical tool registry。

## 与 Skill 的区别

- `tool`：原子动作、稳定输入输出、运行时真正可调用。
- `skillpack`：`SKILL.md` 策略包，只负责提示词、默认约束、推荐 toolset，不执行代码。

## Toolpack 示例

```text
backend/toolpacks/
└── exam_helpers/
    ├── manifest.yaml
    └── handler.py
```

`manifest.yaml`

```yaml
name: exam_helpers
description: 题型辅助工具包
entrypoint: handler.py:register_toolpack
enabled: true
```

`handler.py`

```python
from app.shared.infra.tools import ToolDefinition


def register_toolpack():
    return [
        ToolDefinition(
            name="summarize_question_stem",
            description="提取题干中的关键信息",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                },
                "required": ["question"],
            },
            handler=lambda question: question[:80],
            tags=["teaching", "exam"],
            source="toolpack:exam_helpers",
        )
    ]
```
