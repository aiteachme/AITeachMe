import { apiClient } from "../api/client";
import type { DocGenGetResponse } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export function buildKnowledgeDocStateQueryKey(subjectId: string) {
  return ["knowledge-doc-state", subjectId] as const;
}

export async function fetchKnowledgeDocState(
  subjectId: string,
): Promise<DocGenGetResponse> {
  const response = await apiClient<ApiResponse<DocGenGetResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subjectId}/knowledge/docs`,
  });

  return response.data ?? { exists: false };
}
