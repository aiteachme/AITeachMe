# Interact 模块说明

最后更新：2026-04-16

`interact/` 负责伴读式对话、流式教学输出和检索增强问答。

当前 canonical 结构：

```text
interact/
  __init__.py
  README.md
  application/
  chat/
```

说明：

- `chat/` 是唯一真实链路，真实实现已收口到 `chat/graph.py + chat/state.py + chat/nodes/ + chat/prompts/ + chat/lib/`
- `application/` 承接聊天会话、历史记录与 SSE streaming 外壳等 API-facing 用例
- 根目录旧 `graph.py / runtime.py / state.py / nodes/ / prompts/ / support/` 只保留兼容导入面

上层稳定入口：

```python
from app.workflows.interact import stream_chat_workflow
```
