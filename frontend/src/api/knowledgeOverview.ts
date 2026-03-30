import { apiClient } from "./client";
import type { ApiResponse } from "./types";
import type {
  CurriculumSnapshotResponse,
  FullGraphResponse,
  GraphEdgeResponse,
  KnowledgeNodeResponse,
  PrereqDagResponse,
  TeachingUnitResponse,
  ThemeTreeNodeResponse,
  ThemeTreeResponse,
  TreeUnitItem,
  UnitDependencyItem,
} from "./generated/model";

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

interface KnowledgeOverviewRequest {
  include?: string[];
  full?: boolean;
}

export interface KnowledgeOverviewStats {
  node_count: number;
  edge_count: number;
  unit_count: number;
  theme_node_count: number;
  dependency_count: number;
}

export interface KnowledgeOverviewResponse {
  subject: string;
  generated_at: string;
  snapshot: KnowledgeOverviewSnapshot | null;
  theme_tree: KnowledgeOverviewThemeTree | null;
  prereq_dag: KnowledgeOverviewPrereqDag | null;
  graph: KnowledgeOverviewGraph | null;
  units: KnowledgeOverviewUnit[];
  stats: KnowledgeOverviewStats;
}

export interface FetchKnowledgeOverviewOptions {
  include?: string[];
  full?: boolean;
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
  const request: KnowledgeOverviewRequest = {
    full: options?.full ?? !options?.include,
    include: options?.include,
  };

  const response = await apiClient<ApiResponse<KnowledgeOverviewResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/overview`,
    data: request,
  });
  const payload = response.data;

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
  };
}
