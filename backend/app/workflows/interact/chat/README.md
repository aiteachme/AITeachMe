# Interact Chat 链路说明

最后更新：2026-04-15

`interact/chat/` 是 interact 模块的 canonical lane，负责聊天图、初始状态和运行入口。

目录角色：

- `graph.py`：chat 图入口
- `runtime.py`：chat 运行入口兼容门面
- `state.py`：chat 状态类型
- `prompts/`：聊天 prompt 兼容门面
- `lib/`：流式输出、策略、检索等 helper 门面
- `nodes/`：节点门面

当前仍有一部分历史实现保留在模块根目录，后续继续逐步下沉。
