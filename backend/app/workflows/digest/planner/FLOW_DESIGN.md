# Planner 流程设计

最后更新：2026-05-02

这份文档是 `backend/app/workflows/digest/planner/` 当前唯一的文档文件，同时承担入口说明、流程权威文档和持久化合同说明。

如果当前文档、上游设计文档和代码之间出现冲突，优先级如下：

1. 当前代码：`graph.py`、`state.py`、`nodes/`、`lib/store.py`
2. 当前文档：`FLOW_DESIGN.md`

使用约定：

- `FLOW_DESIGN.md` 必须同时保留两类内容：短流程总览和长流程执行合同。
- `planner/` 目录下不再保留第二份入口 README。
- Planner 只做确认前规划：理解资料、理解目标、合成可确认方案、保存 Planner 会话。
- Planner 不做本地 RAG 检索，不做外部 Web research，不提前替 DocGen 决定证据来源。

核心判断：

```text
Planner 定方向，DocGen 执行知识文档构建。
```

## 0. 目录入口

当前 `planner/` 目录：

```text
planner/
  __init__.py          # lane 稳定导出面
  graph.py             # LangGraph 定义、并行分支、运行入口
  state.py             # BuildPlannerState TypedDict
  nodes/               # 顶层图节点
  lib/                 # 持久化、模型策略、plan normalize、SSE 事件等
  prompts/             # prompt builder
  FLOW_DESIGN.md       # 当前唯一文档文件
```

公开入口：

```python
from app.workflows.digest.planner import (
    append_build_planner_message,
    confirm_build_planner_session,
    create_build_planner_session,
    get_confirmed_build_plan,
    get_latest_planner_session,
    run_build_planner_workflow,
)
```

阅读顺序：

1. `FLOW_DESIGN.md`
2. `graph.py`
3. `state.py`
4. `nodes/load_planner_materials.py`
5. `nodes/stream_brief_and_extract_intent.py`
6. `nodes/stream_and_parse_plan_draft.py`
7. `nodes/generate_course_name.py`
8. `nodes/normalize_and_persist_plan.py`
9. `lib/store.py`

## 1. 流程总览

### 1.1 短流程总览

Planner 主线：

```text
create_build_planner_session / append_build_planner_message
  接收首页/计划调整页请求，生成 planner_session_id，带上 user_prompt、digest_mode、file_ids、model_override。
  |
  v
run_build_planner_workflow
  创建 WorkflowContext(workflow_name="digest.planner")。
  使用 use_runtime_model_override(model_override) 包住整条 Planner LangGraph。
  |
  v
load_planner_materials
  prepare_planner_run:
    - create：创建 planner chat_session，写入用户首轮 chat_message，绑定资料选择。
    - append：读取已有 planner chat_session，追加用户反馈 message，读取 latest_plan 和历史消息。
    - generate_only：跳过持久化，只作为工具/测试式运行。
  prepare material_context:
    - 读取 RawFile、解析后的 Markdown、资料切片、材料 digest 和课程画像。
    - 如果正文未解析完成，退化为基于文件名和用户目标的 seed material_context。
  existing_doc_context:
    - 读取课程已有知识文档摘要，用于重建已有文档场景。
  |
  v
stream_brief_and_extract_intent
  单节点内部并行：
    ├─ stream_planner_brief
    │    流式输出用户可见的资料边界、学习目标理解和规划判断。
    └─ extract_plan_intent
         结构化抽取内部 plan_intent 和 plan_queries。
  |
  v
compose / title 并行分支
  ├─ stream_and_parse_plan_draft
  │    流式生成用户可见计划说明，隐藏 `<PLAN_JSON>` 机器合同。
  │    解析 plan_text、plan_steps、chapters；必要时走结构化修复。
  └─ generate_course_name
       仅 create 时运行，和大纲合成并行生成课程短标题与图标。
  |
  v
normalize_and_persist_plan
  fan-in 等待大纲与标题分支。
  normalize_planner_draft -> save_planner_result。
  写入 latest_plan、assistant chat_message、课程元信息和 planner runtime response。
  |
  v
confirm_planner_session（用户点击确认后，非 LangGraph 节点）
  冻结 latest_plan 为 confirmed_plan。
  写 ConfirmedBuildPlan，更新 planner chat_session 为 confirmed。
  DocGen 后续只消费这份 confirmed plan。
```

并行关系摘要：

```text
stream_brief_and_extract_intent
  stream_planner_brief ┐
  extract_plan_intent  ┘

after understand_goal
  stream_and_parse_plan_draft ┐
  generate_course_name        ├─ fan-in -> normalize_and_persist_plan
                              ┘
```

### 1.2 当前模型槽位总览

Planner 的 `call_purpose + model slot + max_tokens + metadata` 统一由 `lib/model_policy.py` 维护。节点不应各自硬编码模型策略。

当前默认逻辑槽位：

```text
reason  -> settings.models.reason
primary -> settings.models.primary
light   -> settings.models.light
```

运行时模型选择：

- 首页模型选择会作为 `model_override` 传入 Planner。
- `run_build_planner_workflow` 在 workflow 边界使用 `use_runtime_model_override(model_override)`。
- 各节点仍传 `model="light"` 等逻辑槽位，实际 provider 模型由 runtime override 或 settings 决定。
- 保存后的 planner session meta 会记录 `model_override`，确认时会冻结进 `confirmed_plan.plan_json.model_override`，供 DocGen 和自动 KG 同步继承。

当前 LLM 调用：

| 阶段 / 子步骤 | 调用类型 | call_purpose | 逻辑模型槽位 | 默认用途 |
| --- | --- | --- | --- | --- |
| `stream_planner_brief` | stream | `GENERATE` | `light` | 用户可见的资料边界判断和规划思考 |
| `extract_plan_intent` | structured | `CLASSIFY` | `light` | 内部 plan_intent 与 plan_queries |
| `stream_and_parse_plan_draft.compose_plan` | stream | `REASONING` | `light` | 可见计划说明 + 隐藏 JSON 初步大纲 |
| `stream_and_parse_plan_draft.repair` | structured | `REASONING` | `light` | 修复不完整 `<PLAN_JSON>` |
| `generate_course_name` | text | `GENERATE` | `light` | 课程短标题 |
| `select_course_icon` | text | `CLASSIFY` | `light` | 课程图标候选 |

## 2. 长流程执行合同

### 2.1 `create_build_planner_session`

输入：

- `course`：当前课程行，来自 API 层鉴权。
- `user_id`：当前用户。
- `payload.file_ids`：用户本轮选择的资料 UID。
- `payload.user_prompt`：用户学习目标。
- `payload.digest_mode`：用户选择或默认的学习模式。
- `payload.model`：首页模型选择，可能为空、`settings` 或具体模型名。
- `progress_callback / token_callback`：SSE 状态与 token 输出回调。

输出：

- `BuildPlannerSessionResponse`
  - `session_id`
  - `latest_plan`
  - `turns`
  - `runtime_stats`
  - `model_override`

操作：

- 生成新的 `planner_session_id`。
- 调用 `run_build_planner_workflow(planner_operation="create")`。
- 如果任务被取消或失败，标记 planner session 为 `cancelled / failed`。

数据库读写：

- 本函数本身不直接写业务表；真实写入在 `load_planner_materials -> prepare_planner_run` 和 `normalize_and_persist_plan -> save_planner_result` 中完成。

### 2.2 `append_build_planner_message`

输入：

- `course`
- `user_id`
- `session_id`
- `payload.message`：用户修改意见。
- `payload.model`：本轮模型覆盖；会覆盖 planner session meta 中的 `model_override`。

输出：

- 新一轮 `BuildPlannerSessionResponse`。

操作：

- 调用 `run_build_planner_workflow(planner_operation="append")`。
- append 不改变已绑定资料集合，只基于原 session 的 selected files 和 latest plan 修订方案。

数据库读写：

- 真实读写在 `prepare_planner_run` 和 `save_planner_result` 中完成。

### 2.3 `run_build_planner_workflow`

输入：

- `course_id / user_id`
- `planner_operation`
- `requested_file_ids`
- `session_title`
- `feedback_message`
- `file_ids`
- `user_prompt`
- `digest_mode`
- `planner_session_id`
- `message_history`
- `model`
- `latest_plan`
- 回调函数

输出：

- `WorkflowResult[BuildPlannerState]`

操作：

- 规范化 `model_override`。
- 创建 `WorkflowContext(workflow_name="digest.planner")`。
- 创建 LangSmith root trace，记录 `planner_operation / digest_mode / model_override`。
- 用 `use_runtime_model_override(model_override)` 包住 `run_state_graph`。
- 创建初始 state，进入 LangGraph。

数据库读写：

- 无直接 DB 写入。
- LangGraph 节点内部通过 `lib/store.py` 执行 DB 读写。

### 2.4 `load_planner_materials`

输入：

- `planner_operation`
- `course_id / user_id / planner_session_id`
- `requested_file_ids`
- `session_title`
- `feedback_message`
- `user_prompt`
- `digest_mode`
- `model_override`

输出：

- `file_ids`
- `selected_file_ids`
- `message_history`
- `latest_plan`
- `planner_record`
- `planner_turns`
- `material_context`
- `digest_mode`
- `existing_doc_context`
- `planner_context_mode`

内部步骤：

1. 调用 `prepare_planner_run(state)` 准备持久化会话状态。
2. 调用 `prepare_material_context(course_id, file_ids, user_prompt)` 读取资料理解包。
3. 如果没有可用正文，构造 seed material context：
   - 文件名
   - 用户目标
   - RawFile 识别出的学科、内容类型、图片数量
4. 如果存在 source documents，调用 `build_material_digest` 生成材料 digest。
5. 调用 `load_course_llm_context` 读取已有知识文档摘要，决定 `planner_context_mode`：
   - `fresh_build`
   - `rebuild_existing_doc`

数据库与存储读写：

- create 分支：
  - 读 `Course`：用于默认 session title。
  - 读最新 `ChatSession`：检查是否已有 `planning` 状态会话。
  - 读 `RawFile`：校验用户选择文件、判断是否已解析完成。
  - 写 `ChatSession`：
    - `source="build_planner"`
    - `meta_json.source`
    - `meta_json.planner_status="planning"`
    - `meta_json.user_prompt`
    - `meta_json.digest_mode`
    - `meta_json.selected_file_ids`
    - `meta_json.model_override`
  - 写用户 `ChatMessage`：
    - `role="user"`
    - `source="build_planner"`
    - `message_kind="planner_user_request"`
- append 分支：
  - 读 `ChatSession`：必须存在且 `source="build_planner"`。
  - 读 `ChatMessage[]`：作为 message history。
  - 更新 `ChatSession.meta_json`：
    - `planner_status="planning"`
    - `model_override`
    - 清空 `confirmed_plan_id / confirmed_plan`
  - 写用户反馈 `ChatMessage`。
  - 读绑定的 `RawFile`。
- material context：
  - 读 `RawFile`、解析 Markdown 路径、资料切片和材料画像。
  - 可能读取本地/对象存储中的 parsed markdown。
  - 读取 `Course.document_summary_json / llm_context_text` 作为已有知识文档摘要。
- 本节点不写 confirmed plan，不写 KnowledgeDoc。

### 2.5 `stream_brief_and_extract_intent`

输入：

- `material_context`
- `user_prompt`
- `digest_mode`
- `message_history`
- `existing_doc_context`
- `planner_context_mode`
- `model_override`

输出：

- `planner_brief`
- `plan_intent`

内部并行：

```text
stream_planner_brief
  输入：资料 digest、用户目标、历史消息、已有文档摘要。
  输出：PlannerBrief.markdown。
  行为：流式 token 透出给前端；失败时返回 empty brief，不直接失败整轮。

extract_plan_intent
  输入：同上。
  输出：PlanIntent(plan_intent, plan_queries)。
  行为：结构化输出内部规划抓手；为空或失败则失败本轮 Planner。
```

数据库读写：

- 无 DB 写入。
- 只通过 SSE 回调发 `planner.thinking.* / planner.intent.*` 事件和 token。

### 2.6 `stream_and_parse_plan_draft`

输入：

- `material_context`
- `planner_brief`
- `plan_intent`
- `latest_plan`
- `user_prompt`
- `digest_mode`
- `message_history`
- `existing_doc_context`
- `planner_context_mode`
- `model_override`

输出：

- `plan_outline_markdown`
- `build_plan_draft`

内部步骤：

1. 调用 composer LLM 流式生成计划说明。
2. 前端只接收 `<PLAN_JSON>` 之前的可见 Markdown。
3. 后端保留完整响应，从 `<PLAN_JSON>` 中解析：
   - `plan_text`
   - `plan_steps`
   - `chapters[]`
4. 将 chapter sketch 转换为待 normalize 的 `chapter_plan`：
   - `chapter_index`
   - `title`
   - `objective`
   - `required_elements`
   - `writing_instructions`
5. 如果 JSON 缺失或不合法，调用结构化修复 LLM。
6. 修复失败时发 `planner.plan.failed` 并抛错。

数据库读写：

- 无 DB 写入。
- 只透出 token 和 planner 状态事件。

### 2.7 `generate_course_name`

输入：

- `planner_operation`
- `material_context`
- `planner_brief`
- `plan_intent`
- `user_prompt`
- `digest_mode`
- `model_override`

输出：

- `generated_course_name`
- `generated_course_icon_key`

行为：

- 仅 `planner_operation="create"` 时运行。
- 和 `stream_and_parse_plan_draft` 并行。
- 标题来源：
  - 用户目标
  - 文件名
  - material topic hints
  - planner brief
  - plan intent
- 生成的标题只用于课程展示和 plan course 字段，不参与章节规划。

数据库读写：

- 本节点无 DB 写入。
- 后续 `save_planner_result` 才会按条件更新 `Course.name / description / user_intent`。

### 2.8 `normalize_and_persist_plan`

输入：

- `build_plan_draft`
- `material_context`
- `latest_plan`
- `generated_course_name`
- `user_prompt`
- `digest_mode`
- `planner_session_id`
- `model_override`

输出：

- `plan`
- `plan_summary`
- `digest_mode`
- `model_override`
- `selected_file_ids`
- `planner_record`
- `planner_turns`

内部步骤：

1. 调用 `normalize_planner_draft`：
   - 补齐课程名、模式、章节数、章节索引。
   - 规范化 `chapter_plan / build_constraints / plan_steps / plan_summary`。
   - append 时吸收 `latest_plan`，保留用户修订语义。
2. 如果有生成课程名，覆盖 draft course_name。
3. 发 `planner.plan.ready`。
4. 调用 `save_planner_result`。

数据库读写：

- `generate_only`：
  - 不写 DB，只返回内存 plan。
- create / append：
  - 读 `ChatSession`。
  - 读 session meta 中的 `latest_plan / selected_file_ids / digest_mode / user_prompt`。
  - 可能更新 `Course`：
    - `name`：只在课程仍是自动占位名时替换。
    - `description`：根据资料画像和 plan summary 生成。
    - `user_intent`：根据 plan_intent 或 user_prompt 生成。
  - 更新 `ChatSession.meta_json`：
    - `latest_plan`
    - `latest_summary`
    - `digest_mode`
    - `model_override`
    - `planner_status="draft"`
    - `confirmed_plan_id=None`
  - 如果生成了新标题，更新 `ChatSession.title`。
  - 写 assistant `ChatMessage`：
    - `message_kind="planner_plan"`
    - `meta_json.plan_json`
    - `meta_json.plan_summary`
  - 读本 session 的完整 `ChatMessage[]`，返回给前端。

### 2.9 `confirm_planner_session`

这是用户点击确认后的持久化入口，不是 LangGraph 节点，但它是 Planner -> DocGen 的交接边界。

输入：

- `course`
- `user_id`
- `session_id`

输出：

- `BuildPlannerConfirmResponse`
  - `planner_session_id`
  - `confirmed_plan_id`
  - `model_override`
  - `selected_file_ids`
  - `chapter_plan`
  - `build_constraints`
  - `plan_json`

内部步骤：

1. 读取 `ChatSession`，要求 `source="build_planner"`。
2. 读取 session meta 的 `latest_plan`。
3. 读取完整 Planner turns，构建 `planner_context`：
   - `planner_session_id`
   - `planner_turn_count`
   - `user_revision_count`
   - `assistant_revision_count`
   - `latest_plan_summary`
   - `planner_outline_markdown`
   - `docgen_history_brief`
4. 构建冻结 `plan_payload`。
5. 把 `model_override` 写进 `plan_payload.model_override`。
6. 如果已有 confirmed plan 且内容未变，复用原 `ConfirmedBuildPlan`。
7. 否则新建 `ConfirmedBuildPlan(status="confirmed")`。
8. 更新 planner session meta 为 `planner_status="confirmed"`。

数据库读写：

- 读 `ChatSession`。
- 读 `ChatMessage[]`。
- 读可选旧 `ConfirmedBuildPlan`。
- 写新 `ConfirmedBuildPlan`：
  - `course_id`
  - `planner_session_id`
  - `user_id`
  - `status="confirmed"`
  - `user_prompt`
  - `digest_mode`
  - `selected_file_ids_json`
  - `chapter_plan_json`
  - `build_constraints_json`
  - `plan_summary`
  - `plan_json`
- 更新 `ChatSession.meta_json`：
  - `latest_plan=plan_payload`
  - `latest_summary`
  - `confirmed_plan_id`
  - `model_override`
  - `planner_status="confirmed"`

## 3. State 合同

核心输入字段：

| 字段 | 含义 |
| --- | --- |
| `course_id / user_id` | 课程与用户边界 |
| `planner_operation` | `create / append / generate_only` |
| `requested_file_ids` | 用户本轮显式选择的文件 |
| `file_ids` | 实际进入资料准备的文件 |
| `user_prompt` | 原始学习目标 |
| `digest_mode` | `sprint / systematic` |
| `model_override` | 首页模型选择或设置默认 |
| `planner_session_id` | Planner 会话 ID |
| `message_history` | 本轮 prompt 可见的历史消息 |
| `latest_plan` | append 时上一版方案 |

核心中间产物：

| 字段 | 含义 |
| --- | --- |
| `material_context` | 资料理解包，含文件、切片、课程画像和 material digest |
| `existing_doc_context` | 已发布知识文档摘要，重建场景使用 |
| `planner_context_mode` | `fresh_build / rebuild_existing_doc` |
| `planner_brief` | 用户可见规划判断 |
| `plan_intent` | 内部规划意图与 plan_queries |
| `plan_outline_markdown` | 合成阶段可见 Markdown |
| `build_plan_draft` | 从隐藏 JSON 解析出的初步大纲 |
| `generated_course_name / generated_course_icon_key` | create 分支展示元信息 |

核心输出字段：

| 字段 | 含义 |
| --- | --- |
| `plan` | API、确认接口和 DocGen 消费的最终 plan payload |
| `plan_summary` | 方案摘要 |
| `planner_record` | ChatSession 快照 |
| `planner_turns` | ChatMessage 快照 |
| `workflow_elapsed_ms / prepare_ms / bootstrap_ms / compose_ms / title_ms / finalize_ms` | 运行耗时统计 |

## 4. Planner -> DocGen 交接

Confirmed plan 是 DocGen 唯一可信合同：

```text
confirmed_plan
  course / course_name
  user_prompt
  digest_mode
  chapter_plan
  build_constraints
  plan_summary
  plan_steps
  selected_file_ids
  planner_session_id
  confirmed_plan_id
  model_override
  planner_context
  docgen_history_brief
```

交接原则：

- Planner 冻结“学什么、按什么章节学、模式是什么、用户修改历史是什么”。
- DocGen 决定“每章怎么写、查哪些资料、如何组织证据和正文”。
- DocGen 不默认新增、删除、重排用户确认过的章节语义。
- 首页模型选择必须经过 `model_override` 从 Planner 冻结到 confirmed plan，再被 DocGen 和自动 KG 同步继承。

## 5. 边界与关注点

目前没有发现需要推倒重写 Planner 主图的问题。Planner 的边界是确认前规划，不做 research，不直接生成文档。

| 关注点 | 判断 |
| --- | --- |
| `model_override` 贯通 | 必须继续经过 workflow boundary、session meta、confirmed plan 交给 DocGen / KG |
| confirmed plan 冻结 | append 可以改 latest_plan；确认后 DocGen 只消费 confirmed plan |
| 不下沉为 DocGen | 不加入 RAG、网页检索、证据绑定和章节写作 |
| JSON repair | 保持 composer + 结构化修复；失败明确返回，不本地猜大纲 |
| 会话表 | 继续使用 `chat_session / chat_message` 的 `source="build_planner"`，不新建第二套 |

一句话收束：

```text
Planner 的价值不是提前生成答案，
而是把用户目标、资料边界和学习模式收束成一份可确认、可追踪、可交给 DocGen 执行的稳定合同。
```
