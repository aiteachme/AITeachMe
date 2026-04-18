# DocGen 重构流程设计

最后更新：2026-04-17

这份文档只讨论 `digest/docgen` 后续应该怎么生成高质量知识文档。它不是当前代码说明，当前实现细节仍以 `README.md`、`graph.py` 和各节点代码为准。

## 一句话结论

DocGen 不应该拿到 confirmed plan 后立刻逐章写正文。

更稳的流程应该是：

```text
先把计划大纲、用户意图、文件材料统一吃透
  -> 再生成每章可执行的详细生成计划
  -> 再分发给章节生成
  -> 再做章节增强
  -> 最后合并检查和必要回改
```

简单说：

```text
planner 定方向，docgen 定细节并真正写完。
```

## 1. DocGen 的输入和输出

### 输入

DocGen 至少消费：

- 用户上传并解析好的文件内容
- confirmed plan，也就是用户确认后的计划大纲
- 用户目标和 Planner 会话摘要
- 用户历史对话摘要或关键修改意见
- `digest_mode`：`sprint` 或 `systematic`
- `tone`
- `selected_skillpacks`

注意：不建议把完整历史对话直接塞给 DocGen。更合适的是 Planner 固化一份 `conversation_summary` 或 `docgen_history_brief`，只保留和文档生成有关的要求。

### Planner 交接字段

DocGen 从 `confirmed_plan` 中读取这些字段：

```text
chapter_plan：用户确认的章节合同，是 DocGen 的章节边界
user_goal / plan_summary：写作目标和整体方向
digest_mode / tone：决定章节写作风格
selected_skillpacks：加载 DocGen prompt 策略
selected_file_ids：限制本地资料范围
media_plan / build_constraints：控制资产、练习、章节长度和来源策略
planner_context / docgen_history_brief：Planner 会话摘要和修改意见
```

DocGen 可以细化 `chapter_plan`，但不能静默推翻 confirmed plan。

### 输出

DocGen 至少产出：

- 分章节知识文档
- 拼接后的完整知识文档
- 每章摘要
- 练习与自检内容
- 资产增强结果
- manifest

后续更理想的产物：

- `chapter_generation_plan`
- `chapter_summaries`
- `merge_review_report`
- `revision_tasks`
- `evidence_ledger`
- `asset_manifest`
- `practice_manifest`

## 2. 设计原则

### 2.1 先统一章节格式

速成课和系统课先不要拆成两套完全不同的章节模板。

推荐先统一成：

```text
# 章节标题

> 章节导读

## 1. 概念、定义与结论

## 2. 方法、步骤与适用条件

## 3. 例子或例题

## 4. 关键提醒与易错点

## 5. 本章小结

## 本章摘要
```

`sprint` 和 `systematic` 的差异先体现在：

- 内容密度
- 解释深度
- 例题比例
- 检索偏好
- 复盘方式
- 易错点权重

具体理解：

```text
sprint：更像突击课，重考点、题型、步骤、易错点、速查。
systematic：更像系统课，重概念、定义、推导、前置关系、迁移理解。
```

### 2.2 正文生成前先把每章写什么定细

confirmed plan 只是大方向，不能直接当章节写作输入。

DocGen 应该先补三层理解：

```text
计划大纲增强
意图识别
文件摘要
```

然后再统一生成每章的 `chapter_generation_plan`。

### 2.3 章节生成允许继续检索

章节生成不能只依赖一次 research 结果。

更合理的是：

```text
读本章计划
  -> 检索本地材料
  -> 必要时外部补充
  -> 写概念定义
  -> 写例题例子
  -> 发现缺口继续补检索
  -> 留下增强标识符
  -> 生成章节稿
```

### 2.4 正文生成和增强分开

章节生成负责把内容讲清楚。

章节增强负责处理：

- 图表
- 交互块
- Mermaid
- 图片建议或图片生成
- 样式统一
- 章节摘要
- 练习入口

不要让一个 writer 节点同时背所有职责。

### 2.5 合并后必须再检查

单章写得好，不代表整本就好。

合并后必须检查：

- 章节之间是否重复
- 是否有知识断裂
- 是否和计划大纲不一致
- 是否风格漂移
- 是否某些章节太浅或太长
- 是否需要回改某些章节

## 3. 推荐总流程

目标流程直接按下面理解。图上 `generate_draft / enhance / review_content` 都是章节模板节点，运行时按 `ChapterGenerationTask[]` 展开成 N 路并行。

```text
load_context
  输入：confirmed_plan / shared_inputs / selected_skillpacks / planner_context
    - confirmed plan：用户确认后的构建合同，包含章节、模式、目标、约束。
    - shared_inputs：资料理解包，包含文件、切片、画像、统计、资产索引。
    - selected_skillpacks：用户选择的提示词策略包名称。
    - planner_context：confirmed_plan 中固化的 Planner 会话摘要和修改意见。
  输出：DocGenContext / chapter_assignments / document_context
    - DocGenContext：DocGen 全局运行上下文。
    - chapter_assignments：confirmed plan 章节转成的执行章节列表。
    - document_context：发布和写作共用的文档级上下文。
  作用：确认用户已确认的章节合同，补齐资料上下文、模式、语气、技能包和构建状态。

prepare_context
  ├─ enhance_plan_outline
  │    输入：chapter_assignments / material_stats_profile / material_sections / planner_context
  │      - confirmed chapters：用户确认的章节列表。
  │      - material_stats_profile：资料类型、题目密度、公式密度、学科画像等统计。
  │      - material_sections：切片级正文，可抽取高信息密度片段。
  │    输出：EnhancedChapterOutline[] / plan_mismatch_warnings[]
  │      - EnhancedChapterOutline：每章执行级小纲和重点目标。
  │      - plan_mismatch_warnings：模型输出和 confirmed plan 不一致时的 warning。
  │    作用：执行级细化章节，不新增、不删除、不重排 confirmed plan。
  │    注意：这里只做轻量 grounding，不做完整 Web research。
  ├─ infer_docgen_intent
  │    输入：user_goal / plan_summary / digest_mode / chapter_assignments / docgen_history_brief
  │      - user_goal：用户最终学习目标。
  │      - plan_summary：Planner 生成的方案摘要。
  │      - digest_mode：sprint 或 systematic。
  │      - docgen_history_brief：和文档生成有关的历史修改摘要。
  │    输出：DocGenIntentProfile
  │      - DocGenIntentProfile：写作风格、深度、例子偏好、考试倾向、避让项。
  │    作用：识别写作深度、考试倾向、例子偏好、定义粒度、避让项。
  └─ summarize_files
       输入：source_packets / section_packets / chapter_assignments
         - source_packets：文件级正文包。
         - section_packets：切片级正文包。
         - chapters：章节目标，用于判断文件和章节亲和度。
       输出：FileMaterialSummary[]
         - FileMaterialSummary：文件摘要、核心概念、公式、例题、高价值 section、章节亲和度。
       作用：为章节生成提供文件摘要、章节亲和度、高价值 section。

merge_and_dispatch
  输入：EnhancedChapterOutline[] / DocGenIntentProfile / FileMaterialSummary[] / chapter_assignments
  输出：ChapterGenerationPlan / ChapterGenerationTask[]
    - ChapterGenerationPlan：整轮写作规则、格式、预算、章节任务集合。
    - ChapterGenerationTask：单章执行合同，包含标题、目标、检索词、写作规则、预算。
  作用：合并 prepare_context 的三路结果，形成每章唯一执行合同。

generate_draft
  ├─ generate_chapter 0
  ├─ generate_chapter 1
  └─ generate_chapter N
  输入：单章 ChapterGenerationTask / shared_inputs / DocGenContext / retrieval_profile / selected_skillpacks
  输出：ChapterDraft[] / ChapterResearchTrace[] / EvidenceLedger[]
    - ChapterDraft：章节初稿、摘要草稿、占位符、质量信号。
    - ChapterResearchTrace：检索轮次、执行 query、打开上下文、覆盖率。
    - EvidenceLedger：正文中可追溯的证据条目。
  作用：每章执行检索、压缩上下文、evidence ledger、写正文草稿。
  generate_chapter 内部步骤：
    1. 取本章 retrieval_queries / priority_section_refs。
    2. 本地检索资料切片，不足时按 docgen.allow_external_search 做外部补充。
    3. 读取命中内容并压缩为 dense_context。
    4. 构建 evidence ledger，标记来源和覆盖目标。
    5. 按 sprint/systematic 策略写章节草稿，留下增强占位符。
  模式差异：sprint/systematic 的核心差异主要在这里体现。
    - sprint：短、密、题型导向，强调考点、速判、易错点、复盘清单。
    - systematic：长、稳、结构导向，强调定义、推理、例子、迁移和前置关系。

enhance
  ├─ enhance_chapter 0
  ├─ enhance_chapter 1
  └─ enhance_chapter N
  输入：ChapterDraft / placeholder_requests / asset settings / digest_mode
  输出：EnhancedChapterDraft[] / AssetManifest[] / PracticeManifest[]
    - EnhancedChapterDraft：增强后的章节正文。
    - AssetManifest：Mermaid、图片、交互块等资产清单。
    - PracticeManifest：本章自检题和练习种子。
  作用：处理 Mermaid、图片占位、交互块、公式清洗、本章自检。
  enhance_chapter 内部步骤：
    1. 解析章节中的 Mermaid / image / interactive 占位符。
    2. 生成或降级处理对应资产。
    3. 统一公式、Mermaid、Markdown 结构。
    4. 追加本章自检题。
    5. 产出 asset / practice manifest。

review_content
  ├─ review_chapter 0
  ├─ review_chapter 1
  └─ review_chapter N
  输入：EnhancedChapterDraft / ChapterGenerationTask / EvidenceLedger / DocGenIntentProfile
  输出：ReviewedChapterDraft[] / ChapterReviewReport[]
    - ReviewedChapterDraft：最终可合并章节稿。
    - ChapterReviewReport：覆盖率、质量分、缺失点、修补记录、warning。
  作用：复核增强后的最终章节，执行 coverage / quality / bounded patch。
  review_chapter 内部步骤：
    1. 检查 required elements 是否覆盖。
    2. 检查 evidence ledger 是否支撑关键说法。
    3. 检查章节结构、长度、风格和模式要求。
    4. 必要时做小范围 patch，不整章重写。
    5. 输出 review report，保留 warning。
  约束：不改变章节边界，不新增章节，不破坏增强块。

merge_review
  输入：ReviewedChapterDraft[] / ChapterGenerationPlan / research_traces / evidence_ledgers / asset_manifests / practice_manifests
  输出：merged_markdown / chapter_metadatas / MergeReviewReport
    - merged_markdown：整本文档 Markdown。
    - chapter_metadatas：发布和 manifest 使用的章节元数据。
    - MergeReviewReport：整本结构、重复、缺口、风格和来源检查报告。
  作用：合并章节，检查整本结构、重复、缺章、风格断裂、来源覆盖。

finalize_titles
  输入：chapter_metadatas / confirmed_plan.chapter_plan / enhanced titles / merge_review_report
  输出：final_chapter_titles / updated chapter_metadatas / title_review_report
  作用：标题收口，保持 chapter_index 和 confirmed plan 映射。
  约束：只统一标题表达，不推翻用户确认过的章节语义。

publish_document
  输入：merged_markdown / chapter_metadatas / docgen_artifacts / document_context
  输出：markdown files / docgen_manifest.json / KnowledgeDoc rows / version archive
    - docgen_artifacts：DocGenContext、计划、章节、证据、资产、练习、review 报告。
  作用：发布章节 Markdown、整本 Markdown、manifest、数据库记录和版本归档。
```

## 4. 当前实现映射

当前 graph 还不是完全按上面的 vNext 形态拆开的，主要差异如下：

| 目标阶段 | 当前对应 | 状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_context` | `prepare_parallel_inputs` | 已落地，内部并行执行三路准备 |
| `merge_and_dispatch` | `confirm_and_dispatch` | 已落地 |
| `generate_draft` | `generate_chapters` | 已落地，章节 fan-out |
| `enhance` | `enhance_chapters` | 已落地，fan-in 后内部并发增强 |
| `review_content` | `generate_chapters` 内部 critic/rewrite | 待移到 enhance 后并拆独立节点 |
| `merge_review` | `merge_review` | 已落地 |
| `finalize_titles` | 分散在 generation / merge / publish 中 | 待补独立节点 |
| `publish_document` | `publish_document` | 已落地 |

旧 `research_chapters / merge_research / finalize_titles / write_chapters / merge_drafts / enrich_assets / append_practice` 顶层节点已移除。底层可复用 runtime 仍可保留，例如章节研究、writer 和资产处理 runtime。

## 5. Node 0A：计划大纲增强

### 做什么

根据 confirmed plan 的章节大纲，结合资料画像、文件摘要和高价值 section，把每章展开成更细的内容要点和章节小纲。

它不是重新规划课程，而是把 Planner 的粗大纲变成 DocGen 可执行的章节蓝图。

### 输入

- confirmed plan
- 用户上传文件的资料画像、章节候选和高价值 section
- 文件摘要或规则摘要
- Planner grounding 信息
- 用户历史对话摘要

### 输出

`enhanced_outline`

每章至少包含：

```text
chapter_index
title
目标
细化章节大纲
内容要点
重点概念
重点定义
重点公式或结论
例题方向
易错提醒
建议检索方向
可能缺口
```

### 模型和工具

- `reason` 模型
- 本地 section grounding
- 文件摘要和 material profile

### 编排建议

可以按章并行增强，但最后要做一次全局去重，避免两个章节争同一个主题。

这一步不做完整 Web research；外部检索放在后续 `generate_draft` 的章节研究阶段。

## 6. Node 0B：意图识别

### 做什么

根据文件、对话、计划大纲，再深度判断用户真正需要什么样的知识文档。

Planner 的意图识别主要服务于“定大纲”；DocGen 的意图识别服务于“定文档长相”。

### 输入

- 用户目标
- 用户历史对话摘要
- confirmed plan
- 文件摘要或资料速览

### 输出

`docgen_intent_profile`

建议字段：

```text
document_style
depth_level
primary_need
secondary_need
chapter_style_hints
example_preference
definition_depth
exam_orientation
review_orientation
avoid_list
```

例子：

```text
primary_need: "考前突击"
example_preference: "多例题和题型步骤"
definition_depth: "只保留必要定义，不做长推导"
avoid_list: ["不要写太长背景", "不要重复原文"]
```

### 模型和工具

- `primary` 模型

### 编排建议

这一步可以和 0A、0C 并行。

失败时回退到 confirmed plan 中的 `digest_mode`、`tone` 和默认文档风格。

## 7. Node 0C：文件摘要

### 做什么

对每个文件做更细的摘要，形成文件级材料画像。

这不是一句话摘要，而是为后续“每章该吃哪些文件、哪些 section”做准备。

### 输入

- 用户上传并解析后的文件内容
- 文件元信息
- 章节大纲

### 输出

`file_summaries`

每个文件至少包含：

```text
file_id
filename
文件摘要
主要概念
主要定义
主要公式或结论
主要例题 / 题型
适合支撑哪些章节
高信息密度 section
噪音 section
是否适合做例题来源
是否适合做定义来源
```

### 模型和工具

- `primary` 模型
- 长文件可先切片，再汇总

### 编排建议

文件之间可以并行。

失败时保留规则摘要：

```text
文件名 + fast hints + section preview
```

## 8. Node 1：确认和分发

### 做什么

把 0A、0B、0C 统一起来，生成真正给章节生成用的详细计划。

这一步很关键，因为三个前置结果可能会各说各话：

```text
大纲增强认为章节 A 要讲定义
意图识别认为用户更想看例题
文件摘要发现例题主要在文件 B
```

必须由一个全局节点统一收口。

### 输入

- `enhanced_outline`
- `docgen_intent_profile`
- `file_summaries`
- confirmed plan

### 输出

`chapter_generation_plan`

全局计划：

```text
global_style
chapter_format
mode_policy
source_policy
placeholder_policy
writing_rules
conflict_rules
```

每章计划：

```text
chapter_index
title
chapter_outline
content_points
main_file_ids
priority_section_ids
definition_targets
example_targets
formula_targets
pitfall_targets
retrieval_queries
allowed_web_queries
example_ratio
explanation_depth
min_word_count
target_word_count
placeholder_requests
```

### 模型和工具

- `primary` 模型
- 复杂课程可用 `reason` 做全局冲突检查

### 编排建议

这是单点全局节点，不建议按章分开生成。

它的产物是后续所有章节生成的执行合同。

## 9. Node 2：章节生成

### 做什么

根据每章的详细计划、对应材料、公共生成规则，生成章节正文。

章节生成过程中允许继续检索和补充内容。

### 输入

- `chapter_generation_plan`
- 本章 `file_summaries`
- 本章优先 sections
- 本章本地检索结果
- 本章外部补充结果
- global writing rules

### 输出

`chapter_drafts`

每章至少包含：

```text
markdown
chapter_summary_draft
used_sources
evidence_notes
placeholder_requests
generation_notes
quality_signals
```

### 模型和工具

- `reason`：系统课、复杂推导、复杂章节
- `primary`：速成课、结构明确章节
- 本地检索
- 外部检索
- web reader
- context compression

### 编排建议

按章并行。

每章内部建议拆成三个小步骤：

```text
2.1 章节材料补强
2.2 概念、定义、结论生成
2.3 例题、易错点、小结生成
```

### 2.1 章节材料补强

先根据本章计划检索：

- 本地 section
- 相关已发布知识文档
- 必要的外部资料

然后压缩成本章 `chapter_context_pack`。

### 2.2 概念、定义、结论生成

负责写：

- 概念解释
- 定义
- 公式或结论
- 方法步骤
- 适用条件

这部分要求稳，不要编造。

### 2.3 例题、易错点、小结生成

负责写：

- 例子
- 例题
- 题型步骤
- 易错点
- 本章小结
- 后续增强标识符

例题优先来自用户资料。如果资料没有，再用外部检索或模型生成，但要标记来源类型。

## 10. 章节增强标识符

章节生成时可以留下标识符，让后续增强节点处理。

建议先统一成 HTML comment，避免影响 Markdown 展示：

```text
<!-- ATM_ENHANCE:MERMAID id="ch01_m01" hint="本章概念关系图" -->
<!-- ATM_ENHANCE:IMAGE id="ch01_i01" hint="行列式几何意义示意图" -->
<!-- ATM_ENHANCE:INTERACTIVE id="ch01_x01" hint="公式条件自检卡" -->
<!-- ATM_ENHANCE:EXAMPLE id="ch01_e01" hint="补一个中等难度例题" -->
<!-- ATM_ENHANCE:CHECK id="ch01_c01" hint="检查定义是否覆盖 required elements" -->
```

标识符至少要包含：

```text
kind
id
hint
chapter_index
```

后续 `enhance_chapters` 只处理这些标识符，不重新发明整章结构。

## 11. Node 3：章节生成增强

### 做什么

根据章节里的增强标识符，回头增强章节内容，并统一样式，生成章节摘要。

### 输入

- `chapter_drafts`
- `placeholder_requests`
- `chapter_generation_plan`
- global writing rules

### 输出

`enhanced_chapter_drafts`

每章至少包含：

```text
markdown
chapter_summary
assets
practice_seeds
style_warnings
enhance_actions
```

### 模型和工具

- `primary` 模型
- Mermaid 生成
- 图片建议或图片生成
- interactive block 生成
- markdown style checker
- summary generator

### 编排建议

按章并行。

失败时保留原章正文，记录 `enhance_failed`，不要拖垮整轮。

## 12. Node 4：合并检查

### 做什么

合并所有章节后，全局检查整本文档是否需要回改。

### 输入

- `chapter_generation_plan`
- `enhanced_chapter_drafts`
- `chapter_summaries`
- global writing rules

### 输出

`merged_markdown`

`merge_review_report`

可选：

```text
revision_tasks
```

### 检查内容

至少检查：

- 章节是否齐全
- 章节标题和正文是否一致
- required elements 是否覆盖
- 章节之间是否重复
- 章节之间是否断裂
- sprint/systematic 风格是否一致
- 文档是否过长或过短
- 例题是否太少
- 摘要是否能代表章节内容

### revision_tasks

如果发现问题，输出回改任务：

```text
revision_tasks:
  - chapter_index
    target_node: generate_chapters / enhance_chapters
    reason
    instruction
    priority
```

第一版可以不真的回路执行，只把报告写入 manifest。

第二版再支持最多一轮回改：

```text
merge_review
  -> selected revision_tasks
  -> regenerate/enhance selected chapters
  -> merge_review again
```

## 13. Node 5：发布输出

### 做什么

把最终结果落盘，并提供前端展示需要的完整文档。

### 输入

- `merged_markdown`
- `enhanced_chapter_drafts`
- `merge_review_report`
- `asset_manifest`
- `practice_manifest`

### 输出

- 分章节 Markdown
- 合并 Markdown
- 展示用 Markdown
- manifest
- `KnowledgeDoc` DB 记录

### 发布要求

发布时同时保留：

```text
章节级产物
整本展示产物
构建 manifest
构建状态
```

因为后续系统既要整本展示，也要按章引用、问答、练习和 profile 更新。

## 14. 推荐状态模型

先不要求一次全做，但新增字段建议按这些模型靠拢。

### `DocGenIntentProfile`

```text
document_style
depth_level
primary_need
chapter_style_hints
example_preference
definition_depth
avoid_list
```

### `FileMaterialSummary`

```text
file_id
filename
summary
concepts
definitions
formulas
examples
chapter_affinity
high_value_sections
noise_sections
```

### `EnhancedChapterOutline`

```text
chapter_index
title
outline
content_points
concept_targets
definition_targets
example_targets
gap_notes
```

### `ChapterGenerationPlan`

```text
global_plan
chapters[]
```

### `ChapterDraft`

```text
chapter_index
markdown
chapter_summary_draft
used_sources
placeholder_requests
quality_signals
```

### `MergeReviewReport`

```text
passed
issues
revision_tasks
coverage_summary
style_summary
```

## 15. 失败策略

必须按“局部失败不拖垮整轮”设计。

### 必须有的降级

1. 文件摘要失败：回退到规则摘要和 section preview。
2. 大纲增强失败：回退到 confirmed plan 原始章节。
3. 意图识别失败：回退到 confirmed plan 的模式和默认文档风格。
4. 单章生成失败：记录失败，其他章节继续。
5. 章节增强失败：保留原稿。
6. 合并检查失败：至少输出已完成章节拼接稿。
7. 练习生成失败：回退到规则练习。

### 才应该整轮失败的情况

- confirmed plan 无效。
- 所有章节都生成失败。
- 最终发布失败且 staging 也没保住。

## 16. 和当前实现的对应关系

当前实现：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> generate_chapters
  -> enhance_chapters
  -> merge_review
  -> publish_document
```

目标流程映射：

| 目标阶段 | 当前对应 | 状态 |
| --- | --- | --- |
| `load_context` | `load_context` | 已落地 |
| `prepare_context` | `prepare_parallel_inputs` | 已落地，内部并行执行 0A/0B/0C |
| `merge_and_dispatch` | `confirm_and_dispatch` | 已落地，产出 `ChapterGenerationPlan` |
| `generate_draft` | `generate_chapters` | 已落地，章节 fan-out |
| `enhance` | `enhance_chapters` | 已落地，fan-in 后内部并发增强；后续可改 Send x N |
| `review_content` | `generate_chapters` 内部 critic/rewrite | 待移到 enhance 后并拆成独立节点 |
| `merge_review` | `merge_review` | 已落地，第一版只产出 warning/report |
| `finalize_titles` | 分散在 chapter plan / merge / publish 中 | 待补独立标题收口节点 |
| `publish_document` | `publish_document` | 已扩展结构化 manifest |

## 17. 最小落地顺序

建议按这个顺序做，不要一次大改。

### Phase 1：准备计划层

```text
1. 新增 FileMaterialSummary 生成逻辑
2. 新增 DocGenIntentProfile
3. 新增 EnhancedChapterOutline
4. 新增 prepare_parallel_inputs 节点
5. 新增 confirm_and_dispatch 节点生成 ChapterGenerationPlan
```

### Phase 2：增强章节生成

```text
1. generate_chapters 消费更细的章节计划
2. writer prompt 区分概念/定义、例题、易错点、小结
3. 统一 ATM_ENHANCE 标识符
4. 章节输出 chapter_summary_draft
```

### Phase 3：章节增强独立化

```text
1. enhance_chapters 按章处理
2. 生成 chapter_summary
3. 生成 asset_manifest
4. 生成 practice_manifest，并在每章追加本章自检
```

### Phase 4：章节复核独立化

```text
1. 从 generate_chapters 中移出 critic/rewrite
2. 在 enhance_chapters 后新增 review_content
3. 复用 critique_chapter / maybe_rewrite_chapter，但只做 bounded patch
4. 输出 ChapterReviewReport
5. review 失败时保留增强稿和 warning
```

### Phase 5：合并检查、标题收口和回改

```text
1. 新增 merge_review
2. 输出 merge_review_report
3. 新增 finalize_titles，只做标题收口，不推翻 confirmed plan
4. 第一版只记录 revision_tasks
5. 第二版支持最多一轮选中章节回改
```

### Phase 6：产物闭环

```text
1. manifest 写入 chapter_generation_plan
2. manifest 写入 chapter_summaries
3. manifest 写入 merge_review_report
4. manifest 写入 asset_manifest / practice_manifest
5. 后续接 Examine / Interact / Profile
```

## 18. 近期不要做什么

先不要做：

- 不把 DocGen 改成完整多 Agent 动态队列。
- 不让 DocGen 自动推翻 confirmed plan。
- 不一上来做递归 deep research。
- 不恢复 `app/teaching` 旧层。
- 不新建第二套 search/tool registry。
- 不把所有原文一次性塞进 writer prompt。

继续遵守：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

新能力优先复用：

- `app.shared.infra.search`
- `app.shared.infra.facade.research`
- `app.shared.infra.workflow`
- `digest/common`

## 19. 一句话收束

DocGen 的下一步不是更会“写”，而是更会“组织生成”：

```text
先把大纲、意图、文件材料统一成章节生成计划，
再逐章深度生成，
再按标识符增强，
最后全局检查和必要回改，
最终发布分章节和整本两套产物。
```
