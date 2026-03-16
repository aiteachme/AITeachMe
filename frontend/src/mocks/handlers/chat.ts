import { http, HttpResponse } from "msw";
import type { ChatHistoryResponse } from "../../api/generated/model";

const mockHistory: ChatHistoryResponse = {
  items: [
    {
      id: 1,
      turn_id: "turn-1",
      role: "user",
      content: "导数的几何意义是什么？",
      created_at: "2026-03-14T10:00:00Z",
    },
    {
      id: 2,
      turn_id: "turn-1",
      role: "assistant",
      content: "导数 f'(x₀) 表示曲线 y=f(x) 在点 (x₀, f(x₀)) 处切线的斜率。从几何上看，它描述了函数在该点的瞬时变化率。",
      created_at: "2026-03-14T10:00:05Z",
    },
  ],
  total: 2,
};

export const chatHandlers = [
  // SSE 流式对话 mock
  http.post("/api/v1/subjects/:subject/chat", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const tokens = ["这是", "一个", "模拟的", "流式", "回答，", "后端", "接入后", "会替换", "为真实", "内容。"];
        for (const token of tokens) {
          await new Promise((r) => setTimeout(r, 80));
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "token", content: token })}\n\n`));
        }
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "done" })}\n\n`));
        controller.close();
      },
    });
    return new HttpResponse(stream, {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),

  http.post("/api/v1/subjects/:subject/chat/history", () => {
    return HttpResponse.json(mockHistory);
  }),
];
