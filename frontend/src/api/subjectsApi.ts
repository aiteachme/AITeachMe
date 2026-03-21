import { apiClient } from "./client";

export interface SubjectItem {
  id: number;
  subject_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface SubjectDeleteImpactItem {
  key: string;
  label: string;
  count: number;
  description: string;
}

export interface SubjectDeletePreviewData {
  subject_id: string;
  subject_name: string;
  has_content: boolean;
  total_related_records: number;
  impact_items: SubjectDeleteImpactItem[];
  detail_counts: Record<string, number>;
}

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
}

export async function fetchSubjects(): Promise<SubjectItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<SubjectItem>>>({
    method: "POST",
    url: "/api/v1/subjects/list",
    data: { page: 1, size: 100 },
  });
  return res.data.items;
}

export async function createSubject(payload: {
  name: string;
  description: string;
}): Promise<SubjectItem> {
  const res = await apiClient<ApiResponse<SubjectItem>>({
    method: "POST",
    url: "/api/v1/subjects/add",
    data: payload,
  });
  return res.data;
}

export async function fetchSubjectDeletePreview(
  subjectId: string
): Promise<SubjectDeletePreviewData> {
  const res = await apiClient<ApiResponse<SubjectDeletePreviewData>>({
    method: "POST",
    url: "/api/v1/subjects/delete/preview",
    data: { subject_id: subjectId },
  });
  return res.data;
}

export async function deleteSubject(subjectId: string): Promise<void> {
  await apiClient({
    method: "POST",
    url: "/api/v1/subjects/delete",
    data: { subject_id: subjectId, force: true },
  });
}
