import { knowledgeOverviewApiV1SubjectsSubjectKnowledgeOverviewPost } from "./generated/knowledge";
import type {
  CurriculumSnapshotResponse,
  FullGraphResponse,
  KnowledgeOverviewBuildStatus as KnowledgeOverviewBuildStatusModel,
  KnowledgeNodeResponse,
  KnowledgeOverviewRequest,
  KnowledgeOverviewResponse as KnowledgeOverviewPayload,
  KnowledgeOverviewStats as KnowledgeOverviewStatsModel,
  PrereqDagResponse,
  TeachingUnitResponse,
  ThemeTreeNodeResponse,
  ThemeTreeResponse,
  TreeUnitItem,
  UnitDependencyItem,
  GraphEdgeResponse,
} from "./generated/model";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

export type KnowledgeOverviewThemeUnit = TreeUnitItem;
export type KnowledgeOverviewThemeNode = ThemeTreeNodeResponse;
export type KnowledgeOverviewThemeTree = ThemeTreeResponse;
export type KnowledgeOverviewDependency = UnitDependencyItem;
export type KnowledgeOverviewPrereqDag = PrereqDagResponse;
export type KnowledgeOverviewNode = KnowledgeNodeResponse;
export type KnowledgeOverviewEdge = GraphEdgeResponse;
export type KnowledgeOverviewGraph = FullGraphResponse;
export type KnowledgeOverviewUnit = TeachingUnitResponse;
export type KnowledgeOverviewSnapshot = CurriculumSnapshotResponse;
export type KnowledgeOverviewStats = KnowledgeOverviewStatsModel;
export type KnowledgeOverviewBuildStatus = KnowledgeOverviewBuildStatusModel;

export interface KnowledgeOverviewResponse {
  subject: string;
  generated_at: string;
  snapshot: KnowledgeOverviewSnapshot | null;
  theme_tree: KnowledgeOverviewThemeTree | null;
  prereq_dag: KnowledgeOverviewPrereqDag | null;
  graph: KnowledgeOverviewGraph | null;
  units: KnowledgeOverviewUnit[];
  stats: KnowledgeOverviewStats;
  build_status: KnowledgeOverviewBuildStatus | null;
}

export interface FetchKnowledgeOverviewOptions {
  include?: string[];
  full?: boolean;
  jobId?: number;
}

const DEFAULT_STATS: KnowledgeOverviewStats = {
  node_count: 0,
  edge_count: 0,
  unit_count: 0,
  theme_node_count: 0,
  dependency_count: 0,
};

export async function fetchKnowledgeOverview(
  subject: string,
  options?: FetchKnowledgeOverviewOptions,
): Promise<KnowledgeOverviewResponse> {
  const req: KnowledgeOverviewRequest = {
    full: options?.full ?? (options?.include ? false : true),
    include: options?.include,
    job_id: options?.jobId,
  };
  const response = await knowledgeOverviewApiV1SubjectsSubjectKnowledgeOverviewPost(subject, req);
  const payload = unwrapOrvalResponse<KnowledgeOverviewPayload>(response);

  if (!payload) {
    throw new Error("加载知识概览失败");
  }

  return {
    subject: payload.subject,
    generated_at: payload.generated_at,
    snapshot: payload.snapshot ?? null,
    theme_tree: payload.theme_tree ?? null,
    prereq_dag: payload.prereq_dag ?? null,
    graph: payload.graph ?? null,
    units: payload.units ?? [],
    stats: payload.stats ?? DEFAULT_STATS,
    build_status: payload.build_status ?? null,
  };
}
