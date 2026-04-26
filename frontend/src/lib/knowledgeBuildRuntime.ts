import { apiClient } from "../api/client";
import type {
  BuildPreviewChapterPreviewResponse,
  BuildPreviewNodeResponse,
  BuildPreviewRecentEventResponse,
  BuildPreviewChapterProgressResponse,
  BuildPreviewMergePreviewResponse,
  BuildSampleCardResponse,
  KnowledgeBuildMetricsResponse,
  KnowledgeBuildPreviewResponse,
  KnowledgeGraphBuildMetricsResponse,
} from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export interface KnowledgeBuildLaneRuntime {
  lane: "aggregate" | "docgen" | "graph";
  build_group_id?: string | null;
  status?: string | null;
  stage?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  requested_at?: string | null;
  error_message?: string | null;
  progress_pct?: number;
  current_stage_description?: string | null;
  metrics?: Record<string, unknown>;
}

export interface KnowledgeBuildRuntimeResponse {
  build_group_id?: string | null;
  aggregate?: KnowledgeBuildLaneRuntime | null;
  docgen?: KnowledgeBuildLaneRuntime | null;
  graph?: KnowledgeBuildLaneRuntime | null;
  docgen_preview?: KnowledgeBuildPreviewResponse | null;
  docgen_metrics?: KnowledgeBuildMetricsResponse | null;
  graph_metrics?: KnowledgeGraphBuildMetricsResponse | null;
}

export type KnowledgeBuildPreview = KnowledgeBuildPreviewResponse;
export type KnowledgeBuildMetrics = KnowledgeBuildMetricsResponse;
export type KnowledgeGraphBuildMetrics = KnowledgeGraphBuildMetricsResponse;
export type BuildPreviewNode = BuildPreviewNodeResponse;
export type BuildPreviewRecentEvent = BuildPreviewRecentEventResponse;
export type BuildPreviewChapterProgress = BuildPreviewChapterProgressResponse;
export type BuildPreviewChapterPreview = BuildPreviewChapterPreviewResponse;
export type BuildPreviewMergePreview = BuildPreviewMergePreviewResponse;
export type BuildSampleCard = BuildSampleCardResponse;

export function buildKnowledgeBuildRuntimeQueryKey(subjectId: string) {
  return ["knowledge-doc-build", subjectId] as const;
}

export async function fetchKnowledgeBuildRuntime(
  subjectId: string,
): Promise<KnowledgeBuildRuntimeResponse> {
  const response = await apiClient<ApiResponse<KnowledgeBuildRuntimeResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subjectId}/knowledge/build/runtime`,
  });

  return response.data ?? {};
}
