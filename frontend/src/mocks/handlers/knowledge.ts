import { http, HttpResponse } from "msw";
import type { OutlineResponse } from "../../api/generated/model";

const mockOutlines: OutlineResponse[] = [
  {
    knowledge_id: 1,
    title: "函数与极限",
    nodes: [
      { id: 1, title: "函数的概念", level: 1, children: [
        { id: 2, title: "定义域与值域", level: 2 },
        { id: 3, title: "复合函数", level: 2 },
      ]},
      { id: 4, title: "极限的定义", level: 1, children: [
        { id: 5, title: "数列极限", level: 2 },
        { id: 6, title: "函数极限", level: 2 },
      ]},
    ],
  },
  {
    knowledge_id: 2,
    title: "导数与微分",
    nodes: [
      { id: 7, title: "导数的定义", level: 1, children: [
        { id: 8, title: "几何意义", level: 2 },
        { id: 9, title: "物理意义", level: 2 },
      ]},
      { id: 10, title: "求导法则", level: 1, children: [
        { id: 11, title: "基本求导公式", level: 2 },
        { id: 12, title: "链式法则", level: 2 },
      ]},
    ],
  },
];

export const knowledgeHandlers = [
  http.post("/api/v1/knowledge/:subject/outline", () => {
    return HttpResponse.json(mockOutlines);
  }),
];
