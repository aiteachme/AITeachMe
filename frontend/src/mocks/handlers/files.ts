import { http, HttpResponse } from "msw";

const mockFiles = [
  { id: 1, filename: "高数第一章.pdf", filetype: "pdf", status: "done", markdown_ready: true, latest_updated_at: "2026-03-14T10:00:00Z", created_at: "2026-03-14T10:00:00Z" },
  { id: 2, filename: "导数与微分笔记.docx", filetype: "docx", status: "done", markdown_ready: true, latest_updated_at: "2026-03-13T09:00:00Z", created_at: "2026-03-13T09:00:00Z" },
  { id: 3, filename: "积分练习题.pdf", filetype: "pdf", status: "pending", markdown_ready: false, latest_updated_at: "2026-03-16T08:00:00Z", created_at: "2026-03-16T08:00:00Z" },
];

export const fileHandlers = [
  http.post("/api/v1/subjects/:subject/files/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockFiles, total: mockFiles.length },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/upload", async () => {
    await new Promise((r) => setTimeout(r, 800));
    return HttpResponse.json({
      code: 0,
      data: { subject: "gaoshu", file_ids: [99], filenames: ["新文件.pdf"] },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/delete", () => {
    return HttpResponse.json({ code: 0, data: { deleted_file_ids: [1] } });
  }),

  http.post("/api/v1/subjects/:subject/files/parse", () => {
    return HttpResponse.json({ code: 0, data: { accepted_file_ids: [99] } });
  }),
];
