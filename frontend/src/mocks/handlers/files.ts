import { http, HttpResponse } from "msw";
import type { FileListResponse } from "../../api/generated/model";

const mockFiles: FileListResponse = {
  items: [
    { id: 1, filename: "高数第一章.pdf", filetype: "pdf", parse_status: "parsed", created_at: "2026-03-14T10:00:00Z" },
    { id: 2, filename: "导数与微分笔记.docx", filetype: "docx", parse_status: "parsed", created_at: "2026-03-13T09:00:00Z" },
    { id: 3, filename: "积分练习题1111.pdf", filetype: "pdf", parse_status: "pending", created_at: "2026-03-16T08:00:00Z" },
  ],
  total: 3,
};

export const fileHandlers = [
  http.post("/api/v1/files/:subject", () => {
    return HttpResponse.json(mockFiles);
  }),

  http.post("/api/v1/upload", async () => {
    await new Promise((r) => setTimeout(r, 800));
    return HttpResponse.json({ task_id: 99, filename: "新文件.pdf", subject: "高数" });
  }),

  http.delete("/api/v1/subjects/:subject/files/:fileId", () => {
    return HttpResponse.json({ success: true });
  }),
];
