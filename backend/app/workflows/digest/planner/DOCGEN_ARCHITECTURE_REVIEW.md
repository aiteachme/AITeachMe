# DocGen 架构评估与后续重构计划

> 最后更新：2026-04-17  
> 适用范围：`backend/app/workflows/digest/docgen/`、`backend/app/workflows/digest/planner/`、`backend/app/workflows/digest/common/contracts.py`

## 1. 本文档目的

本文档记录一次针对 `digest/docgen` 的架构评估结论、关键风险、外部项目参考和后续改造顺序，供后续智能体接手时快速建立上下文。

本文档不记录不可复用的隐藏推理链，只记录可验证、可执行、可维护的工程结论。

如果本文档与当前代码冲突，优先以当前代码和 `backend/app/workflows/digest/docgen/README.md`、`backend/app/workflows/digest/docgen/FLOW_DESIGN.md` 为准。

## 2. 当前主线判断

当前知识文档生成主线已经基本正确，不建议推倒重来。

真实主线是：

```text
api/knowledge_docs.py
  -> workflows/digest/planner/sessions.py
  -> confirmed_plan
  -> workflows/digest/docgen/builds.py
  -> workflows/digest.run_docgen_workflow
  -> workflows/digest/docgen graph
```

DocGen 的职责也已经基本收口：

```text
confirmed_plan
  -> load_context
  -> research_chapters
  -> merge_research
  -> finalize_titles
  -> write_chapters
  -> merge_drafts
  -> enrich_assets
  -> append_practice
  -> publish_document
```

这个设计比“单 prompt 写全文”更稳，因为它先用 Planner 固化章节合同，再让 DocGen 按章节研究、写作、增强和发布。

## 3. 当前值得保留的设计

### 3.1 Planner 与 DocGen 分离

`planner` 负责生成可确认的构建方案，`docgen` 只消费已确认方案。这个边界是正确的。

保留理由：

- 用户确认前后状态清晰。
- DocGen 不再承担“临时想大纲”的职责。
- 构建失败时可以回溯到具体 `confirmed_plan_id`。
- 后续可以在 Planner 侧增强 research surface，而不打乱 DocGen 图结构。

关键入口：

- `backend/app/workflows/digest/planner/sessions.py`
- `backend/app/workflows/digest/docgen/builds.py`
- `backend/app/workflows/digest/docgen/__init__.py`

### 3.2 confirmed plan 合同层

`backend/app/workflows/digest/common/contracts.py` 已经把章节计划扩展为执行合同，包括：

- `DigestChapterContract`
- `DigestChapterExecutionContract`
- `DigestMediaQuota`
- `DigestPracticeQuota`
- `DigestBuildConstraints`

这层是 Planner 和 DocGen 之间最重要的稳定边界，后续改动应优先扩展合同，而不是在节点 dict 上继续隐式加字段。

### 3.3 分阶段生成而不是全文生成

当前 DocGen 已经拆成：

```text
context_pack
chapter_research
mode_outline
chapter_write
enrich_and_test
publish
```

这个方向正确。后续不应重新退回“一个 prompt 写全文”的做法。

### 3.4 本地优先、外部补充

`DocGenChapterContextRuntime` 当前已经做到：

- 本地 RAG 优先。
- 本地命中不足才启用外部 retriever。
- 外部 URL 会经过读取与压缩。
- 覆盖不足时会追加 gap queries。

这符合 AITeachMe 的产品定位：用户资料是第一优先级，联网研究是补充和校准。

## 4. 重大问题清单

下面只列值得优先处理的问题。普通样式、命名或局部 prompt 优化不在本节展开。

### P0. `finalize_titles` 缺少单章失败降级

现状：

- `finalize_titles_node.py` 中 `_resolve_material_title(...)` 会调用轻量模型生成章节标题。
- 外层使用 `asyncio.gather(...)` 并发处理全部章节。
- 任何单章标题 LLM 失败，都可能导致整批失败。

影响：

- 标题收口属于低价值增强步骤，不应该拖垮整次文档构建。
- search-only 或外部模型波动时，构建稳定性会明显下降。

建议：

```text
单章标题解析失败
  -> 记录 warning / progress event
  -> resolved_title 回退到 planner title
  -> 整体继续进入 write_chapters
```

验收：

- mock 单章 `acompletion_with_fallback` 抛异常时，最终仍能进入 `write_chapters`。
- 构建状态里能看到 fallback_used 或 title_resolution_failed_count。

### P0. 缺少可复用的 `evidence_ledger`

现状：

- research 阶段有 `source_details`、`dense_context`、`coverage_score`。
- 但没有记录“关键定义 / 公式 / 例题 / 方法分别来自哪些来源”的细粒度证据账本。

影响：

- 文档可核验性不足。
- 后续 Examine 难以基于证据生成题目。
- Interact 难以引用“这段讲义来自哪条材料”。
- KG 难以复用 DocGen 的研究结果。

建议新增章节级 `evidence_ledger`：

```json
{
  "chapter_index": 1,
  "items": [
    {
      "kind": "definition",
      "claim": "行列式是...",
      "source_url": "local://...",
      "source_title": "线性代数讲义",
      "source_span": "section_3",
      "confidence": 0.82
    }
  ]
}
```

第一阶段只写入 manifest 或 chapter metadata，不强改前端展示。

验收：

- 每章至少能产出若干 `definition / formula / method / example` 类型证据项。
- `publish_staged_knowledge_docs(...)` 能把 ledger 写入 chapter manifest。
- writer prompt 可以消费 ledger 摘要，但不强制逐句引用。

### P1. DocGen state 与章节 payload 过重

现状：

- `chapter_materials`、`title_resolved_chapter_materials`、`chapter_drafts`、`chapter_metadatas` 都是 dict。
- 很多字段在多个阶段重复复制。
- `merged_markdown` 和 `enriched_markdown` 同时保存在 state 里。

影响：

- 后续加 critic、evidence、asset、practice 后，state 会继续膨胀。
- 同名字段在不同阶段语义容易漂移。
- Debug 时很难判断字段来自哪个阶段。

建议：

先不要大拆 graph。可以分阶段引入 typed record：

```text
ChapterResearchRecord
ChapterTitleRecord
ChapterDraftRecord
ChapterPublishRecord
AssetManifest
PracticeManifest
```

第一阶段可以继续用 dict 序列化进 LangGraph state，但节点内部优先使用 Pydantic model。

验收：

- 新增字段优先进入 typed model。
- `chapter_metadatas` 只保留发布所需字段。
- research-only 字段不再无差别复制到 publish payload。

### P1. Writer 缺少真正的 critic / rewrite loop

现状：

- writer 已有标题结构修复。
- writer 已有 scaffold fallback。
- writer 已有 coverage / length repair。
- 但这些主要是格式与覆盖修补，不是内容审校。

影响：

- 章节可能结构完整，但事实稳健性和教学质量不稳定。
- systematic / sprint 的风格可能被格式修复拉平。

建议：

增加轻量 critic：

```text
write_chapter
  -> critic_chapter
      - 是否符合 digest_mode
      - 是否使用了 dense_context
      - 是否有明显编造
      - 是否缺核心 required_elements
  -> 不通过时最多 rewrite 一次
  -> 仍不通过则保留原稿并标记 quality_warning
```

验收：

- 单章最多额外 1 次 rewrite。
- 成本和时延可控。
- `quality_score` 与 `quality_warning` 能进入 lane summary。

### P1. 引用重复与引用层级不清

现状：

- `enrich_assets` 会按章追加 reference section。
- `build_merged_markdown(...)` 又会追加全局 reference block。

影响：

- 成品文档可能重复出现来源。
- 前端后续做 citation UI 时难以区分章节引用和全局引用。

建议：

先收口为一种策略：

```text
默认只保留全局 reference block。
章节级来源进入 chapter manifest / evidence_ledger。
如需章节内显示，后续由前端基于 manifest 渲染。
```

验收：

- 同一 URL 不在正文中重复出现多次 reference section。
- `include_sources=false` 时章节和全局都不追加来源块。
- `include_sources=true` 时至少全局来源完整。

### P1. Practice layer 仍是规则生成

现状：

- `append_practice_node.py` 通过规则生成“练习与自检”。
- 尚未接入 `workflows/examine/question_build`。

影响：

- 练习质量稳定但不够个性化。
- 难以体现 AITeachMe 的“诊断引擎”价值。

建议：

```text
append_practice
  -> try Examine question_build
  -> 成功：写入结构化 questions + markdown
  -> 失败：保留当前规则 fallback
```

验收：

- Examine 失败不影响 DocGen 发布。
- 题目能按 `digest_mode` 和章节证据生成。
- `practice_manifest` 记录题目来源、题型、章节归属。

## 5. 不建议现在做的大改

### 5.1 不建议重写整张 DocGen graph

当前图的阶段边界是合理的。问题主要在降级、证据、产物合同和质量闭环，不在 graph 形状。

### 5.2 不建议把 DocGen 重新并回 Planner

Planner 负责计划，DocGen 负责执行。二者合并会让确认流程、构建锁、失败恢复和前端状态都变复杂。

### 5.3 不建议优先做真实图片生成

图片生成需要 asset 存储、manifest、前端渲染、失败兜底和成本控制。当前更应该先定义 `asset_manifest`，再接真实 image generation。

### 5.4 不建议把所有来源直接塞进 writer prompt

writer 应消费压缩后的 `dense_context` 和证据摘要。直接塞全部来源会增加成本，并削弱可控性。

## 6. 外部项目参考

以下项目只作为架构参考，不作为直接迁移目标。

### 6.1 Stanford STORM

参考地址：

- https://github.com/stanford-oval/storm

可参考点：

- 先 research，再 outline，再 long-form article generation。
- 强调 citation 和来源支撑。
- 适合参考“研究后再写作”的总体节奏。

对 AITeachMe 的启发：

- DocGen 当前方向是对的。
- 需要补的是 evidence/citation 的显式账本，而不是再增加一个全能 agent。

### 6.2 LangChain Open Deep Research

参考地址：

- https://github.com/langchain-ai/open_deep_research
- https://www.langchain.com/blog/open-deep-research

可参考点：

- 流程按 `Scope -> Research -> Write` 划分。
- 多 agent 主要用于 research 阶段。
- 报告写作阶段需要统一收束，不能让并行写作无限发散。

对 AITeachMe 的启发：

- Planner 对应 Scope。
- DocGen research 对应 Research。
- `merge_drafts / enrich / publish` 对应 Write 收束。
- 后续重点应放在 research 结果的结构化收束和最终质量审校。

### 6.3 GPT Researcher

参考地址：

- https://docs.gptr.dev/docs/gpt-researcher/getting-started/introduction
- https://docs.gptr.dev/docs/gpt-researcher/context/local-docs

可参考点：

- planner 生成研究任务。
- execution agents 搜索与阅读。
- 最终 report 聚合。
- 支持 local docs 与 web hybrid。

对 AITeachMe 的启发：

- `local_first / web_first` 是正确方向。
- 需要更清楚地区分“检索候选”“实际打开阅读”“进入写作的证据包”。

### 6.4 LlamaIndex Agentic Report / Citation Workflow

参考地址：

- https://developers.llamaindex.ai/python/examples/agent/nvidia_document_research_assistant_for_blog_creation/
- https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/

可参考点：

- outline、research question、parallel research、writer、critic、iterative refinement 的分工。
- citation workflow 会把来源切成更细粒度 source nodes。

对 AITeachMe 的启发：

- 可以补 `critic / rewrite`。
- `evidence_ledger` 应尽量记录到 source span，而不是只记录 URL。

### 6.5 Microsoft GraphRAG

参考地址：

- https://microsoft.github.io/graphrag/query/overview/

可参考点：

- local search、global search、DRIFT search、question generation 面向不同查询场景。

对 AITeachMe 的启发：

- GraphRAG 更适合作为 Planner / DocGen 的上游增强能力。
- 不应把 DocGen 改造成 GraphRAG；应让 KG 的全局视角反哺章节计划和证据检索。

## 7. 推荐改造顺序

### Phase 1：稳定性与低风险质量提升

目标：不改 API，不改前端主流程，不大改 graph。

任务：

1. `finalize_titles` 单章失败 fallback。
2. 引用策略收口，避免章节和全局 reference 重复。
3. `append_practice` 保留规则 fallback，但为后续 `practice_manifest` 预留结构。
4. 给 research 输出增加最小 `evidence_ledger`，先写 manifest。

验收：

- LLM 局部失败不会拖垮整次构建。
- 发布文档来源显示不重复。
- 每章 manifest 能看到证据摘要。

### Phase 2：内容质量闭环

目标：让章节不只是“格式完整”，还要“内容可学、可核验”。

任务：

1. 增加 `critic_chapter` 或 writer 内部 critic。
2. 不通过时最多 rewrite 一次。
3. 将 `quality_warning` 写入 chapter metadata。
4. `coverage_score` 增加 `example_density / formula_presence / source_quality_score`。

验收：

- systematic 章节更像系统课。
- sprint 章节更像突击课。
- 质量不过线时有可追踪标记。

### Phase 3：产物合同收口

目标：减少 dict 漂移，给后续前端和其他引擎可消费的 manifest。

任务：

1. 引入章节级 typed record。
2. 引入 `asset_manifest`。
3. 引入 `practice_manifest`。
4. 将 research/draft/publish 字段分层，避免无差别复制。

验收：

- publish manifest 能独立描述文档、章节、证据、资产和练习。
- 后续前端无需解析 markdown 就能展示来源、资产和练习。

### Phase 4：跨引擎整合

目标：让 DocGen 产物真正进入 AITeachMe 的五大引擎闭环。

任务：

1. `append_practice` 接入 `examine/question_build`。
2. `evidence_ledger` 供 Interact 引用。
3. DocGen evidence 与 KG evidence 对齐。
4. Profile 可使用 practice 结果更新掌握度。

验收：

- 文档生成后可以自然进入练习、问答和掌握度更新。

## 8. 后续智能体接手时的阅读顺序

建议按下面顺序读：

1. `backend/app/workflows/README.md`
2. `backend/app/workflows/digest/README.md`
3. `backend/app/workflows/digest/planner/DOCGEN_ARCHITECTURE_REVIEW.md`
4. `backend/app/workflows/digest/docgen/README.md`
5. `backend/app/workflows/digest/docgen/FLOW_DESIGN.md`
6. `backend/app/workflows/digest/docgen/graph.py`
7. `backend/app/workflows/digest/docgen/state.py`
8. `backend/app/workflows/digest/docgen/nodes/*.py`
9. `backend/app/workflows/digest/docgen/lib/*.py`
10. `backend/app/workflows/digest/common/contracts.py`

## 9. 修改代码前的检查清单

改 DocGen 前先确认：

- 是否仍然必须消费 `confirmed_plan`。
- 是否会修改 `chapter_materials` 这类 `operator.add` fan-in 字段。
- 是否需要新增合同字段，而不是只在 dict 上临时加字段。
- 是否有失败降级。
- 是否会影响 `ContentStore` 写入路径。
- 是否会影响 `KnowledgeDoc` DB 记录。
- 是否会影响前端 `build_preview` 展示。
- 是否需要 Orval 重新生成。

## 10. 一句话收束

DocGen 当前不是要推倒重来，而是要补上四个闭环：

```text
稳定性闭环：局部失败不拖垮整次构建
证据闭环：每章讲了什么、依据什么可以追踪
质量闭环：写完后能审校、必要时有限重写
产物闭环：markdown 之外有 manifest 支撑前端和其他引擎
```

