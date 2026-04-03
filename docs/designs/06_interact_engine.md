# 06. Interact 引擎

## 1. 目标与职责

Interact 负责把知识材料、学习者状态和教学策略组合成“可持续伴读”的对话体验。  
它不是通用闲聊层，而是围绕当前学科与资料的教学型问答引擎。

当前目标：

- 基于 `retrieval_chunk` 做证据化检索回答；
- 结合聊天历史、画像、掌握状态构造教学上下文；
- 通过 `POST + SSE` 主通道进行流式输出；
- 在完成后落库可追踪的会话与消息记录。

---

## 2. 当前实现落点

- 前端页面：`frontend/src/pages/ChatPage.tsx`
- API：`backend/app/api/chats.py`
- Service：`backend/app/services/chats_service.py`
- Workflow Runtime：`backend/app/workflows/interact/runtime.py`
- Workflow Nodes：`backend/app/workflows/interact/nodes/*`
- 关键模型：`chat_session`、`chat_message`

---

## 3. 当前主链路

## 3.1 请求入口

主入口是：

- `POST /api/v1/subjects/{subject}/chats/send`（SSE）

支持输入：

- `question`
- `session_id`（可选）
- `selected_context`（可选）
- `source_chunk_id`（可选）

## 3.2 Workflow 主 Pipeline

当前编排在 `build_interact_workflow_graph()`，主步骤：

1. `history`：加载近期会话与学习状态摘要。
2. `retrieval`：按 subject 检索相关 chunk。
3. `strategy`：决定回答策略与讲解力度。
4. `prompt`：组装 messages。
5. `stream`：流式生成 token。
6. `persist`：持久化 user/assistant turn 与 contexts。

## 3.3 事件输出

SSE 事件主语义：

- `token`
- `done`（含 `turn_id` 和 `contexts`）
- `error`

---

## 4. 上下文组装原则

## 4.1 资料绑定优先

回答优先基于当前 `Subject` 的资料证据，不鼓励脱离资料自由发挥。

## 4.2 学习状态入模

当前上下文应综合：

- 最近聊天历史；
- 用户级画像（`user.profile_json`）；
- `backend/data/users/<user_id>/LEARNER.md` 运行时学习者档案；
- 学科级画像（`subject.profile_json`）；
- 掌握与复习状态（`user_knowledge_state`）；
- 近期做题表现（`exam_paper_item` 派生摘要）；
- 用户选中的片段（`selected_context`）。

## 4.3 引用可追溯

assistant 消息保存结构化 `contexts_json`，支持前端展示来源卡片与原文跳转。

---

## 5. 数据落点与事务边界

Interact 当前直接写入：

- `chat_session`
- `chat_message`

约束：

- 无会话时先创建 `chat_session`；
- user/assistant turn 成对落库；
- 流式中断或异常时不写半成品 assistant 结果。

---

## 6. 与其他引擎的关系

## 6.1 与 Digest

Interact 消费 digest 产出的 `retrieval_chunk` 与知识对象，不反向写 digest 主结构。

## 6.2 与 Examine / Profile

当前会读取 exam/profile 派生状态用于教学策略；同时会自动读入 `LEARNER.md` 运行时档案，但不直接改 exam/profile 业务对象。

---

## 7. 当前边界

1. 主通道仍是单轮对话流，不是多代理并行教学流程。
2. 观测主要在 runtime 日志，尚未形成对外统一指标 API。
3. 上下文预算与缓存策略已有基础设施，但 `LEARNER.md + 记忆 + 检索片段` 的动态裁剪仍可继续加强。

---

## 8. 未来演进（保持 API 简单）

1. 强化 profile 对策略节点的直接影响（解释风格、节奏、追问层级）。
2. 强化 curriculum/KG 先修关系在回答组织中的约束。
3. 增加 interact runtime 汇总观测（不扩散新业务接口）。

---

## 9. 一句话结论

Interact 当前已经形成“证据检索 + 教学策略 + SSE 流式 + 可追溯落库”的稳定闭环。  
后续重点是策略质量和观测能力升级，而不是接口扩张。
