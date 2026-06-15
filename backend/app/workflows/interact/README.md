# Interact 工作流

最后更新：2026-06-15

`interact/` 负责伴读引擎：对话、划选问答、检索增强教学、工具辅助和 SSE 流式输出。

```text
user question / selected context
  -> chat
  -> retrieval + strategy + prompt
  -> streamed answer
  -> chat history
```

## 目录

```text
interact/
  chat/      # 唯一真实对话链路
```

对应文档：

- [chat/README.md](chat/README.md)

## 当前链路

| 链路 | 入口 | 输出 |
| --- | --- | --- |
| `chat` | `stream_chat_workflow` | SSE token、client actions、ChatMessage |

## 总流程

## 1. 接收对话请求

入口：`stream_chat_workflow`

输入：

```text
course_id
user_id
session_id
question
source
anchor_id
selected_text
selected_context
selection_context
attached_file_ids
model_override
```

输出：SSE 流和最终 `InteractWorkflowState`

## 2. 图内教学处理

动作：解析会话、读历史、检索上下文、选择教学策略、选择执行模式、组装 prompt、流式回答。

输出：

```text
assistant_response
client_actions
contexts
strategy_mode
execution_mode
```

## 3. 持久化对话

动作：把 user/assistant 消息写入同一个 `turn_id`，更新会话标题和最后消息时间。

输出：

```text
ChatMessage(user)
ChatMessage(assistant)
ChatSession.title
ChatSession.last_message_at
```

## 边界

Interact 不生成知识文档，不更新知识图谱，不更新 Profile 掌握度。

它会读取 Profile 薄弱点、近期错题、Digest 知识文档和知识图谱作为教学上下文。

普通对话、知识文档划选提问、考试题讲解和构建过程触发都走同一条 `chat` 图，只通过 `source` 和上下文字段区分。
