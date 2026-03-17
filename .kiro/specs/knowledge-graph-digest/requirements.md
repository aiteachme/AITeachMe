# 需求文档：知识图谱增量构建 + 多视图课程结构派生

## 简介

将现有 Digest 引擎从"批次构建 DocSet"模式重构为"知识图谱型增量构建 + 多视图课程结构派生"模式。

核心架构分三层：
- **底层 Knowledge Graph**：知识以图谱（节点 + 边 + 证据）为真相源，严格增量更新
- **中层 Teaching Unit**：从知识节点通过 graph-aware 聚类生成教学单元（最小可讲授单位，leaf-only），作为组织层的基本粒度。TeachingUnit 不形成自身层级树，上层 module/chapter 结构完全由 ThemeTreeNode 负责
- **上层 Curriculum Views**：从教学单元派生三种视图——主题树（Theme Tree）、先修 DAG（Prerequisite DAG）、线性大纲（Linear Syllabus）

每次上传新文档后自动增量更新学科知识图谱，再局部更新教学单元和课程视图。Anchor 从"硬分类目标"降级为"软约束骨架"，为主题树的 module/chapter 层级提供命名、排序、对齐和稳定约束。

本需求聚焦 MVP 范围：
- 节点类型：Topic / Concept / Definition / Method / Example
- 边类型：belongs_to_topic / prerequisite_of / defined_by / illustrated_by / part_of
- MVP-1：图谱增量 + Teaching Unit + Theme Tree + Prerequisite DAG
- MVP-2（后续）：Linear Syllabus + 层次聚类自动发现 + LLM curriculum structuring

## 术语表

- **Knowledge_Graph**：学科知识图谱，由 KnowledgeNode 和 KnowledgeEdge 组成的有向图，是系统的真相源
- **KnowledgeNode**：知识图谱中的节点实体，表示一个知识单元
- **KnowledgeEdge**：知识图谱中的有向边，表示两个知识节点之间的关系
- **KnowledgeRevision**：知识节点的版本化修订记录
- **EdgeRevision**：知识边的版本化修订记录
- **EvidenceLink**：证据链接，将知识节点或边追溯到源文档的具体 chunk
- **KnowledgeAlias**：知识节点的别名记录，独立表支持高效索引
- **Teaching_Unit**：教学单元（leaf-only），一组紧密相关的知识节点组成的最小可讲授单位（如"导数定义与几何意义"包含 Concept:导数 + Definition:导数定义 + Example:切线斜率例题 + Method:用极限求导）。TeachingUnit 不形成自身层级树，上层 module/chapter 结构完全由 ThemeTreeNode 负责
- **TeachingUnitRevision**：教学单元的版本化修订记录
- **TeachingUnitMembership**：知识节点在教学单元中的归属关系
- **Theme_Tree**：主题树，用于浏览与目录导航，回答"这些内容主题上怎么分组"
- **ThemeTreeVersion**：主题树的版本化快照
- **ThemeTreeNode**：主题树中的节点
- **UnitTreeMembership**：教学单元在主题树中的归属关系
- **Prerequisite_DAG**：先修有向无环图，表达教学依赖关系，回答"学 B 之前要先会什么"
- **PrereqDagVersion**：先修 DAG 的版本化快照
- **UnitDependency**：教学单元之间的先修依赖边
- **Linear_Syllabus**：线性教学大纲，有序的章节结构，回答"课按什么顺序讲"（MVP-2）
- **TaxonomyAnchor**：分类锚点，作为软约束骨架为聚类结果提供命名、排序和稳定约束
- **CandidateNode**：从文档 chunk 中抽取的候选知识节点
- **CandidateEdge**：从文档 chunk 中抽取的候选知识边
- **Entity_Resolution**：实体对齐，将候选节点与已有图谱节点匹配的过程
- **Relation_Resolution**：关系对齐，将候选边与已有图谱边匹配的过程
- **GraphDigestJob**：图谱增量构建任务
- **CurriculumDeriveJob**：课程结构派生任务（替代原 TreeDeriveJob），产出 Teaching Unit + Theme Tree + Prerequisite DAG
- **CurriculumSnapshot**：课程视图一致性快照，明确记录当前课程结构 = 哪个 tree version + 哪个 dag version 的组合，解决部分派生成功时版本不一致问题
- **Impact_Set**：影响集，增量构建中受变更影响的对象集合
- **Ingest_Engine**：现有的文档摄入引擎
- **DocumentChunk**：文档切块，Ingest_Engine 产出的文本片段
- **Interact_Engine**：现有的交互辅导引擎，依赖 chunk + embedding 向量检索

## 需求

### 需求 1：知识图谱数据模型

**用户故事：** 作为系统开发者，我希望有一套版本化、可追溯的知识图谱数据模型，以便在 SQLite 中持久化学科知识节点、边、修订和证据。

#### 验收标准

1. THE Digest_Engine SHALL 使用 SQLModel 定义 KnowledgeNode 表，包含 id、subject、node_type（枚举：Topic / Concept / Definition / Method / Example）、canonical_name、normalized_name、status（枚举：active / deprecated / merged / pending）、confidence、current_revision_id、merged_into_node_id（自引用外键，合并谱系追踪）、created_at、updated_at 字段。Node 表不存 summary/body，内容完全从 current_revision_id 指向的 KnowledgeRevision 读取
2. THE Digest_Engine SHALL 使用 SQLModel 定义 KnowledgeAlias 表，包含 id、node_id、alias、normalized_alias、language、source（llm / manual / rule）、confidence、is_primary、status、created_at 字段，替代 aliases_json 以支持高效索引
3. THE Digest_Engine SHALL 使用 SQLModel 定义 KnowledgeEdge 表，包含 id、subject、source_node_id、target_node_id、edge_type（枚举：belongs_to_topic / prerequisite_of / defined_by / illustrated_by / part_of）、weight、confidence、status（枚举：active / deprecated / pending）、current_revision_id、created_at、updated_at 字段
4. THE Digest_Engine SHALL 使用 SQLModel 定义 KnowledgeRevision 表，包含 id、node_id、revision_no、title、summary、body、revision_reason（枚举：new_evidence / merge / split / human_edit / conflict_resolution）、digest_job_id、is_current、created_at 字段
5. THE Digest_Engine SHALL 使用 SQLModel 定义 EdgeRevision 表，包含 id、edge_id、revision_no、description、weight、confidence、revision_reason、digest_job_id、is_current、created_at 字段
6. THE Digest_Engine SHALL 使用 SQLModel 定义 EvidenceLink 表，包含 id、subject、entity_type（node / edge）、entity_id、entity_revision_id、document_id、chunk_id、quote_text、source_span_start、source_span_end、evidence_role（枚举：supports / elaborates / contradicts / exemplifies / taxonomy_hint）、extraction_method（llm / manual / rule）、field_scope（name / summary / body / edge_description / taxonomy_hint）、confidence、is_active、created_at 字段
7. WHEN 创建或更新 KnowledgeNode 时，THE Digest_Engine SHALL 同时创建对应的 KnowledgeRevision 记录，并将旧修订的 is_current 设为 False
8. WHEN 创建或更新 KnowledgeEdge 时，THE Digest_Engine SHALL 同时创建对应的 EdgeRevision 记录，并将旧修订的 is_current 设为 False
9. THE Digest_Engine SHALL 对 KnowledgeNode 表设置 UniqueConstraint(subject, node_type, normalized_name)，对 KnowledgeEdge 表设置 UniqueConstraint(subject, source_node_id, target_node_id, edge_type)，对 KnowledgeAlias 表设置 UniqueConstraint(node_id, normalized_alias)

### 需求 2：教学单元数据模型

**用户故事：** 作为系统开发者，我希望有一套教学单元数据模型，将紧密相关的知识节点聚合为最小可讲授单位，作为课程组织层的基本粒度。

#### 验收标准

1. THE Digest_Engine SHALL 使用 SQLModel 定义 TeachingUnit 表，包含 id、subject、canonical_name、normalized_name、member_signature（结构签名：排序后 core node ids 的 hash，用于稳定身份定位）、status（active / deprecated / merged / pending）、confidence、current_revision_id、created_at、updated_at 字段，并设置 UniqueConstraint(subject, member_signature)。TeachingUnit 仅表示 leaf-level 最小可讲授单位，不含 cluster_level 或 parent_unit_id，上层 module/chapter 结构完全由 ThemeTreeNode 负责
2. THE Digest_Engine SHALL 使用 SQLModel 定义 TeachingUnitRevision 表，包含 id、unit_id、revision_no、title、summary、learning_objectives_json（JSON 数组格式的学习目标）、revision_reason、curriculum_job_id、is_current、created_at 字段
3. THE Digest_Engine SHALL 使用 SQLModel 定义 TeachingUnitMembership 表，包含 id、unit_id、knowledge_node_id、role（枚举：core / support / example / prerequisite_bridge）、score、created_at 字段
4. THE Digest_Engine SHALL 保证每个 active 状态的 KnowledgeNode 至多属于一个 TeachingUnit 的 core 角色。同一个 node 可以作为多个 unit 的 support / example / prerequisite_bridge，但作为 core 只能属于一个 active unit
5. WHEN 创建或更新 TeachingUnit 时，THE Digest_Engine SHALL 同时创建对应的 TeachingUnitRevision 记录

### 需求 3：主题树数据模型

**用户故事：** 作为系统开发者，我希望有一套版本化的主题树数据模型，从教学单元派生出稳定的目录树结构用于浏览导航。

#### 验收标准

1. THE Digest_Engine SHALL 使用 SQLModel 定义 TaxonomyAnchor 表，包含 id、subject、anchor_type（枚举：teacher_defined / syllabus / textbook_toc / graph_discovered / system）、title、normalized_title、parent_anchor_id、order_index、confidence、is_system、status、created_at、updated_at 字段。Anchor 作为软约束骨架，不再是硬分类目标
2. THE Digest_Engine SHALL 使用 SQLModel 定义 ThemeTreeVersion 表，包含 id、subject、version_no、status（draft / published / archived）、curriculum_job_id、created_at 字段
3. THE Digest_Engine SHALL 使用 SQLModel 定义 ThemeTreeNode 表，包含 id、tree_version_id、anchor_id（可选）、parent_tree_node_id、title、node_type（枚举：chapter / section / theme / unit_bucket / uncategorized，其中 theme 对应知识图谱中 Topic 级别的主题分组，避免与 KGNodeType.TOPIC 混淆）、order_index、summary、created_at 字段。ThemeTreeNode 负责全部层级结构（chapter → section → theme → unit_bucket），TeachingUnit 仅作为叶节点挂载到 unit_bucket 或 theme 下
4. THE Digest_Engine SHALL 使用 SQLModel 定义 UnitTreeMembership 表，包含 id、tree_version_id、tree_node_id、teaching_unit_id、membership_role（primary / secondary / cross_link）、membership_source（auto / human_fixed）、score、created_at 字段。主题树挂载的是 TeachingUnit 而非直接挂 KnowledgeNode
5. THE Digest_Engine SHALL 保证每个 TeachingUnit 在同一 ThemeTreeVersion 中至多有一个 membership_role 为 primary 的 UnitTreeMembership 记录
6. THE Digest_Engine SHALL 确保每个 subject 有且仅有一个 anchor_type="system"、title="待归类" 的系统锚点

### 需求 4：先修 DAG 数据模型

**用户故事：** 作为系统开发者，我希望有一套先修依赖图数据模型，从知识图谱的依赖边聚合出教学单元级别的先修关系。

#### 验收标准

1. THE Digest_Engine SHALL 使用 SQLModel 定义 PrereqDagVersion 表，包含 id、subject、version_no、status（draft / published / archived）、curriculum_job_id、created_at 字段
2. THE Digest_Engine SHALL 使用 SQLModel 定义 UnitDependency 表，包含 id、dag_version_id、source_unit_id（前置单元）、target_unit_id（后续单元）、dependency_type（prerequisite / corequisite）、confidence、supporting_edge_count（支撑的知识边数量）、derivation_metadata_json（派生元数据：supporting edge ids、cycle resolution 记录、confidence 聚合详情）、created_at 字段，并设置 UniqueConstraint(dag_version_id, source_unit_id, target_unit_id, dependency_type)
3. THE Digest_Engine SHALL 确保 UnitDependency 构成的图是 DAG（无环），在检测到环时通过置信度最低边断环
4. THE Digest_Engine SHALL 对 UnitDependency 执行传递约简（transitive reduction），移除可通过其他路径推导的冗余依赖边

### 需求 5：候选知识抽取

**用户故事：** 作为系统开发者，我希望 Digest_Engine 能从文档 chunk 中抽取候选知识节点和候选知识边，以便后续与已有图谱进行对齐归并。

#### 验收标准

1. WHEN Ingest_Engine 完成一篇文档的解析和切块后，THE Digest_Engine SHALL 对该文档的每个 DocumentChunk 调用 LLM 抽取候选知识节点，每个 CandidateNode 包含 name、node_type、local_summary、taxonomy_hint 和 source_chunk_id；Definition/Example 类型还需包含 parent_entity_name
2. WHEN Ingest_Engine 完成一篇文档的解析和切块后，THE Digest_Engine SHALL 对该文档的每个 DocumentChunk 调用 LLM 抽取候选知识边，每个 CandidateEdge 包含 source_name、target_name、edge_type、description 和 source_chunk_id
3. THE Digest_Engine SHALL 将 CandidateNode 的 node_type 限定为 Topic / Concept / Definition / Method / Example 五种类型
4. THE Digest_Engine SHALL 将 CandidateEdge 的 edge_type 限定为 belongs_to_topic / prerequisite_of / defined_by / illustrated_by / part_of 五种类型
5. IF LLM 调用失败或返回无法解析的结果，THEN THE Digest_Engine SHALL 记录错误日志并跳过该 chunk 的抽取，继续处理后续 chunk

### 需求 6：节点对齐（Entity Resolution）

**用户故事：** 作为系统开发者，我希望 Digest_Engine 能将候选节点与已有知识图谱中的节点进行匹配对齐，以避免重复创建知识节点。

#### 验收标准

1. WHEN 处理一个 CandidateNode 时，THE Digest_Engine SHALL 先通过 normalized_name 精确匹配已有 KnowledgeNode
2. WHEN normalized_name 精确匹配未命中时，THE Digest_Engine SHALL 通过 KnowledgeAlias 表中的 normalized_alias 进行匹配
3. WHEN 别名匹配未命中时，THE Digest_Engine SHALL 通过 embedding 相似度计算候选节点与已有同类型节点的语义相似度，相似度超过可配置阈值时视为 probable_match
4. WHEN probable_match 出现时，THE Digest_Engine SHALL 调用 LLM 判断候选节点与匹配节点是否为同一知识点，返回 EntityMatchDecision（EXACT / ALIAS / BROADER / NARROWER / RELATED_NOT_SAME / NO_MATCH / UNSURE）
5. WHEN 对齐结果为 EXACT 或 ALIAS 时，THE Digest_Engine SHALL 为已有节点追加 EvidenceLink，并在内容有实质性补充时创建新的 KnowledgeRevision
6. WHEN 对齐结果为 NO_MATCH 时，THE Digest_Engine SHALL 创建新的 KnowledgeNode 及其初始 KnowledgeRevision 和 EvidenceLink
7. THE Digest_Engine SHALL 对一级实体节点（Topic / Concept / Method）采用名称中心策略（normalized_name → alias → embedding + LLM），对二级说明对象（Definition / Example）采用父实体+内容策略（parent_entity_name + 内容语义相似度）

### 需求 7：边对齐（Relation Resolution）

**用户故事：** 作为系统开发者，我希望 Digest_Engine 能将候选边与已有知识图谱中的边进行匹配对齐，以避免重复创建知识关系。

#### 验收标准

1. WHEN 处理一个 CandidateEdge 时，THE Digest_Engine SHALL 先将 source_name 和 target_name 解析为已有或新创建的 KnowledgeNode ID
2. WHEN 已存在相同 source_node_id、target_node_id 和 edge_type 的 KnowledgeEdge 时，THE Digest_Engine SHALL 为该边追加 EvidenceLink 并重算 confidence
3. WHEN 不存在匹配的 KnowledgeEdge 时，THE Digest_Engine SHALL 创建新的 KnowledgeEdge 及其初始 EdgeRevision 和 EvidenceLink
4. IF CandidateEdge 的 source_name 或 target_name 无法解析为任何 KnowledgeNode，THEN THE Digest_Engine SHALL 记录警告日志并跳过该边
5. THE Digest_Engine SHALL 使用 confidence = f(active_evidence_count, contradicting_evidence_count) 计算边置信度，当 evidence 被标记为 inactive 时 confidence 下降

### 需求 8：增量构建任务管理

**用户故事：** 作为用户，我希望上传新文档后系统自动触发增量构建，并能查看构建进度和结果。

#### 验收标准

1. THE Digest_Engine SHALL 使用 SQLModel 定义 GraphDigestJob 表，包含 id、subject、idempotency_key（幂等键，推荐由客户端传入；若服务端生成则基于 subject + 排序后 file_ids + 文件当前 chunk parse version 计算 hash，不混入 timestamp）、status、progress、current_step、input_file_ids_json、input_chunk_count、extractor_version、nodes_added、nodes_updated、nodes_merged、edges_added、edges_updated、retry_of_job_id、error_message、created_at、updated_at 字段
2. THE Digest_Engine SHALL 使用 SQLModel 定义 CurriculumDeriveJob 表（替代原 TreeDeriveJob），包含 id、subject、graph_job_id、status、progress、current_step、units_added、units_updated、theme_tree_version_id、prereq_dag_version_id、error_message、created_at、updated_at 字段
3. THE Digest_Engine SHALL 使用 SQLModel 定义 CurriculumSnapshot 表，包含 id、subject、version_no、status（draft / published / archived）、curriculum_job_id、theme_tree_version_id（可选）、prereq_dag_version_id（可选）、syllabus_version_id（MVP-2 预留，可选）、created_at 字段。CurriculumSnapshot 明确记录当前课程结构 = 哪个 tree version + 哪个 dag version 的组合
4. WHEN 用户通过 API 触发增量构建时，THE Digest_Engine SHALL 创建 GraphDigestJob 记录并在后台异步执行；GraphDigestJob 完成后自动触发 CurriculumDeriveJob
5. WHEN CurriculumDeriveJob 完成时，THE Digest_Engine SHALL 创建 CurriculumSnapshot 记录，将本次派生的 tree version 和 dag version 组合为一致性快照，旧快照状态设为 archived
6. WHILE 任务处于 processing 状态时，THE Digest_Engine SHALL 在每个主要步骤完成后更新 progress 和 current_step
7. THE Digest_Engine SHALL 使用 subject 级构建锁防止同一学科并发构建
8. THE Digest_Engine SHALL 支持指定一组 file_ids 触发增量构建，仅处理这些文件对应的 DocumentChunk

### 需求 9：教学单元生成

**用户故事：** 作为系统开发者，我希望 Digest_Engine 能从知识图谱中通过 graph-aware 聚类生成教学单元，将紧密相关的知识节点组织为最小可讲授单位。

#### 验收标准

1. WHEN CurriculumDeriveJob 执行时，THE Digest_Engine SHALL 对 Impact Set 中受影响的知识节点及其局部子图执行 graph-aware 聚类，生成 leaf-level 教学单元
2. THE Digest_Engine SHALL 使用综合距离函数进行聚类，距离函数结合：embedding 语义距离、图关系距离（part_of / defined_by / illustrated_by 边权重）、文档结构邻近性（共现于同一 chunk/section）、类型兼容性（Concept + Definition + Example 容易聚在一起）
3. THE Digest_Engine SHALL 为每个教学单元中的知识节点分配角色：core（核心概念）、support（支撑定义/方法）、example（示例）、prerequisite_bridge（前置桥接）
4. THE Digest_Engine SHALL 对教学单元调用 LLM 生成单元名称、摘要和学习目标，创建 TeachingUnitRevision
5. WHEN 知识节点无法归入任何教学单元时（聚类距离均超过阈值），THE Digest_Engine SHALL 将其标记为孤立节点，不强行聚合
6. THE Digest_Engine SHALL 仅对 Impact Set 影响范围内的局部子图重新聚类，未受影响的教学单元保持不变

### 需求 10：主题树派生

**用户故事：** 作为用户，我希望系统能从教学单元中派生出稳定的主题树，以便按层级浏览学科知识。

#### 验收标准

1. WHEN CurriculumDeriveJob 执行教学单元生成后，THE Digest_Engine SHALL 基于 TaxonomyAnchor 和教学单元集合派生主题树，ThemeTreeNode 负责全部层级结构（chapter / section / theme / unit_bucket）
2. THE Digest_Engine SHALL 将 TaxonomyAnchor 作为软约束骨架：teacher_defined / syllabus 锚点作为高优先级约束固定骨架，textbook_toc 作为中优先级参考，graph_discovered 作为自动发现补充
3. THE Digest_Engine SHALL 将 TeachingUnit（leaf-only）挂载到主题树的 theme 或 unit_bucket 节点下，上层 chapter / section 结构完全由 ThemeTreeNode 自身的 parent-child 关系表达
4. THE Digest_Engine SHALL 为每个 TeachingUnit 计算对各 ThemeTreeNode 的 membership_score，综合考虑语义相似度、文档结构位置、邻居投票、belongs_to_topic 边传播和 taxonomy_hint
5. THE Digest_Engine SHALL 为每个 TeachingUnit 选择 membership_score 最高且超过阈值的 ThemeTreeNode 作为 primary membership
6. WHEN membership_score 最高的两个 ThemeTreeNode 分数差距小于 stability_threshold 时，THE Digest_Engine SHALL 保持该单元在上一版本树中的归属不变
7. WHEN TeachingUnit 的所有 membership_score 均低于阈值时，THE Digest_Engine SHALL 将该单元归入"待归类"池
8. WHEN membership_source 为 human_fixed 时，THE Digest_Engine SHALL 绝对优先保留人工固定归属，自动派生不覆盖
9. WHEN 主题树派生完成时，THE Digest_Engine SHALL 创建新的 ThemeTreeVersion，旧版本状态设为 archived。MVP 采用"逻辑局部重算 + 存储全量快照"的版本策略：仅对 Impact Set 影响范围内对象重新计算，但落库时生成完整新版本
10. THE Digest_Engine SHALL 使用乐观锁创建新树版本，防止并发冲突

### 需求 11：先修 DAG 派生

**用户故事：** 作为用户，我希望系统能从知识图谱中提炼出教学单元级别的先修依赖图，用于推荐学习路径和诊断前置知识缺口。

#### 验收标准

1. WHEN CurriculumDeriveJob 执行时，THE Digest_Engine SHALL 从知识图谱中的 prerequisite_of / part_of 边聚合出教学单元级别的依赖关系。defined_by 边采用保守策略：优先用于单元内聚合，仅当 Concept 与 Definition 已被分到不同 units 且满足高置信度 + 额外支持信号时才生成 unit-level dependency candidate
2. WHEN 单元 A 内多个节点通过 prerequisite_of 边指向单元 B 内多个节点时，THE Digest_Engine SHALL 聚合为 UnitDependency(source=A, target=B)，confidence 基于支撑边数量和置信度加权
3. THE Digest_Engine SHALL 对聚合后的 DAG 执行传递约简（transitive reduction），移除冗余依赖
4. THE Digest_Engine SHALL 检测并消除环路：当检测到环时，断开环中 confidence 最低的边并记录日志
5. WHEN 先修 DAG 派生完成时，THE Digest_Engine SHALL 创建新的 PrereqDagVersion，旧版本状态设为 archived。MVP 采用"逻辑局部重算 + 存储全量快照"的版本策略：仅对 Impact Set 影响范围内对象重新计算，但落库时生成完整新版本
6. THE Digest_Engine SHALL 仅对 Impact Set 影响范围内的教学单元重新计算依赖关系

### 需求 12：增量构建 API

**用户故事：** 作为前端开发者，我希望有一组 RESTful API 来触发增量构建、查询构建状态、获取知识图谱数据、教学单元数据和课程视图数据。

#### 验收标准

1. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/digest/build` 接口，接受 file_ids 列表参数，触发增量构建并返回 job_id
2. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/digest/status` 接口，返回 GraphDigestJob 和关联 CurriculumDeriveJob 的完整状态
3. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/graph/nodes` 接口，支持分页查询 KnowledgeNode 列表，支持按 node_type 过滤
4. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/graph/node` 接口，返回节点详情包含 revisions、evidence_links、related_edges 和所属 teaching_unit
5. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/units` 接口，支持分页查询 TeachingUnit 列表
6. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/units/{unit_id}` 接口，返回教学单元详情包含成员节点、学习目标和先修依赖
7. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/theme-tree/current` 接口，返回当前已发布的 ThemeTreeVersion 完整树结构，树节点下挂载的是 TeachingUnit
8. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/prereq-dag/current` 接口，返回当前已发布的 PrereqDagVersion 完整 DAG 结构
9. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/taxonomy/anchors` 接口，支持查询和管理 TaxonomyAnchor
10. THE Digest_Engine SHALL 提供 POST `/api/v1/subjects/{subject}/curriculum/current` 接口，返回当前已发布的 CurriculumSnapshot（包含 tree version + dag version 组合）

### 需求 13：向量检索兼容性

**用户故事：** 作为系统开发者，我希望重构后的 Digest_Engine 保留现有的 chunk + embedding 向量检索能力，确保 Interact_Engine 的 RAG 功能不受影响。

#### 验收标准

1. THE Digest_Engine SHALL 在增量构建过程中继续为每个 DocumentChunk 生成 embedding 并写入 chunk_embeddings 向量表
2. THE Digest_Engine SHALL 保留现有 vector_search 函数的接口签名和行为
3. THE Digest_Engine SHALL 保留现有 Document 和 DocumentChunk 表结构，新增表与现有表共存于同一学科数据库

### 需求 14：知识追溯

**用户故事：** 作为用户，我希望能查看每个知识点和教学单元的来源证据。

#### 验收标准

1. WHEN 查询 KnowledgeNode 详情时，THE Digest_Engine SHALL 返回该节点关联的所有 EvidenceLink
2. WHEN 查询 KnowledgeEdge 详情时，THE Digest_Engine SHALL 返回该边关联的所有 EvidenceLink
3. THE Digest_Engine SHALL 确保每个 active 状态的 KnowledgeNode 至少关联一条 is_active=True 的 EvidenceLink
4. THE Digest_Engine SHALL 确保每个 active 状态的 KnowledgeEdge 至少关联一条 is_active=True 的 EvidenceLink
5. WHEN 查询 TeachingUnit 详情时，THE Digest_Engine SHALL 返回该单元所有成员节点的 primary EvidenceLink 列表
