import { http, HttpResponse } from "msw";

const mockContexts = [
  {
    chunk_id: 101,
    document_id: 11,
    title: "项目计划与执行",
    header_path: "一、项目目标 > 1.2 执行路径",
    score: 0.92,
  },
  {
    chunk_id: 102,
    document_id: 11,
    title: "项目计划与执行",
    header_path: "二、交付节奏 > 2.1 阶段拆解",
    score: 0.84,
  },
];

const mockChunkContext: Record<
  number,
  {
    chunk_id: number;
    document_id: number;
    document_title: string;
    chunk_title: string;
    chunk_header_path: string;
    chunk_content: string;
  }
> = {
  101: {
    chunk_id: 101,
    document_id: 11,
    document_title: "项目计划与执行",
    chunk_title: "项目计划与执行",
    chunk_header_path: "一、项目目标 > 1.2 执行路径",
    chunk_content:
      "本阶段重点是把复杂任务拆成稳定的工作流节点，先保证输入输出契约清晰，再逐步增强策略判断与引用能力。",
  },
  102: {
    chunk_id: 102,
    document_id: 11,
    document_title: "项目计划与执行",
    chunk_title: "项目计划与执行",
    chunk_header_path: "二、交付节奏 > 2.1 阶段拆解",
    chunk_content:
      "推荐按阶段推进：第一阶段先做可用闭环，第二阶段增强引用与上下文，第三阶段再完善教学策略与更多交互模式。",
  },
};

const mockHistory = [
  {
    id: 1,
    turn_id: "turn-1",
    role: "user",
    content: "导数的几何意义是什么？",
    contexts: null,
    created_at: "2026-03-14T10:00:00Z",
  },
  {
    id: 2,
    turn_id: "turn-1",
    role: "assistant",
    content:
      "导数表示函数在某一点的瞬时变化率，也可以理解成该点切线的斜率。如果你愿意，我还可以结合一个具体函数继续推导。",
    contexts: mockContexts,
    created_at: "2026-03-14T10:00:05Z",
  },
];

let nextMessageId = 3;

export const chatHandlers = [
  http.post("/api/v1/subjects/:subject/chats/send", async ({ request }) => {
    const body = (await request.json()) as {
      question?: string;
    };
    const question = body.question?.trim() || "请解释一下这份资料";
    const turnId = `mock-turn-${Date.now()}`;
    const encoder = new TextEncoder();
    const answer =
      "我先给你一个可用版解释：这份材料的重点是先把复杂系统拆成清晰工作流，再在每个节点补齐上下文、策略和持久化。这样后续改动会更稳，也更容易定位问题。";
    const tokens = answer.match(/.{1,8}/g) ?? [answer];

    const stream = new ReadableStream({
      async start(controller) {
        for (const token of tokens) {
          await sleep(70);
          controller.enqueue(
            encoder.encode(
              `event: token\ndata: ${JSON.stringify({ content: token })}\n\n`,
            ),
          );
        }

        controller.enqueue(
          encoder.encode(
            `event: done\ndata: ${JSON.stringify({ turn_id: turnId, contexts: mockContexts })}\n\n`,
          ),
        );
        controller.close();

        const createdAt = new Date().toISOString();
        mockHistory.push(
          {
            id: nextMessageId++,
            turn_id: turnId,
            role: "user",
            content: question,
            contexts: null,
            created_at: createdAt,
          },
          {
            id: nextMessageId++,
            turn_id: turnId,
            role: "assistant",
            content: answer,
            contexts: mockContexts,
            created_at: new Date(Date.now() + 1000).toISOString(),
          },
        );
      },
    });

    return new HttpResponse(stream, {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),

  http.post("/api/v1/subjects/:subject/chats/list", () =>
    HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        items: [...mockHistory].sort((left, right) =>
          right.created_at.localeCompare(left.created_at),
        ),
        total: mockHistory.length,
        page: 1,
        size: 100,
        pages: 1,
      },
    }),
  ),

  http.post("/api/v1/subjects/:subject/chats/clear", () => {
    const deletedCount = mockHistory.length;
    mockHistory.length = 0;
    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: { cleared: true, deleted_count: deletedCount },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/chunks/context", async ({ request }) => {
    const body = (await request.json()) as { chunk_id?: number };
    const chunkId = body.chunk_id ?? 0;
    const context = mockChunkContext[chunkId];
    if (!context) {
      return HttpResponse.json(
        {
          code: 404,
          message: "引用切块不存在",
          error_code: "KNOWLEDGE_CHUNK_NOT_FOUND",
          data: null,
        },
        { status: 404 },
      );
    }

    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: context,
    });
  }),
];

function sleep(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
