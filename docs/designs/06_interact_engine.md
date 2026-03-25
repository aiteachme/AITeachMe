# 06. Interact 引擎

## 1. 目标与职责

Interact 负责把知识材料、学习者状态和教学策略组合成“会教”的对话体验。它不是泛聊天窗口，而是围绕当前学科和资料展开的教学型问答层。

当前目标包括：

- 基于 `RetrievalChunk` 做语义召回并回答问题
- 结合聊天历史、薄弱点、错题做上下文装配
- 通过 `POST + SSE` 流式返回回答
- 在回答完成后保存可追踪消息记录和引用来源

---

## 2. 当前实现落点

- 前端页面：`frontend/src/pages/ChatPage.tsx`
- 后端资源组：`chats`
- 业务入口：`backend/app/services/chats_service.py`
- 工作流编排：`backend/app/workflows/interact/*`
- 关键模型：`ChatMessage`

当前 Interact 的主链路已经迁移到 `workflows/interact/*`，不再以旧 `agents/interact/*` 为主。

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 请求接入 | `POST /api/v1/subjects/{subject}/chats/send` | `question`、可选 `selected_context`、`source_chunk_id` | 对话请求 |
| 2. 历史与状态加载 | `nodes/history.py` | `subject` | 最近消息、弱项、错题摘要 |
| 3. 召回上下文 | `nodes/retrieval.py` | `question`、`subject` | `retrieval_chunk` 引用上下文 |
| 4. 教学策略选择 | `nodes/strategy.py` | 问题、上下文、选段信息 | 当前回答策略 |
| 5. Prompt 装配 | `nodes/prompt.py` | 历史、召回结果、策略 | LLM messages |
| 6. 流式生成 | `nodes/stream.py` | messages | SSE token 流 |
| 7. 结果持久化 | `nodes/persist.py` | 用户问题、助手回答、contexts | `chat_message` 成对记录 |
| 8. 前端完成事件 | SSE done 事件 | `turn_id`、contexts | 页面级完成态 |

---

## 4. 核心设计原则

### 4.1 教学优先，而不是闲聊优先

Interact 的价值在于：

- 讲解概念
- 引导推理
- 复盘错题
- 指向具体证据
- 帮用户建立下一步学习动作

### 4.2 对话必须绑定资料

当前回答必须尽量基于当前 `Subject` 下的 `RetrievalChunk`，而不是脱离资料开放发挥。

### 4.3 语义召回优先，而不是关键词命中优先

更合理的主链路应该是：

- 先理解问题意图和语义中心
- 再做向量召回、结构邻域扩展、证据重排
- 最后才把标题、章节名、术语词面当作弱提示

只有像“第 X 章”“定义”“定理”“证明”这类显式结构锚点，才适合作为较强信号。

### 4.4 学习者状态要进入上下文

教学对话不仅看当前问题，还应该消化：

- 最近聊天历史
- 当前薄弱点
- 近期错题
- 用户主动选中的片段上下文

### 4.5 来源可解释性很重要

当前对话结果需要能够回到：

- 哪个 `chunk_id`
- 哪个文档
- 哪个标题路径

这样前端才能展示“引用来源卡片”和“查看原文”。

### 4.6 流式输出是主通道

Interact 当前以 `POST + SSE` 为主，而不是普通同步 JSON 返回。所有设计都要围绕“边生成边展示”展开。

---

## 5. 数据库写入对象

当前 Interact 直接写入：

- `chat_message`

具体表现为：

- 一个 user / assistant turn 成对落库
- assistant 记录中保存 contexts JSON

Interact 当前不直接写图谱、课程、掌握度等知识层对象。

---

## 6. 本地落盘对象

当前 Interact 没有强依赖的正式本地业务文件，主真相在数据库和 SSE 过程里。

后续如果增加调试快照，统一写入：

`data/<subject>/debug/interact.chat/<turn_or_request_id>/`

建议只保存：

- 请求摘要
- 最终策略
- 引用 chunk 列表
- 最终回答摘要

不要重复保存完整敏感上下文或密钥。

---

## 7. 关键状态推进

当前主状态推进主要体现在两层：

### 7.1 流式阶段

- token
- done
- error

### 7.2 持久化阶段

- 生成成功且未中断：落库 `chat_message`
- 生成中断或报错：跳过持久化或只返回错误事件

---

## 8. 节点到表责任

| 节点 / 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `nodes/history.py` | `chat_message`、旧 `user_profile`、旧 `mistake` | 无 | 无 |
| `nodes/retrieval.py` | `retrieval_chunk`、向量索引 | 无 | 无 |
| `nodes/stream.py` | 无 | 无 | 无 |
| `nodes/persist.py` | 无 | `chat_message` | 无 |

补充说明：

- 当前引用上下文来自 `retrieval_chunk`
- 查看原文接口消费的是 `chunk_id`
- 当前弱项和错题摘要仍主要来自旧 profile/exam 查询链路

---

## 9. 开发关注点

### 9.1 当前 Interact 是 workflow-backed，但学习状态来源仍有旧链路成分

历史、弱项、错题已经进入工作流上下文，但其中一部分仍通过旧 repo 查询得到。后续演进时要显式说明自己依赖的是哪套状态层。

### 9.2 前端应该把 contexts 用起来

当前后端已经能返回结构化 contexts，前端必须把它们展示成可点击来源卡片，而不是只当成隐藏元数据。

### 9.3 文档伴读模式要复用同一条主链路

`KnowledgeDocsPage` 右侧对话栏不应该自建另一套聊天后端，而应复用 Interact 主链路，只是换上下文装配策略。

---

## 10. 总结

Interact 当前已经形成清晰的工作流闭环：

- 从 `RetrievalChunk` 做语义召回、邻域扩展和证据重排
- 结合历史、弱项和错题决定回答策略
- 用 SSE 流式把答案推给前端
- 把最终 turn 和引用来源落到 `chat_message`

后续只要继续强化“教学策略、来源展示、状态接入”这三层，Interact 就会越来越像真正的教学陪练，而不只是一个资料问答窗口。
