export async function downloadSubjectPackage(subject: string): Promise<void> {
  const token = localStorage.getItem("token");
  const base = import.meta.env.VITE_API_URL ?? "";
  const url = `${base}/api/v1/subjects/${encodeURIComponent(subject)}/export`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error(`导出失败 (${response.status})`);
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
