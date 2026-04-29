import { apiClient } from "../api/client";
import type { DocGenGetResponse } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export function buildKnowledgeDocStateQueryKey(courseId: string) {
  return ["knowledge-doc-state", courseId] as const;
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
