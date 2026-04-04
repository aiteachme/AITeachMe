# 06. Interact 引擎

## 1. 目标与职责

Interact 负责把知识材料、学习者状态和教学策略组合成“可持续伴读”的对话体验。
它不是通用闲聊层，而是围绕当前学科与资料的教学型问答引擎。

当前目标：

- 基于 `retrieval_chunk` 做证据化检索回答
- 结合聊天历史、画像、掌握状态构造教学上下文
- 通过 `POST + SSE` 主通道进行流式输出
- 在完成后落库可追踪的会话与消息记录

从本版开始，本文档区分两件事：

- 当前 workflow 已经稳定落地的输入与输出
- 下一阶段应与 Profile / runtime memory 打通的目标设计

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

### 3.1 请求入口

主入口是：

- `POST /api/v1/subjects/{subject}/chats/send`（SSE）

支持输入：

- `question`
- `session_id`（可选）
- `selected_context`（可选）
- `source_chunk_id`（可选）

### 3.2 Workflow 主 Pipeline

当前编排在 `build_interact_workflow_graph()`，主步骤：

1. `history`：加载近期会话、薄弱点、近期错题。
2. `retrieval`：按 subject 检索相关 chunk。
3. `strategy`：决定回答策略与讲解力度。
4. `prompt`：组装 messages。
5. `stream`：流式生成 token。
6. `persist`：持久化 user / assistant turn 与 contexts。

### 3.3 事件输出

SSE 事件主语义：

- `token`
- `done`（含 `turn_id` 和 `contexts`）
- `error`

---

## 4. 上下文组装原则

### 4.1 资料绑定优先

回答优先基于当前 `Subject` 的资料证据，不鼓励脱离资料自由发挥。

### 4.2 当前已经稳定注入的上下文

按当前代码核对，Interact 主 workflow 里已经稳定进入 prompt 的输入主要是：

- 最近聊天历史
- 薄弱点摘要
- 近期错题摘要
- RAG 检索片段
- 用户选中的片段（`selected_context`）

其中：

- 薄弱点和近期错题来自 profile / exam 派生状态
- 检索引用会保存到 assistant 消息的 `contexts_json`
- `selected_context` 会影响教学策略和 prompt 构造

### 4.3 下一阶段应补齐的 Profile / Memory 上下文

当前文档不再假定这些内容已经稳定接入主 workflow，但下一阶段推荐明确补上：

- 用户级画像（`user.profile_json`）
- 学科级画像（`subject.profile_json`）
- `LEARNING_PROFILE.md`
- `LEARNING_SUBJECT_PROFILE.md`
- recall 出来的高价值 memory entries

推荐做法不是再造第三套 prompt builder，而是让 Interact 统一复用 shared profile-memory context provider，避免：

- 一处读 `user.profile_json`
- 一处读 `LEARNER.md`
- 一处读 memory store
- 最后彼此描述还不一致

### 4.4 引用可追溯

assistant 消息保存结构化 `contexts_json`，支持前端展示来源卡片与原文跳转。

---

## 5. 数据落点与事务边界

### 5.1 当前已经稳定落库的事实

当前对话主链路稳定落库的对象是：

- `chat_session`
- `chat_message`
- assistant 引用来源对应的 `contexts_json`

这些对象共同构成了 Interact 当前最可靠的事实层。

### 5.2 当前仍需补强的事实

以下输入虽然已经出现在请求或 prompt 侧，但还不应被文档描述成“完整闭环”：

- `selected_context` 的全链路持久化与回放
- `source_chunk_id` 的稳定回写与再利用
- 对话后提炼出的 memory entry
- runtime markdown 档案的统一刷新

也就是说，当前已经有“学习事实进入对话”的入口，但还没有把这些事实稳定地沉淀回 Profile / Memory 全链路。

### 5.3 持久化原则

Interact 后续补强时，应坚持以下顺序：

1. 先把原始事实写入结构化对象
2. 再由 Profile / Memory 聚合层提炼长期状态
3. 最后再刷新 runtime markdown 档案

不推荐：

- 直接把整轮聊天原文 append 到画像 markdown
- 由 Interact 自己维护另一套长期掌握度状态

---

## 6. 与其他引擎的关系

### 6.1 与 Ingest / Digest 的关系

Interact 的资料基础来自：

- Ingest 产出的材料层 markdown
- Digest 发布后的知识文档与检索索引

没有这些知识底座时，Interact 可以回答，但不应被视为完整教学模式。

### 6.2 与 Profile 的关系

当前 Interact 已经稳定读取 Profile 派生出来的两类摘要：

- 薄弱点
- 近期错题

但它还没有稳定完整读取：

- `user.profile_json`
- `subject.profile_json`
- runtime markdown 学习档案
- memory recall 结果

因此当前最准确的说法是：

- Interact 已经“部分消费 Profile”
- 但还没有形成完整的 `Profile -> Interact -> Memory -> Profile` 闭环

### 6.3 与 Examine 的关系

Examine 会产出更强结构化学习信号：

- 对错
- 错因
- 命中的 unit / node
- 判卷反馈

这些信号经由 Profile 聚合后，会间接影响 Interact 的后续教学策略。

所以从当前工程现实看：

- `Examine -> Profile` 是最稳定的强闭环
- `Profile -> Interact` 是已经起步但仍需补强的链路

---

## 7. 当前边界

### 7.1 Interact 不是通用聊天 SDK

它的定位始终是教学对话，而不是一个无边界的闲聊代理层。

### 7.2 Interact 不拥有知识真相源

知识真相来自：

- 学科资料
- 检索片段
- `user_knowledge_state`
- `exam_paper_item`
- `chat_message`

Interact 负责消费这些事实，而不是重新定义这些事实。

### 7.3 Interact 不应自己维护长期画像真相

长期画像应继续由：

- `user.profile_json`
- `subject.profile_json`
- `user_knowledge_state`
- runtime memory docs

共同承载。

Interact 可以写学习事件，但不应自己变成新的画像中心。

### 7.4 shared 上下文底座已存在，但还没成为主路径

仓库里已经存在 `app.shared.infra.context` 这类更通用的上下文组装能力，可以统一读取：

- 用户画像
- `LEARNER.md`
- recall memory
- 知识检索结果

但当前 Interact 主 workflow 还没有完全收敛到这条 shared 路径。

这意味着：

- 底层能力不是没有
- 主链路只是还没有完全接过去

---

## 8. 下一步演进建议

### 8.1 统一 profile-memory context provider

优先目标不是继续扩 prompt 文本，而是把当前分散在 shared / interact / memory 的上下文读取逻辑，统一成一个规范 provider。

### 8.2 补齐 `selected_context` 的事实沉淀

需要把：

- 用户滑选了什么
- 选中内容来自哪个 chunk
- 这轮回答如何引用这段上下文

稳定写回结构化事实层，保证后续可以用于 memory 提炼、教学回放与画像更新。

### 8.3 runtime markdown 文档应由 Profile 统一刷新

推荐继续坚持：

- Interact 写对话事实
- Profile 聚合长期状态
- Profile 统一刷新 `LEARNING_PROFILE.md` / `LEARNING_SUBJECT_PROFILE.md` / `LEARNER.md`

而不是让 Interact 在每轮对话结束后直接向这些文档追加自然语言段落。

### 8.4 新实现统一走 `app.shared.*`

后续若补：

- 画像读取
- memory recall
- learner docs
- context assembly

都应以 `app.shared.*` 为规范入口，`app.teaching.*` 保持兼容语义，不再反向定义主设计。

---

## 9. 一句话结论

当前 Interact 最稳定的现实能力是：

- 基于资料检索回答
- 读取近期聊天、薄弱点、近期错题
- 流式输出并持久化会话消息

下一阶段真正值得做的，不是再写一版更长的 prompt，而是把 `subject / user profile + runtime markdown + memory recall` 这套上下文，稳定接进主 workflow，并把 `selected_context` 沉淀回可追溯的学习事实。
