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

export type KnowledgeDocExportFormat = "md" | "pdf";

export async function downloadKnowledgeDocExport(
  subjectId: string,
  format: KnowledgeDocExportFormat,
): Promise<void> {
  const blob = await apiClient<Blob>({
    method: "GET",
    url: `/api/v1/subjects/${subjectId}/knowledge/docs/export`,
    params: { format },
    responseType: "blob",
    timeout: 0,
  });
  const url = URL.createObjectURL(blob);
  const filename = `knowledge_doc_${subjectId}.${format}`;
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
