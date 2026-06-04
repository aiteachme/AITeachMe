# Planner 链路说明

最后更新：2026-06-03

`planner/` 是 Digest 的第一条链路。它只做一件事：把用户目标、资料范围和修改意见整理成一份可确认的学习方案。

```text
Planner 定方向：学什么、分几章、每章目标是什么。
DocGen 做执行：怎么查资料、怎么写正文、怎么发布知识文档。
```

Planner 不写 `KnowledgeDoc`，不做章节检索，不绑定证据，不生成正文。

## 先看这几个文件

```text
planner/
  graph.py                         # LangGraph 主线和公开运行入口
  state.py                         # 图内 state 字段
  nodes/load_planner_materials.py   # 读取资料、会话、历史方案
  nodes/stream_brief_and_extract_intent.py
  nodes/stream_and_parse_plan_draft.py
  nodes/normalize_and_persist_plan.py
  lib/store.py                     # planner session / confirmed plan 持久化
  lib/model_policy.py              # Planner LLM 策略
```

公开入口：

```python
from app.workflows.digest.planner import (
    create_build_planner_session,
    append_build_planner_message,
    confirm_build_planner_session,
    get_confirmed_build_plan,
    run_build_planner_workflow,
)
```

## 短流程

```text
1. create / append
   用户发起新方案，或在旧方案上继续提修改意见。

2. load_planner_materials
   读取 planner 会话、用户选择的文件、最近对话、上一版 latest_plan 和资料摘要。

3. stream_brief_and_extract_intent
   节点内部并行：
   - 流式输出给用户看的理解说明。
   - 结构化抽取 PlanIntent：是新建、局部修改，还是替换旧大纲。

4. compose plan + generate title
   LangGraph 分两路并行：
   - stream_and_parse_plan_draft：生成可见计划说明 + 机器可解析章节合同。
   - generate_course_name：仅 create 时生成课程短标题和图标。

5. normalize_and_persist_plan
   把模型草稿整理成稳定 latest_plan，写回 planner chat_session 和 assistant message。

6. confirm_build_planner_session
   用户点击确认后，把 latest_plan 冻结为 ConfirmedBuildPlan。
   DocGen 后续只消费 confirmed_plan。
```

并行关系只看这张图：

```text
load_planner_materials
  -> stream_brief_and_extract_intent
       ├─ stream_planner_brief      # 节点内部 run_llm_tasks
       └─ extract_plan_intent       # 节点内部 run_llm_tasks
  -> stream_and_parse_plan_draft ┐
       ├─ stream_visible_plan    │  # 节点内部 asyncio 并行
       └─ structured_plan        │  # 节点内部 asyncio 并行
     generate_course_name        ┘  # LangGraph 分支并行
  -> normalize_and_persist_plan
  -> END
```

## 长流程

### 1. API / 用例入口

`create_build_planner_session(...)`

- 创建新的 `planner_session_id`。
- 使用用户传入的 `file_ids / user_prompt / digest_mode / model`。
- 调用 `run_build_planner_workflow(planner_operation="create")`。
- 失败或取消时更新 planner session 状态。

`append_build_planner_message(...)`

- 读取已有 planner session。
- 追加用户反馈 message。
- 不重新选择资料，继续使用原 session 绑定的文件。
- 调用 `run_build_planner_workflow(planner_operation="append")`。

`record_build_planner_adjust_click(...)`

- 只记录用户打开了调整入口。
- 不改 plan，不跑 LLM。

### 2. 图运行入口

`run_build_planner_workflow(...)`

- 创建 `WorkflowContext(workflow_name="digest.planner")`。
- 把 `planner_operation / planner_session_id / digest_mode / model_override` 写进 trace metadata。
- 使用 `use_runtime_model_override(model_override)` 包住整条图。
- 初始 state 只带用户输入、会话 id、历史消息、回调和上一版 plan。

### 3. `load_planner_materials`

这个节点负责把“请求”变成“可规划上下文”。

输入：

- `planner_operation`
- `course_id / user_id / planner_session_id`
- `requested_file_ids`
- `user_prompt / feedback_message`
- `digest_mode / model_override`

它做三件事：

1. 调 `prepare_planner_run(state)` 处理会话。
   - `create`：创建 `ChatSession(source="build_planner")`，写首条用户消息，保存文件选择。
   - `append`：读取旧 session、最近历史消息、上一版 `latest_plan`，写入用户反馈。
   - `generate_only`：只在内存跑，不写数据库。
2. 调 `prepare_material_context(...)` 读取资料。
   - 读取 `RawFile`、解析后的 Markdown、资料切片、课程画像、material digest。
   - 如果正文还没解析好，退化为 seed context：文件名 + 用户目标 + RawFile 识别信息。
3. 读取已有知识文档摘要。
   - 有摘要：`planner_context_mode="rebuild_existing_doc"`。
   - 没摘要：`planner_context_mode="fresh_build"`。

输出：

- `selected_file_ids / file_ids`
- `message_history`
- `latest_plan`
- `material_context`
- `existing_doc_context`
- `planner_context_mode`

### 4. `stream_brief_and_extract_intent`

这个节点把“资料和用户话语”变成两类信号。

并行子任务：

| 子任务 | 输出 | 用途 |
| --- | --- | --- |
| `stream_planner_brief` | `planner_brief.markdown` | 用户可见，说明系统如何理解资料范围和目标 |
| `extract_plan_intent` | `PlanIntent` | 机器使用，决定本轮如何生成或修改大纲 |

`PlanIntent` 最重要的字段：

- `plan_change_mode`
  - `create_new`：新建方案。
  - `patch_existing`：在旧方案上局部修改。
  - `replace_existing_outline`：用户给了新主题或明确章数，旧方案只当上下文。
- `target_scope`
- `requested_chapter_count`
- `plan_queries`
- `adjustment_options`

失败边界：

- `planner_brief` 失败可以退化为空说明。
- `PlanIntent` 结构化失败会让本轮 Planner 失败，因为后续大纲不能靠本地规则猜。

### 5. `stream_and_parse_plan_draft`

这个节点生成真正的方案草稿。

节点内部并行：

| 子任务 | 输出 | 用途 |
| --- | --- | --- |
| `stream_visible_plan_response` | `plan_outline_markdown` | 用户正在看的流式计划说明 |
| `compose_outline_sketch_with_llm` | `PlannerOutlineSketch` | 机器可解析章节合同 |

结构化草稿会被转换成：

```text
build_plan_draft
  plan_text
  plan_steps
  chapter_plan[]
    chapter_index
    title
    objective
    required_elements
    writing_instructions
  build_constraints
  adjustment_questions
```

关键规则：

- 如果用户指定章数，结构化大纲必须严格等于这个章数。
- `adjustment_questions` 来自上游 `PlanIntent.adjustment_options`，不是本节点重新发明。
- 标题必须是课程目录标题；练习密度、易错点、教学动作放在 `key_points` 或章节说明里。
- 结构化输出不完整时失败，不用本地关键词补大纲。

### 6. `generate_course_name`

只在 `planner_operation="create"` 时有意义。

输入：

- 用户目标
- 文件名
- material topic hints
- planner brief
- plan intent

输出：

- `generated_course_name`
- `generated_course_icon_key`

这个标题只用于课程展示，不参与章节规划。

### 7. `normalize_and_persist_plan`

这个节点是 Planner 图的收口。

步骤：

1. 调 `normalize_planner_draft(...)`。
   - 补齐课程名、章节索引、模式、摘要和构建约束。
   - append 场景会吸收 `latest_plan`，保留用户修订语义。
2. 如果生成了课程名，写进 plan。
3. 发 `planner.plan.ready`。
4. 调 `save_planner_result(...)`。

数据库写入：

- 更新 `ChatSession.meta_json.latest_plan`。
- 更新 `latest_summary / digest_mode / model_override / planner_status="draft"`。
- 写 assistant `ChatMessage(message_kind="planner_plan")`。
- 必要时更新 `Course.name / description / user_intent`。

输出给 API：

- `plan`
- `plan_summary`
- `selected_file_ids`
- `planner_record`
- `planner_turns`
- runtime timing

### 8. `confirm_build_planner_session`

确认不是 LangGraph 节点，但它是 Planner -> DocGen 的交接点。

步骤：

1. 读取 planner `ChatSession`。
2. 读取 session meta 里的 `latest_plan`。
3. 读取完整 Planner turns，生成 `planner_context` 和 `docgen_history_brief`。
4. 构建冻结 `plan_payload`。
5. 把 `model_override` 写进 `plan_payload.model_override`。
6. 如果内容未变，复用旧 `ConfirmedBuildPlan`。
7. 否则新建一条 `ConfirmedBuildPlan(status="confirmed")`，递增 `version_no`。
8. 更新 planner session meta 为 confirmed。

DocGen 消费的就是这份 confirmed plan。

## 关键数据流

```text
用户目标 / 修改意见
  -> material_context
  -> planner_brief + plan_intent
  -> build_plan_draft
  -> latest_plan
  -> confirmed_plan
  -> DocGen
```

`latest_plan` 和 `confirmed_plan` 不一样：

| 字段 | 含义 |
| --- | --- |
| `latest_plan` | 可继续修改的草稿，存在 planner session meta |
| `confirmed_plan` | 用户确认后的冻结合同，存在 `ConfirmedBuildPlan` |

`model_override` 贯通路径：

```text
首页模型选择
  -> Planner state.model_override
  -> ChatSession.meta_json.model_override
  -> ConfirmedBuildPlan.plan_json.model_override
  -> DocGen
  -> 自动 KG 同步
```

## 模型调用

策略集中在 `lib/model_policy.py`。

| 步骤 | 调用 | 槽位 |
| --- | --- | --- |
| `stream_planner_brief` | stream | `light` |
| `extract_plan_intent` | structured | `light` |
| `visible_plan` | stream | `light` |
| `structured_plan` | structured | `light` |
| `generate_course_name` | text | `light` |
| `select_course_icon` | text | `light` |

运行时如果传了 `model_override`，逻辑槽位仍写 `light`，实际 provider 模型由 runtime override / settings 决定。

## 修改这条链路时检查

- `graph.py` 节点顺序是否和本 README 的短流程一致。
- 新 LLM 调用是否进了 `lib/model_policy.py`。
- 新进度事件是否走 `planner_events.py`。
- 任何会影响 DocGen 的字段，是否最终进入 `ConfirmedBuildPlan.plan_json`。
- 不要在 Planner 里做正文生成、证据绑定或章节检索。

建议提交类型：改本文档用 `docs`，改链路行为用 `refactor` 或 `fix`。
