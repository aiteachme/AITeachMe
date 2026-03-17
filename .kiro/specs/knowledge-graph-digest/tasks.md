# Implementation Plan: 知识图谱增量构建 + 多视图课程结构派生

## Overview

将现有 Digest Engine 重构为"知识图谱型增量构建 + 多视图课程结构派生"模式。

实现按四阶段交付：
- **Phase 1 — 图谱底座**：枚举/模型/DB + 工具/异常 + kg_repo + 抽取/聚类/对齐/影响集 + kg_workflow + 图谱服务与 API + 图谱 e2e
- **Phase 2 — 教学单元**：curriculum 模型/repo（仅 TeachingUnit 部分）+ unit_builder + curriculum_workflow v1（仅 units）+ 单元 API + e2e
- **Phase 3 — 主题树**：锚点 + 主题树模型/repo + theme_tree_builder + publish/finalize snapshot v2 + 主题树 API + e2e
- **Phase 4 — 先修 DAG**：先修 DAG 模型/repo + dag_builder + snapshot finalize v3 + DAG API + 完整课程 e2e

关键设计约束（硬规则）：
- **版本发布边界**：builder 只能创建 draft/pending，禁止调用任何 publish/archive helper；publish/archive 仅供 finalize_curriculum_node 使用
- **CurriculumDeriveJob 触发时序**：在 finalize_graph_node 成功后创建，不预创建
- **cleanup 精确性**：所有可清理表均含 created_by_job_id，按此字段精确清理
- **MVP defined_by 范围**：defined_by 不参与跨 unit dependency 生成，仅用于单元内聚合
- **DAG 算法顺序**：先去环（break_cycles），再传递约简（transitive_reduction）

## Tasks

### Phase 1 — 图谱底座

- [ ] 1. 数据模型与枚举定义
  - [ ] 1.1 在 `backend/app/models/enums.py` 中追加所有新增枚举类型
    - 追加 KGNodeType、KGEdgeType、KGNodeStatus、KGEdgeStatus、EntityMatchDecision、RevisionReason、EvidenceRole、ExtractionMethod、FieldScope、AliasStatus、UnitMemberRole、UnitStatus、AnchorType、AnchorStatus、TreeVersionStatus、ThemeTreeNodeType（使用 THEME 而非 TOPIC）、UnitTreeMembershipRole、MembershipSource、DependencyType、DigestJobStatus
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 3.1, 3.3, 4.1, 4.2, 5.3, 5.4, 6.4, 8.1, 8.2_

  - [ ] 1.2 创建 `backend/app/models/knowledge_graph.py`，定义知识图谱 SQLModel 表
    - 定义 KnowledgeNode（身份+路由+状态，不存内容，含 created_by_job_id）、KnowledgeAlias（独立别名表，含 created_by_job_id）、KnowledgeEdge（含 created_by_job_id）、KnowledgeRevision（含 UniqueConstraint(node_id, revision_no)）、EdgeRevision（含 UniqueConstraint(edge_id, revision_no)）、EvidenceLink（polymorphic association，DB 层不做外键强约束到 node/edge，完整性由服务层保证，含 created_by_job_id）、GraphDigestJob（含 idempotency_key + curriculum_job_id 回填字段）、SubjectBuildLock
    - 设置 UniqueConstraint：node(subject, node_type, normalized_name)、alias(node_id, normalized_alias)、edge(subject, source_node_id, target_node_id, edge_type)、revision(node_id, revision_no)、edge_revision(edge_id, revision_no)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 8.1_

  - [ ] 1.3 创建 `backend/app/models/curriculum.py`，定义课程结构 SQLModel 表
    - 定义 TeachingUnit（含 member_signature + UniqueConstraint(subject, member_signature) + created_by_job_id，leaf-only）、TeachingUnitRevision（含 UniqueConstraint(unit_id, revision_no)）、TeachingUnitMembership（含 UniqueConstraint(unit_id, knowledge_node_id, role) + created_by_job_id）
    - 定义 TaxonomyAnchor、ThemeTreeVersion（含 UniqueConstraint(subject, version_no) + **created_by_job_id**）、ThemeTreeNode（含 created_by_job_id）、UnitTreeMembership（含 UniqueConstraint(tree_version_id, tree_node_id, teaching_unit_id, membership_role) + created_by_job_id）
    - 定义 PrereqDagVersion（含 UniqueConstraint(subject, version_no) + **created_by_job_id**）、UnitDependency（含 UniqueConstraint + derivation_metadata_json + created_by_job_id）
    - 定义 CurriculumDeriveJob、CurriculumSnapshot（含 UniqueConstraint(subject, version_no) + **created_by_job_id**）
    - **created_by_job_id 补齐说明**：ThemeTreeVersion、PrereqDagVersion、CurriculumSnapshot 均需包含 created_by_job_id 字段，以支持 cleanup_pending_by_job 在失败恢复时精确清理 draft 版本。TaxonomyAnchor 不属于 job staging 对象，不参与 cleanup_pending_by_job
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 8.2, 8.3_

  - [ ] 1.4 在 `backend/app/core/database.py` 中注册新模型，确保 create_all 能创建所有新增表
    - 确保新增表与现有 Document/DocumentChunk/chunk_embeddings 表共存于同一学科 .db 文件
    - 验证已有学科库升级兼容性（CREATE TABLE IF NOT EXISTS 语义）
    - _Requirements: 13.3_

  - [ ]* 1.5 编写数据模型单元测试
    - 验证所有字段类型、外键、唯一约束与 design.md 一致（含新增的 created_by_job_id 字段和所有 UniqueConstraint）
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

  - [ ]* 2.3 编写 normalize_name 属性测试（P0）
    - **Property 5: 名称规范化幂等性**
    - **Validates: Requirements 6.1**

  - [ ] 2.4 实现 `update_job_progress` 辅助函数
    - 保证 progress 单调递增：传入值 <= 当前值则跳过更新
    - 同时更新 current_step 字段
    - GraphDigestJob 和 CurriculumDeriveJob 统一通过此函数更新进度
    - _Requirements: 8.4_

  - [ ] 2.5 实现 `cleanup_pending_by_job` 工具函数（两层清理策略）
    - **普通路径：cleanup_pending_by_job(job_id, job_type)** — 常规失败补偿
      - 通过 `created_by_job_id` 字段精确定位待清理数据
      - job_type="graph"：清理 created_by_job_id=job_id 的 pending nodes/edges/revisions/aliases/evidence_links
      - job_type="curriculum"：清理 created_by_job_id=job_id 的 pending units/memberships/draft tree versions/tree nodes/unit tree memberships/draft dag versions/unit dependencies/draft snapshots
    - **管理员/恢复路径：cleanup_orphan_pending_by_subject(subject)** — 仅清理满足以下全部条件的 pending 数据：
      - 超过 TTL（可配置，默认 1 小时）
      - 无对应 processing 状态的 job
      - 不在当前锁持有期内
    - _Requirements: 8.1, 8.2_

  - [ ] 2.6 实现版本发布与归档辅助函数
    - 实现 publish_theme_tree_version、publish_prereq_dag_version、publish_curriculum_snapshot、archive_old_versions
    - **硬规则：这些函数仅供 finalize_curriculum_node 调用，禁止 builder 内部调用**
    - _Requirements: 10.9, 11.5, 8.3_

  - [ ] 2.7 实现 pending → active 批量激活集中 helper
    - 实现 `activate_graph_entities_by_job(job_id)` — 集中激活 graph 层 pending 实体（nodes/edges/aliases/evidence_links），避免遗漏
    - 实现 `activate_curriculum_entities_by_job(job_id)` — 集中激活 curriculum 层 pending 实体（units/memberships/unit tree memberships/unit dependencies），避免遗漏
    - 激活逻辑集中、可单测、不容易漏改别名/证据/unit membership 等对象
    - _Requirements: 8.1, 8.2_

  - [ ] 2.8 创建测试数据工厂与 Fixtures
    - 创建 `backend/tests/factories.py` 或 conftest.py fixtures
    - 提供所有新增模型的最小 fixture 和 create_test_subject_db() 辅助函数
    - _Requirements: 1.1-1.9, 2.1-2.5_

- [ ] 3. Checkpoint — 数据模型与基础设施就绪
  - 验收标准：
    - 所有新增模型可成功 create_all
    - 关键唯一约束通过测试（含 uq_unit_node_role、uq_tree_unit_role、uq_node_revision_no、uq_edge_revision_no、uq_unit_revision_no、uq_theme_tree_subject_version、uq_prereq_dag_subject_version、uq_curriculum_snapshot_subject_version）
    - normalize_name / compute_member_signature 工具函数测试通过
    - cleanup_pending_by_job 在 graph/curriculum 两类场景下测试通过
    - created_by_job_id 字段在所有需要清理的表上存在

- [ ] 4. 数据访问层
  - [ ] 4.1 创建 `backend/app/repositories/kg_repo.py`，实现知识图谱 Repository
    - 构建锁：acquire_subject_build_lock、release_subject_build_lock
    - 节点 CRUD：create_knowledge_node、get_knowledge_node_by_id、find_node_by_normalized_name、find_nodes_by_alias、list_nodes_by_subject、get_node_with_current_revision
    - 别名 CRUD：create_alias、find_alias、list_aliases_by_node
    - 边 CRUD：create_knowledge_edge、find_edge、list_edges_by_node、list_edges_by_type
    - 修订：create_knowledge_revision、deactivate_old_revisions、create_edge_revision、deactivate_old_edge_revisions
    - 证据：create_evidence_link、list_evidence_by_entity、count_active_evidence
    - 任务：create_digest_job（含幂等键检查）、update_digest_job、find_job_by_idempotency_key
    - **默认状态过滤语义**：
      - `list_nodes_by_subject` 默认只返回 status="active"，除非显式传 status 参数
      - `find_node_by_normalized_name` 默认只匹配 active | pending，不匹配 merged | deprecated
      - `list_edges_by_node` / `list_edges_by_type` 默认只返回 active
      - `get_node_with_current_revision` 如果 node 非 active，需要由服务层决定是否允许访问（repo 层不拦截，但返回 node.status 供调用方判断）
      - 增量构建期间对齐查询可能要看 pending，对外 API 默认只看 active
    - _Requirements: 1.7, 1.8, 6.1, 6.2, 6.5, 6.6, 7.2, 7.3, 8.1, 8.5_

  - [ ] 4.2 为 kg_repo 添加关键索引
    - 确认 knowledge_node、knowledge_alias、knowledge_edge、knowledge_revision、edge_revision、evidence_link 的索引覆盖
    - 对典型查询路径执行 EXPLAIN QUERY PLAN 确认走索引
    - _Requirements: 1.9, 6.1, 6.2_

  - [ ]* 4.3 编写 kg_repo 单元测试
    - 测试所有 CRUD 函数、唯一约束冲突、构建锁获取/释放、幂等键查找
    - _Requirements: 1.7, 1.8, 8.5_

- [ ] 5. LLM 抽取层
  - [ ] 5.1 创建 `backend/app/agents/digest/kg_extractor.py`，实现候选知识抽取
    - 定义 Pydantic 模型：CandidateNode、CandidateEdge、ChunkExtractionResult
    - 实现 extract_candidates 异步函数，使用 Instructor 结构化输出
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 5.2 创建 `backend/app/agents/digest/prompts/kg_prompts.py`，编写候选抽取 prompt
    - 包含节点类型限定、边类型限定、taxonomy_hint 和 parent_entity_name 要求
    - _Requirements: 5.1, 5.2_

  - [ ]* 5.3 编写候选抽取属性测试（P1）
    - **Property 4: 候选抽取结构合规性**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ]* 5.4 编写抽取容错属性测试（P1）
    - **Property 18: 抽取容错连续性**
    - **Validates: Requirements 5.5**

  - [ ] 5.5 创建 `backend/app/agents/digest/kg_clusterer.py`，实现批内候选聚类
    - 定义 ClusteredCandidate 数据类
    - 实现 cluster_candidates 函数（基于 normalized_name + embedding 相似度的批内去重聚类）
    - 输出 candidate_name_to_cluster_id 映射供后续边解析使用
    - _Requirements: 5.1, 6.1_

- [ ] 6. 对齐层
  - [ ] 6.1 创建 `backend/app/agents/digest/kg_resolver.py`，实现节点对齐（Entity Resolution）
    - 实现 resolve_node 异步函数，按分层递进流程：一级实体（normalized_name → alias → embedding + LLM）、二级说明对象（parent_entity_name + 内容语义相似度）
    - MVP 先消费 EXACT / ALIAS / NO_MATCH 三种判定结果
    - 输出 candidate_name_to_resolved_node_id 映射供后续边解析使用
    - 在 kg_prompts.py 中追加实体对齐判断 prompt
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 6.2 编写节点对齐属性测试（P1）
    - **Property 6: 实体对齐可达性**
    - **Validates: Requirements 6.1, 6.2**

  - [ ] 6.3 在 `kg_resolver.py` 中实现边对齐（Relation Resolution）
    - 实现 resolve_edge 函数，使用名称映射解析边端点：优先 candidate_name_to_resolved_node_id → candidate_name_to_cluster_id 间接查找 → fallback find_node_by_normalized_name
    - 实现 compute_edge_confidence 函数（非单调递增公式）
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 6.4 编写边置信度属性测试（P1）
    - **Property 8: 边置信度为证据函数**
    - **Validates: Requirements 7.5**

  - [ ]* 6.5 编写对齐必产证据属性测试（P1）
    - **Property 7: 对齐操作必产证据**
    - **Validates: Requirements 6.5, 6.6, 7.2, 7.3**

- [ ] 7. 影响集分析
  - [ ] 7.1 创建 `backend/app/agents/digest/kg_impact_analyzer.py`，实现影响集分析器
    - 定义 ImpactSet 数据类，包含四层闭包规则：图谱层、教学单元层、树视图层、DAG 层
    - 实现 analyze_impact 函数，基于已落库状态 + 当前课程结构版本状态运行
    - _Requirements: 8.6, 9.6, 10.9, 11.6_

  - [ ]* 7.2 编写影响集分析单元测试
    - 验证闭包规则完整覆盖所有受影响对象
    - _Requirements: 8.6, 9.6_

- [ ] 8. GraphDigestJob 工作流
  - [ ] 8.1 创建 `backend/app/agents/digest/kg_workflow.py`，实现 KG 工作流状态机
    - 定义 KGDigestState TypedDict（含 candidate_name_to_cluster_id、candidate_name_to_resolved_node_id 映射）
    - 实现 LangGraph StateGraph 节点：acquire_lock_node、prepare_node、extract_node、cluster_node（生成 candidate_name_to_cluster_id）、resolve_nodes_node（生成 candidate_name_to_resolved_node_id）、resolve_edges_node（使用名称映射解析边端点）、analyze_impact_node、finalize_graph_node、fail_node
    - 实现条件分支（锁获取失败 → reject，LLM 异常 → fail）
    - fail_node 调用 cleanup_pending_by_job（按 created_by_job_id）清理 pending 数据并释放锁
    - finalize_graph_node：调用 activate_graph_entities_by_job 批量激活 pending → active → 释放锁 → 创建 CurriculumDeriveJob → 回填 curriculum_job_id 到 GraphDigestJob → 异步触发 CurriculumDeriveJob
    - 所有步骤通过 update_job_progress 更新进度
    - _Requirements: 8.1, 8.4, 8.5, 8.6_

  - [ ]* 8.2 编写构建进度单调递增属性测试（P0）
    - **Property 10: 构建进度单调递增**
    - **Validates: Requirements 8.4**

  - [ ]* 8.3 编写文件范围限定属性测试（P1）
    - **Property 11: 文件范围限定**
    - **Validates: Requirements 8.6**

- [ ] 9. 图谱服务层与 API
  - [ ] 9.1 创建 `backend/app/services/knowledge_graph_service.py`，实现图谱服务（Phase 1 部分）
    - 实现 trigger_digest_build：三层检查（幂等键命中 → 运行中冲突 409 → 创建新 job），不在此处获取构建锁
    - 实现 run_graph_digest_background
    - 实现 get_digest_status → 返回 DigestStatusResponse 聚合响应（graph_job + curriculum_job + current_snapshot_id）
    - **Phase 1 超前依赖说明**：DigestStatusResponse 中 curriculum_job 字段在 Phase 1 可能为空（`CurriculumJobResponse | None = None`），current_curriculum_snapshot_id 在 Phase 1 固定为 None
    - 实现 get_graph_nodes、get_graph_node_detail
    - 确保引用链 api/ → services/ → agents/ → repositories/ 单向依赖
    - _Requirements: 8.1, 8.4, 8.5, 12.1, 12.2, 12.3, 12.4_

  - [ ] 9.2 创建 `backend/app/schemas/knowledge_graph.py`，定义 API Schema（Phase 1 部分）
    - 请求：DigestBuildRequest、DigestStatusRequest、GraphNodesQueryRequest、GraphNodeDetailRequest
    - 响应：DigestStatusResponse（聚合：graph_job + curriculum_job + current_curriculum_snapshot_id）、GraphDigestJobResponse、CurriculumJobResponse、KnowledgeNodeResponse、KnowledgeNodeDetailResponse
    - **Phase 1 超前依赖说明**：DigestStatusResponse 中 `curriculum_job: CurriculumJobResponse | None = None`（Phase 1 可能为空），`current_curriculum_snapshot_id: int | None = None`（Phase 1 固定为空）
    - **KnowledgeNodeDetailResponse 显式包含**：node base info、current revision（title, summary, body）、aliases、active evidence summaries（document_id, chunk_id, quote_text, evidence_role）、incident edges（with edge type, target/source node info）
    - _Requirements: 12.1-12.4, 14.1_

  - [ ] 9.3 扩展 `backend/app/api/knowledge.py`，新增图谱路由
    - POST /api/v1/subjects/{subject}/digest/build — 触发增量构建
    - POST /api/v1/subjects/{subject}/digest/status — 查询聚合状态
    - POST /api/v1/subjects/{subject}/graph/nodes/query — 分页查询节点
    - POST /api/v1/subjects/{subject}/graph/nodes/detail — 节点详情
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [ ] 9.4 在 `backend/app/main.py` 中注册新路由
    - _Requirements: 12.1_

- [ ] 10. 向量检索兼容性保障
  - [ ] 10.1 确认增量构建过程中继续为每个 DocumentChunk 生成 embedding 并写入 chunk_embeddings
    - 确认现有 vector_search 函数接口签名和行为不变
    - 确认 Document/DocumentChunk 表结构不变，新增表与现有表共存
    - _Requirements: 13.1, 13.2, 13.3_

  - [ ]* 10.2 编写向量检索往返兼容性属性测试（P2）
    - **Property 17: 向量检索往返兼容性**
    - **Validates: Requirements 13.1**

- [ ] 11. Checkpoint — Phase 1 图谱底座就绪
  - 验收标准：
    - 上传文档 → Ingest → GraphDigestJob 完整流程可运行
    - 增量更新：上传第二篇文档后仅处理新 chunks，已有图谱数据保留
    - 并发控制：幂等键命中返回已有 job；同 subject 非幂等重复请求返回 409
    - staging/active 两层状态：Job 失败时 pending 数据被清理（通过 created_by_job_id 精确清理）
    - 图谱查询 API（nodes/query、nodes/detail）返回正确数据
    - 向量检索功能不受影响

### Phase 2 — 教学单元

- [ ] 12. 教学单元数据访问层
  - [ ] 12.1 在 `backend/app/repositories/curriculum_repo.py` 中实现教学单元 Repository（Phase 2 部分）
    - 教学单元：create_teaching_unit、get_teaching_unit_by_id、find_unit_by_signature、find_units_overlapping_nodes、find_unit_by_normalized_name、list_units_by_subject、create_unit_revision、deactivate_old_unit_revisions、create_unit_membership、list_memberships_by_unit、find_unit_by_node
    - 课程任务：create_curriculum_job、update_curriculum_job
    - _Requirements: 2.1, 2.4, 2.5, 8.2_

  - [ ]* 12.2 编写 curriculum_repo 教学单元部分单元测试
    - 测试 CRUD 函数、签名查找、UniqueConstraint(unit_id, knowledge_node_id, role) 冲突
    - _Requirements: 2.4, 2.5_

- [ ] 13. 教学单元生成
  - [ ] 13.1 创建 `backend/app/agents/digest/unit_builder.py`，实现局部子图提取与距离计算
    - 从 Impact Set 中受影响的 active 节点出发，提取 changed nodes + 1-hop + 2-hop 子图
    - 实现 compute_unit_distance 多维距离函数（semantic 0.30 + graph_relation 0.25 + co_outline 0.20 + prerequisite_penalty 0.15 + type_compatibility 0.10）
    - 实现 pairwise 距离矩阵计算
    - _Requirements: 9.1, 9.2_

  - [ ] 13.2 在 `unit_builder.py` 中实现聚类切割 + 角色分配 + 身份签名
    - 实现层次聚类（agglomerative clustering）→ 切割阈值 → leaf teaching units
    - 实现角色分配逻辑：core / support / example / prerequisite_bridge
    - 使用 compute_member_signature 计算结构签名，通过 find_unit_by_signature 查找已有单元
    - 新节点优先尝试加入已有 unit（距离 < 阈值），否则形成新 unit
    - _Requirements: 9.1, 9.3, 9.5, 9.6_

  - [ ]* 13.3 编写教学单元核心唯一不变式属性测试（P0）
    - **Property 2: 教学单元核心唯一不变式**
    - **Validates: Requirements 2.4**

  - [ ] 13.4 在 `unit_builder.py` 中实现 LLM 命名 + 单元 Upsert
    - 实现 derive_teaching_units 异步函数（组合子图提取 + 聚类 + 命名）
    - 对每个新/变更的教学单元调用 LLM 生成单元名称、摘要和学习目标
    - 创建 TeachingUnit(status="pending") + TeachingUnitRevision + TeachingUnitMembership，所有记录设置 created_by_job_id
    - **禁止在 unit_builder 内部调用任何 publish/archive helper**
    - 已有单元（通过 signature 匹配到）：更新 revision，不重建 unit，不改 unit status
    - LLM 命名失败时 fallback 到 core 节点名称
    - 在 kg_prompts.py 中追加教学单元命名 prompt
    - **旧 TeachingUnit 的 deprecated/merged 生命周期规则**：
      - 若新派生结果通过 member_signature 命中已有 unit → 更新 revision，不改 unit status
      - 若旧 active unit 在本次受影响范围内（Impact Set affected_unit_ids）未被新结果保留 → 在 finalize_curriculum_node 中标记为 deprecated / merged
      - 未受影响范围外的旧 unit 保持 active，不做任何变更
    - _Requirements: 9.1, 9.4, 9.5_

- [ ] 14. CurriculumDeriveJob 工作流 v1（仅 units）
  - [ ] 14.1 创建 `backend/app/agents/digest/curriculum_workflow.py`，实现课程派生工作流状态机 v1
    - 定义 CurriculumDeriveState TypedDict（含 snapshot_id: int | None）
    - **snapshot_id 语义说明**：snapshot_id 仅供 v2/v3 使用，v1 恒为 None（v1 不创建 CurriculumSnapshot）
    - 实现 LangGraph StateGraph 节点：derive_units_node、finalize_curriculum_node（v1：仅激活 pending 单元 + 更新 job 状态）、fail_curriculum_node
    - derive_theme_tree_node 和 derive_prereq_dag_node 在 v1 中为 pass-through（Phase 3/4 实现）
    - fail_curriculum_node 调用 cleanup_pending_by_job（按 created_by_job_id）清理 pending 数据
    - 所有步骤通过 update_job_progress 更新进度
    - _Requirements: 8.2, 9.1_

  - [ ]* 14.2 编写修订唯一当前版本属性测试（P0）
    - **Property 1: 修订唯一当前版本不变式**
    - **Validates: Requirements 1.7, 1.8, 2.5**

- [ ] 15. 教学单元服务与 API
  - [ ] 15.1 在 `knowledge_graph_service.py` 中追加教学单元服务函数
    - 实现 run_curriculum_derive_background
    - 实现 get_teaching_units、get_teaching_unit_detail
    - _Requirements: 12.5, 12.6_

  - [ ] 15.2 在 `schemas/knowledge_graph.py` 中追加教学单元 Schema
    - 请求：UnitsQueryRequest、UnitDetailRequest
    - 响应：TeachingUnitResponse、TeachingUnitDetailResponse
    - _Requirements: 12.5, 12.6_

  - [ ] 15.3 在 `api/knowledge.py` 中追加教学单元路由
    - POST /api/v1/subjects/{subject}/units/query — 分页查询教学单元
    - POST /api/v1/subjects/{subject}/units/detail — 教学单元详情
    - _Requirements: 12.5, 12.6_

- [ ] 16. Checkpoint — Phase 2 教学单元就绪
  - 验收标准：
    - GraphDigestJob → CurriculumDeriveJob（v1）完整流程可运行
    - TeachingUnit 稳定身份：同一批成员节点即使 LLM 改名，通过 member_signature 仍能定位到同一 unit
    - CurriculumDeriveJob 失败时 pending 单元/memberships 被精确清理
    - 教学单元查询 API（units/query、units/detail）返回正确数据
    - 每个 active KnowledgeNode 至多属于一个 unit 的 core 角色

### Phase 3 — 主题树

- [ ] 17. 主题树数据访问层
  - [ ] 17.1 在 `curriculum_repo.py` 中追加锚点与主题树 Repository
    - 锚点：create_taxonomy_anchor、list_anchors_by_subject、get_uncategorized_anchor
    - 主题树：create_theme_tree_version、get_current_theme_tree_version、create_theme_tree_version_with_optimistic_lock、create_theme_tree_node、create_unit_tree_membership
    - _Requirements: 3.1, 3.5, 3.6_

  - [ ]* 17.2 编写主题树 repo 单元测试
    - 测试乐观锁冲突、UniqueConstraint(subject, version_no) 冲突、UniqueConstraint(tree_version_id, tree_node_id, teaching_unit_id, membership_role) 冲突
    - _Requirements: 3.5_

- [ ] 18. 主题树派生
  - [ ] 18.1 创建 `backend/app/agents/digest/theme_tree_builder.py`，实现主题树构建器
    - 实现 derive_theme_tree 异步函数，按 Step A-E：生成 Anchor Skeleton → 挂载 TeachingUnit → 计算 membership_score（6 源证据融合）→ 确定归属（human_fixed 绝对优先 → 稳定规则 → 待归类池）→ 生成 ThemeTreeVersion(status="draft")
    - **UNCATEGORIZED 固定节点规则**：builder 必须确保每个 ThemeTreeVersion 都生成一个固定的 UNCATEGORIZED 节点（node_type="uncategorized"），所有低于 membership_threshold 的 unit 挂到该节点
    - 实现 compute_unit_membership_score 函数
    - MVP 采用"逻辑局部重算 + 存储全量快照"版本策略
    - **禁止在 theme_tree_builder 内部调用任何 publish/archive helper；只能创建 draft version + ThemeTreeNode + UnitTreeMembership**
    - 所有新建记录设置 created_by_job_id
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9, 10.10, 3.6_

  - [ ]* 18.2 编写主题树归属唯一属性测试（P0）
    - **Property 3: 主题树归属唯一不变式**
    - **Validates: Requirements 3.5**

  - [ ]* 18.3 编写锚点优先级稳定性属性测试（P2）
    - **Property 14: 锚点骨架优先级稳定性**
    - **Validates: Requirements 10.2**

- [ ] 19. CurriculumDeriveJob 工作流 v2（units + theme tree）
  - [ ] 19.1 升级 `curriculum_workflow.py`，启用 derive_theme_tree_node
    - finalize_curriculum_node v2：调用 activate_curriculum_entities_by_job 批量激活 pending 单元 → publish tree version → 创建 CurriculumSnapshot（仅含 tree version）→ 归档旧 tree version + 旧 snapshot → 标记受影响范围内未被保留的旧 active unit 为 deprecated → 更新 job 状态
    - **publish/archive 操作仅在 finalize_curriculum_node 中执行**
    - _Requirements: 8.2, 8.3, 10.9_

- [ ] 20. 主题树服务与 API
  - [ ] 20.1 在 `knowledge_graph_service.py` 中追加主题树服务函数
    - 实现 get_current_theme_tree、manage_taxonomy_anchors
    - _Requirements: 12.7, 12.9_

  - [ ] 20.2 在 `schemas/knowledge_graph.py` 中追加主题树 Schema
    - 请求：AnchorManageRequest
    - 响应：ThemeTreeResponse、CurriculumSnapshotResponse
    - _Requirements: 12.7, 12.9, 12.10_

  - [ ] 20.3 在 `api/knowledge.py` 中追加主题树路由
    - POST /api/v1/subjects/{subject}/theme-tree/current — 当前主题树
    - POST /api/v1/subjects/{subject}/taxonomy/anchors — 锚点管理
    - _Requirements: 12.7, 12.9_

- [ ] 21. Checkpoint — Phase 3 主题树就绪
  - 验收标准：
    - CurriculumDeriveJob v2 完整流程可运行（units + theme tree）
    - 版本发布原子性：builder 只产出 draft，finalize 统一发布，无"旧版本已 archived 但新版本未 published"窗口期
    - 每个 TeachingUnit 在同一 ThemeTreeVersion 中至多一个 primary membership
    - 主题树查询 API 返回正确数据
    - CurriculumSnapshot 正确记录 tree version

### Phase 4 — 先修 DAG

- [ ] 22. 先修 DAG 数据访问层
  - [ ] 22.1 在 `curriculum_repo.py` 中追加先修 DAG Repository
    - 实现 create_prereq_dag_version、get_current_prereq_dag_version、create_prereq_dag_version_with_optimistic_lock、create_unit_dependency、list_dependencies_by_version、list_dependencies_by_unit
    - _Requirements: 4.1, 4.2, 11.1, 11.5_

  - [ ]* 22.2 编写先修 DAG repo 单元测试
    - 测试乐观锁冲突、UniqueConstraint(dag_version_id, source_unit_id, target_unit_id, dependency_type) 冲突
    - _Requirements: 4.2_

- [ ] 23. 先修 DAG 派生
  - [ ] 23.1 创建 `backend/app/agents/digest/prereq_dag_builder.py`，实现先修 DAG 构建器
    - 实现 derive_prereq_dag 异步函数，按 Step 1-5：
      - Step 1：收集节点级依赖边（prerequisite_of + part_of 约束传播 + defined_by 保守策略）
      - Step 2：聚合为单元级依赖（同一 unit 内部的依赖边不产生 UnitDependency）
      - Step 3：去环处理（Tarjan SCC + 断开 confidence 最低边 + 记录到 derivation_metadata_json）
      - Step 4：传递约简（transitive reduction，移除冗余间接依赖）
      - Step 5：生成 PrereqDagVersion(status="draft")
    - **硬规则：先去环再约简**，因为 transitive reduction 的定义基于 DAG，对含环图行为未定义
    - **MVP defined_by 范围**：defined_by 优先用于单元内聚合；仅当 Concept 与 Definition 已被分到不同 units 且满足高置信度（confidence > 0.7）+ 无聚类并入证据 + 额外支持信号时才生成 unit-level dependency candidate
    - 实现 aggregate_unit_dependencies、transitive_reduction、break_cycles 函数
    - MVP 采用"逻辑局部重算 + 存储全量快照"版本策略
    - **禁止在 prereq_dag_builder 内部调用任何 publish/archive helper；只能创建 draft version + UnitDependency**
    - 所有新建记录设置 created_by_job_id
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 4.3, 4.4_

  - [ ]* 23.2 编写 DAG 无环性属性测试（P0）
    - **Property 15: DAG 无环性不变式**
    - 验证 break_cycles 后的输出图不含环（使用 Tarjan/DFS 检测）
    - **Validates: Requirements 4.3, 11.4**

  - [ ]* 23.3 编写 DAG 传递约简属性测试（P1）
    - **Property 16: 传递约简正确性**
    - 验证 transitive_reduction 后的 DAG 可达性与原 DAG 一致（即 transitive closure 不变），且边数 ≤ 原 DAG
    - **Validates: Requirements 4.4, 11.3**

- [ ] 24. CurriculumDeriveJob 工作流 v3（units + theme tree + prereq dag）
  - [ ] 24.1 升级 `curriculum_workflow.py`，启用 derive_prereq_dag_node
    - finalize_curriculum_node v3：调用 activate_curriculum_entities_by_job 批量激活 pending 单元 → publish tree version → publish dag version → 创建 CurriculumSnapshot（含 tree version + dag version）→ 归档旧 tree version + 旧 dag version + 旧 snapshot → 标记受影响范围内未被保留的旧 active unit 为 deprecated → 更新 job 状态
    - **publish/archive 操作仅在 finalize_curriculum_node 中执行**
    - _Requirements: 8.2, 8.3, 10.9, 11.5_

  - [ ]* 24.2 编写版本归档不变式属性测试（P2）
    - **Property 19: 版本归档不变式**
    - 验证 finalize 完成后：每个 subject 至多一个 published ThemeTreeVersion、至多一个 published PrereqDagVersion、至多一个 published CurriculumSnapshot；旧版本均为 archived
    - **Validates: Requirements 8.3, 10.9, 11.5**

- [ ] 25. 先修 DAG 服务与 API
  - [ ] 25.1 在 `knowledge_graph_service.py` 中追加先修 DAG 服务函数
    - 实现 get_current_prereq_dag、get_current_curriculum_snapshot
    - _Requirements: 12.8, 12.10_

  - [ ] 25.2 在 `schemas/knowledge_graph.py` 中追加先修 DAG Schema
    - 响应：PrereqDagResponse（含 UnitDependencyResponse 列表）、CurriculumSnapshotResponse（更新：含 tree_version_id + dag_version_id）
    - _Requirements: 12.8, 12.10_

  - [ ] 25.3 在 `api/knowledge.py` 中追加先修 DAG 路由
    - POST /api/v1/subjects/{subject}/prereq-dag/current — 当前先修 DAG
    - POST /api/v1/subjects/{subject}/curriculum/current — 当前课程快照（tree + dag 组合版本）
    - _Requirements: 12.8, 12.10_

- [ ] 26. Checkpoint — Phase 4 先修 DAG + 完整课程 e2e 就绪
  - 验收标准：
    - CurriculumDeriveJob v3 完整流程可运行（units + theme tree + prereq dag）
    - DAG 无环性：任意输入下 break_cycles 后输出图不含环
    - 传递约简正确性：约简后可达性不变，边数不增
    - 版本归档一致性：每个 subject 至多一个 published tree/dag/snapshot
    - 先修 DAG 查询 API 返回正确数据
    - CurriculumSnapshot 正确记录 tree version + dag version 组合
    - 完整 e2e：上传文档 → Ingest → GraphDigestJob → CurriculumDeriveJob v3 → 图谱/单元/主题树/先修 DAG/课程快照 API 全部返回正确数据
    - 增量 e2e：上传第二篇文档后仅处理新 chunks，已有课程结构局部更新

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- **版本发布边界**：builder 只能创建 draft/pending，publish/archive 仅供 finalize_curriculum_node 使用
- **cleanup 两层策略**：普通路径按 job_id 精确清理，管理员路径按 subject + TTL + 无 processing job 条件清理
- **批量激活集中 helper**：activate_graph_entities_by_job / activate_curriculum_entities_by_job 集中管理状态转换，避免遗漏
