import { buildApiUrl, getDeviceKey } from "../api/client";

export async function downloadSubjectPackage(subject: string): Promise<void> {
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
    body: JSON.stringify({}),
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
  let filename = `${subject}.atmx`;
  if (disposition) {
    const match = disposition.match(/filename[^;=\n]*=["']?([^"';\n]*)["']?/);
    if (match?.[1]) {
      filename = match[1];
    }
  }

  const link = document.createElement("a");
  const blobUrl = URL.createObjectURL(blob);
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}
