# Interact 模块说明

最后更新：2026-04-15

`interact/` 负责伴读式对话、流式教学输出和检索增强问答。

当前 canonical 结构：

```text
interact/
  __init__.py
  README.md
  chat/
```

说明：

- `chat/` 是唯一真实链路
- 根目录旧 `graph.py / runtime.py / state.py / support/` 仍保留兼容导入面

上层稳定入口：

```python
from app.workflows.interact import stream_chat_workflow
```
