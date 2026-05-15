# Planner 流程说明

最后更新：2026-05-15

这份文档是 `backend/app/workflows/digest/planner/` 的当前主文档，同时承担入口说明、流程权威文档和持久化合同说明。

如果当前文档、上游设计文档和代码之间出现冲突，优先级如下：

1. 当前代码：`graph.py`、`state.py`、`nodes/`、`lib/store.py`
2. 当前文档：`README.md`

使用约定：

- `README.md` 必须同时保留两类内容：短流程总览和长流程执行合同。
- `planner/` 目录下不再保留平行的流程设计文档。
- Planner 只做确认前规划：理解资料、理解目标、合成可确认方案、保存 Planner 会话。
- Planner 不执行 DocGen 阶段的资料读取、外部 research、证据绑定或正文写作。

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
  lib/                 # 持久化、模型策略、plan normalize、Planner 常量、SSE 事件等
  prompts/             # prompt builder
  README.md           # 当前主文档
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

1. `README.md`
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
         结构化抽取 plan_change_mode、target_scope、requested_chapter_count、plan_intent、plan_queries 和 adjustment_options。
  |
  v
compose / title 并行分支
  ├─ stream_and_parse_plan_draft
  │    并行流式生成用户可见计划说明，并通过 `response_model` 结构化生成机器大纲合同。
  │    结构化得到 plan_text、plan_steps、chapters；用户调整引导直接复用 PlanIntent.adjustment_options。
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
  stream_and_parse_plan_draft
    ├─ stream_visible_plan      # 流式给用户看的计划说明
    └─ compose_structured_plan  # response_model 结构化生成机器大纲合同
  generate_course_name          ┐
                                ├─ fan-in -> normalize_and_persist_plan
                                ┘
```

### 1.2 当前模型槽位总览

Planner 的 `model slot + max_tokens + timeout_s + max_retries + metadata` 统一由 `lib/model_policy.py` 维护。节点不应各自硬编码模型策略。

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

| 阶段 / 子步骤 | 调用类型 | 逻辑模型槽位 | 默认用途 |
| --- | --- | --- | --- |
| `stream_planner_brief` | stream | `light` | 用户可见的资料边界判断和规划思考 |
| `extract_plan_intent` | structured | `light` | 内部变更模式、目标范围、指定章数与规划抓手 |
| `stream_and_parse_plan_draft.visible_plan` | stream | `light` | 用户可见计划说明和调整引导 |
| `stream_and_parse_plan_draft.structured_plan` | structured | `light` | 通过 `response_model` 生成机器可解析初步大纲 |
| `generate_course_name` | text | `light` | 课程短标题 |
| `select_course_icon` | text | `light` | 课程图标候选 |

### 1.3 Planner 本地常量

Planner 的章节数量参考值和目标成稿长度不是用户可配置的运行参数，而是提示词合同的一部分，集中放在：

```text
lib/constants.py
```

当前常量：

| 模式 | 默认参考章节 | 目标成稿长度 |
| --- | --- | --- |
| `sprint` | 4-7 章 | 8000-30000 字 |
| `systematic` | 5-12 章 | 30000-100000 字 |

使用边界：

- `lib/constants.py` 只放 Planner 产品合同常量，例如章节预算、长度预算和模式归一化。
- `settings.planner` 只保留真正运行期可调的值，例如 `default_digest_mode` 和 `history_turns`。
- 旧配置文件里的 `planner.sprint / planner.systematic` 会被设置升级逻辑忽略，避免已删除的提示词预算继续污染运行时设置。
- 如果用户明确指定章节数，以 LLM 结构化意图里的 `requested_chapter_count` 为准，不受默认参考章节数限制。

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
- `planner_context_stats`
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
  - 读 `ChatMessage[]`：按 `planner.history_turns` 截取最近对话，作为 message history。
  - 更新 `ChatSession.meta_json`：
    - `planner_status="planning"`
    - `model_override`
    - 清空 `confirmed_plan_id / confirmed_plan`
  - 写用户反馈 `ChatMessage`。
  - 读绑定的 `RawFile`。
- material context：
  - 读 `RawFile`、解析 Markdown 路径、资料切片和材料画像。
  - 可能读取本地/对象存储中的 parsed markdown。
  - 优先读取 `Course.document_summary_json` 的结构化摘要作为已有知识文档真源；`llm_context_text` 只是由该摘要渲染出的 prompt 缓存。
- 本节点不写 confirmed plan，不写 KnowledgeDoc。

### 2.5 `stream_brief_and_extract_intent`

输入：

- `material_context`
- `user_prompt`
- `digest_mode`
- `message_history`
- `latest_plan`
- `feedback_message`
- `existing_doc_context`
- `planner_context_mode`
- `model_override`

输出：

- `planner_brief`
- `plan_intent`

内部并行：

```text
stream_planner_brief
  输入：资料 digest、用户目标、最近历史消息、上一版方案、本轮反馈、已有文档摘要。
  输出：PlannerBrief.markdown。
  行为：流式 token 透出给前端；修订场景必须先判断局部补丁还是整体重定向，明确新专题/章数时不能继续说保留旧章节；失败时返回 empty brief，不直接失败整轮。

extract_plan_intent
  输入：同上。
  输出：PlanIntent(plan_change_mode, target_scope, requested_chapter_count, plan_intent, plan_queries, adjustment_options)。
  行为：结构化输出内部规划抓手和用户可调整方向；为空或失败则失败本轮 Planner。这里依赖字段合同和 response_model，不靠堆 few-shot 示例或本地关键词提取判断用户意图。
```

`plan_change_mode` 是修订质量的关键分支：

- `create_new`：新建方案。
- `patch_existing`：用户是在上一版上局部增删改某章、顺序、风格或重点；后续结构化大纲以旧方案为工作副本，未受影响章节保持。
- `replace_existing_outline`：用户给出新的具体专题、明确章数，或说“改成/生成 XXX 的 N 个章节”；后续结构化大纲把旧方案作为被替换对象和上下文，不保留无关旧章节。

典型例子：

- “把第二章拆开” -> `patch_existing`
- “改成定积分的 5 个章节” -> `replace_existing_outline` + `target_scope=定积分` + `requested_chapter_count=5`
- “生成洛必达法则的几个章节” -> `replace_existing_outline` + `target_scope=洛必达法则`

`adjustment_options` 也是在这个结构化意图阶段生成的。它和 `plan_queries / target_scope / requested_chapter_count` 同源，代表“接下来最值得让用户确认的调整方向”。后续结构化大纲不再单独生成 `adjustment_questions`，而是把这些 options 清洗后写入 plan payload 的 `adjustment_questions`，供前端 “可以继续这样改” 区域展示。

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

1. 并行启动两条 LLM 调用：
   - `stream_visible_plan`：只负责流式输出用户可见计划说明。
   - `compose_structured_plan`：通过 infra `response_model` 结构化输出生成机器大纲合同。
2. 前端接收可见 Markdown，并只展示当前运行状态点与已经流出的可见文本；`planner.intent.scope / planner.plan.visible_* / planner.plan.structure_*` 等状态事件仍通过 SSE 透出给客户端状态机，但不再作为一串内部过程历史展示给用户。
   - 如果更早的可见思考流与结构化意图冲突，后续可见计划说明必须以 `PlanIntent` 为准，不能复述“局部收缩/保留旧章节”的冲突说法。
3. 结构化大纲合同包含：
   - `plan_text`
   - `plan_steps`
   - `chapters[]`
   - 注意：`adjustment_questions` 不由本节点的结构化大纲 LLM 生成，而是来自上游 `PlanIntent.adjustment_options`。
4. 将 chapter sketch 转换为待 normalize 的 `chapter_plan`：
   - `chapter_index`
   - `title`
   - `objective`
   - `required_elements`
   - `writing_instructions`
5. 结构化大纲通过校验后立即通过 SSE status 事件透出 `plan_preview`，前端可以在保存完成前先渲染只读方案卡。
6. 如果 `requested_chapter_count` 非空，结构化大纲必须严格等于该章数；首次不匹配时再走一次结构化 LLM 重生成，而不是本地补章或删章。
7. 用户指定的章数会写入 `build_constraints.requested_chapter_count`，normalize 阶段必须尊重该数量，不再用模式默认 min/max 压缩或补齐。
8. 结构化输出由 Pydantic 合同校验：`plan_text` 和 `chapters` 必须非空，每章必须有可读标题和 `key_points`。
   - 章节标题必须由 LLM 生成成“课程目录标题”：像讲义/教材课时主题，直接说明本章讲什么知识对象、方法主题或题型主题。
   - 学习动作、例题密度、易错点和训练方式放在 `key_points`，不要压进标题里。
   - 本地代码不做关键词提取、规则截取或规则补标题。
9. persist/normalize 只做 reindex、去重和超预算合并；不会因为默认最小章节数不足就在本地补章。
10. 如果结构化合同校验失败，发 `planner.plan.failed` 并抛错；不使用本地规则臆造大纲。

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
   - 补齐课程名、模式、章节索引，并冻结模型生成的章节数。
   - 规范化 `chapter_plan / build_constraints / plan_steps / plan_summary / adjustment_questions`。
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
7. 否则新建 `ConfirmedBuildPlan(status="confirmed")`，递增 `version_no`，并写入 `confirmed_plan_history`。
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
  - `confirmed_plan`
  - `confirmed_plan_history`
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
| `planner_context_stats` | 本轮从会话补齐的历史/上一版方案统计，仅用于观测与排查 |

核心中间产物：

| 字段 | 含义 |
| --- | --- |
| `material_context` | 资料理解包，含文件、切片、课程画像和 material digest |
| `existing_doc_context` | 已发布知识文档摘要，重建场景使用 |
| `planner_context_mode` | `fresh_build / rebuild_existing_doc` |
| `planner_brief` | 用户可见规划判断 |
| `plan_intent` | 内部规划意图、plan_queries、target_scope、requested_chapter_count 和 adjustment_options |
| `plan_outline_markdown` | 合成阶段可见 Markdown |
| `build_plan_draft` | 从结构化 LLM 输出得到的初步大纲 |
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
  adjustment_questions
  selected_file_ids
  planner_session_id
  confirmed_plan_id
  model_override
  planner_context
  docgen_history_brief
```

交接原则：

- Planner 冻结“学什么、按什么章节学、模式是什么、用户修改历史是什么”。
- DocGen 决定“每章怎么写、如何使用资料、如何组织证据和正文”。
- DocGen 不默认新增、删除、重排用户确认过的章节语义。
- 首页模型选择必须经过 `model_override` 从 Planner 冻结到 confirmed plan，再被 DocGen 和自动 KG 同步继承。

## 5. 边界与关注点

目前没有发现需要推倒重写 Planner 主图的问题。Planner 的边界是确认前规划，不做 research，不直接生成文档。

| 关注点 | 判断 |
| --- | --- |
| `model_override` 贯通 | 必须继续经过 workflow boundary、session meta、confirmed plan 交给 DocGen / KG |
| confirmed plan 冻结 | append 可以改 latest_plan；确认后 DocGen 只消费 confirmed plan |
| confirmed plan 版本 | 当前在 `chat_session.meta_json.confirmed_plan_history` 里保留轻量历史，避免重建/再确认覆盖旧方案 |
| 不下沉为 DocGen | 不加入资料读取、外部 research、证据绑定和章节写作 |
| 结构化输出 | 主路径使用 `response_model` 生成机器合同；展示流只给用户看，不承载机器合同 |
| 修订分支 | 必须先由 LLM 判定 `patch_existing` 还是 `replace_existing_outline`；明确新专题/章数时替换旧方案，不保留无关章节 |
| SSE 过程 | status 事件和 token 都要透出；前端只展示当前状态点、可见 token 和 `plan_preview` 只读方案卡，不展示内部过程历史列表 |
| 历史上下文 | prompt 默认读取最近 `planner.history_turns=10` 个用户轮次及其间规划器消息；完整 ChatMessage 仍持久化，确认时进入 `planner_context.docgen_history_brief` |
| 用户输入处理 | `user_prompt` / `feedback_message` 都进入 stream brief、PlanIntent、visible plan 和 structured plan 的 LLM prompt；本地代码只做校验、持久化和合同归一化 |
| 指定章数 | `requested_chapter_count` 来源于 LLM 结构化意图；结构化大纲和 normalize 都必须尊重该数量，避免默认章节预算覆盖用户要求 |
| 调整引导 | `adjustment_questions` 来源于 `extract_plan_intent` 的 `adjustment_options`，不是结构化大纲阶段再生成一套 |
| 章节预算 | sprint/systematic 的默认章节范围和目标长度是 `lib/constants.py` 的 Planner 产品合同常量，不再放项目 settings |
| 会话表 | 继续使用 `chat_session / chat_message` 的 `source="build_planner"`，不新建第二套 |

一句话收束：

```text
Planner 的价值不是提前生成答案，
而是把用户目标、资料边界和学习模式收束成一份可确认、可追踪、可交给 DocGen 执行的稳定合同。
```
