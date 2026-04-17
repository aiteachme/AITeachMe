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

推荐目标流程：

```text
0A. 计划大纲增强
0B. 意图识别
0C. 文件摘要
1.  确认和分发
2.  章节生成
3.  章节生成增强
4.  合并检查
5.  发布输出
```

依赖关系：

```text
0A 计划大纲增强
0B 意图识别
0C 文件摘要
        -> 1 确认和分发
        -> 2 章节生成
        -> 3 章节生成增强
        -> 4 合并检查
        -> 5 发布输出
```

并行关系：

```text
阶段 0A / 0B / 0C 可以并行
阶段 2 按章并行
阶段 3 按章并行
阶段 4 是全局检查
阶段 5 是最终发布
```

## 4. 目标 Graph 形状

概念上可以理解成：

```text
load_context
  -> prepare_parallel_inputs
       ├─ enhance_plan_outline
       ├─ infer_docgen_intent
       └─ summarize_files
  -> confirm_and_dispatch
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> merge_review
  -> publish_document
```

当前实现已经按这个形状重构完成。

当前 graph：

```text
load_context
  -> prepare_parallel_inputs      # 内部并行承接 0A/0B/0C
  -> confirm_and_dispatch         # 内部确认和分发
  -> generate_chapters (Send x N)
  -> enhance_chapters             # fan-in 后内部并发增强全部章节
  -> merge_review
  -> publish_document
```

旧 `research_chapters / merge_research / finalize_titles / write_chapters / merge_drafts / enrich_assets / append_practice` 顶层节点已移除。底层可复用 runtime 仍可保留，例如章节研究、writer 和资产处理 runtime。

## 5. Node 0A：计划大纲增强

### 做什么

根据 confirmed plan 的章节大纲，结合本地资料和检索结果，把每章展开成更细的内容要点和章节小纲。

它不是重新规划课程，而是把 Planner 的粗大纲变成 DocGen 可执行的章节蓝图。

### 输入

- confirmed plan
- 用户上传文件内容
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

- 本地检索
- 外部检索
- `primary` 模型

### 编排建议

可以按章并行增强，但最后要做一次全局去重，避免两个章节争同一个主题。

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
| 0A/0B/0C | `prepare_parallel_inputs` | 已落地，内部并行执行 |
| 1. 确认和分发 | `confirm_and_dispatch` | 已落地，产出 `ChapterGenerationPlan` |
| 2. 章节生成 | `generate_chapters` | 已落地，章节 fan-out |
| 3. 章节增强 | `enhance_chapters` | 已落地，fan-in 后内部并发增强 |
| 4. 合并检查 | `merge_review` | 已落地，第一版只产出 warning/report |
| 5. 发布输出 | `publish_document` | 已扩展结构化 manifest |

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

### Phase 4：合并检查和回改

```text
1. 新增 merge_review
2. 输出 merge_review_report
3. 第一版只记录 revision_tasks
4. 第二版支持最多一轮选中章节回改
```

### Phase 5：产物闭环

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
