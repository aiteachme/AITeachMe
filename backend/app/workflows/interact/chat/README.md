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
解析或创建会话
  -> 读取对话状态
  -> 检索学习上下文
  -> 选择教学策略
  -> 选择执行模式
  -> 组装伴读提示词
  -> 流式生成回答
  -> 保存对话轮次
  -> 更新会话元信息
```

节点说明：

- `解析或创建会话`：读取 `chat_session`，如果请求里没有可用 `session_id` 就创建新会话；同时发出 `status:session_resolved`，让前端先拿到真实会话 ID。
- `读取对话状态`：读取近期对话、课程展示信息、用户整体画像、薄弱知识点和近期错题。它们只做个性化背景，不能覆盖本轮划选主题。
- `检索学习上下文`：普通闲聊且没有入口上下文时跳过课程检索；学习问题会把用户问题和划选内容合成检索 query，优先查 KnowledgeUnit/知识图谱证据；只有图谱没有命中时才使用向量检索兜底。LangSmith 中该节点下会出现 `interact.retrieval.knowledge_unit_search` 和按需出现的 `interact.retrieval.vector_fallback_search` 子 span。
- `选择教学策略`：根据问题和入口上下文选择讲解、引导、复盘、规划或练习策略。
- `选择执行模式`：决定本轮是 `single_pass` 直接回答还是 `plan_execute` 受控工具模式；划词问答和通用闲聊默认直接回答，避免工具调用稀释划选上下文或把通用对话拉回课程。
- `组装伴读提示词`：先解析场景，再选择专属 system prompt：通用对话、常规学习、知识文档划词、考试题讲解、知识库构建各自独立；没有入口上下文且用户只是闲聊时，课程只保留为会话归属，不展开完整背景。划词和考试题场景只保留极简课程背景；划词入口上下文足够时，不再把重复检索正文追加成 `参考资料`。
- `流式生成回答`：调用主模型或受控工具，持续发出 SSE token；如果客户端断开，会标记 `stream_interrupted` 并停止后续写库。
- `保存对话轮次`：将 user/assistant 两条消息写入同一个 `turn_id`，并保存引用上下文、划选 anchor 和 source 信息。
- `更新会话元信息`：更新 `last_message_at`；如果仍是默认标题，生成或回退一个短标题。

关键约定：

- 所有入口都走同一张图：普通对话、知识文档划选提问、构建过程触发只通过 `source` 标记区分，不再使用旁路 direct chat。
- 图内节点 id 保持稳定英文，LangSmith 展示名、路由名和文档链路统一使用中文。
- 每个 LangSmith 节点 metadata 都带 `node_key`、`node_description`、`reads`、`writes`、`emits`、`state_inputs`、`state_outputs`，排障时先看这些字段判断节点职责。
- 所有 LLM 输出默认使用 `primary` 模型选择器；`流式生成回答` 节点的最终回答必须以 SSE token 形式推送。
- 工具扩展只改 `lib/tooling.py` 的工具计划策略；节点不直接硬编码工具清单。
- Prompt 面向模型时使用 `course.name` 作为课程展示名；`course.id`/内部 id 只作为状态和数据库定位字段，不应该出现在“围绕某课程教学”的自然语言位置。
- 课程背景由 `course_context` 提供，包括课程说明、学习目标、课程简介、教学背景摘要和用户整体画像。
- 划选文本会进入检索 query 和 prompt，但会做长度截断，避免大段选区挤占上下文。
- 如果用户在划词入口问“看不懂这个”，prompt 必须把“这个”绑定到划选内容；近期错题只作为个性化背景。

API 层如果需要聊天会话 / 历史 / SSE 外壳，应直接依赖 `interact/chat/use_cases.py` 或 `interact.chat` 的稳定导出。
