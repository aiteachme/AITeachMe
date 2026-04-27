import { buildApiUrl, getDeviceKey } from "../api/client";
import { apiClient } from "../api/client";
import type { ExportOptions } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export interface ImportResultData {
  subject_id: string;
  subject_name: string;
  imported_counts: Record<string, number>;
  warnings: string[];
}

function stripQuotes(value: string): string {
  const trimmed = value.trim();
  if ((trimmed.startsWith("\"") && trimmed.endsWith("\"")) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function decodeHeaderFilename(value: string): string {
  const cleaned = stripQuotes(value);
  try {
    return decodeURIComponent(cleaned);
  } catch {
    return cleaned;
  }
}

function parseContentDispositionFilename(disposition: string | null): string | null {
  if (!disposition) return null;

  const encodedMatch = disposition.match(/filename\*\s*=\s*([^;]+)/i);
  if (encodedMatch?.[1]) {
    const value = stripQuotes(encodedMatch[1]);
    const parts = value.split("''");
    return decodeHeaderFilename(parts.length > 1 ? parts.slice(1).join("''") : value);
  }

  const plainMatch = disposition.match(/filename\s*=\s*([^;]+)/i);
  return plainMatch?.[1] ? decodeHeaderFilename(plainMatch[1]) : null;
}

export async function downloadSubjectPackage(subject: string, options: ExportOptions = {}): Promise<void> {
  const token = localStorage.getItem("token");
  const url = buildApiUrl(`/api/v1/subjects/${encodeURIComponent(subject)}/export`);
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Device-Key": getDeviceKey(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(options),
  });
  if (!response.ok) {
    const rawText = await response.text();
    try {
      const payload = JSON.parse(rawText) as { detail?: string; message?: string };
      throw new Error(payload.detail || payload.message || `导出失败 (${response.status})`);
    } catch {
      throw new Error(rawText.trim() || `导出失败 (${response.status})`);
    }
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition");
  const filename = parseContentDispositionFilename(disposition) ?? `${subject}.atmx`;

  const link = document.createElement("a");
  const blobUrl = URL.createObjectURL(blob);
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

export async function importSubjectPackage(file: File, newName?: string): Promise<ImportResultData> {
  const formData = new FormData();
  formData.append("file", file);
  if (newName?.trim()) {
    formData.append("new_subject_name", newName.trim());
  }

  const response = await apiClient<ApiResponse<ImportResultData>>({
    method: "POST",
    url: "/api/v1/subjects/import",
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  if (!response.data) {
    throw new Error("导入结果为空");
  }
  return response.data;
}
