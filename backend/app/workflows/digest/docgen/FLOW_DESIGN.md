# DocGen 流程设计

最后更新：2026-04-16

一句话概括：DocGen 不应该让一个 prompt 直接写全文，而是先把 confirmed plan 和资料整理成“写作任务”，再按章节检索和压缩资料，最后按 `systematic / sprint` 两种教学模式写成不同形态的知识文档。

本文档是 `digest/docgen` 的唯一流程设计说明。更细的待办不再单独散成多份文档，后续直接在这里维护。

## 1. 蜂考样本给出的模式差异

参考样本：

- `e:\QuarkDownload\01. 蜂考系统课\07 线性代数【蜂考系统课】.pdf`
- `e:\QuarkDownload\02. 蜂考突击课\03 线性代数【蜂考突击课】.pdf`

观察结果：

| 维度 | 系统课 | 突击课 |
| --- | --- | --- |
| 页数 | 约 155 页 | 约 29 页 |
| 课时 | 19 个课时，每课时后有练习 | 8 个课时，每课时后有练习 |
| 组织方式 | 按知识边界细拆：行列式概念、性质、展开、计算、应用分别成课 | 按考试模块压缩：行列式（一）（二）、矩阵、初等行变换、向量、方程组、特征值、二次型 |
| 内容目标 | 逐步建立概念、定义、性质、方法和题型 | 快速抓必考点、分值、常见题型和解题步骤 |
| 页面形态 | 细颗粒知识点 + 例题/空题 + 练习，适合跟学 | 高频考点表 + 公式/方法 + 已解例题密集排布，适合考前扫 |
| 对 DocGen 的启发 | 要保留知识依赖顺序、概念解释和章节衔接 | 要压缩成得分抓手、题型模板、易错判断和速查清单 |

因此，DocGen 的 `digest_mode` 不能只影响语气和长度，而应该影响整套编排：

```text
systematic：按知识结构细拆，重解释、重推导、重前置关系。
sprint：按考试模块压缩，重题型、重公式使用条件、重易错点、重快速复盘。
```

## 2. 推荐的 DocGen 六段流程

为了减少节点膨胀，后续设计先按 6 个概念阶段理解。当前代码仍可保持现有 LangGraph 节点，只要职责往这 6 段收敛。

```text
1. context_pack      准备上下文
2. chapter_research  逐章研究
3. mode_outline      按系统课/突击课重排章节形态
4. chapter_write     逐章写作
5. enrich_and_test   增强图文并注入练习
6. publish           发布文档
```

下面按阶段写清楚输入、输出、模型、检索和步骤。

## 3. context_pack：准备上下文

对应当前节点：

- `load_context`

输入：

- `confirmed_plan`
- `subject`
- `file_ids`
- `user_prompt`
- 用户选择的 `digest_mode`
- 已解析上传文件的 markdown / sections

输出：

- `shared_inputs`
- `chapter_assignments`
- `document_context`
- `digest_mode`
- `retrieval_profile`
- `selected_skillpacks`

模型调用：

- 默认不调用模型。
- 后续如果资料很长，可以用 `light` 模型给每份资料生成短摘要；资料短则直接使用原始 sections。

检索内容：

- 不做外部检索。
- 只读取本地已解析资料。

具体步骤：

```text
1. 校验 confirmed_plan 是否存在。
2. 调 prepare_shared_inputs 读取上传资料，生成 sections、fast_hints、subject_profile、material_profile。
3. 把 confirmed_plan.chapter_plan 转成 chapter_assignments。
4. 判断本轮是 local_first 还是 web_first。
5. 准备 document_context：用户目标、方案摘要、是否带来源、skillpack guidance。
6. 写入构建状态：planner_confirmed。
```

需要优化的点：

- 把“资料摘要 source_brief”做成显式字段，避免每个后续节点都重新理解原始资料。
- search-only 模式要在前端和 build status 里明确展示。

## 4. chapter_research：逐章研究

对应当前节点：

- `research_chapters`
- `merge_research`

输入：

- `chapter_assignments`
- `shared_inputs.section_packets`
- `document_context`
- `retrieval_profile`
- `digest_mode`

输出：

- `chapter_materials`
- 每章 `dense_context`
- 每章 `source_details`
- 每章 `coverage_score`
- 每章 `research_rounds`

模型调用：

- `reason`：生成本章子查询。
- `light`：压缩后的研究材料再提纯。
- embedding：用于 context compression。

检索内容：

```text
第一优先级：local_rag
  从用户上传资料和 subject 本地索引中检索。

第二优先级：外部 retriever
  local 命中不足时才启用。
  systematic 偏教育站、公开课、学术来源。
  sprint 偏题型、例题、易错点、考试资料。

第三步：read_urls
  对外部 URL 读取正文。

第四步：ContextCompressor
  把本地片段和网页正文压成 dense_context。
```

具体步骤：

```text
1. 每章生成 focus_text：标题 + 学习目标 + required_elements。
2. 根据 focus_text 生成 2-6 个检索 query。
3. 先跑 local_rag。
4. 如果 local_hits 不足，再跑外部 retrievers。
5. SourceCurator 对来源排序和去噪。
6. read_urls 读取外部网页正文。
7. ContextCompressor 压缩成 dense_context。
8. 检查 required_elements 覆盖度。
9. 覆盖不足时生成 gap queries，最多补 1-2 轮。
10. 输出 chapter_material。
```

需要优化的点：

- 复用 `shared.infra.search` 里已有的并发检索和 RRF 融合，减少 DocGen 内部手写串行调度。
- 增加 `evidence_ledger`，记录关键定义、公式、例题、方法分别来自哪里。
- coverage 不要只做关键词命中，要补 `example_density`、`formula_presence`、`source_quality_score`。

## 5. mode_outline：按系统课/突击课重排章节形态

对应当前节点：

- `finalize_titles`

输入：

- `chapter_materials`
- `confirmed_plan`
- `digest_mode`

输出：

- `title_resolved_chapter_materials`
- 最终章节标题
- 每章写作形态提示

模型调用：

- `light`：根据研究材料生成更准确的章节标题。
- 如果失败，直接使用 planner 标题，不应该中断整次构建。

检索内容：

- 不做新检索。
- 只使用上一阶段 research 结果。

具体步骤：

```text
1. 等所有章节研究完成。
2. 对每章 dense_context、source_titles、objective 做标题收口。
3. systematic 模式保留知识依赖顺序，标题体现概念、性质、推导、应用、边界。
4. sprint 模式压缩成考试模块，标题体现题型、公式速用、易错点、速查。
5. 给每章生成 writing_shape：
   systematic：导入 -> 定义 -> 推导/方法 -> 例子 -> 总结。
   sprint：考点表 -> 公式/方法 -> 题型步骤 -> 易错点 -> 速查。
6. 输出 title_resolved_chapter_materials。
```

需要优化的点：

- `finalize_titles` 单章失败要 fallback 到 planner title。
- 这里不应该重新发散研究，只负责“定形”：标题、顺序、写作形态。

## 6. chapter_write：逐章写作

对应当前节点：

- `write_chapters`
- `merge_drafts`

输入：

- `title_resolved_chapter_materials`
- 每章 `dense_context`
- 每章 `source_details`
- `writing_shape`
- `digest_mode`
- `tone`

输出：

- `chapter_drafts`
- `chapter_metadatas`
- 初版 `merged_markdown`

模型调用：

- `primary`：普通章节写作。
- `reason`：systematic 且涉及复杂推导时使用。
- `light`：修复标题结构。

检索内容：

- 不做新检索。
- 只使用 research 阶段给出的资料。

具体步骤：

```text
1. 构造 writer prompt。
2. 注入标题、目标、required_elements、dense_context、writing_shape。
3. systematic 按“解释为什么”来写。
4. sprint 按“考什么、怎么做、哪里错”来写。
5. 检查一级标题和二级标题。
6. 结构不合格时调用 light 修复标题结构。
7. 缺少 required_elements 时补关键点。
8. 字数不足时补复盘或理解段。
9. 根据 media_quota 插入 Mermaid / Image / Interactive 占位。
10. 清理研究笔记、内部 subject id、原始来源堆砌。
11. 合并所有章节，生成初版 merged_markdown。
```

需要优化的点：

- 增加轻量 review：章节是否符合模式、是否可学、是否有明显编造。
- 质量不过线时最多重写一次，不要无限循环。

## 7. enrich_and_test：增强图文并注入练习

对应当前节点：

- `enrich_assets`
- `append_practice`

输入：

- `chapter_metadatas`
- `merged_markdown`
- `digest_mode`
- `source_details`

输出：

- `enriched_markdown`
- `asset_summary`
- `exam_questions`
- `practice_count`

模型调用：

- `light`：生成 Mermaid。
- image model：后续生成真实图片。
- Examine question build：后续生成结构化练习。

检索内容：

- 不做外部检索。
- 后续可读取用户 Profile / 错题 / 薄弱点。

具体步骤：

```text
1. 处理 Mermaid 占位。
   失败时降级为规则 mindmap。
2. 处理图片占位。
   有图片模型则生成图片，没有则生成配图建议块。
3. 处理 Interactive 占位。
   systematic 偏公式推导展开器、概念关系卡。
   sprint 偏公式速记卡、题型流程卡、易错对比卡。
4. 标准化 LaTeX 和 Mermaid。
5. 如果 include_sources=true，追加参考来源。
6. 生成练习与自检。
   systematic：概念解释、推理链、应用迁移。
   sprint：高频题型、易错判断、速记回忆、变式训练。
7. 重新合并全文。
```

需要优化的点：

- 练习层接入 `workflows/examine/question_build`，当前规则题只做 fallback。
- 建立 `asset_manifest`，不要只把资产混在 markdown 里。

## 8. publish：发布文档

对应当前节点：

- `publish_document`

输入：

- `chapter_metadatas`
- `enriched_markdown`
- `asset_summary`
- `exam_questions`
- `requested_at`

输出：

- `doc_ids`
- `built_paths`
- `manifest`
- 正式 `merged_knowledge_base.md`

模型调用：

- 不调用模型。

检索内容：

- 不做检索。

具体步骤：

```text
1. 写入 `_build/chapter_xx.md`。
2. 写入 `_build/merged_knowledge_base.md`。
3. 写入版本归档。
4. 写入当前正式 knowledge markdowns。
5. 创建 KnowledgeDoc DB 记录。
6. 写 manifest。
7. 清理 staging。
8. 更新 build status = completed。
```

需要优化的点：

- Research material、draft、asset manifest 分阶段写 staging。
- 构建失败时保留最近可读草稿和失败阶段，方便前端展示。

## 9. 当前代码到六段流程的映射

| 六段流程 | 当前节点 |
| --- | --- |
| `context_pack` | `load_context` |
| `chapter_research` | `research_chapters`、`merge_research` |
| `mode_outline` | `finalize_titles` |
| `chapter_write` | `write_chapters`、`merge_drafts` |
| `enrich_and_test` | `enrich_assets`、`append_practice` |
| `publish` | `publish_document` |

## 10. 最小改造顺序

先不要大拆 graph，建议按这个顺序做：

```text
1. 修 docs 构建必须带 confirmed_plan_id 的前端入口。
2. 明确 systematic / sprint 在 mode_outline 和 writer prompt 中的结构差异。
3. finalize_titles 单章失败 fallback 到 planner title。
4. chapter_research 复用 shared search 的并发检索与融合。
5. 增加 evidence_ledger，但先只写入 manifest，不强改前端。
6. 增加轻量 review，不通过时最多 rewrite 一次。
7. append_practice 接 Examine，规则题保留 fallback。
8. asset_manifest 落地。
```

## 11. 一句话总结

DocGen 应该按“课程类型”生成两种不同文档：

```text
systematic：像系统课，细拆知识边界，解释概念和推导，建立完整学习路径。
sprint：像突击课，压缩为考试模块，突出分值、题型、公式使用、易错点和速查复盘。
```

所以流程上要先研究资料，再判断章节形态，最后按模式写作，而不是把同一套 Markdown 模板换个字数。

