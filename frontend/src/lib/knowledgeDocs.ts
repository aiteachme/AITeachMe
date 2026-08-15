import { apiClient, LONG_RUNNING_API_TIMEOUT_MS } from "../api/client";
import type { CourseVectorStatusResponse, DocGenGetResponse } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export function buildKnowledgeDocStateQueryKey(courseId: string) {
  return ["knowledge-doc-state", courseId] as const;
}

export interface CourseVectorIndexRebuildResult {
  status: "ready" | "rebuilt";
  indexed_chunk_count: number;
  vector_status: CourseVectorStatusResponse;
}

export async function fetchKnowledgeDocState(
  courseId: string,
): Promise<DocGenGetResponse> {
  const response = await apiClient<ApiResponse<DocGenGetResponse>>({
    method: "POST",
    url: `/api/v1/courses/${courseId}/knowledge/docs`,
  });

  return response.data ?? { exists: false };
}

export async function rebuildCourseVectorIndex(
  courseId: string,
): Promise<CourseVectorIndexRebuildResult> {
  const response = await apiClient<ApiResponse<CourseVectorIndexRebuildResult>>({
    method: "POST",
    url: `/api/v1/courses/${courseId}/knowledge/docs/vector-index/rebuild`,
    timeout: LONG_RUNNING_API_TIMEOUT_MS,
  });

  if (!response.data) {
    throw new Error("向量索引重建未返回结果。");
  }
  return response.data;
}
