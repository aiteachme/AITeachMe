import { apiClient } from "./client";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
}

export interface FileItem {
  id: number;
  filename: string;
  filetype: string;
  status: string;
  ingest_status: string;
  markdown_ready: boolean;
  asset_ready: boolean;
  error_message: string | null;
  file_size_bytes: number | null;
  detected_language: string | null;
  estimated_pages: number | null;
  image_count: number | null;
  parser_used: string | null;
  latest_updated_at: string;
  created_at: string;
}

export interface FileAssetItem {
  path: string;
}

export interface FileGetData {
  file_id: number;
  filename: string;
  filetype: string;
  status: string;
  ingest_status: string;
  markdown_ready: boolean;
  asset_ready: boolean;
  error_message: string | null;
  file_size_bytes: number | null;
  detected_language: string | null;
  estimated_pages: number | null;
  image_count: number | null;
  parser_used: string | null;
  markdown_content: string;
  assets: FileAssetItem[];
  latest_updated_at: string;
  created_at: string;
}

export interface FilesUploadData {
  subject: string;
  filenames: string[];
  uploaded_items: FileItem[];
  accepted_parse_file_ids: number[];
  started_parse_count: number;
}

export async function fetchFiles(subject: string): Promise<FileItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<FileItem>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/list`,
    data: { page: 1, size: 100 },
  });
  return res.data.items;
}

export async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const res = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/upload`,
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function retryFile(subject: string, fileId: number): Promise<void> {
  await apiClient({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/retry`,
    data: { file_id: fileId },
  });
}

export async function deleteFile(subject: string, fileId: number): Promise<void> {
  await apiClient({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/delete`,
    data: { file_id: fileId },
  });
}

export async function fetchFileResult(subject: string, fileId: number): Promise<FileGetData> {
  const res = await apiClient<ApiResponse<FileGetData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/get`,
    data: { file_id: fileId },
  });
  return res.data;
}
