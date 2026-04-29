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

export interface KnowledgeGraphBuildData {
  course?: string;
  status?: string;
  requested_at?: string;
  build_group_id?: string | null;
  build_session_id?: string | null;
  source_file_ids?: string[];
  message?: string;
}

export interface KnowledgeBuildCancelData {
  course?: string;
  status?: string;
  cancelled_task_count?: number;
  requested_at?: string | null;
  message?: string;
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

export function buildKnowledgeBuildRuntimeQueryKey(courseId: string) {
  return ["knowledge-doc-build", courseId] as const;
}

export function buildRuntimeFailureBackoffMs(fetchFailureCount: number): number | null {
  if (fetchFailureCount <= 0) return null;
  const cappedFailures = Math.min(fetchFailureCount - 1, 3);
  return Math.min(30_000, 5_000 * 2 ** cappedFailures);
}

export async function fetchKnowledgeBuildRuntime(
  courseId: string,
): Promise<KnowledgeBuildRuntimeResponse> {
  const response = await apiClient<ApiResponse<KnowledgeBuildRuntimeResponse>>({
    method: "POST",
    url: `/api/v1/courses/${courseId}/knowledge/build/runtime`,
  });

  return response.data ?? {};
}

export async function triggerKnowledgeGraphBuild(courseId: string): Promise<KnowledgeGraphBuildData> {
  const response = await apiClient<ApiResponse<KnowledgeGraphBuildData>>({
    method: "POST",
    url: `/api/v1/courses/${courseId}/knowledge/build/graph`,
  });

  return response.data ?? {};
}

export async function cancelKnowledgeBuild(courseId: string): Promise<KnowledgeBuildCancelData> {
  const response = await apiClient<ApiResponse<KnowledgeBuildCancelData>>({
    method: "POST",
    url: `/api/v1/courses/${courseId}/knowledge/build/cancel`,
  });

  return response.data ?? {};
}
