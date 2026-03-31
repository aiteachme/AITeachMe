TODO 一定要有检索的功能，用户要知道自己想学什么f
TODO 对，检索更应该放在ingest模块 摄取模块包括网络检索、知识库检索以及上传内容的解析


# 05. Digest 引擎总控设计

## 1. 文档定位

本篇是 Digest 的总控文档，只负责讲三件事：

- unified digest 的顶层编排方式
- 知识文档 lane、知识图谱 lane、curriculum lane 如何协同
- 在质量、速度、成本之间如何做分层与门控

本篇不再承担“把知识文档怎么写、知识图谱怎么建、课程树怎么讲透”的全部细节。更细的内容拆到：

- [05a_digest_knowledge_document.md](./05a_digest_knowledge_document.md)
- [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)

Digest 的目标也不再是“把材料总结一下”，而是把 ingest 已经产出的原始资料，重组为一个稳定可发布的学习资产包：

- 面向用户的知识文档包
- 面向系统的知识图谱快照
- 面向教学组织的 curriculum 信号与版本

---

## 2. 当前 Unified Digest 的问题与拆分原则

当前 `digest` 在工程上已经收口成 unified build，但设计上仍然有几个明显问题：

### 2.1 当前主要问题

- `05_digest_engine.md` 同时描述知识文档、知识图谱、curriculum、发布逻辑，导致单篇文档信息密度过高，读者很难快速定位职责边界。
- 当前 unified consistency 主要校验 coverage gap、taxonomy drift 等“有没有覆盖到”，但还没有把“教学顺序对不对、章节粒度合不合理、例题和易错点够不够”纳入正式质量门控。
- 当前 docs lane 和 kg lane 的共享契约仍然偏薄，尤其 `TopicAnchorSnapshot` 只能给出主题名、类型、置信度、chunk 映射，无法真正支撑高质量讲义规划。
- 当前 build 主链路还是在“先生成文档初稿，再让 curriculum 对齐”，但未来目标应该是“知识文档、图谱、课程结构围绕同一份 blueprint 协同”。

### 2.2 本次文档拆分原则

- 本篇只讲 unified digest 顶层真相，不重复细讲 05a 和 05b 的内部对象。
- 任何状态对象、质量门控、发布语义，都必须先在总控文档中说明其全局角色，再由 05a / 05b 分别展开。
- 未来如果 digest 再增加新的处理模式，优先扩展统一编排和对象契约，不再把新逻辑直接塞回单个 lane 的 prompt 或 fallback 模板。

---

## 3. 顶层编排总览

未来目标态的 unified digest 不再只是：

`shared prepare -> doc/kg parallel -> consistency -> repair -> curriculum -> rebuild docs -> publish`

而是要升级成三层机制：

1. `Fast pass`
2. `Deep pass`
3. `Repair pass`

### 3.1 Fast Pass

目标是用规则、轻量模型和并发 I/O 快速完成基础结构化，不在这个阶段追求最终讲义质量。

负责内容：

- 原始材料画像
- section / primitive 级切分
- 图片、公式、表格、题目块定位
- 粗粒度 topic clustering
- 粗粒度依赖识别
- 初步 curriculum 信号提取

### 3.2 Deep Pass

目标是只把昂贵的大模型预算花在真正需要智能重组的地方。

负责内容：

- topic cluster 命名与归并
- document blueprint 规划
- chapter blueprint 规划
- 图谱歧义点 resolve
- 章节讲义写作
- 教学质量审校

### 3.3 Repair Pass

目标是 bounded repair，而不是出现问题就全量重跑。

负责内容：

- 修复失败章节
- 修复高风险 cluster
- 修复关键 coverage 缺口
- 修复 graph/docs 的结构不一致 

---

## 4. Shared Prepare 设计

Shared Prepare 仍然只执行一次，但未来职责要比当前更强。

### 4.1 输入

- `raw_file.markdown_path`
- `raw_file.asset_dir`
- ingest 已产出的规范化 markdown 与资源目录

### 4.2 当前已存在的核心产物

- `SourcePacket`
- `SectionPacket`
- `ChunkIdentityMap`
- `FastTopicHints`
- `AssetRegistry`

### 4.3 目标态新增产物

- `MaterialProfile`
- `PrimitiveIndex`
- `SectionFeatureMap`
- `SourceReliabilitySummary`

### 4.4 Shared Prepare 的职责升级

当前 `prepare_shared_inputs()` 只负责：

- 读取 markdown
- 规范化文本
- 切 section
- 提取 fast hints
- 识别 subject profile

未来它必须额外明确：

- 哪些 section 是概念密集型，哪些是题目密集型
- 哪些 section 更像定义、定理、方法、例题、警告、程序化说明
- 哪些 source 重复度高、可信度低、OCR 噪声高
- 哪些 chunk 适合成为章节主轴，哪些只适合做证据补充
- 当前学科/子学科是什么，材料更像教材、题单还是讲义
- 当前更适合走 `sprint` 还是 `systematic`，以及这个判断来自哪些证据

### 4.5 设计约束

- Shared Prepare 仍然不承担最终讲义编写。
- Shared Prepare 输出的是“可复用、可缓存、可供多 lane 消费的材料画像”。
- Shared Prepare 不直接切 live，也不写任何最终知识产物。
- `subject recognition / material profiling / user prompt normalization / asset indexing` 应允许并行执行，先完成 Fast Pass，再进入 blueprint 规划。

---

## 5. Knowledge Document Lane 设计

知识文档 lane 的详细设计见 [05a_digest_knowledge_document.md](./05a_digest_knowledge_document.md)。本篇只定义它在 unified digest 中的角色。

### 5.1 目标职责

- 根据材料画像、图谱信号与模式配置，生成知识文档包
- 输出可发布的章节文档、聚合文档与 manifest
- 对用户呈现“系统课”或“速成课”两种模式
- 两种模式共用同一套 shared prepare、图谱、curriculum 与文档包骨架，不拆成两套独立 workflow

### 5.2 输入契约

- `MaterialProfile`
- `PrimitiveIndex`
- `TopicMapSnapshot`
- `CurriculumBlueprintSignal`
- `DigestModeDecision`
- `digest_mode = sprint | systematic`

### 5.3 输出契约

- `DocumentBlueprint`
- `ChapterBlueprint[]`
- `ChapterAuditReport[]`
- `DocumentPackageManifest`
- `chapter documents`
- `subchapter documents`
- `merged knowledge document`

### 5.4 设计要求

- docs lane 不能再只依赖标题归纳和 prompt 自由发挥。
- docs lane 必须以 blueprint 为核心，不允许直接从 section packet 跳到成文讲义。
- docs lane 的最终发布产物是 `document package`，不是只有一个 merged markdown。

---

## 6. Knowledge Graph Lane 设计

知识图谱 lane 的详细设计见 [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)。本篇只定义它在 unified digest 中的角色。

### 6.1 目标职责

- 产出可被知识文档、curriculum、interact、examine 共同消费的语义底座
- 维护主题、概念、方法、别名、依赖、证据之间的稳定关系
- 在增量重建时输出受影响范围，而不是只生成一份静态图

### 6.2 输入契约

- `MaterialProfile`
- `PrimitiveIndex`
- `ChunkIdentityMap`
- 可选的 `ChapterBlueprint` 先验

### 6.3 输出契约

- `TopicMapSnapshot`
- `ConceptDependencySnapshot`
- `CurriculumBlueprintSignal`
- `GraphImpactSet`

### 6.4 设计要求

- kg lane 不再只服务于图谱展示页。
- kg lane 必须显式服务于知识讲义规划、课程编排、未来 memory / skills / tools 等扩展能力。
- kg lane 的输出不能再收敛为薄弱的 `TopicAnchorSnapshot`。

---

## 7. Curriculum 生成与对 Docs 的反向约束

curriculum 仍然是 unified digest 的重要收口层，但它不应再只是图谱下游的附属产物。

### 7.1 Curriculum 的目标角色

- 把图谱中的主题与依赖关系转译成可教学组织的结构
- 为知识文档提供“哪些主题应该成为章节主轴”的稳定约束
- 为未来的 examine / profile 提供教学颗粒度一致的组织骨架

### 7.2 对 Docs 的反向约束

curriculum 未来要对知识文档提供三类约束：

- 章节主轴约束：哪些主题必须成为主章节而不是埋在小节里
- 依赖顺序约束：哪些内容必须先讲，哪些内容必须后讲
- 聚合边界约束：哪些知识点适合合并成一个单元，哪些应该拆开

### 7.3 设计原则

- curriculum 不是直接把树渲染成讲义。
- docs 也不能完全无视 curriculum。
- 最终讲义要“受 curriculum 约束，但不机械复制 curriculum 节点名”。

---

## 8. 一致性校验、质量门控与 Bounded Repair

当前 `unified/consistency.py` 主要围绕四类问题：

- `doc_over_graph_gaps`
- `graph_over_doc_gaps`
- `orphan_signals`
- `taxonomy_drifts`

这套校验对于发现明显漏项有用，但还不够。

### 8.1 目标态质量门控

未来 unified digest 需要正式引入：

- `DigestQualityReport`
- `RepairPlan`

并把质量门控扩展为两大类：

### 8.2 结构一致性

- docs 是否覆盖图谱主主题
- 图谱是否存在无人消费的孤立主题
- curriculum 是否与 docs 主轴严重漂移
- graph/docs 是否引用了不同 chunk 边界

### 8.3 教学质量

- 章节顺序是否满足前置依赖
- 章节粒度是否过粗或过细
- 概念、方法、例题、易错点比例是否失衡
- 公式保真是否达标
- 速成课与系统课是否遵守各自质量门槛

### 8.4 Bounded Repair 原则

- 修失败章节，不修整本书
- 修高风险 topic cluster，不重建所有 cluster
- 修 manifest 缺口，不重新生成所有章节资源
- repair 必须有预算上限，避免无限循环

---

## 9. 速度、成本与质量的分层策略

Digest 未来必须正面支持“上千页资料”的处理，而不是默认材料量永远较小。

### 9.1 速度优先策略

- 大规模文本先做层级压缩，不把全量原文直接送入同一个大 prompt
- 先在 primitive / block / cluster 层完成大部分归并
- 只把高价值节点送进 Deep Pass

### 9.2 成本优先策略

- 轻量结构化阶段优先规则和便宜模型
- 大模型只做命名、重组、规划、审校
- repair 优先局部重跑

### 9.3 质量优先策略

- 系统课模式优先保障依赖链、概念完整性和推导逻辑
- 速成课模式优先保障题型归纳、易错点、复习抓手和压缩效率
- 两种模式共享底层材料画像、图谱、curriculum 与发布结构，只在 chapter blueprint、提示词深度、证据预算和审校标准上做差异化

---

## 10. 发布语义、失败恢复与运行指标

### 10.1 发布语义

未来统一发布语义保持如下约束：

- docs、graph、curriculum 共用同一 `build_session_id`
- 任一核心产物不达标，则整体不切 live
- build 中间态只写 staging
- 最终只发布同一批次一致的知识文档包、图谱快照和 curriculum 版本

### 10.2 文档包发布形态

知识文档最终发布为：

- `chapter documents`
- `subchapter documents`
- `merged knowledge document`
- `manifest`

重建规则：

- 每次正式重建都生成新的文档版本
- 当前版本切到 `is_current = true`
- 老版本不直接删除，只标记为 superseded

`manifest` 至少包含：

- `mode`
- `chapter order`
- `chapter type`
- `source coverage`
- `graph/topic references`
- `curriculum alignment`

### 10.3 失败恢复

- graph 失败时，不发布 docs 半成品
- docs 失败时，不发布 graph-only 的用户态知识文档
- curriculum 失败时，本次 unified build 视为未完成
- bounded repair 失败时，保留旧 live，不覆盖发布

### 10.4 运行指标

Digest 后续需要监控的运行指标包括：

- source 数量、page 数、primitive 数
- cluster 数、resolved topic 数
- chapter 数、chapter audit 失败率
- graph/docs consistency gap 数
- 单次 build 总耗时、Deep Pass 耗时、Repair Pass 耗时

---

## 11. 实施顺序与验收标准

本轮只改设计文档，不改代码。后续实现建议按以下顺序推进：

1. 先重写 docs lane 设计与对象契约
2. 再升级 kg lane 输出契约
3. 然后重写 unified consistency 和 repair 语义
4. 最后再改前端 digest 模式选择和文档包消费

### 11.1 文档层验收标准

- 读者可以只看本篇，就理解 unified digest 的总控边界
- 读者可以顺着本篇跳到 05a / 05b，不再被单文档信息堆叠淹没
- 本篇明确规定了 `digest_mode`、`document package`、`TopicMapSnapshot` 等核心目标对象
- 本篇明确规定了 Fast Pass / Deep Pass / Repair Pass 三层机制

### 11.2 后续实现层验收标准

- 前端能选择 `sprint | systematic`
- 知识文档以文档包发布，而不只是一个 merged markdown
- docs lane 与 kg lane 通过 richer contract 协同，而不是只靠 `TopicAnchorSnapshot`
- unified quality gate 同时覆盖一致性与教学质量
## 11. Runtime Alignment Update (2026-03-30)

This update records what is already wired into the current implementation, even if older sections below still describe the aspirational target state.

### Shared prepare

- `prepare_shared_inputs()` now emits both `material_profile` and `digest_mode_decision`.
- Docs, KG, and curriculum lanes consume the same material-type judgement instead of repeating separate guesses later in the pipeline.

### Fast path for exam-like materials

- Question-dense or exam-paper-like inputs can now skip the heaviest KG extraction path for many chunks.
- The fast path uses existing signals such as `question_block_count`, `exercise_density`, `content_type=exam_paper`, and `digest_mode_decision.mode`.
- The design rule is: heavy LLM calls should be reserved for naming, planning, resolve ambiguity, and pedagogical synthesis, not for every obvious question block.

### Unified build lifecycle

The runtime now writes explicit stages instead of relying on vague completion logs:

1. `accepted` / `build_accepted`
2. `running` / `prepare_shared`
3. `running` / `doc_lane_staged`
4. `running` / `graph_ready`
5. `running` / `curriculum_deriving`
6. `publishing`
7. `completed` / `failed` / `cancelled`

### Throughput-oriented refactors already aligned with this document

- KG mutation persistence is now batched instead of committing every single node, edge, alias, or evidence write.
- Curriculum unit naming is no longer strictly serial; it uses bounded concurrency and a lighter task profile.
- Theme-tree construction now preloads unit and evidence context to avoid membership-level N+1 lookups.

### Background task ownership

- API-triggered long workflows are now owned by an application-level background-task registry.
- Shutdown sends cancellation to tracked tasks and waits briefly for cleanup.
- Digest fan-out points are expected to propagate `CancelledError` instead of silently leaving detached subtasks alive.

## 2026-03-31 Observability Addendum

The digest runtime now treats timing and token observability as a shared cross-lane contract rather than ad-hoc logging inside each workflow.

- Every digest build is scoped by `build_session_id`, and LLM calls inherit `subject`, `workflow`, `lane`, and `node` automatically from runtime context.
- Every lane must emit exactly one summary log on completion and one partial summary on runtime failure. The summary must include `status`, `error_message`, `workflow_elapsed_ms`, per-step elapsed times, token totals, model/task-type mix, and Top-K slow items.
- Unified digest must aggregate lane-level timing and token totals and publish a single `unified_digest_timing_summary` payload that can be used for regression comparisons.
- New digest lanes should plug into the common helpers in `backend/app/workflows/digest/observability.py` instead of inventing a lane-specific logging format.
- Runtime observability is token-based for now. Currency conversion is intentionally deferred until a stable pricing table is introduced.
