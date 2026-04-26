# 06. Interact 伴读引擎

最后更新：2026-04-27

本文是 Interact 的跨模块事实页。目录结构和入口以 `backend/app/workflows/interact/README.md` 为准。

## 当前职责

Interact 负责伴读式对话、知识文档划选问答、检索增强上下文组装和 SSE 流式教学输出。

它不负责：

- 生成知识文档。
- 构建知识图谱。
- 生成或批改试卷。
- 直接改写用户画像。

## 代码入口

| 职责 | 文件 |
| --- | --- |
| 稳定导入面 | `backend/app/workflows/interact/__init__.py` |
| 当前唯一链路 | `backend/app/workflows/interact/chat/` |
| 图定义 | `backend/app/workflows/interact/chat/graph.py` |
| 状态合同 | `backend/app/workflows/interact/chat/state.py` |
| API-facing 用例 | `backend/app/workflows/interact/chat/use_cases.py` |
| Prompt builder | `backend/app/workflows/interact/chat/prompts/` |

稳定入口：

```python
from app.workflows.interact import stream_chat_workflow
```

## 主流程

```text
load_or_create_session
  -> load_history
  -> retrieve_context
  -> select_teaching_strategy
  -> build_messages
  -> stream_answer
  -> persist_turn
```

上下文来源包括聊天历史、知识文档划选、检索证据、薄弱项和近期错题。最终回答使用 `settings.models.primary`，通过 SSE token 流返回。

## 入口形态

- 常规聊天。
- 知识文档划选提问。
- 构建过程中的解释/追问入口。

这些入口都进入 `chat` 主链路；`source`、`anchor_id`、`selected_context` 只作为触发元数据和 turn 元数据，不另开平行链路。

## 约束

- Prompt 只在 `chat/prompts/` 拼装，不在 API 层拼 prompt。
- 检索和教学策略可以读 Profile/Examine 产物，但不在 Interact 内直接写画像。
- 会话历史持久化由 chat use case 统一处理。
- 模块根只导出稳定入口，不承载业务实现。
