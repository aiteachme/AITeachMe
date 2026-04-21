# Interact 模块说明

最后更新：2026-04-16

`interact/` 负责伴读式对话、流式教学输出和检索增强问答。

当前 canonical 结构：

```text
interact/
  __init__.py
  README.md
  chat/
    graph.py
    state.py
    use_cases.py
    nodes/
    prompts/
    lib/
```

说明：

- `chat/` 是唯一真实链路，聊天图、运行入口、API-facing 用例、会话/历史/SSE 外壳都已下沉到 `chat/`
- `chat/lib/events.py` 承接 Interact 领域事件定义，不再在模块根保留 `events.py`
- 根目录只保留稳定导入面和 README；`WORKFLOW_EXPORTS` 直接由 `interact.__init__` 懒加载暴露，不再单独保留 `exports.py`

上层稳定入口：

```python
from app.workflows.interact import stream_chat_workflow
```
