# Interact Chat 链路说明

最后更新：2026-04-16

`interact/chat/` 是 interact 模块的 canonical lane，负责聊天图、初始状态、运行入口以及 API-facing 聊天用例。

目录角色：

- `graph.py`：chat 图入口，同时承接单次运行入口与 `WORKFLOW_EXPORTS`
- `state.py`：chat 状态类型
- `use_cases.py`：聊天会话、历史记录、SSE 外壳等 API-facing 用例
- `prompts/`：聊天 prompt 构造
- `lib/`：流式输出、策略、检索等 helper
- `nodes/`：LangGraph 节点

API 层如果需要聊天会话 / 历史 / SSE 外壳，应直接依赖 `interact/chat/use_cases.py` 或 `interact.chat` 的稳定导出。
