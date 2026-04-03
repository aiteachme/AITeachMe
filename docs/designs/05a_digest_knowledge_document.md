# 05A. Digest 知识文档设计

## 1. 文档定位

本篇专门定义 Digest 的知识文档 lane，回答两个问题：

- 为什么当前 digest 生成的知识文档效果差、像拼接摘要
- 未来怎样把多份原始资料重组成“像老师整理出来的课程讲义”或“像蜂考那样的冲刺讲义”

本篇不讨论统一编排和图谱内部实现细节，它们分别由：

- [05_digest_engine.md](./05_digest_engine.md)
- [05b_digest_knowledge_graph.md](./05b_digest_knowledge_graph.md)

来承担。

---

## 2. 当前知识文档链路的问题审计

当前 docs lane 的主链路大致是：

`load files -> cleanse -> outline_map -> outline_reduce -> draft chapter -> review chapter -> finalize_assemble`

这条链路能产出“可读文本”，但距离“好讲义”还有明显差距。

### 2.1 问题一：大纲仍然过度依赖标题与弱主题词

当前 `outline_service.py` 会大量依赖：

- markdown 标题
- 编号标题
- header path
- 弱规则 theme title 归纳
- procedural packet 兜底分类

这意味着：

- 文档结构很容易被原始 PDF / OCR 的标题质量绑死
- 跨文件相同主题难以自然归并
- 一旦原始标题写得差，生成的大纲就会显得机械而发散

### 2.2 问题二：当前 prompt 还是“根据素材写章”，不是“先重组知识”

当前 `docgen_prompts.py` 中：

- `GLOBAL_OUTLINE_PROMPT` 让模型直接从局部标题汇总出章节结构
- `WRITER_PROMPT` 让模型根据素材写出一章讲义

问题在于：

- 模型没有先明确知识主线、前置依赖、题型归并和章节原型
- 模型做的是“写作”，不是“教学重组”
- 这会直接导致成文更像美化过的总结，而不是老师整理后的讲义



TODO 对，这里首先的一个比较重要的点应该是把所有的内容看完了之后，再去详细思考标题应该如做，并且可以接下来根据标题和对应的切片内容去整理一部分文档，然后根据整理的文档再进行几次的反思流程迭代
TODO 我们运行的参数什么都可以作为一些商业化指标？试用版最开始都是试用，然后会有新模式很好的模式可以提供试用，做好试用后可以之后的体验再收费？



### 2.3 问题三：writer 的质量检查太模板化

当前 `writer_service.py` 主要检查：

- 有没有 H1
- 有没有 H2
- 有没有摘要
- 有没有标签

但几乎不检查：

- 概念顺序是否合理
- 公式是否在该出现的地方出现
- 方法有没有对应例题
- 章节有没有易错点与复习抓手
- 章节是否过粗或过细


TODO 是的，这里太严重了把，这里digest生成简直就是没啥逻辑的感觉

TODO 还有就是生成知识文档的时候可以SSE的形式展现其中的一些内容？
TODO 这里改digest文档后应该还没更新过

所以即便形式看起来像“讲义”，内容上仍可能只是摘要扩写。

### 2.4 问题四：curriculum 驱动的最终拼装仍偏机械

当前 `curriculum_book.py` 主要是：

- 从 tree node 找 teaching unit
- 从 teaching unit 找知识点和证据
- 按树结构拼成章节

它的优点是稳定，但问题也很明显：

- 更像“把树渲染成文档”
- 还不是真正按教学意图重写讲义
- 缺少“概念建立章、方法求解章、题型突破章、综合复习章”等章节原型

### 2.5 当前问题的本质

当前 docs lane 的核心问题不是模型不够强，而是流程设计层级太低：

- 先做标题归纳
- 再写章节
- 最后补结构

未来必须升级成：

- 先做材料画像
- 再做教学切分
- 再做主题聚类
- 再规划章节蓝图
- 最后按蓝图写讲义

TODO 可以，这个不错，还有就是这里的流程方向应该是可以模仿真实老师的整理流程一样？


---

## 3. 目标讲义形态与用户模式

未来知识文档不再只有一种“统一讲义”，而是要正式支持两种模式。

### 3.1 模式一：速成课 `sprint`

定位：

- 更像蜂考式冲刺讲义
- 更强调抓主线、记方法、练题型、避坑
- 面向短时间提分与快速复习

核心特征：

- 章节更短、更聚焦
- 压缩率更高
- 更强调题型归纳与易错点
- 可以牺牲部分推导细节

### 3.2 模式二：系统课 `systematic`

定位：

- 更像老师整理后的系统讲义
- 更强调概念依赖、推导链、方法体系
- 面向长期学习、建立完整理解

核心特征：

- 章节更完整
- 更强调定义、定理、方法之间的依赖
- 更重视推导、条件与边界
- 更适合反复阅读

### 3.3 共同原则

无论哪种模式，知识文档都不是：

- 原文摘要堆叠
- 图谱树节点清单
- 关键词分类页面

它必须是围绕教学目标组织的“成体系文档包”。

### 3.4 模式判定输入与优先级

`速成课 / 系统课` 不能只靠一个开关拍脑袋决定，至少要综合三类输入：

1. 用户上传文档的自动识别结果
2. `subject` 的学科名、描述与学科级画像
3. 用户在上传或构建时附带的详细提示词

建议优先级如下：

- 第一优先级：用户显式提示词
- 第二优先级：`subject.name + subject.description + subject.profile_json` 形成的稳定学科先验
- 第三优先级：上传文件识别出的材料画像与题型/公式/讲义特征

理由如下：

- 用户显式要求最直接，应该拥有最终覆盖权
- `subject` 元数据和学科级画像是稳定先验，适合作为整个 workspace 的长期默认方向
- 文件自动识别最适合做“补充判断 + 冲突校验”，不应单独决定全部风格

如果三者冲突，目标不是简单多数投票，而是生成一份 `DigestModeDecision`：

- 最终模式
- 置信度
- 判定理由
- 各输入源的贡献与冲突说明

这个决策对象既服务当前 build，也应写入最终知识文档元数据，方便后续审计与重建。

### 3.5 两种模式不是两套独立系统

`速成课` 和 `系统课` 的差异主要体现在：

- chapter blueprint 的组织方式
- prompt 的深度和表达目标
- 证据打包时的压缩强度
- 审校时的质量门槛

但它们不应该变成两套完全独立的 pipeline。两种模式应共享：

- 同一套 `MaterialProfile`
- 同一套 `ContentPrimitive / PedagogicalBlock / TopicCluster`
- 同一套 `TopicMapSnapshot / CurriculumBlueprintSignal`
- 同一套 `knowledge_document` 文档包发布结构

也就是说，模式差异应该是“同一条主流程上的参数化分支”，而不是“把大部分层都复制一遍”。

---

## 4. 知识文档内部对象模型

为了从“摘要生成”升级到“教学重组”，docs lane 需要正式引入以下对象。

### 4.1 `MaterialProfile`

描述当前资料集的整体画像：

- 学科与子学科
- 材料类型分布
- 公式密度、题目密度、图片密度
- OCR 噪声水平
- source 之间的重复度和可信度

### 4.2 `ContentPrimitive`

最小教学原子，不再只以 `SectionPacket` 为最低单位。

建议类型：

- `definition`
- `theorem`
- `formula`
- `method`
- `example`
- `exercise`
- `warning`
- `narrative`
- `procedural`
- `noise`

### 4.3 `PedagogicalBlock`

若干 primitive 的可教学组合块，用于后续聚类和章节规划。

它应该回答：

- 这一块在讲什么主题
- 这一块是概念说明、方法讲解还是例题支撑
- 这一块适合放在“系统课”还是“速成课”的什么位置

### 4.4 `TopicCluster`

跨文件、跨章节归并后的主题簇。

它不依赖写死关键词，而是基于：

- 语义相似度
- 共享公式
- 共享概念名
- 共享方法与题型
- 图谱候选信号

### 4.5 `DigestModeDecision`

描述本次知识文档应该采用哪种模式，以及为什么。

至少包含：

- `resolved_mode`
- `confidence`
- `user_prompt_evidence`
- `subject_metadata_evidence`
- `uploaded_material_evidence`
- `decision_reason`

### 4.6 `DocumentBlueprint`

整本文档包的总蓝图，定义：

- 模式：`sprint` 或 `systematic`
- 全书主线
- 章节顺序
- 章节原型分布
- 证据预算
- `package_key`
- `version_no`
- 发布形态

### 4.7 `ChapterBlueprint`

单章蓝图，定义：

- 章节标题
- 章节原型
- 章节目标
- 前置依赖
- 需要消耗的 topic cluster
- 需要覆盖的公式、方法、例题、易错点

### 4.8 `EvidenceBundle`

单章可消费的证据集合，包含：

- source sections
- primitives
- images
- formulas
- example packets
- graph-backed topic signals

### 4.9 `ChapterAuditReport`

单章审校报告，至少记录：

- coverage 是否充分
- prerequisite 是否正确
- formula fidelity 是否合格
- example / warning 是否充分
- 模式风格是否跑偏

---

## 5. 知识文档生成流程

目标态流程如下：

`source profiling -> mode decision -> pedagogical segmentation -> topic clustering -> chapter blueprint planning -> evidence packing -> chapter drafting -> pedagogical audit -> document package assembly`

### 5.1 Source Profiling

职责：

- 对材料做结构画像
- 判断材料更偏教材、课堂笔记、题单、讲义还是说明页
- 判断 OCR 噪声、重复度、页级碎片化程度
- 识别当前更接近哪一类学科与子学科
- 为模式判定准备材料证据


TODO 比如说最开始进来进来的时候可以直接每个markdown文件都先输入llm开一个线程解析，并且还有一个线程是单纯的文本输入，还有一个线程是所有内容加一起，几个llm并行思考，然后汇聚一下观点


输出：

- `MaterialProfile`

说明：

- `source profiling`、`subject` 元数据读取、用户提示词规范化、清洗前噪声扫描可以并行执行
- 这一步属于 Fast Pass，目标是尽早拿到稳定先验，而不是直接写章

### 5.2 Mode Decision

职责：

- 综合三类输入决定本次走 `sprint` 还是 `systematic`
- 记录这个判断来自哪些证据
- 把最终模式传给 chapter blueprint 规划与审校

输入：

- 上传文件自动识别结果
- `subject.name`
- `subject.description`
- 用户附带提示词

输出：

- `DigestModeDecision`

### 5.3 Pedagogical Segmentation

职责：

- 把 `SectionPacket` 进一步拆成 `ContentPrimitive`
- 识别定义、定理、公式、方法、例题、警告、噪声块

输出：

- `ContentPrimitive[]`
- `PedagogicalBlock[]`

### 5.4 Topic Clustering

职责：

- 跨 source 聚合同主题内容
- 合并不同讲法、不同章节中的同一知识点
- 拆分表面相似但教学角色不同的材料

输出：

- `TopicCluster[]`

### 5.5 Chapter Blueprint Planning

职责：

- 决定这本讲义怎么讲
- 决定哪些 cluster 做章节主轴，哪些只做支撑
- 根据 `DigestModeDecision` 决定采用速成课还是系统课模式的章节组织方式

说明：

- 这里的模式分歧是主流程里的参数化分支，不是从这里开始拆成两套独立 pipeline
- 绝大部分上游对象和下游发布结构都保持一致，只调整章节粒度、解释深度、题型比重和压缩程度

输出：

- `DocumentBlueprint`
- `ChapterBlueprint[]`

### 5.6 Evidence Packing

职责：

- 给每章分配可用证据
- 保证每章都有足够的概念、公式、方法、例题、易错点支撑

输出：

- `EvidenceBundle[]`

### 5.7 Chapter Drafting

职责：

- 按 blueprint 和 evidence bundle 写章
- 明确禁止自由漂移
- 章节写作必须服务于教学目标，而不是追求文风统一

### 5.8 Pedagogical Audit

职责：

- 检查章节是否满足模式要求
- 检查有没有漏掉前置知识
- 检查有没有只有概念没有例题、只有题目没有方法的失衡问题

输出：

- `ChapterAuditReport[]`

### 5.9 Document Package Assembly

职责：

- 产出最终知识文档包
- 组织章节文档、小章节文档、聚合文档和 manifest
- 为本次构建生成新的 `package_key / version_no`
- 把旧版本标记为非当前版本，而不是直接覆盖删除

输出：

- `chapter documents`
- `subchapter documents`
- `merged knowledge document`
- `manifest`

---

## 6. 章节蓝图与教学原型

当前 docs lane 最大的问题之一，是没有正式的章节原型。未来必须把章节类型文档化。

### 6.1 `概念建立章`

适用场景：

- 新引入的核心主题
- 需要先建立定义、边界和直觉



TODO 这里好几个必须包含，应该没必要吧！！为什么必须包含？？不同的学科的设计都不一样

必须包含：

- 核心定义
- 关键关系
- 最小必要公式
- 基础理解例子

### 6.2 `方法求解章`

适用场景：

- 已有概念基础，开始进入套路和解法

必须包含：

- 方法前提
- 解题步骤
- 关键判断点
- 典型变式

### 6.3 `题型突破章`

适用场景：

- 冲刺阶段
- 某类高频题型需要集中突破

必须包含：

- 题型识别
- 解题框架
- 高频误区
- 代表性例题

### 6.4 `综合复习章`

适用场景：

- 一个大主题的收尾
- 考前总复盘

必须包含：

- 章节主线回顾
- 常见串联关系
- 快速记忆抓手
- 高危易错点

### 6.5 模式差异

系统课：

- `概念建立章` 与 `方法求解章` 占比更高
- 更强调依赖链与推导

速成课：

- `题型突破章` 与 `综合复习章` 占比更高
- 更强调提分抓手和高频错误

---

## 7. 写作、审核、局部修复

### 7.1 写作原则

- 先服从 blueprint，再生成文案
- 先保证教学顺序，再追求语言流畅
- 允许不同章节风格略有差异，但不允许失去章节功能

### 7.2 审核原则

未来审校不再只看 H1 / H2 / 标签，而要正式检查：

- 章节目标是否达成
- 前置依赖是否满足
- 公式是否完整且未失真
- 方法是否有对应例题
- 例题后是否有易错点或总结
- 模式风格是否符合 `sprint | systematic`

### 7.3 局部修复原则

- 某章 audit 失败，只重修该章或相关 evidence bundle
- 某个 topic cluster 歧义，只重跑该 cluster 对应蓝图
- manifest 缺项时，不重写所有章节

### 7.4 失败边界

以下情况不得切 live：

- 关键章节 audit 未通过
- 核心 topic 缺失
- chapter order 与 prerequisite 冲突
- merged 文档与章节 manifest 不一致

---

## 8. 与知识图谱 / Curriculum 的协同契约

知识文档未来不能脱离图谱和 curriculum 单独工作。

### 8.1 Docs 需要从图谱获得什么

- `TopicMapSnapshot`
- `ConceptDependencySnapshot`
- topic 的代表证据
- topic 的核心公式 / 方法 / 例题线索
- 哪些 topic 适合作为章节主轴

### 8.2 Docs 需要从 Curriculum 获得什么

- 哪些主题适合合并成教学单元
- 哪些主题必须先讲
- 哪些主题只应作为从属点出现

### 8.3 Docs 反向提供什么

- `ChapterBlueprint`
- `DigestModeDecision`
- 章节覆盖范围
- 文档包 manifest
- 可供 overview / interact / examine 消费的章节索引

---

## 9. 大规模资料处理与性能预算

未来必须默认 digest 处理的不只是几十页，而可能是上千页。

### 9.1 禁止的方案

- 禁止把所有原文直接送进单个 global outline prompt （TODO，和刚才的TODO对比一下，就用户的输入也不能太长，这里对就会对用户的输入量有限制，以及可能并发啥的要有限制）
- 禁止把“整本书成文”作为一次性生成任务 
- 禁止把所有 source 当成同等可信的平铺材料

### 9.2 推荐的层级压缩策略

- `section -> primitive -> block -> cluster -> chapter blueprint -> chapter`

### 9.3 模式与成本的关系

速成课：

- 更强调压缩
- 允许更快的章节规划
- 需要更强的题型与易错点抽取

系统课：

- 更强调准确依赖
- blueprint 规划和 audit 更重
- 对大模型预算要求更高

### 9.4 缓存与重建边界

- `MaterialProfile` 可复用
- `TopicCluster` 可增量更新
- `ChapterBlueprint` 受 graph impact 驱动局部失效
- `chapter drafting` 只对受影响章节重跑

---

## 10. 质量指标与验收标准

### 10.1 核心质量指标

- 教学顺序合理性
- 章节覆盖率
- 章节重复率
- 公式保真度
- 方法与例题匹配度
- 易错点覆盖率
- 章节粒度稳定性
- 模式一致性

### 10.2 速成课额外指标

- 压缩效率
- 高频题型命中率
- 复习抓手密度
- 易错点可操作性

### 10.3 系统课额外指标

- 概念依赖完整性
- 推导链清晰度
- 条件与边界完整性
- 跨章节衔接自然度

### 10.4 文档层验收标准

- 能清楚解释当前 docs lane 为什么会产出“像摘要”的内容
- 能清楚定义从 `SectionPacket` 升级到 `ContentPrimitive / TopicCluster / ChapterBlueprint` 的必要性
- 能清楚定义 `sprint | systematic` 两种模式的差异
- 能清楚定义最终对外是 `document package`，不是单一 markdown 文件
## 12. 草稿可见性与发布语义更新（2026-03-30）

本节记录 docs lane 当前已经落地的运行时契约，并覆盖文档里那些曾暗示“用户只能在最终发布后看到 merged book”的旧描述。

### staging 与预览语义

- docs lane 现在会在当前构建的章节装配结果可用后，尽早写出一份 staging draft。
- 这份草稿通过同一个 `/api/v1/subjects/{subject}/knowledge/docs` 接口对外暴露，主要字段包括：
  - `draft_markdown`
  - `draft_updated_at`
  - `build.draft_available`
- 草稿预览被明确设计为只读能力。它用于提升可见性，不用于重新定义“官方知识文档”的判定标准。

### 正式发布仍然统一收口

- 最终 live 切换仍要求 unified digest 先后通过 graph readiness、curriculum derivation 与 publish coordination。
- 换句话说，`draft != live`。
- 对外正式生效的仍然是 `exists + markdown + updated_at` 这组字段，它代表与 curriculum 对齐后的已发布文档包。

### 与 docs lane 相关的运行时阶段

- `prepare_shared`：开始做源材料 profiling 与 mode decision
- `doc_lane_staged`：staging markdown 已可预览
- `graph_ready`：图谱结果已经可用于后续发布推进
- `curriculum_deriving`：系统正在生成 units / theme tree / prerequisite 结构
- `publishing`：正在切换 live 文档包

### Implication for docs-lane design

- The lane must optimize for “show something correct enough early” without violating the invariant that only unified publish can change the official book.
- The lane should therefore separate:
  - staging assembly for visibility
  - unified publish for truth

### Interaction with fast pass

- `MaterialProfile` and `DigestModeDecision` are now shared upstream signals, not docs-lane-only ideas.
- For question-heavy materials, the rest of the digest system may take faster structural paths so the docs lane receives cleaner, earlier signals from the overall unified run.

## 2026-03-31 Docs Lane Observability Addendum

The knowledge-document lane now owns a stable summary contract for performance review.

- `docgen_timing_summary` must be emitted for success and runtime failure.
- Required fields: `status`, `error_message`, `workflow_elapsed_ms`, `load_ms`, `cleanse_ms`, `outline_ms`, `draft_ms`, `review_ms`, `metadata_ms`, `finalize_ms`, chapter counts, and draft visibility.
- Required token fields: total tokens, tokens by model, tokens by task type, call counts by model/task type, latency totals, and light-vs-heavy model mix.
- Chapter-level slow-item reporting is limited to Top-K output so the summary stays readable while remaining actionable.
- Future doc sub-components should append data through the common summary helpers instead of extending the HTTP response contract.
