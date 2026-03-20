/**
 * 知识图谱 API 调用层
 * 对应后端 backend/app/api/graph.py 的所有端点
 */
import { apiClient } from "./client";

/* ---------- 通用类型 ---------- */

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
}

/* ---------- 响应类型 ---------- */

export interface DigestBuildData {
  job_id: number;
  is_existing: boolean;
}

export interface GraphDigestJobResponse {
  id: number;
  subject: string;
  status: string;
  progress: number;
  current_step: string | null;
  input_chunk_count: number;
  nodes_added: number;
  nodes_updated: number;
  nodes_merged: number;
  edges_added: number;
  edges_updated: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface CurriculumJobResponse {
  id: number;
  subject: string;
  graph_job_id: number;
  status: string;
  progress: number;
  current_step: string | null;
  units_added: number;
  units_updated: number;
  theme_tree_version_id: number | null;
  prereq_dag_version_id: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DigestStatusResponse {
  graph_job: GraphDigestJobResponse;
  curriculum_job: CurriculumJobResponse | null;
  current_curriculum_snapshot_id: number | null;
}

export interface KnowledgeNodeResponse {
  id: number;
  subject: string;
  node_type: string;
  canonical_name: string;
  status: string;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface NodeRevisionItem {
  title: string;
  summary: string;
  body: string;
}

export interface AliasItem {
  id: number;
  alias: string;
  language: string;
  source: string;
  confidence: number;
  is_primary: boolean;
}

export interface IncidentEdgeItem {
  id: number;
  edge_type: string;
  direction: string;
  other_node_id: number;
  other_node_name: string;
  other_node_type: string;
  confidence: number;
}

export interface EvidenceSummary {
  id: number;
  document_id: number;
  chunk_id: number;
  quote_text: string;
  evidence_role: string;
  field_scope: string;
  confidence: number;
}

export interface KnowledgeNodeDetailResponse {
  id: number;
  subject: string;
  node_type: string;
  canonical_name: string;
  normalized_name: string;
  status: string;
  confidence: number;
  current_revision: NodeRevisionItem | null;
  aliases: AliasItem[];
  evidence: EvidenceSummary[];
  incident_edges: IncidentEdgeItem[];
  created_at: string;
  updated_at: string;
}

export interface TeachingUnitResponse {
  id: number;
  subject: string;
  canonical_name: string;
  status: string;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface UnitMembershipItem {
  id: number;
  knowledge_node_id: number;
  node_canonical_name: string;
  node_type: string;
  role: string;
  score: number;
}

export interface UnitRevisionItem {
  title: string;
  summary: string;
  learning_objectives: string[];
}

export interface TeachingUnitDetailResponse {
  id: number;
  subject: string;
  canonical_name: string;
  normalized_name: string;
  member_signature: string;
  status: string;
  confidence: number;
  current_revision: UnitRevisionItem | null;
  members: UnitMembershipItem[];
  created_at: string;
  updated_at: string;
}

export interface TreeUnitItem {
  teaching_unit_id: number;
  canonical_name: string;
  membership_role: string;
  membership_source: string;
  score: number;
}

export interface ThemeTreeNodeResponse {
  id: number;
  tree_version_id: number;
  anchor_id: number | null;
  parent_tree_node_id: number | null;
  title: string;
  node_type: string;
  order_index: number;
  summary: string;
  children: ThemeTreeNodeResponse[];
  units: TreeUnitItem[];
}

export interface ThemeTreeResponse {
  version_id: number;
  version_no: number;
  subject: string;
  status: string;
  created_at: string;
  tree: ThemeTreeNodeResponse[];
}

export interface UnitDependencyItem {
  id: number;
  source_unit_id: number;
  source_unit_name: string;
  target_unit_id: number;
  target_unit_name: string;
  dependency_type: string;
  confidence: number;
  supporting_edge_count: number;
}

export interface PrereqDagResponse {
  version_id: number;
  version_no: number;
  subject: string;
  status: string;
  created_at: string;
  dependencies: UnitDependencyItem[];
}

export interface CurriculumSnapshotResponse {
  id: number;
  subject: string;
  version_no: number;
  status: string;
  theme_tree_version_id: number | null;
  prereq_dag_version_id: number | null;
  syllabus_version_id: number | null;
  created_at: string;
}

/* ---------- API 调用函数 ---------- */

/** 触发增量构建 */
export async function triggerDigestBuild(
  subject: string,
  fileIds: number[],
  idempotencyKey?: string,
): Promise<DigestBuildData> {
  const res = await apiClient<ApiResponse<DigestBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/digest/build`,
    data: { file_ids: fileIds, idempotency_key: idempotencyKey },
  });
  return res.data;
}

/** 查询增量构建状态 */
export async function fetchDigestStatus(
  subject: string,
  jobId: number,
): Promise<DigestStatusResponse> {
  const res = await apiClient<ApiResponse<DigestStatusResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/digest/status`,
    data: { job_id: jobId },
  });
  return res.data;
}

/** 分页查询知识节点 */
export async function fetchGraphNodes(
  subject: string,
  nodeType?: string,
  page = 1,
  size = 50,
): Promise<PaginatedData<KnowledgeNodeResponse>> {
  const res = await apiClient<ApiResponse<PaginatedData<KnowledgeNodeResponse>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/graph/nodes/query`,
    data: { node_type: nodeType, page, size },
  });
  return res.data;
}

/** 知识节点详情 */
export async function fetchGraphNodeDetail(
  subject: string,
  nodeId: number,
): Promise<KnowledgeNodeDetailResponse> {
  const res = await apiClient<ApiResponse<KnowledgeNodeDetailResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/graph/nodes/detail`,
    data: { node_id: nodeId },
  });
  return res.data;
}

/** 分页查询教学单元 */
export async function fetchTeachingUnits(
  subject: string,
  status?: string,
  page = 1,
  size = 50,
): Promise<PaginatedData<TeachingUnitResponse>> {
  const res = await apiClient<ApiResponse<PaginatedData<TeachingUnitResponse>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/units/query`,
    data: { status, page, size },
  });
  return res.data;
}

/** 教学单元详情 */
export async function fetchTeachingUnitDetail(
  subject: string,
  unitId: number,
): Promise<TeachingUnitDetailResponse> {
  const res = await apiClient<ApiResponse<TeachingUnitDetailResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/units/detail`,
    data: { unit_id: unitId },
  });
  return res.data;
}

/** 获取当前主题树 */
export async function fetchThemeTree(
  subject: string,
): Promise<ThemeTreeResponse> {
  const res = await apiClient<ApiResponse<ThemeTreeResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/theme-tree/current`,
  });
  return res.data;
}

/** 获取当前先修 DAG */
export async function fetchPrereqDag(
  subject: string,
): Promise<PrereqDagResponse> {
  const res = await apiClient<ApiResponse<PrereqDagResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/prereq-dag/current`,
  });
  return res.data;
}

/** 获取当前课程快照 */
export async function fetchCurriculumSnapshot(
  subject: string,
): Promise<CurriculumSnapshotResponse> {
  const res = await apiClient<ApiResponse<CurriculumSnapshotResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/curriculum/current`,
  });
  return res.data;
}

/** 清空学科所有知识数据 */
export async function clearSubjectKnowledge(
  subject: string,
): Promise<{ subject: string; deleted_counts: Record<string, number> }> {
  const res = await apiClient<ApiResponse<{ subject: string; deleted_counts: Record<string, number> }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/clear`,
  });
  return res.data;
}

/* ---------- 全图查询（力导向图可视化） ---------- */

export interface GraphEdgeResponse {
  id: number;
  source_node_id: number;
  target_node_id: number;
  edge_type: string;
  weight: number;
  confidence: number;
}

export interface FullGraphResponse {
  nodes: KnowledgeNodeResponse[];
  edges: GraphEdgeResponse[];
}

/** 获取完整知识图谱（节点+边） */
export async function fetchFullGraph(
  subject: string,
): Promise<FullGraphResponse> {
  const res = await apiClient<ApiResponse<FullGraphResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/graph/full`,
  });
  return res.data;
}

/* ---------- 证据上下文 ---------- */

export interface EvidenceContextResponse {
  evidence_id: number;
  document_id: number;
  document_title: string;
  chunk_id: number;
  chunk_title: string;
  chunk_header_path: string;
  chunk_content: string;
  quote_text: string;
  highlight_start: number | null;
  highlight_end: number | null;
}

/** 获取证据原文上下文 */
export async function fetchEvidenceContext(
  subject: string,
  evidenceId: number,
): Promise<EvidenceContextResponse> {
  const res = await apiClient<ApiResponse<EvidenceContextResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/graph/evidence/context`,
    data: { evidence_id: evidenceId },
  });
  return res.data;
}
