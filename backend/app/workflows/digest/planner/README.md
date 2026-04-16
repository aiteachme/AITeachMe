# Planner 构建方案链路说明

最后更新：2026-04-16

`digest/planner/` 是知识文档主线的第一条链路，负责把用户目标、资料提示、轻量概念检索和历史反馈整理成可确认的构建方案。Planner 的产物不是知识文档正文，而是后续 DocGen 必须消费的 `confirmed_plan` 草案。

## 一句话总览

Planner 做的事就是：先看用户想学什么和手里有什么资料，再补一点概念锚点，最后生成一份用户可以确认的“知识文档施工图”。

## 步骤总览

| 顺序 | 步骤 | 具体做什么 | 目的 | 主要模块/工具 |
| --- | --- | --- | --- | --- |
| 0 | 创建 planner session | API 创建 `BuildPlannerSession`，保存用户目标、选中文件 ID、digest mode、tone，并写入第一条 `BuildPlannerTurn` | 给“生成方案、继续追问、确认方案”一个可追踪的会话容器 | `api/knowledge_docs.py`、`build_planner_service.py`、`build_planner_repo.py` |
| 1 | `load_context` | 读取文件内容和材料画像，生成 `shared_inputs`；如果没有可用正文，就用文件名、学科名、用户目标生成 seed context | 先确定“用户要学什么、资料大概是什么、应该按什么模式规划” | `prepare_shared_inputs`、`list_raw_files_by_ids`、`Subject`、`SharedInputs`、`resolve_digest_course_type` |
| 2 | `ground_concepts` | 基于用户目标、资料主题、历史方案生成检索词；先查本地 RAG，再按配置少量查外部搜索，并整理成 `concept_briefing` | 给 LLM 一个概念校准包，减少空泛标题、错方向和网页标题污染 | `collect_planner_concept_briefing`、`get_retriever`、`SourceCurator`、`read_urls`、`get_teaching_runtime_config` |
| 3 | `draft_plan` | 先构造 fallback plan；再流式生成研究任务；把任务解析成章节；最后规范化 plan 并二次生成章节标题 | 产出前端可展示、可修改、可确认的 draft plan | `build_fallback_plan`、`build_planner_prompt`、`acompletion_stream`、`normalize_planner_draft`、`acompletion_with_fallback` |
| 4 | confirm | 把 latest draft 再规范化，创建或复用 `ConfirmedBuildPlan`，冻结章节、检索词、媒体计划和构建约束 | 给 DocGen 一个稳定执行合同，避免边生成边变 | `confirm_build_planner_session_service`、`normalize_planner_payload`、`create_confirmed_plan` |

## `shared_inputs` 是什么

一句话：`shared_inputs` 是 Digest 给多条链路共用的“资料理解包”。它把上传资料的正文、切片、主题提示、资产、学科画像和模式判断打包在一起，避免 planner、docgen、knowledge graph 各自重复读文件、重复猜主题。

可以把它理解成：

```text
raw_file / raw_markdown
  -> prepare_shared_inputs(...)
  -> SharedInputs
     -> planner 用它规划章节
     -> docgen 用它研究和写作
     -> knowledge_graph 用它做 chunk / source 对齐
```

### 它从哪里来

主要由 `digest/shared/prepare.py::prepare_shared_inputs(...)` 生成。

生成过程：

1. `load_source_packets(...)` 读取每个文件的 parsed markdown。
2. `normalize_markdown_content(...)` 清洗换行和空行。
3. `split_into_sections(...)` 把正文切成更小的 section。
4. `extract_fast_topic_hints(...)` 用规则抽主题、公式、题目密度等提示。
5. `recognize_subject_profile(...)` 判断学科、子学科、材料类型和难度。
6. `build_material_profile(...)` 统计总字符数、公式密度、题目密度、图片/表格数量等。
7. `decide_digest_mode(...)` 判断更适合 `sprint` 还是 `systematic`。
8. `build_asset_registry(...)` 收集图片等资产信息。

### 它里面有什么

| 字段 | 人话解释 | Planner 怎么用 |
| --- | --- | --- |
| `source_packets` | 文件级资料包：一个文件一份，包含文件名、markdown 路径、正文、是否有公式/表格/图片 | `load_context` 用它判断有没有可用资料；prompt 里会放前几份资料摘要 |
| `section_packets` | 内容切片：把文件正文按标题/长度拆成小段 | `ground_concepts` 用它做本地 RAG；没有它本地检索就没东西可查 |
| `chunk_identity_map` | section 和稳定 chunk uid 的映射 | Planner 里用得少，主要给跨链路对齐和 KG 使用 |
| `fast_hints` | 规则抽出来的快速提示，比如高频词、候选章节、公式模式、题目密度 | `load_context` 和 `draft_plan` 用它生成章节主题和 fallback plan |
| `asset_registry` | 当前资料里有哪些图片类资产 | Planner 基本不用，DocGen 生成图文文档时会用 |
| `subject_profile` | 学科画像：学科名、领域、子领域、材料类型、难度、核心主题、是否重公式/重题目 | `draft_plan` 用它决定章节方向、章节数、标题和写作重点 |
| `material_profile` | 材料统计画像：总字数、总 section、公式密度、题目密度、图片/表格数量等 | `decide_digest_mode` 和 fallback plan 用它判断系统课/冲刺课、是否需要更多题型章节 |
| `digest_mode_decision` | 系统根据资料和目标给出的模式建议：`sprint` 或 `systematic` | 用户没指定 digest mode 时，`load_context` 用它决定默认模式 |

### 为什么不直接把文件内容丢给 LLM

原因有三个：

1. **上下文太大**：几十万字不能直接塞进 planner prompt。
2. **多链路要复用同一份理解**：planner、docgen、KG 如果各自分析，结果容易不一致。
3. **很多判断不需要 LLM**：公式密度、题目密度、标题候选、图片引用这些用规则更快、更便宜、更稳定。

### 在 Planner 三个节点里的作用

```text
load_context
  负责创建 shared_inputs。
  如果读到了 markdown，就生成完整资料理解包。
  如果没读到正文，就退化成 seed shared_inputs，只包含文件名/用户目标猜出的主题。

ground_concepts
  使用 shared_inputs.section_packets 做本地 RAG。
  使用 shared_inputs.subject_profile.key_topics 和 fast_hints.chapter_candidates 生成检索词。
  检索到的新 topic hints 会合并回 shared_inputs。

draft_plan
  使用 shared_inputs.subject_profile 识别学科和材料类型。
  使用 shared_inputs.fast_hints 决定章节候选。
  使用 shared_inputs.digest_mode_decision 兜底选择 sprint/systematic。
  使用 shared_inputs.material_profile 判断重公式、重题目、章节数量等。
```

### 空资料时会怎样

如果 `prepare_shared_inputs(...)` 读不到任何正文，`load_context` 不会直接失败，而是走 `_build_seed_shared_inputs(...)`。

这时的 `shared_inputs` 只有很薄的一层：

- 文件名
- 用户目标
- subject 名称
- raw_file 上已有的 discipline/content_type 元数据

目的不是“假装读懂资料”，而是让 Planner 还能先给出一版可修改的草案。真正写文档的 DocGen 后面仍然会按 confirmed plan 和可用资料重新研究。

## 节点级说明

这一段按代码执行顺序写，维护时可以直接对照 `planner/nodes/*.py` 和 `planner/lib/*.py`。

### 0. 创建 planner session

文件：`digest/application/knowledge_docs/build_planner_service.py`

具体做什么：

1. `_select_planner_files(...)` 解析用户选择的文件；如果用户没选，就拿当前 subject 下已有文件。
2. 创建 `BuildPlannerSession`，记录：
   - `subject`
   - `user_id`
   - `user_goal`
   - `digest_mode`
   - `tone`
   - `selected_file_ids_json`
3. 创建一条用户 turn：`BuildPlannerTurn(role="user")`。
4. 调 `run_build_planner_workflow(...)` 进入 LangGraph。
5. workflow 成功后，把 `final_state["plan"]` 再走 `_normalize_persisted_plan(...)`，存入 `latest_plan_json`。
6. 创建 assistant turn，把本次方案摘要和 plan 保存下来。

目的：

- 把一次“我要生成知识文档”的请求变成可持续对话的会话。
- 后续用户补充反馈时，可以拿历史 turns 和 latest plan 重新规划。
- 用户确认时，可以从 session 里冻结出 `ConfirmedBuildPlan`。

主要模块/工具：

- `app.repositories.build_planner_repo`
- `app.repositories.files_repo`
- `app.models.build_planner`
- `app.workflows.digest.planner.run_build_planner_workflow`
- `app.workflows.digest.planner.normalize_planner_payload`

### 1. `load_context`

文件：`planner/nodes/load_context.py`

输入：

- `subject`
- `file_ids`
- `user_goal`
- `digest_mode`
- `tone`

具体做什么：

1. 先发进度事件：`emit_progress(stage="load_context")`。
2. 调 `prepare_shared_inputs(subject, file_ids, user_prompt=user_goal)`。
   - 这里会读取 raw markdown。
   - 切分或整理 section packets。
   - 生成 source packets。
   - 分析 subject profile、fast hints、digest mode decision。
3. 如果 `shared_inputs.source_packets` 为空，说明当前还没有可用正文，于是走 `_build_seed_shared_inputs(...)`：
   - 用 `managed_session()` 打开 DB。
   - 用 `list_raw_files_by_ids(...)` 读取文件元数据。
   - 读取 `Subject` 获取学科名。
   - 从 `user_goal`、文件名、subject 名称里猜 `topic_hints`。
   - 从 raw_file 的 discipline/content_type 元数据里统计学科画像。
   - 构造最小可用的 `SourcePacket` 和 `SubjectProfile`。
4. 确定本轮 `digest_mode`：
   - 用户传了就用用户的。
   - 没传就用 `shared_inputs.digest_mode_decision.mode.value`。
5. 写入课程和检索相关字段：
   - `course_type = resolve_digest_course_type(digest_mode)`
   - `retrieval_profile = resolve_planner_retrieval_profile()`
   - `teaching_action = "plan_course"`
   - `tone = state tone 或 encouraging`

目的：

- 让后面的 LLM 不只看到一句用户目标，而是看到“资料、主题、学科画像、模式判断”。
- 即使资料还没解析完，也能用文件名和目标生成一版不至于空白的计划。

输出：

- `shared_inputs`
- `digest_mode`
- `course_type`
- `retrieval_profile`
- `teaching_action`
- `tone`

主要模块/工具：

- `app.shared.infra.workflow.emit_progress`
- `app.shared.infra.database.managed_session`
- `app.repositories.files_repo.list_raw_files_by_ids`
- `app.models.subject.Subject`
- `app.workflows.digest.shared.prepare.prepare_shared_inputs`
- `app.workflows.digest.shared.models.SharedInputs`
- `app.workflows.digest.shared.contracts.resolve_digest_course_type`
- `app.workflows.digest.shared.contracts.resolve_planner_retrieval_profile`

### 2. `ground_concepts`

文件：`planner/nodes/ground_concepts.py`、`planner/lib/grounding.py`

输入：

- `subject`
- `user_goal`
- `shared_inputs`
- `latest_plan`

具体做什么：

1. 发进度事件：`emit_progress(stage="ground_concepts")`。
2. 调 `collect_planner_concept_briefing(...)`。
3. `build_planner_concept_queries(...)` 先构造最多 4 个检索词，来源包括：
   - subject display name
   - `shared_inputs.subject_profile.key_topics`
   - `shared_inputs.fast_hints.chapter_candidates`
   - `latest_plan.chapter_plan[*].title`
   - `user_goal` 里的短主题片段
4. 先跑本地检索：
   - retriever 固定是 `local_rag`
   - local sections 来自 `shared_inputs.section_packets`
   - 每个 query 最多取 2 条
   - 用 `asyncio.wait_for(...)` 控制 provider timeout
5. 再决定要不要跑外部搜索：
   - 由 `get_teaching_runtime_config().planner.allow_external_search` 控制。
   - 如果 `settings.parse_retrievers(...)` 存在，就按 planner retrieval profile 解析 retriever。
   - 否则 fallback 到 `searxng / bocha / duckduckgo`。
6. 外部搜索结果进入 `SourceCurator.curate_sources(...)` 做来源筛选。
7. 对筛选后的少量 URL 调 `read_urls(...)` 读取页面正文。
8. 从本地和外部结果里提取 topic hints。
9. `_format_concept_briefing(...)` 生成给 prompt 用的概念校准摘要。
10. 回到 node 后，`_merge_planner_topic_hints(...)` 把检索到的 topic hints 合并进 `shared_inputs.fast_hints.chapter_candidates` 和 `subject_profile.key_topics`。

目的：

- 用很小的检索成本给 planner 增加概念边界。
- 告诉 LLM “应该覆盖哪些概念、哪些只是来源网页不能写进任务”。
- 避免方案只有“概述、基础、应用、总结”这种空泛目录。

输出：

- `shared_inputs`：合并了新 topic hints 的版本
- `concept_queries`
- `concept_briefing`
- `concept_topic_hints`
- `concept_local_hit_count`
- `concept_web_hit_count`

主要模块/工具：

- `app.workflows.digest.planner.lib.grounding.collect_planner_concept_briefing`
- `app.shared.infra.search.factory.get_retriever`
- `app.shared.infra.search.SourceCurator`
- `app.shared.infra.tools.builtin.web_reading.read_urls`
- `app.shared.infra.execution.TracedExecutionContext`
- `app.workflows.digest._shared.runtime_config.get_teaching_runtime_config`
- `app.workflows.digest.shared.contracts.resolve_planner_retrieval_profile`

### 3. `draft_plan`

文件：`planner/nodes/draft_plan.py`、`planner/lib/plans.py`、`planner/prompts/draft_plan.py`

输入：

- `shared_inputs`
- `user_goal`
- `digest_mode`
- `tone`
- `message_history`
- `latest_plan`
- `concept_briefing`
- `selected_skillpacks`
- `token_callback`

具体做什么：

1. 解析显示名称：`_resolve_subject_display_name(...)`。
   - 避免把 `subj_xxx` 这种 slug 写进用户可见方案。
2. 先构造 fallback plan：`build_fallback_plan(...)`。
   - 根据 `sprint/systematic` 选择不同章节角度。
   - 根据 topic hints、用户目标、重公式/重题目特征估计章节数。
   - 生成章节标题、目标、required elements、search queries、media hints、build constraints。
3. 构造 planner prompt：`build_planner_prompt(...)`。
   - 注入 subject、user_goal、digest_mode、tone。
   - 注入 `shared_inputs`。
   - 注入历史消息和 latest plan。
   - 注入 `concept_briefing`。
   - 注入 skillpack guidance 和 recommended tool tags。
4. `_build_fast_planner_prompt(...)` 追加严格输出要求：
   - 只输出研究任务。
   - 不写 JSON。
   - 不写正文。
   - 不重复前端已经输出的标题和“研究任务”。
   - 禁止把百度百科、知乎、作者名、网页标题写进任务。
5. 先通过 `token_callback` 给前端输出预览标题和“研究任务”。
6. 调 `acompletion_stream(...)` 流式生成任务行。
7. `_build_raw_plan_from_preview(...)` 从流式文本里解析任务：
   - `_extract_preview_tasks(...)` 提取 `(1) ...` 任务行。
   - 每条任务转成一个章节 objective。
   - search queries 合并任务文本和 fallback queries。
   - 如果任务太少，就用 fallback plan 补齐。
8. `normalize_planner_draft(...)` 规范化 raw draft：
   - 清洗 digest mode、tone、skillpacks。
   - 合并 latest plan 与当前 draft。
   - 按 runtime config 限制章节数。
   - 规范 required elements、search queries、media hints、build constraints。
   - 去重和修正章节标题。
9. `_generate_planner_titles(...)` 再调用一次轻量结构化 LLM，为每章生成更具体标题。
10. `_apply_generated_titles_to_draft(...)` 应用标题，并再次去重。
11. 发进度事件：方案整理完成。

目的：

- 先用 fallback plan 保证“无论如何都有结构”。
- 再用流式 LLM 让前端快速看到生成过程。
- 最后用 normalize 把 LLM 输出压回稳定合同，避免字段缺失、章节数失控、标题重复。

输出：

- `plan`
- `plan_summary`
- `digest_mode`
- `course_type`
- `retrieval_profile`
- `teaching_action`
- `tone`
- `selected_skillpacks`
- `planner_generation_mode = "stream_plaintext"`

主要模块/工具：

- `app.shared.infra.llm_support.acompletion_stream`
- `app.shared.infra.llm_support.acompletion_with_fallback`
- `app.shared.infra.llm_support.routing.TaskType`
- `app.shared.infra.skills.render_prompt_scoped_skillpacks`
- `app.shared.infra.skills.collect_recommended_tool_tags`
- `app.workflows.digest.planner.prompts.build_planner_prompt`
- `app.workflows.digest.planner.prompts.build_planner_chapter_title_messages`
- `app.workflows.digest.planner.lib.plans.build_fallback_plan`
- `app.workflows.digest.planner.lib.plans.normalize_planner_draft`
- `app.workflows.digest._shared.pedagogy.coerce_resolved_chapter_title`

### 4. confirm

文件：`digest/application/knowledge_docs/build_planner_service.py`

具体做什么：

1. 读取 `BuildPlannerSession`。
2. 检查 `latest_plan_json` 是否存在。
3. `_normalized_plan_payload(...)` 把 plan 固定成持久化字段。
4. 如果当前 session 已经有相同内容的 confirmed plan，就复用。
5. 否则创建新的 `ConfirmedBuildPlan`，写入：
   - `chapter_plan_json`
   - `research_queries_json`
   - `media_plan_json`
   - `build_constraints_json`
   - `plan_json`
   - `selected_file_ids_json`
6. 更新 planner session：
   - `confirmed_plan_id = confirmed.id`
   - `status = confirmed`

目的：

- Draft plan 可以反复改；confirmed plan 是 DocGen 的执行合同。
- 构建开始后，DocGen 只读 confirmed plan，不再读易变的 latest draft。

主要模块/工具：

- `get_planner_session`
- `create_confirmed_plan`
- `get_confirmed_plan`
- `update_planner_session`
- `normalize_planner_payload`

## 对外入口

稳定入口：

```python
from app.workflows.digest.planner import (
    normalize_planner_payload,
    run_build_planner_workflow,
)
```

调图入口：

- `build_planner_graph(...)`
- `get_langgraph_dev_planner_graph()`

## 目录结构

```text
planner/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
    load_context.py
    ground_concepts.py
    draft_plan.py
  prompts/
    draft_plan.py
  lib/
    grounding.py
    plans.py
```

分层规则：

- `graph.py` 放节点接线、初始 state 和 workflow runner。
- `state.py` 放 `BuildPlannerState`、输入投影和输出投影。
- `nodes/` 放 LangGraph 顶层节点。
- `prompts/` 放 planner prompt。
- `lib/grounding.py` 放轻量概念检索。
- `lib/plans.py` 放 fallback plan、plan normalize、标题去重等纯逻辑。

## API 到 Planner 的完整链路

```text
POST /build/plans
  -> api/knowledge_docs.py
  -> create_build_planner_session_service(...)
  -> 创建 BuildPlannerSession + user turn
  -> run_build_planner_workflow(...)
  -> digest/planner graph
  -> 写 latest_plan_json + assistant turn
  -> 返回 draft plan

POST /build/plans/{session_id}/messages
  -> append_build_planner_message_service(...)
  -> 读取历史 turns + latest_plan
  -> run_build_planner_workflow(...)
  -> 覆盖 latest_plan_json
  -> confirmed_plan_id 清空，回到 draft

POST /build/plans/{session_id}/confirm
  -> confirm_build_planner_session_service(...)
  -> normalize latest_plan_json
  -> 创建或复用 ConfirmedBuildPlan
  -> PlannerSession.status = confirmed
```

SSE 版本入口：

- `/build/plans/stream`
- `/build/plans/{session_id}/messages/stream`

SSE 中 `token_callback` 会把 planner 草案 token 流式推给前端，`progress_callback` 会推阶段状态。

## 当前 LangGraph 节点

```text
load_context
  -> ground_concepts
  -> draft_plan
  -> END
```

错误路由：

- `load_context` 或 `ground_concepts` 如果返回 `error`，直接结束。
- `draft_plan` 中 LLM 失败会抛异常，由 `run_state_graph(...)` 包装为 workflow failed。

## State 字段心智模型

| 字段 | 说明 |
| --- | --- |
| `subject` | subject slug |
| `file_ids` | 本次 planner 参考的 raw_file ID |
| `user_goal` | 用户学习目标 |
| `digest_mode` | `sprint` / `systematic` |
| `course_type` | 由 digest mode 映射出的课程类型 |
| `retrieval_profile` | Planner 当前检索 profile |
| `shared_inputs` | Digest 共享材料分析结果 |
| `concept_queries` | Planner 概念校准检索词 |
| `concept_briefing` | 注入 planner prompt 的概念校准摘要 |
| `concept_topic_hints` | 检索后合并进主题候选的概念提示 |
| `plan` | 最终可持久化的 plan payload |
| `plan_summary` | 给前端和历史 turn 使用的摘要 |
| `planner_generation_mode` | 当前生成模式，例如 `stream_plaintext` |

## 当前明显优化点

### 建议优先级 P0/P1

1. **为 draft_plan 增加真正的 fallback 返回**
   当前主模型流式失败会抛异常。既然已经有高质量 fallback plan，可以在主模型失败时返回 fallback plan，并在 `planner_generation_mode` 标记为 `fallback`。

2. **让 Planner 文件选择策略更明确**
   当前 planner 可以引用未解析完成的文件，并用文件名生成 seed hints。这对快速体验有利，但如果用户期待“严格基于资料内容”，应在前端或 application 层提示并允许切换。

3. **把概念 grounding 的外部检索预算做成前端可解释状态**
   目前只回传命中数量。可以把“本地/外部是否启用、是否超时、是否降级”放进 runtime stats，便于调试为什么方案偏空。

4. **减少标题二次生成的失败影响**
   `_generate_planner_titles(...)` 失败会影响整个 planner。建议失败时保留临时标题，整体继续返回。

5. **把 latest_plan 合并策略做成显式 diff**
   现在 append message 会把 latest_plan 与新草案按位置合并。后续可以保留章节级变更 diff，方便前端展示“你刚刚的反馈改了哪些章节”。

## 一句话总结

Planner 是一条短链路，但它决定 DocGen 的执行合同。当前最佳维护策略是：先保证 `confirmed_plan` 结构稳定，再逐步增强失败降级、状态解释和用户反馈的可控性。
