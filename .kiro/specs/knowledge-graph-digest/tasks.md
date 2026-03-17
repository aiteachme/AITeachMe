# Implementation Plan: 知识图谱增量构建 + 多视图课程结构派生

## Overview

将现有 Digest Engine 重构为"知识图谱型增量构建 + 多视图课程结构派生"模式。实现分为：数据模型与基础设施 → 数据访问层 → LLM 抽取与对齐 → 工作流状态机 → 课程派生 → 服务层与 API → 集成验证。

## Tasks

- [ ] 1. 数据模型与枚举定义
  - [ ] 1.1 在 `backend/app/models/enums.py` 中追加所有新增枚举类型
    - 追加 KGNodeType、KGEdgeType、KGNodeStatus、KGEdgeStatus、EntityMatchDecision、RevisionReason、EvidenceRole、ExtractionMethod、FieldScope、AliasStatus、UnitMemberRole、UnitStatus、AnchorType、AnchorStatus、TreeVersionStatus、ThemeTreeNodeType（使用 THEME 而非 TOPIC）、UnitTreeMembershipRole、MembershipSource、DependencyType、DigestJobStatus
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 3.1, 3.3, 4.1, 4.2, 5.3, 5.4, 6.4, 8.1, 8.2_

  - [ ] 1.2 创建 `backend/app/models/knowledge_graph.py`，定义知识图谱 SQLModel 表
    - 定义 KnowledgeNode（身份+路由+状态，不存内容）、KnowledgeAlias（独立别名表）、KnowledgeEdge、KnowledgeRevision、EdgeRevision、EvidenceLink、GraphDigestJob（含 idempotency_key）、SubjectBuildLock
    - 设置 UniqueConstraint：node(subject, node_type, normalized_name)、alias(node_id, normalized_alias)、edge(subject, source_node_id, target_node_id, edge_type)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 8.1_

  - [ ] 1.3 创建 `backend/app/models/curriculum.py`，定义课程结构 SQLModel 表
    - 定义 TeachingUnit（含 member_signature + UniqueConstraint(subject, member_signature)，leaf-only，不含 cluster_level/parent_unit_id）、TeachingUnitRevision（learning_objectives_json: str = Field(default="[]")）、TeachingUnitMembership
    - 定义 TaxonomyAnchor、ThemeTreeVersion、ThemeTreeNode（node_type 使用 ThemeTreeNodeType）、UnitTreeMembership
    - 定义 PrereqDagVersion、UnitDependency（含 UniqueConstraint + derivation_metadata_json）
    - 定义 CurriculumDeriveJob、CurriculumSnapshot（记录 tree version + dag version 组合）
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 8.2, 8.3_

  - [ ] 1.4 在 `backend/app/core/database.py` 中注册新模型，确保 create_all 能创建所有新增表
    - 确保新增表与现有 Document/DocumentChunk/chunk_embeddings 表共存于同一学科 .db 文件
    - 验证已有学科库升级兼容性（CREATE TABLE IF NOT EXISTS 语义）
    - _Requirements: 13.3_

  - [ ]* 1.5 编写数据模型单元测试
    - 验证所有字段类型、外键、唯一约束与 design.md 一致
    - 验证已有表结构不被破坏
    - _Requirements: 1.9, 13.3_

- [ ] 2. 基础设施工具层
  - [ ] 2.1 在 `backend/app/core/exceptions.py` 中追加新增异常类
    - 追加 DigestJobNotFoundError、KnowledgeNodeNotFoundError、TeachingUnitNotFoundError、ThemeTreeNodeNotFoundError、NoPublishedTreeError、NoPublishedDagError、NoPublishedCurriculumSnapshotError、SubjectBuildLockConflictError、TreeVersionConflictError
    - _Requirements: 8.5, 12.1, 12.2_

  - [ ] 2.2 在 `backend/app/utils/` 中实现工具函数
    - 实现 `normalize_name`（NFKC 归一化 + 去空格/标点 + 小写）
    - 实现 `compute_member_signature`（排序后 core node ids 的 hash）
    - _Requirements: 6.1, 2.1_

  - [ ]* 2.3 编写 normalize_name 属性测试
    - **Property 5: 名称规范化幂等性**
    - **Validates: Requirements 6.1**

  - [ ] 2.4 实现 `update_job_progress` 辅助函数
    - 保证 progress 单调递增：传入值 <= 当前值则跳过更新
    - 同时更新 current_step 字段
    - GraphDigestJob 和 CurriculumDeriveJob 统一通过此函数更新进度
    - _Requirements: 8.4_

  - [ ] 2.5 实现 `cleanup_pending_by_job` 工具函数
    - job_type="graph"：清理该 job 产生的 pending nodes/edges/revisions/aliases/evidence_links
    - job_type="curriculum"：清理该 job 产生的 pending units/memberships/draft tree versions/draft dag versions
    - 支持按 subject 全量清理 pending 数据（异常恢复）
    - _Requirements: 8.1, 8.2_

  - [ ] 2.6 实现版本发布与归档辅助函数
    - 实现 publish_theme_tree_version、publish_prereq_dag_version、publish_curriculum_snapshot、archive_old_versions
    - builder 阶段只生成 draft，finalize 统一调用这些函数发布
    - _Requirements: 10.9, 11.5, 8.3_

  - [ ] 2.7 创建测试数据工厂与 Fixtures
    - 创建 `backend/tests/factories.py` 或 conftest.py fixtures
    - 提供所有新增模型的最小 fixture 和 create_test_subject_db() 辅助函数
    - _Requirements: 1.1-1.9, 2.1-2.5_

- [ ] 3. Checkpoint - 确保数据模型与基础设施就绪
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. 数据访问层
  - [ ] 4.1 创建 `backend/app/repositories/kg_repo.py`，实现知识图谱 Repository
    - 构建锁：acquire_subject_build_lock、release_subject_build_lock
    - 节点 CRUD：create_knowledge_node、get_knowledge_node_by_id、find_node_by_normalized_name、find_nodes_by_alias、list_nodes_by_subject、get_node_with_current_revision
    - 别名 CRUD：create_alias、find_alias、list_aliases_by_node
    - 边 CRUD：create_knowledge_edge、find_edge、list_edges_by_node、list_edges_by_type
    - 修订：create_knowledge_revision、deactivate_old_revisions、create_edge_revision、deactivate_old_edge_revisions
    - 证据：create_evidence_link、list_evidence_by_entity、count_active_evidence
    - 任务：create_digest_job、update_digest_job
    - _Requirements: 1.7, 1.8, 6.1, 6.2, 6.5, 6.6, 7.2, 7.3, 8.1, 8.5_

  - [ ] 4.2 为 kg_repo 添加关键索引
    - 确认 knowledge_node、knowledge_alias、knowledge_edge、knowledge_revision、edge_revision、evidence_link 的索引覆盖
    - 对典型查询路径执行 EXPLAIN QUERY PLAN 确认走索引
    - _Requirements: 1.9, 6.1, 6.2_

  - [ ]* 4.3 编写 kg_repo 单元测试
    - 测试所有 CRUD 函数、唯一约束冲突、构建锁获取/释放
    - _Requirements: 1.7, 1.8, 8.5_

  - [ ] 4.4 创建 `backend/app/repositories/curriculum_repo.py`，实现课程结构 Repository
    - 教学单元：create_teaching_unit、get_teaching_unit_by_id、find_unit_by_signature、find_units_overlapping_nodes、find_unit_by_normalized_name、list_units_by_subject、create_unit_revision、deactivate_old_unit_revisions、create_unit_membership、list_memberships_by_unit、find_unit_by_node
    - 锚点：create_taxonomy_anchor、list_anchors_by_subject、get_uncategorized_anchor
    - 主题树：create_theme_tree_version、get_current_theme_tree_version、create_theme_tree_version_with_optimistic_lock、create_theme_tree_node、create_unit_tree_membership
    - 先修 DAG：create_prereq_dag_version、get_current_prereq_dag_version、create_unit_dependency、list_dependencies_by_version
    - 课程任务：create_curriculum_job、update_curriculum_job
    - 课程快照：create_curriculum_snapshot、get_current_curriculum_snapshot、archive_old_snapshots
    - _Requirements: 2.1, 2.4, 2.5, 3.1, 3.5, 3.6, 4.1, 4.2, 8.2, 8.3_

  - [ ] 4.5 为 curriculum_repo 添加关键索引
    - 确认 teaching_unit、teaching_unit_membership、teaching_unit_revision、unit_tree_membership、theme_tree_node、unit_dependency、curriculum_snapshot 的索引覆盖
    - _Requirements: 2.1, 3.4, 4.2_

  - [ ]* 4.6 编写 curriculum_repo 单元测试
    - 测试所有 CRUD 函数、签名查找、乐观锁冲突
    - _Requirements: 2.4, 2.5, 3.5_

- [ ] 5. Checkpoint - 确保数据访问层就绪
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. LLM 抽取层
  - [ ] 6.1 创建 `backend/app/agents/digest/kg_extractor.py`，实现候选知识抽取
    - 定义 Pydantic 模型：CandidateNode、CandidateEdge、ChunkExtractionResult
    - 实现 extract_candidates 异步函数，使用 Instructor 结构化输出
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 6.2 创建 `backend/app/agents/digest/prompts/kg_prompts.py`，编写候选抽取 prompt
    - 包含节点类型限定、边类型限定、taxonomy_hint 和 parent_entity_name 要求
    - _Requirements: 5.1, 5.2_

  - [ ]* 6.3 编写候选抽取属性测试
    - **Property 4: 候选抽取结构合规性**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ]* 6.4 编写抽取容错属性测试
    - **Property 18: 抽取容错连续性**
    - **Validates: Requirements 5.5**

  - [ ] 6.5 创建 `backend/app/agents/digest/kg_clusterer.py`，实现批内候选聚类
    - 定义 ClusteredCandidate 数据类
    - 实现 cluster_candidates 函数（基于 normalized_name + embedding 相似度的批内去重聚类）
    - _Requirements: 5.1, 6.1_

- [ ] 7. 对齐层
  - [ ] 7.1 创建 `backend/app/agents/digest/kg_resolver.py`，实现节点对齐（Entity Resolution）
    - 实现 resolve_node 异步函数，按分层递进流程：一级实体（normalized_name → alias → embedding + LLM）、二级说明对象（parent_entity_name + 内容语义相似度）
    - MVP 先消费 EXACT / ALIAS / NO_MATCH 三种判定结果
    - 在 kg_prompts.py 中追加实体对齐判断 prompt
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 7.2 编写节点对齐属性测试
    - **Property 6: 实体对齐可达性**
    - **Validates: Requirements 6.1, 6.2**

  - [ ] 7.3 在 `kg_resolver.py` 中实现边对齐（Relation Resolution）
    - 实现 resolve_edge 函数
    - 实现 compute_edge_confidence 函数（非单调递增公式）
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 7.4 编写边置信度属性测试
    - **Property 8: 边置信度为证据函数**
    - **Validates: Requirements 7.5**

  - [ ]* 7.5 编写对齐必产证据属性测试
    - **Property 7: 对齐操作必产证据**
    - **Validates: Requirements 6.5, 6.6, 7.2, 7.3**

- [ ] 8. 影响集分析
  - [ ] 8.1 创建 `backend/app/agents/digest/kg_impact_analyzer.py`，实现影响集分析器
    - 定义 ImpactSet 数据类，包含四层闭包规则：图谱层、教学单元层、树视图层、DAG 层
    - 实现 analyze_impact 函数，基于已落库状态 + 当前课程结构版本状态运行
    - _Requirements: 8.6, 9.6, 10.9, 11.6_

  - [ ]* 8.2 编写影响集分析单元测试
    - 验证闭包规则完整覆盖所有受影响对象
    - _Requirements: 8.6, 9.6_

- [ ] 9. Checkpoint - 确保抽取与对齐层就绪
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. GraphDigestJob 工作流
  - [ ] 10.1 创建 `backend/app/agents/digest/kg_workflow.py`，实现 KG 工作流状态机
    - 定义 KGDigestState TypedDict
    - 实现 LangGraph StateGraph 节点：acquire_lock_node、prepare_node、extract_node、cluster_node、resolve_nodes_node、resolve_edges_node、analyze_impact_node、finalize_graph_node、fail_node
    - 实现条件分支（锁获取失败 → reject，LLM 异常 → fail）
    - fail_node 调用 cleanup_pending_by_job 清理 pending 数据并释放锁
    - finalize_graph_node 批量激活 pending → active，释放锁，触发 CurriculumDeriveJob
    - 所有步骤通过 update_job_progress 更新进度
    - _Requirements: 8.1, 8.4, 8.5, 8.6_

  - [ ]* 10.2 编写构建进度单调递增属性测试
    - **Property 10: 构建进度单调递增**
    - **Validates: Requirements 8.4**

  - [ ]* 10.3 编写文件范围限定属性测试
    - **Property 11: 文件范围限定**
    - **Validates: Requirements 8.6**

- [ ] 11. 教学单元生成
  - [ ] 11.1 创建 `backend/app/agents/digest/unit_builder.py`，实现局部子图提取与距离计算
    - 从 Impact Set 中受影响的 active 节点出发，提取 changed nodes + 1-hop + 2-hop 子图
    - 实现 compute_unit_distance 多维距离函数（semantic 0.30 + graph_relation 0.25 + co_outline 0.20 + prerequisite_penalty 0.15 + type_compatibility 0.10）
    - 实现 pairwise 距离矩阵计算
    - _Requirements: 9.1, 9.2_

  - [ ] 11.2 在 `unit_builder.py` 中实现聚类切割 + 角色分配 + 身份签名
    - 实现层次聚类（agglomerative clustering）→ 切割阈值 → leaf teaching units
    - 实现角色分配逻辑：core / support / example / prerequisite_bridge
    - 使用 compute_member_signature 计算结构签名，通过 find_unit_by_signature 查找已有单元
    - 新节点优先尝试加入已有 unit（距离 < 阈值），否则形成新 unit
    - _Requirements: 9.1, 9.3, 9.5, 9.6_

  - [ ]* 11.3 编写教学单元核心唯一不变式属性测试
    - **Property 2: 教学单元核心唯一不变式**
    - **Validates: Requirements 2.4**

  - [ ] 11.4 在 `unit_builder.py` 中实现 LLM 命名 + 单元 Upsert
    - 实现 derive_teaching_units 异步函数（组合子图提取 + 聚类 + 命名）
    - 对每个新/变更的教学单元调用 LLM 生成单元名称、摘要和学习目标
    - 创建 TeachingUnit(status="pending") + TeachingUnitRevision + TeachingUnitMembership
    - 已有单元（通过 signature 匹配到）：更新 revision，不重建 unit
    - LLM 命名失败时 fallback 到 core 节点名称
    - 在 kg_prompts.py 中追加教学单元命名 prompt
    - _Requirements: 9.1, 9.4, 9.5_

- [ ] 12. 主题树派生
  - [ ] 12.1 创建 `backend/app/agents/digest/theme_tree_builder.py`，实现主题树构建器
    - 实现 derive_theme_tree 异步函数，按 Step A-E：生成 Anchor Skeleton → 挂载 TeachingUnit → 计算 membership_score（6 源证据融合）→ 确定归属（human_fixed 绝对优先 → 稳定规则 → 待归类池）→ 生成 ThemeTreeVersion(status="draft")
    - 实现 compute_unit_membership_score 函数
    - MVP 采用"逻辑局部重算 + 存储全量快照"版本策略
    - 不在此处归档旧版本或发布新版本——统一在 finalize_curriculum_node 中完成
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9, 10.10_

  - [ ]* 12.2 编写主题树归属唯一属性测试
    - **Property 3: 主题树归属唯一不变式**
    - **Validates: Requirements 3.5**

  - [ ]* 12.3 编写锚点优先级稳定性属性测试
    - **Property 14: 锚点骨架优先级稳定性**
    - **Validates: Requirements 10.2**

- [ ] 13. 先修 DAG 派生
  - [ ] 13.1 创建 `backend/app/agents/digest/prereq_dag_builder.py`，实现先修 DAG 构建器
    - 实现 derive_prereq_dag 异步函数：收集节点级依赖边 → 聚合为单元级依赖 → 去环处理（Tarjan SCC + 断开最低 confidence 边）→ 传递约简 → 生成 PrereqDagVersion(status="draft")
    - 实现 aggregate_unit_dependencies、break_cycles、transitive_reduction 函数
    - MVP 阶段 defined_by 仅用于单元内聚合，不生成跨 unit 依赖
    - 不在此处归档旧版本或发布新版本——统一在 finalize_curriculum_node 中完成
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 13.2 编写先修 DAG 无环性属性测试
    - **Property 12: 先修 DAG 无环性**
    - **Validates: Requirements 4.3**

  - [ ]* 13.3 编写先修 DAG 传递约简属性测试
    - **Property 13: 先修 DAG 传递约简**
    - **Validates: Requirements 4.4**

- [ ] 14. CurriculumDeriveJob 工作流
  - [ ] 14.1 创建 `backend/app/agents/digest/curriculum_workflow.py`，实现课程派生工作流状态机
    - 定义 CurriculumDeriveState TypedDict（含 snapshot_id: int | None）
    - 实现 LangGraph StateGraph 节点：derive_units_node、derive_theme_tree_node、derive_prereq_dag_node、finalize_curriculum_node、fail_curriculum_node
    - finalize_curriculum_node 统一完成：批量激活 pending 单元 → publish tree → publish dag → 创建并发布 CurriculumSnapshot → 更新 job 状态
    - fail_curriculum_node 调用 cleanup_pending_by_job 清理 pending 数据
    - 所有步骤通过 update_job_progress 更新进度
    - _Requirements: 8.2, 8.3, 9.1, 10.9, 11.5_

  - [ ]* 14.2 编写修订唯一当前版本属性测试
    - **Property 1: 修订唯一当前版本不变式**
    - **Validates: Requirements 1.7, 1.8, 2.5**

  - [ ]* 14.3 编写树版本归档不变式属性测试
    - **Property 16: 树版本归档不变式**
    - **Validates: Requirements 10.9, 11.5**

- [ ] 15. Checkpoint - 确保工作流与课程派生就绪
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. 服务层与 API Schema
  - [ ] 16.1 创建 `backend/app/services/knowledge_graph_service.py`，实现知识图谱服务
    - 实现 trigger_digest_build（幂等检查 + 创建 GraphDigestJob + 调度后台执行，不在此处获取构建锁）
    - 实现 run_graph_digest_background、run_curriculum_derive_background
    - 实现 get_digest_job_status、get_graph_nodes、get_graph_node_detail、get_teaching_units、get_teaching_unit_detail
    - 实现 get_current_theme_tree、get_current_prereq_dag、get_current_curriculum_snapshot、manage_taxonomy_anchors
    - 确保引用链 api/ → services/ → agents/ → repositories/ 单向依赖
    - _Requirements: 8.1, 8.4, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10_

  - [ ] 16.2 创建 `backend/app/schemas/knowledge_graph.py`，定义 API Schema
    - 请求：DigestBuildRequest、DigestStatusRequest、GraphNodesQueryRequest、GraphNodeDetailRequest、UnitsQueryRequest、UnitDetailRequest、AnchorManageRequest
    - 响应：DigestJobResponse、KnowledgeNodeResponse、KnowledgeNodeDetailResponse、TeachingUnitResponse、TeachingUnitDetailResponse、ThemeTreeResponse、PrereqDagResponse、CurriculumSnapshotResponse
    - _Requirements: 12.1-12.10_

- [ ] 17. API 路由
  - [ ] 17.1 扩展 `backend/app/api/knowledge.py`，新增路由
    - POST /api/v1/subjects/{subject}/digest/build — 触发增量构建
    - POST /api/v1/subjects/{subject}/digest/status — 查询构建状态
    - POST /api/v1/subjects/{subject}/graph/nodes/query — 分页查询节点
    - POST /api/v1/subjects/{subject}/graph/nodes/detail — 节点详情
    - POST /api/v1/subjects/{subject}/units/query — 分页查询教学单元
    - POST /api/v1/subjects/{subject}/units/detail — 教学单元详情
    - POST /api/v1/subjects/{subject}/theme-tree/current — 当前主题树
    - POST /api/v1/subjects/{subject}/prereq-dag/current — 当前先修 DAG
    - POST /api/v1/subjects/{subject}/curriculum/current — 当前课程快照
    - POST /api/v1/subjects/{subject}/taxonomy/anchors — 锚点管理
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10_

  - [ ] 17.2 在 `backend/app/main.py` 中注册新路由
    - 确保 API 层仅调用 services 层，不直接操作 repositories 或 agents
    - _Requirements: 12.1_

- [ ] 18. 向量检索兼容性保障
  - [ ] 18.1 确认增量构建过程中继续为每个 DocumentChunk 生成 embedding 并写入 chunk_embeddings
    - 确认现有 vector_search 函数接口签名和行为不变
    - 确认 Document/DocumentChunk 表结构不变，新增表与现有表共存
    - _Requirements: 13.1, 13.2, 13.3_

  - [ ]* 18.2 编写向量检索往返兼容性属性测试
    - **Property 17: 向量检索往返兼容性**
    - **Validates: Requirements 13.1**

- [ ] 19. Checkpoint - 确保服务层与 API 就绪
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 20. 集成与端到端验证
  - [ ] 20.1 验证完整流程：上传文档 → Ingest → GraphDigestJob → CurriculumDeriveJob → CurriculumSnapshot
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 20.2 验证增量更新：上传第二篇文档后仅处理新 chunks，已有图谱数据保留
    - _Requirements: 8.6_

  - [ ] 20.3 验证 TeachingUnit 稳定身份：同一批成员节点即使 LLM 改名，通过 member_signature 仍能定位到同一 unit
    - _Requirements: 2.1_

  - [ ] 20.4 验证 staging/active 两层状态：Job 失败时 pending 数据被清理
    - _Requirements: 8.1, 8.2_

  - [ ] 20.5 验证并发控制：subject 级构建锁 + 幂等键
    - 对同一 subject 的非幂等重复构建请求，若已有 processing 状态的 GraphDigestJob，则返回 409
    - 对相同 idempotency_key 的重复请求，直接返回已有 job，不视为冲突
    - _Requirements: 8.5, 8.1_

  - [ ] 20.6 验证版本发布原子性：builder 只产出 draft，finalize 统一发布，无"旧版本已 archived 但新版本未 published"窗口期
    - _Requirements: 10.9, 11.5, 8.3_

  - [ ] 20.7 验证已有学科库升级：对含旧数据的 .db 文件执行完整流程，旧数据不受影响
    - _Requirements: 13.3_

  - [ ]* 20.8 编写图谱实体证据完整性属性测试
    - **Property 9: 图谱实体证据完整性不变式**
    - **Validates: Requirements 14.3, 14.4**

- [ ] 21. Final checkpoint - 确保所有测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 22. MVP+1 增强项
  - [ ]* 22.1 补充 EntityMatchDecision 完整语义
    - 补充 BROADER / NARROWER / RELATED_NOT_SAME / UNSURE 的处理逻辑
    - BROADER / NARROWER 触发节点拆分/合并候选；UNSURE 保守策略标记为 NO_MATCH
    - _Requirements: 6.4_

  - [ ]* 22.2 实现主题树归属稳定性精细规则
    - 前两名 score 差距 < stability_threshold 时保持上一版归属
    - 实现锚点集变化时的局部重评估逻辑
    - _Requirements: 10.6_

  - [ ]* 22.3 编写归属稳定性属性测试
    - **Property 15: 归属稳定性**
    - **Validates: Requirements 10.6**

  - [ ]* 22.4 补充 defined_by 跨 unit 保守依赖生成
    - 仅当 Concept 与 Definition 已被分到不同 units，且满足高置信度 + 无聚类并入证据 + 额外支持信号时才生成 unit-level dependency candidate
    - _Requirements: 11.1_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from design.md
- 版本策略：MVP 采用"逻辑局部重算 + 存储全量快照"
- 版本发布责任边界：builder 只生成 draft，finalize_curriculum_node 统一发布
- 实现语言：Python（与现有后端一致）
