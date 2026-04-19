# DocGen 后续重构落地计划

最后更新：2026-04-19

本文档是 `FLOW_DESIGN.md` 的执行版。它基于当前代码现状，而不是旧版 `research_chapters / write_chapters / enrich_assets / append_practice` 线性流程。

当前代码基线：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> build_document_backbone
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> review_content
  -> repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

总体判断：

- 不需要推倒重写 DocGen。
- 需要把文档、回流、manifest 和 state 语义继续收口。
- 代码改动要按“小步、可运行、可回滚”的顺序推进。

## 0. 总原则

- DocGen 不推翻 `confirmed_plan`。
- Planner 负责确认级方案，DocGen 负责执行级生成。
- `enhance_chapters` 只处理表现层，不新增核心知识。
- `review_content` 只判断，不检索、不改正文。
- `repair_or_route` 是唯一修补入口。
- `merge_review` 之后只允许很小的发布级修补。
- 所有新增关键状态都要进 `lib/models.py` typed contract 和 `docgen_manifest.json`。
- 不新增第二套 search/tool registry，运行时能力继续走 `shared.infra`。

## 1. 当前基线与差距

### 1.1 已落地能力

当前已经落地：

- confirmed plan 校验和 `DocGenContext`。
- prepare 三路并行：大纲增强、意图识别、文件摘要。
- `ChapterGenerationPlanSeed` / `ChapterGenerationTaskSeed`。
- `BackboneResearchAgenda`。
- `DocumentBackbone` 及 fallback。
- 单章 RAG / web reading / context compression。
- `EvidenceLedger`。
- `ClaimLedger`。
- `ClaimEvidenceMap`。
- `ConflictReport`。
- writer 轻量 critic 和最多一次 rewrite。
- `EnhancedChapterDraft`、`AssetManifest`、`PracticeManifest`。
- `review_content` 和 `repair_or_route` MVP。
- 发布级 `docgen_manifest.json`。

### 1.2 主要差距

| 优先级 | 差距 | 当前影响 |
| --- | --- | --- |
| P0 | 文档落后代码 | 接手者容易按旧流程改错位置 |
| P1 | `repair_or_route` 没有真实闭环 | 局部 patch 可执行，但证据补强、重写和二次复核还没闭环 |
| P1 | `ReviewAction` 已驱动局部 patch，但证据补强和重写未闭环 | section patch 已可执行，evidence patch / regenerate 仍只是记录 |
| P1 | 循环下 state append 字段会重复 | 后续一旦回流，旧章节和新章节可能一起进入 manifest |
| P1 | 图片 disabled 状态不显式 | 资产降级不可追踪 |
| P2 | `final_merge_patch` 缺失 | 合并后小瑕疵没有独立收口点 |
| P2 | research budget 偏静态 | 还没充分利用覆盖度、证据缺口、章节难度 |

## 2. Phase 0：文档基线收口

状态：本次已执行。

目标：

- README 与当前 graph 对齐。
- `FLOW_DESIGN.md` 同时描述当前流程和目标缺口。
- `REFACTOR_PLAN.md` 改为从当前代码继续演进的计划。
- `DOCGEN_ARCHITECTURE_REVIEW.md` 移除旧主线误导。

涉及文件：

```text
README.md
FLOW_DESIGN.md
REFACTOR_PLAN.md
DOCGEN_ARCHITECTURE_REVIEW.md
```

验收：

- 文档中不再把已经移除的 `research_chapters / write_chapters / enrich_assets / append_practice` 当作当前主线。
- 文档中明确 `build_document_backbone`、`review_content`、`repair_or_route`、`finalize_titles` 已在当前 graph。
- 后续重构重点清楚指向 repair loop、ReviewAction、state reducer、asset manifest 和 final merge patch。

## 3. Phase 1：修正 repair 动作语义

状态：已落地基础版。

目标：

在没有引入循环前，先让 `repair_or_route` 的记录语义真实可信。

当前问题：

- patch 类动作不再被标记为 `applied`。
- `review_chapter` 对“章节偏短”使用 `record_only`，不会让 repair 层误以为需要执行表层 patch。
- `repair_or_route` 已输出基础 `repair_trace`。

建议改动：

```text
lib/models.py
lib/chapter_review.py
lib/repair.py
nodes/repair_or_route.py
```

步骤：

1. 扩展 `ReviewAction.status`：

```text
recorded / applied / skipped / downgraded
```

2. 在真正修改正文前，不把任何动作标成 `applied`。
3. 对当前 MVP 中不会执行的动作统一标 `recorded` 或 `downgraded`。
4. `repair_or_route` 输出 `repair_trace` 的最小结构：

```text
repair_trace:
  - action_id
  - action_type
  - chapter_index
  - status
  - reason
  - changed: false
```

5. `publish_document` 将 `repair_trace` 写入 `docgen_manifest.json`。

验收：

- 当前不改正文时，manifest 不会出现“已应用但正文没变”的动作。
- `unresolved_warnings` 仍保留重动作说明。
- 不改变现有 graph 形状。

## 4. Phase 2：扩展 ReviewAction 合同

状态：已落地合同字段，`surface_patch` / `section_patch` 已接入 repair 执行，证据补强和重写仍待后续阶段接入。

目标：

让复核结果能直接驱动安全修补，而不是只有一段 reason。

涉及文件：

```text
lib/models.py
lib/chapter_review.py
lib/document_consistency.py
nodes/review_content.py
lib/repair.py
```

已新增或扩展字段：

```text
ReviewAction:
  action_id
  action_type
  chapter_index
  severity
  reason
  target_anchor
  instruction
  constraints
  expected_effect
  status
```

`action_type` 已扩展为：

```text
surface_patch
section_patch
evidence_patch
regenerate_chapter
record_only
re_dispatch
rebuild_backbone
```

规则：

- 缺少关键点：优先 `section_patch`。
- 证据支撑不足：优先 `evidence_patch`，不要直接 `regenerate_chapter`。
- 章节偏短但覆盖充足：`surface_patch` 或 `record_only`。
- 会改变章节边界的问题：`record_only` 或 `re_dispatch`，不自动执行。

验收：

- 每条 action 都有可定位的 `target_anchor` 或明确章节级范围。
- repair 层不需要解析自然语言 reason 才知道要改哪里。
- manifest 读取按当前 schema 收口。

## 5. Phase 3：新增 RepairLoopState 与路由

目标：

把一次性 `review_content -> repair_or_route -> merge_review` 升级为最多两轮有限闭环。

涉及文件：

```text
graph.py
state.py
lib/models.py
nodes/review_content.py
nodes/repair_or_route.py
nodes/common.py
```

新增模型：

```text
RepairLoopState:
  repair_round_total
  chapter_patch_rounds
  chapter_regenerate_rounds
  evidence_patch_rounds
  last_review_decision
  max_rounds
```

新增 state 字段：

```text
review_decision
repair_loop_state
repair_trace
```

建议路由：

```text
review_content
  -> route_after_review
       good / publish_with_warnings -> merge_review
       needs_repair and budget left -> repair_or_route
       fail or budget exhausted -> merge_review with unresolved_warnings

repair_or_route
  -> review_content
```

第一版只支持：

- `surface_patch`
- `section_patch`
- `record_only`

暂不支持：

- 自动 `evidence_patch`
- 自动 `regenerate_chapter`

验收：

- 无 action 时不进入 repair。
- 有可处理 action 时最多回流两轮。
- 超预算后带 warning 发布，不无限循环。
- LangGraph 编译通过。

## 6. Phase 4：解决循环下章节产物替换问题

目标：

避免引入 repair loop 后，`operator.add` 字段把同一章节多个版本都累进最终 publish。

涉及文件：

```text
state.py
graph.py
nodes/repair_or_route.py
nodes/merge_review.py
nodes/publish_document.py
lib/models.py
```

当前 append 字段：

```text
chapter_drafts
enhanced_chapter_drafts
research_traces
evidence_ledgers
claim_ledgers
claim_evidence_maps
conflict_reports
asset_manifests
practice_manifests
research_sources
```

推荐方案 A：新增 active/latest 投影。

```text
active_chapter_drafts
active_enhanced_chapter_drafts
active_claim_ledgers
active_evidence_ledgers
chapter_artifact_versions
```

推荐方案 B：保留 append 历史，但每个消费节点按 `chapter_index + version` 选 latest。

第一版建议用方案 B，改动较小：

1. 每次 repair 产物写入 `artifact_version`。
2. `merge_review` 只消费每章 latest reviewed/enhanced draft。
3. `publish_document` manifest 同时保留 latest 和 history trace。

验收：

- 重修某章后，最终 Markdown 只出现该章最新版本。
- manifest 能追踪旧版本和修补来源。
- 不影响当前无 repair loop 的正常发布。

## 7. Phase 5：实现安全 section patch

状态：已落地基础版。

目标：

让 `repair_or_route` 真正能做小范围文本修补。

涉及文件：

```text
lib/repair.py
nodes/repair_or_route.py
lib/models.py
prompts/repair.py        # 如需 LLM patch
```

策略：

- `surface_patch` 优先用规则 patch，不调 LLM。
- `section_patch` 可以调用 LLM，但输入只给：
  - 目标章节 markdown
  - `target_anchor`
  - `instruction`
  - `constraints`
  - 对应 claim/evidence 摘要
- patch 后必须保留原章节标题、资产块、自检块。
- patch 后只替换目标章节，不影响其他章节。

验收：

- 标题层级、重复句、短过渡可规则修复。
- 小节缺少总结/边界提醒可 LLM 局部修复。
- patch 后回到 `review_content`。
- patch 失败降级为 `record_only`。

## 8. Phase 6：实现 evidence_patch

目标：

证据不足时只补证据和局部改写，不整章重写。

涉及文件：

```text
lib/repair.py
lib/chapter_context.py
lib/evidence.py
lib/claims.py
nodes/repair_or_route.py
```

步骤：

1. `review_chapter` 将证据不足生成 `evidence_patch`。
2. `repair_or_route` 针对目标 `claim_id` 或 `target_anchor` 生成少量查询。
3. 复用 `DocGenChapterContextRuntime` 做定向检索、打开网页、压缩上下文。
4. 更新目标章 `EvidenceLedger` 和 `ClaimEvidenceMap`。
5. 只改写相关小节。
6. 写入 `repair_trace`：

```text
query_count
read_url_count
new_evidence_ids
snippet_fallback_used
source_details
```

验收：

- 证据不足不会默认重写整章。
- 新证据进入 chapter manifest 和 docgen manifest。
- 没有可用证据时只记录 unresolved warning。

## 9. Phase 7：实现单章 regenerate

目标：

只有章节严重失败时，才重写问题章节。

涉及文件：

```text
graph.py
nodes/repair_or_route.py
nodes/generate_chapters.py
nodes/enhance_chapters.py
lib/repair.py
```

建议：

- 不直接复用整张图。
- 抽出可单章调用的 generate/enhance helper。
- regenerate 只替换目标章节的 active artifact。
- regenerate 后必须经过 `enhance_chapters` 的单章增强逻辑，再回 `review_content`。

验收：

- 单章 writer 失败或质量严重不足时能重写该章。
- 其他章节不重新生成。
- 每章最多 regenerate 一次。

## 10. Phase 8：AssetManifest 与文生图收口

状态：已落地基础版，仍需前端展示和失败重试。

目标：

图片模型未启用、图片请求被降级或跳过时，manifest 必须解释原因；图片模型启用时，DocGen 应生成图片、写入存储并回填 Markdown。

涉及文件：

```text
lib/chapter_generation.py
lib/chapter_enhancement.py
lib/assets.py
lib/models.py
nodes/enhance_chapters.py
```

已处理：

- `shared.infra.llm_support.agenerate_image` 已作为统一文生图入口。
- DocGen image 占位会生成图片、写入 `assets/docgen/...`，并回填 Markdown 图片链接。
- disabled / failed / generated 状态会进入 `AssetManifest`。

后续建议：

1. 前端基于 `AssetManifest` 做图片展示和错误解释。
2. 针对 transient failure 增加一次轻量重试或手动重跑。
3. 继续保持正文不泄露内部 image 占位符。

```text
kind: image
status: disabled
reason: image_generation_disabled
source_placeholder
```

3. 不把内部 image 占位符泄露到 Markdown。

验收：

- settings 未启用图片时，正文无内部占位符。
- manifest 有 disabled image asset 记录。
- 前端或后续任务能解释为什么没有图片。

## 11. Phase 9：final_merge_patch

目标：

新增合并后的轻量修补节点，只处理发布级小问题。

涉及文件：

```text
graph.py
state.py
nodes/final_merge_patch.py
lib/merge_review.py
lib/models.py
nodes/__init__.py
nodes/publish_document.py
```

允许修：

- 目录重复。
- 跨章过渡缺失。
- 重复摘要。
- 空 manifest 字段。
- 明显 Markdown 结构小问题。

禁止：

- 重新检索。
- 改写章节核心内容。
- 改 claim/evidence。
- 改 confirmed plan 映射。

Graph：

```text
merge_review
  -> final_merge_patch
  -> finalize_titles
```

验收：

- `final_merge_patch_report` 进入 manifest。
- `finalize_titles` 仍只执行一次。
- patch 失败不阻断发布，只记录 warning。

## 12. Phase 10：动态研究预算

目标：

让章节研究预算从“模式默认值”升级为“按覆盖度和缺口调整”。

涉及文件：

```text
lib/models.py
lib/chapter_generation.py
lib/file_summaries.py
lib/chapter_context.py
nodes/confirm_and_dispatch.py
nodes/build_document_backbone.py
nodes/generate_chapters.py
```

新增模型：

```text
ResearchBudgetDecision:
  chapter_index
  local_coverage_hint
  evidence_gap_hint
  max_research_rounds
  max_local_queries
  max_web_queries
  max_opened_urls
  max_context_chars
  reason
```

预算来源：

- `digest_mode`
- 本地资料覆盖度
- source affinity
- high confidence evidence count
- chapter difficulty / target length
- previous research_trace gap notes

验收：

- 资料覆盖充足的章节减少 web budget。
- 缺证据章节增加 targeted budget。
- budget 决策写入 `research_trace` 和 manifest。

## 13. Phase 11：发布 manifest 与跨引擎复用

目标：

让 DocGen 产物更容易被 Interact / Examine / Profile 消费。

涉及文件：

```text
nodes/publish_document.py
lib/publish.py
schemas / frontend consumers（如后续需要）
```

建议新增 manifest 分层：

```text
planner_artifacts
docgen_contracts
research_artifacts
review_artifacts
repair_artifacts
asset_artifacts
practice_artifacts
publish_artifacts
```

短期不必改前端 API，但要保证 JSON 内部结构清晰。

验收：

- Interact 可以按章节拿 evidence / claim / sources。
- Examine 可以按章节拿 practice seed / claim targets / confusion targets。
- Profile 后续可以接 practice 结果和章节掌握度。

## 14. 测试与验证

文档改动：

```text
无需运行 Python 测试。
检查 git diff 即可。
```

代码改动至少运行：

```text
conda run -n atm python -m compileall backend/app/workflows/digest/docgen
```

关键阶段额外做：

```text
graph compile smoke test
小资料 sprint 构建
小资料 systematic 构建
无本地资料 web-first fallback
LLM 失败 fallback
manifest 字段检查
```

建议优先补的稳定测试：

```text
ReviewAction validate
repair_or_route status semantics
build_document_backbone fallback
asset disabled manifest
merge_review latest chapter selection
publish docgen_manifest snapshot
```

不要为了临时 prompt 或高度变化的文档内容盲目加测试。

## 15. 推荐提交拆分

```text
docs: 同步 DocGen 当前流程文档
fix: 修正 DocGen 回流动作状态语义
feat: 扩展 DocGen ReviewAction 修补合同
feat: 增加 DocGen 有限复核回流状态
refactor: 收口 DocGen 回流下的章节产物版本
feat: 支持 DocGen 局部章节修补
feat: 支持 DocGen 定向证据补强
feat: 增加 DocGen 单章重写回流
fix: 记录 DocGen 图片资产禁用状态
feat: 增加 DocGen 合并后轻量修补节点
refactor: 增强 DocGen 动态研究预算
docs: 更新 DocGen manifest 跨引擎复用说明
```

## 16. 近期不要做

- 不做无限循环 agent。
- 不做全章节自动重写。
- 不让 DocGen 修改用户确认章节。
- 不把所有 review action 都交给 LLM 自由发挥。
- 不把 `repair_or_route` 变成第二个 writer。
- 不恢复已移除的 prompt 扩展层。
- 不新建 parallel search/tool registry。

## 17. 最小下一步建议

如果下一轮要动代码，建议先做 Phase 1 和 Phase 2：

```text
先让 review action 记录真实可信，
再让 action 合同足够驱动修补。
```

这两步风险小、收益高，也不会强迫现在立刻改 graph 循环。
