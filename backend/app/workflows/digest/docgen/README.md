# DocGen 知识文档生成链路说明

最后更新：2026-04-16

`digest/docgen/` 是 Digest 的知识文档生成链路。它不再负责生成构建方案，而是严格消费已经确认的 `confirmed_plan`，按章节研究、写作、增强、注入练习并发布知识文档。

## 一句话总览

DocGen 做的事就是：拿已经确认的构建方案，逐章找资料、写讲义、补图表和自检练习，最后把草稿暂存或发布成正式知识文档。

## 步骤总览

| 顺序 | 步骤 | 具体做什么 | 目的 | 主要模块/工具 |
| --- | --- | --- | --- | --- |
| 0 | 触发构建 | API 校验 `confirmed_plan_id`、获取构建锁、选择 ready 文件或进入 search-only 模式 | 保证同一学科不会并发乱写，并确认本次构建有明确方案 | `trigger_docgen_build`、`KnowledgeBuildLock`、`get_confirmed_build_plan_service` |
| 1 | `load_context` | 读取 confirmed plan，转换成 `chapter_assignments`，准备 `shared_inputs` 和 `document_context` | 把“用户确认的方案”变成图里可执行的章节任务 | `normalize_confirmed_plan_contract`、`prepare_shared_inputs`、`resolve_skillpacks` |
| 2 | `research_chapters` | 每章并行做本地 RAG、外部检索、网页读取、来源筛选和上下文压缩 | 给每章准备足够可靠的写作材料，而不是让 LLM 凭空写 | `DocGenChapterContextRuntime`、`LocalRAGRetriever`、`SourceCurator`、`ContextCompressor`、`read_urls` |
| 3 | `merge_research` | 等所有章节研究结束，汇总研究结果和进度 | 确认资料已收齐，准备进入标题收口和写作 | `update_knowledge_build_status`、`publish_docgen_progress` |
| 4 | `finalize_titles` | 根据每章研究内容重新收口章节标题，并写入 `title_resolved_chapter_materials` | 让目录更贴近真实内容，并避免 fan-in 累加导致重复写作 | `build_chapter_title_resolution_messages`、`acompletion_with_fallback`、`coerce_resolved_chapter_title` |
| 5 | `write_chapters` | 每章并行调用 writer，把研究材料写成教学化 Markdown，并做结构修复和质量补齐 | 生成真正给学生看的讲义正文 | `DocGenWriterRuntime`、`build_docgen_writer_messages`、`ensure_chapter_learning_scaffold` |
| 6 | `merge_drafts` | 去重并排序章节草稿，合并成完整文档草稿 | 得到可统一增强、可预览的整本文档 | `build_merged_markdown`、`prepend_table_of_contents`、`count_words` |
| 7 | `enrich_assets` | 处理 Mermaid、图片、交互块占位，规范公式和来源 | 把纯文本讲义增强成更适合学习的多媒体文档 | `DocGenAssetRuntime`、`normalize_math_delimiters`、`validate_latex`、`append_reference_section` |
| 8 | `append_practice` | 按 `sprint/systematic` 规则追加“练习与自检”章节 | 让知识文档不只讲内容，还能引导学生自测和复盘 | `build_examine_markdown`、`build_merged_markdown` |
| 9 | `publish_document` | 写入 `_build` 草稿；独立构建时发布正式 `KnowledgeDoc` | 把生成结果落到存储和数据库，供前端展示和后续链路消费 | `stage_knowledge_docs`、`publish_staged_knowledge_docs`、`docgen_repo`、`ContentStore` |

## 对外入口

上层稳定入口：

```python
from app.workflows.digest import run_docgen_workflow
```

链路内部入口：

- `build_docgen_graph(...)`
- `create_docgen_initial_state(...)`
- `get_langgraph_dev_docgen_graph()`

## 目录结构

```text
docgen/
  __init__.py
  README.md
  graph.py
  state.py
  nodes/
  prompts/
  lib/
```

分层约定：

- `graph.py` 只负责 LangGraph 节点、路由、fan-out/fan-in 和初始 state。
- `state.py` 只定义 DocGen 链路状态。
- `nodes/` 放图上的顶层节点。
- `prompts/` 放 research / title / writer / asset prompt builder。
- `lib/` 放章节研究、写作、媒体增强、发布、诊断摘要等节点内部逻辑。

## 前置链路

DocGen 通常不是直接从上传文件启动，而是从知识文档构建 API 启动：

```text
api/knowledge_docs.py
  -> trigger_docgen_build(...)
  -> 校验 confirmed_plan_id
  -> 获取构建锁
  -> run_docgen_background(...) 或 run_unified_build_background(...)
  -> run_docgen_workflow(...)
  -> digest/docgen graph
```

关键前置条件：

- 必须有已确认的 `ConfirmedBuildPlan`。
- 对 docs-only 构建，允许没有本地 ready 文件，此时进入 search-only / web-first 研究模式。
- 如果有本地文件，文件必须处于 Digest 可消费态。
- 同一 subject 同时只能有一个知识构建锁。

## 当前 LangGraph 节点

```text
load_context
  -> research_chapters (Send x N)
  -> merge_research
  -> finalize_titles
  -> write_chapters (Send x N)
  -> merge_drafts
  -> enrich_assets
  -> append_practice
  -> publish_document
  -> END
```

## 状态字段心智模型

最重要的状态字段如下：

| 字段 | 说明 |
| --- | --- |
| `chapter_assignments` | 从 confirmed plan 转换出的可执行章节任务 |
| `chapter_materials` | `research_chapters` fan-in 收集的原始章节研究结果，使用 `operator.add` 累加 |
| `title_resolved_chapter_materials` | `finalize_titles` 收口标题后的章节研究结果，供写作阶段消费 |
| `chapter_drafts` | `write_chapters` fan-in 收集的章节草稿 |
| `chapter_metadatas` | 合并、增强和发布阶段使用的章节元数据与 Markdown |
| `merged_markdown` | 当前合并后的完整知识文档 |
| `doc_ids` | standalone 发布模式下创建的正式知识文档 ID |

注意：`chapter_materials` 是 fan-in 累加字段，不能在后续节点里直接当“替换字段”写回，否则会导致同一章重复写作。标题收口后的结果必须写入 `title_resolved_chapter_materials`。

## Step 1：load_context

文件：`nodes/load_context_node.py`

职责：

1. 读取或准备 `shared_inputs`。
2. 校验 `confirmed_plan` 是否存在。
3. 用 `normalize_confirmed_plan_contract(...)` 解析确认后的构建方案。
4. 从 plan 中解析：
   - `digest_mode`
   - `course_type`
   - `retrieval_profile`
   - `tone`
   - `selected_skillpacks`
   - `chapter_assignments`
5. 初始化知识构建状态：
   - `stage = planner_confirmed`
   - `chapter_progress = planned`
   - `plan_summary`
6. 发布轻量 DocGen progress event。

输出：

- `shared_inputs`
- `raw_chunks`
- `subject_profile`
- `chapter_assignments`
- `confirmed_plan`
- `document_context`

失败条件：

- 缺少 confirmed plan。
- confirmed plan 字段不完整。
- confirmed plan 没有可执行章节。

## Step 2：research_chapters

文件：`nodes/research_chapters_node.py`

这是 fan-out 节点，每个章节一个 `Send`。

输入来自 `chapter_assignment`，核心流程：

1. 更新章节状态为 `researching`。
2. 构建 `TracedExecutionContext`，写入：
   - `build_session_id`
   - `planner_session_id`
   - `confirmed_plan_id`
   - `digest_mode`
   - `course_type`
   - `retrieval_profile`
   - `chapter_index`
3. 调 `DocGenChapterContextRuntime.run(...)`。
4. 本地 RAG 优先检索，如果本地命中不足，再启用外部 retriever。
5. 读取外部网页，做来源筛选与上下文压缩。
6. 根据覆盖率缺口追加检索轮次。
7. 必要时用轻量 LLM 做 research material purify。
8. 返回一个 `chapter_material`。

输出写入 `chapter_materials`，包括：

- `dense_context`
- `sources`
- `source_details`
- `local_hits / web_hits`
- `executed_queries / planned_queries / fallback_queries`
- `coverage_score`
- `research_rounds`
- `curated_source_count`
- `trusted_source_count`

## Step 3：merge_research

文件：`nodes/merge_research_node.py`

职责很轻：

1. 等待所有 `chapter_materials` fan-in 完成。
2. 更新全局构建状态为 `drafting`。
3. 记录“研究收齐，开始标题收口”的事件。
4. 发布 progress。

它不修改 `chapter_materials`。

## Step 4：finalize_titles

文件：`nodes/finalize_titles_node.py`

目标是根据研究材料把 planner 中较粗的章节标题收口成更像知识文档目录的标题。

流程：

1. 读取所有 `chapter_materials`。
2. 对每章提取：
   - `dense_context`
   - `source_titles`
   - `search_queries`
   - `objective`
   - `required_elements`
3. 并发调用轻量 LLM 生成标题。
4. 用 `coerce_resolved_chapter_title(...)` 做标题清洗和兜底。
5. 更新章节 progress 的标题。
6. 输出 `title_resolved_chapter_materials`。

关键实现点：

- 不再把结果写回 `chapter_materials`，避免 `operator.add` 累加造成重复写作。
- 后续 `build_craft_sends(...)` 优先消费 `title_resolved_chapter_materials`。

## Step 5：write_chapters

文件：`nodes/write_chapters_node.py`

这是第二个 fan-out 节点，每个章节一个 `Send`。

流程：

1. 读取 `title_resolved_chapter_materials`。
2. 每章构建 `TracedExecutionContext`。
3. 调 `DocGenWriterRuntime.run(...)`。
4. writer prompt 消费：
   - 标题
   - 章节目标
   - required elements
   - dense research context
   - execution contract
   - skillpack guidance
5. LLM 生成 Markdown 后，执行：
   - 标题结构检查
   - 必要时 LLM heading repair
   - 必要时 scaffold fallback
   - 媒体占位补齐
   - 覆盖率和长度修复
   - 面向学生的 Markdown 清洗
6. 返回 `chapter_draft`。

输出写入 `chapter_drafts`，包括：

- `markdown`
- `summary`
- `tags`
- `source_details`
- `word_count`
- `placeholder_count`
- `coverage_score`
- `quality_score`
- `repair_actions`

## Step 6：merge_drafts

文件：`nodes/merge_drafts_node.py`

流程：

1. 按 `chapter_index` 对草稿排序。
2. 同一章如果有多个草稿，保留分数更高的一个。
3. 构造 `chapter_metadatas`。
4. 调 `build_merged_markdown(...)` 合并成完整文档。
5. 追加目录。
6. 更新状态为 `enriching`。

输出：

- `chapter_metadatas`
- `merged_markdown`
- `enriched_markdown`

## Step 7：enrich_assets

文件：`nodes/enrich_assets_node.py`

职责是处理写作阶段留下的媒体占位：

- `<!-- [MERMAID: ...] -->`
- `<!-- [IMAGE: ...] -->`
- `<!-- [INTERACTIVE: ...] -->`

处理逻辑：

1. Mermaid：调用 LLM 生成 Mermaid mindmap；失败时降级为规则生成的简单 mindmap。
2. Image：当前生成配图建议块；如果配置了文生图模型，可继续扩展为真实图片生成。
3. Interactive：生成内置 HTML 交互块，例如公式展开器、概念自检卡。
4. 统一规范公式分隔符、校验 LaTeX、规范 Mermaid。
5. 如构建方案允许来源，追加章节参考来源。
6. 重新合并完整文档。

输出：

- `chapter_metadatas`
- `merged_markdown`
- `enriched_markdown`
- `mermaid_block_count`
- `image_block_count`
- `interactive_block_count`
- `asset_summary`

## Step 8：append_practice

文件：`nodes/append_practice_node.py`

职责是在文档末尾追加“练习与自检”章节。

当前是规则生成，不调用 Examine 图：

- `sprint` 模式偏高频题型、自检、易错复盘。
- `systematic` 模式偏理解、推理、迁移。

输出：

- 追加后的 `chapter_metadatas`
- `exam_questions`
- `practice_count`
- 更新后的 `merged_markdown / enriched_markdown`

## Step 9：publish_document

文件：`nodes/publish_document_node.py`

发布分两种模式：

### standalone DocGen

如果没有有效 unified build session：

1. `stage_knowledge_docs(...)` 写入 `_build/` 草稿。
2. `publish_staged_knowledge_docs(...)` 发布正式版本：
   - 写章节 Markdown
   - 写版本归档
   - 写 merged knowledge base
   - 写 `KnowledgeDoc` DB 记录
   - 写 manifest
   - 清理 staging
3. 返回 `doc_ids`。

### unified build 中的 DocGen

如果存在 unified build session：

1. 只暂存 DocGen 草稿。
2. 等 unified lane 后续统一发布。
3. `doc_ids` 为空，但 `built_paths` 和 `merged_markdown` 可用。

## 当前明显优化点

### 已处理

- 标题收口结果写入 `title_resolved_chapter_materials`，避免同一章重复触发 `write_chapters`。
- Mermaid LLM 生成失败时会降级为规则 mindmap，避免单个媒体块拖垮整份文档。

### 建议优先级 P0/P1

1. **给 `finalize_titles` 增加更温和的失败降级**
   现在标题 LLM 失败会抛出异常。可以改为单章失败时使用 planner 标题，整体继续写作。

2. **把 practice layer 接入 Examine 的真实题目生成能力**
   当前练习是规则生成，质量稳定但个性化不足。后续应让 `append_practice` 调用 Examine 的 question build 能力，并保持失败时规则兜底。

3. **媒体资产从“建议块”升级到真实资产生命周期**
   图片目前主要是建议文本。后续如果接入 image generation，需要定义 asset 存储、manifest、前端渲染和失败降级合同。

4. **补章节级 rewrite loop**
   writer 当前有结构修复和 scaffold fallback，但缺少“审校不过则重写”的闭环。建议先做单章最多 1 次 rewrite，避免成本失控。

5. **把 search-only 模式显式体现在前端**
   当前后端支持无本地资料时 web-first 生成，但前端体验上最好明确提示“本轮主要基于联网研究”。

## 一句话总结

DocGen 当前链路是“确认方案 -> 逐章研究 -> 标题收口 -> 逐章写作 -> 媒体增强 -> 练习注入 -> 暂存/发布”。最重要的维护点是 fan-out/fan-in 状态字段不要混用，以及所有 LLM/媒体子步骤都要有可用降级。
