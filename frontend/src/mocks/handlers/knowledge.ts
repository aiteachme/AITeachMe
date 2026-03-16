import { http, HttpResponse } from "msw";

const mockDocsets = [
  {
    id: 1,
    title: "函数与极限",
    description: "第一章",
    status: "done",
    documents_count: 2,
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
  },
];

const mockTree = {
  docset_id: 1,
  title: "函数与极限",
  documents: [
    {
      document_id: 1,
      title: "高数第一章.pdf",
      nodes: [
        {
          id: 1, title: "函数的概念", level: 1, children: [
            { id: 2, title: "定义域与值域", level: 2, children: [] },
            { id: 3, title: "复合函数", level: 2, children: [] },
          ],
        },
        {
          id: 4, title: "极限的定义", level: 1, children: [
            { id: 5, title: "数列极限", level: 2, children: [] },
            { id: 6, title: "函数极限", level: 2, children: [] },
          ],
        },
      ],
    },
  ],
};

export const knowledgeHandlers = [
  http.post("/api/v1/subjects/:subject/knowledge/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockDocsets, total: mockDocsets.length },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/tree", () => {
    return HttpResponse.json({ code: 0, data: mockTree });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/status", () => {
    return HttpResponse.json({
      code: 0,
      data: { docset_id: 1, status: "done", progress: 100, message: "完成", docs_count: 2, chunks_count: 20 },
    });
  }),
];
