# Interact Chat 链路说明

最后更新：2026-04-24

`interact/chat/` 是 interact 模块的 canonical lane，负责聊天图、初始状态、运行入口以及 API-facing 聊天用例。

目录角色：

- `graph.py`：chat 图入口，同时承接单次运行入口与 `WORKFLOW_EXPORTS`
- `state.py`：chat 状态类型
- `use_cases.py`：聊天会话、历史记录、SSE 外壳等 API-facing 用例
- `prompts/`：聊天 prompt 构造
- `lib/`：流式输出、策略、检索、工具计划等 helper
- `nodes/`：LangGraph 节点

当前链路：

```text
读取对话状态
  -> 检索学习上下文
  -> 选择教学策略
  -> 选择执行模式
  -> 组装伴读提示词
  -> 流式生成回答
  -> 保存对话轮次
```

关键约定：

- 所有入口都走同一张图：普通对话、知识文档划选提问、构建过程触发只通过 `source` 标记区分，不再使用旁路 direct chat。
- 图内节点 id 保持稳定英文，LangSmith 展示名、路由名和文档链路统一使用中文。
- 所有 LLM 输出默认使用 `primary` 模型选择器；`流式生成回答` 节点的最终回答必须以 SSE token 形式推送。
- 工具扩展只改 `lib/tooling.py` 的工具计划策略；节点不直接硬编码工具清单。
- 划选文本会进入检索 query 和 prompt，但会做长度截断，避免大段选区挤占上下文。

API 层如果需要聊天会话 / 历史 / SSE 外壳，应直接依赖 `interact/chat/use_cases.py` 或 `interact.chat` 的稳定导出。
