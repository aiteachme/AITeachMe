import { http, HttpResponse } from "msw";

type ChatRole = "user" | "assistant";

interface ChatContextItem {
  chunk_id: number;
  document_id: number;
  title: string;
  header_path: string;
  score: number;
}

interface ChatHistoryItem {
  id: number;
  turn_id: string;
  role: ChatRole;
  content: string;
  contexts: ChatContextItem[] | null;
  created_at: string;
}

interface ChatSendBody {
  question?: unknown;
  selected_context?: unknown;
}

const mockContexts: ChatContextItem[] = [
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

const mockHistory: ChatHistoryItem[] = [
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
      "导数 f'(x₀) 表示曲线 y=f(x) 在点 (x₀, f(x₀)) 处切线的斜率，描述函数在该点的瞬时变化率。",
    contexts: mockContexts,
    created_at: "2026-03-14T10:00:05Z",
  },
];

let nextMessageId = mockHistory.length + 1;
let turnSeq = 2;

function chunkText(text: string): string[] {
  const chars = Array.from(text);
  const chunks: string[] = [];
  let i = 0;
  while (i < chars.length) {
    const size = 2 + Math.floor(Math.random() * 4);
    chunks.push(chars.slice(i, i + size).join(""));
    i += size;
  }
  return chunks;
}

function buildMockAnswer(question: string, selectedContext: string): string {
  const context = selectedContext.trim();
  if (context) {
    return [
      "我先基于你划的这段内容来回答：",
      `「${context}」`,
      "",
      `关于“${question}”，可以这样理解：`,
      "1. 先明确这段话的核心概念和边界条件。",
      "2. 再把它和当前章节标题对应起来，确认它在知识结构里的位置。",
      "3. 最后用一个小例子验证理解是否一致。",
      "",
      "如果你愿意，我可以继续把这段拆成“定义 / 推导 / 易错点”三层继续讲。",
    ].join("\n");
  }
  return [
    `收到问题：“${question}”。`,
    "先给你一个简版回答：",
    "- 先看概念定义是什么。",
    "- 再看它和前后知识点如何连接。",
    "- 最后用一个例子确认是否能应用。",
    "",
    "你可以继续追问，我会按同一上下文接着答。",
  ].join("\n");
}

function pushHistory(
  turnId: string,
  question: string,
  answer: string,
  contexts: ChatContextItem[] | null,
) {
  const now = new Date();
  mockHistory.push(
    {
      id: nextMessageId,
      turn_id: turnId,
      role: "user",
      content: question,
      contexts: null,
      created_at: now.toISOString(),
    },
    {
      id: nextMessageId + 1,
      turn_id: turnId,
      role: "assistant",
      content: answer,
      contexts,
      created_at: new Date(now.getTime() + 1000).toISOString(),
    },
  );
  nextMessageId += 2;
}

async function streamChatResponse(request: Request) {
  let body: ChatSendBody = {};
  try {
    body = (await request.json()) as ChatSendBody;
  } catch {
    body = {};
  }

  const question = typeof body.question === "string" && body.question.trim()
    ? body.question.trim()
    : "请解释这段内容";
  const selectedContext = typeof body.selected_context === "string"
    ? body.selected_context
    : "";
  const turnId = `turn-${turnSeq++}`;
  const answer = buildMockAnswer(question, selectedContext);
  const chunks = chunkText(answer);
  const contexts = mockContexts;

  pushHistory(turnId, question, answer, contexts);

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      for (const chunk of chunks) {
        await sleep(60);
        controller.enqueue(
          encoder.encode(`event: token\ndata: ${JSON.stringify({ content: chunk })}\n\n`),
        );
      }
      controller.enqueue(
        encoder.encode(`event: done\ndata: ${JSON.stringify({ turn_id: turnId, contexts })}\n\n`),
      );
      controller.close();
    },
  });

  return new HttpResponse(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

function buildHistoryPayload() {
  return {
    code: 0,
    message: "ok",
    data: {
      items: [...mockHistory].sort((left, right) => left.created_at.localeCompare(right.created_at)),
      total: mockHistory.length,
      page: 1,
      size: 100,
      pages: 1,
    },
  };
}

function clearHistoryPayload() {
  const deletedCount = mockHistory.length;
  mockHistory.length = 0;
  nextMessageId = 1;
  return {
    code: 0,
    message: "ok",
    data: { cleared: true, deleted_count: deletedCount },
  };
}

export const chatHandlers = [
  http.post("/api/v1/subjects/:subject/chat/send", async ({ request }) => streamChatResponse(request)),
  http.post("/api/v1/subjects/:subject/chats/send", async ({ request }) => streamChatResponse(request)),

  http.post("/api/v1/subjects/:subject/chat/list", () => HttpResponse.json(buildHistoryPayload())),
  http.post("/api/v1/subjects/:subject/chats/list", () => HttpResponse.json(buildHistoryPayload())),

  http.post("/api/v1/subjects/:subject/chat/clear", () => HttpResponse.json(clearHistoryPayload())),
  http.post("/api/v1/subjects/:subject/chats/clear", () => HttpResponse.json(clearHistoryPayload())),

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
