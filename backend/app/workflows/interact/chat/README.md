# Interact Chat 链路

最后更新：2026-06-15

职责：把用户问题、课程资料、划选上下文和学习画像组织成一次流式教学回答。

```text
输入: question + course context + selection context + profile context
输出: SSE token + assistant_response + chat turn
```

## 主流程

```text
resolve_chat_session
  -> load_history_state
  -> retrieve_context
  -> select_teaching_strategy
  -> select_execution_mode
  -> build_prompt
  -> stream_answer
  -> persist_turn
  -> finalize_chat_session
```

## 入口

`stream_chat_workflow`

输入：

```text
course_id
user_id
session_id
question
scene
source
model_override
anchor_id
selected_text
selected_context
selection_context
source_chunk_id
attached_file_ids
```

输出：

```text
session_id
assistant_response
client_actions
turn_id
stream_interrupted
error
```

## 1. `resolve_chat_session`

输入：`course_id`, `user_id`, `session_id`, `question`, `source`, `model_override`

动作：确认本轮写入哪个 `ChatSession`；没有可用会话则创建新会话，并通过 SSE 返回会话 ID。

输出：

```text
session_id
session_title
session_created
```

SSE：

```text
status:session_resolved
```

## 2. `load_history_state`

输入：`course_id`, `user_id`, `session_id`

动作：读取近期对话、课程展示信息、用户画像、薄弱知识点和近期错题。

输出：

```text
recent_messages
course_context
weak_points
recent_mistakes
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `course_context` | 课程名、说明、学习目标、用户画像摘要 |
| `weak_points` | Profile 薄弱知识点，用于个性化提醒 |
| `recent_mistakes` | 近期错题摘要，用于复盘式教学 |

## 3. `retrieve_context`

输入：`question`, `selected_context`, `selection_context`, `course_id`, `user_id`

动作：把用户问题和划选内容合成检索 query；优先查 KnowledgeUnit/知识图谱，必要时向量检索兜底。

输出：

```text
retrieval_results
contexts
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `retrieval_results` | 图谱或向量检索证据，供 prompt 使用 |
| `contexts` | 保存到聊天消息里的引用上下文 |
| `selection_context` | 划选来源、标题、段落、chunk 等定位信息 |

## 4. `select_teaching_strategy`

输入：`question`, `selected_context`

动作：判断本轮应该讲解、引导、复盘、规划还是练习。

输出：

```text
strategy_mode
```

## 5. `select_execution_mode`

输入：`question`, `selected_context`, `strategy_mode`, `retrieval_results`

动作：决定直接回答还是进入受控工具模式。

输出：

```text
execution_mode
```

常见值：

```text
single_pass
plan_execute
```

## 6. `build_prompt`

输入：

```text
course_context
question
selection_context
retrieval_results
recent_messages
weak_points
recent_mistakes
strategy_mode
execution_mode
```

动作：按优先级组装最终 LLM messages。

输出：

```text
messages
```

上下文优先级：

```text
划选上下文 > 用户问题 > 检索证据 > 近期历史 > Profile 背景
```

## 7. `stream_answer`

输入：`messages`, `execution_mode`, `retrieval_results`, `model_override`, `source`, `attached_file_ids`

动作：调用模型或工具计划，持续发送 SSE token；客户端断开时停止后续写库。

输出：

```text
assistant_response
client_actions
stream_interrupted
error
```

SSE：

```text
status:answering
status:home_intake
token
```

## 8. `persist_turn`

输入：

```text
course_id
user_id
session_id
question
assistant_response
contexts
source
anchor_id
selected_text
source_chunk_id
```

动作：保存 user/assistant 两条消息，并关联同一个 `turn_id`。

输出：

```text
turn_id
ChatMessage(user)
ChatMessage(assistant)
```

## 9. `finalize_chat_session`

输入：`course_id`, `user_id`, `session_id`, `question`, `assistant_response`, `turn_id`

动作：更新 `last_message_at`；如果还是默认标题，则生成或回退短标题。

输出：

```text
session_title
```

## API 用例

`use_cases.py` 负责图外 HTTP 用例：

```text
list_chat_sessions
list_recent_chat_sessions
create_session
list_chat_threads
delete_session
clear_messages
```

这些函数只管理会话/历史列表；真正生成回答必须走 `stream_chat_workflow`。

## 模型策略

模型选择、输出 token 预算和 trace metadata 统一在 `lib/model_policy.py`。

工具计划策略在 `lib/tooling.py`。

LangSmith 节点读写字段在 `graph.py` 的 `NODE_TRACE_DETAILS`。
