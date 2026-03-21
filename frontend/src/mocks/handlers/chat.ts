import { http, HttpResponse } from "msw";

const mockHistory = [
  { id: 1, turn_id: "turn-1", role: "user", content: "导数的几何意义是什么？", created_at: "2026-03-14T10:00:00Z" },
  { id: 2, turn_id: "turn-1", role: "assistant", content: "导数 f'(x₀) 表示曲线 y=f(x) 在点 (x₀, f(x₀)) 处切线的斜率，描述函数在该点的瞬时变化率。", created_at: "2026-03-14T10:00:05Z" },
];

export const chatHandlers = [
  // SSE 流式对话
  http.post("/api/v1/subjects/:subject/chats/send", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const tokens = ["这是", "一个", "模拟的", "流式", "回答，", "后端", "接入后", "会替换", "为真实", "内容。"];
        for (const token of tokens) {
          await new Promise((r) => setTimeout(r, 80));
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ content: token })}\n\n`));
        }
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ turn_id: "mock-turn", contexts: null })}\n\n`));
        controller.close();
      },
    });
    return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
  }),

  // 历史记录
  http.post("/api/v1/subjects/:subject/chats/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockHistory, total: mockHistory.length },
    });
  }),

  // 清空记录
  http.post("/api/v1/subjects/:subject/chats/clear", () => {
    mockHistory.length = 0;
    return HttpResponse.json({ code: 0, data: { cleared: true, deleted_count: 2 } });
  }),
];
