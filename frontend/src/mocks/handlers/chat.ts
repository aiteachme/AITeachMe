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

interface ChatTurnItem {
  turn_id: string;
  session_id: string;
  subject_id?: string | null;
  source?: string | null;
  anchor_id?: string | null;
  selected_text?: string | null;
  created_at: string;
}

interface ChatSessionItem {
  id: string;
  title: string;
  subject_id?: string | null;
  subject_name?: string | null;
  source?: string | null;
  anchor_id?: string | null;
  selected_text?: string | null;
  source_chunk_id?: number | null;
  message_count?: number;
  created_at: string;
  updated_at: string;
  last_message_at: string;
}

interface ChatSendBody {
  question?: unknown;
  session_id?: unknown;
  selected_text?: unknown;
  selected_context?: unknown;
  selection_context?: {
    selected_text?: unknown;
    section_excerpt?: unknown;
  } | null;
  source?: unknown;
  anchor_id?: unknown;
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
    content: "矩阵乘法为什么常见？",
    contexts: null,
    created_at: "2026-03-14T10:00:00Z",
  },
  {
    id: 2,
    turn_id: "turn-1",
    role: "assistant",
    content:
      "矩阵乘法能把大量线性变换批量表达出来，所以在前向传播、特征映射和注意力计算里都会高频出现。",
    contexts: mockContexts,
    created_at: "2026-03-14T10:00:05Z",
  },
];

const mockTurns: ChatTurnItem[] = [
  {
    turn_id: "turn-1",
    session_id: "session-1",
    subject_id: "math",
    source: "quick_chat",
    anchor_id: "2-矩阵乘法-空间的变换",
    selected_text: "矩阵乘法可能是机器学习中最频繁进行的操作",
    created_at: "2026-03-14T10:00:00Z",
  },
];

const mockSessions: ChatSessionItem[] = [
  {
    id: "session-1",
    title: "矩阵乘法为什么常见？",
    subject_id: "math",
    subject_name: "数学",
    source: "quick_chat",
    anchor_id: "2-矩阵乘法-空间的变换",
    selected_text: "矩阵乘法可能是机器学习中最频繁进行的操作",
    created_at: "2026-03-14T09:59:58Z",
    updated_at: "2026-03-14T10:00:05Z",
    last_message_at: "2026-03-14T10:00:05Z",
  },
];

const turnSessionMap = new Map<string, string>([["turn-1", "session-1"]]);
let nextMessageId = mockHistory.length + 1;
let turnSeq = 2;
let sessionSeq = 2;

function getParamText(value: string | readonly string[] | undefined): string {
  return typeof value === "string" ? value : value?.[0] ?? "";
}

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

function buildSessionTitle(question: string): string {
  const text = question.trim();
  if (!text) return "新会话";
  return text.length > 24 ? `${text.slice(0, 24)}...` : text;
}

function getMockSubjectName(subjectId: string | null): string {
  if (!subjectId || subjectId === "global") {
    return "通用";
  }
  const names: Record<string, string> = {
    math: "数学",
    physics: "物理",
  };
  return names[subjectId] ?? subjectId;
}

function resolveSession(
  sessionId: string | null,
  question: string,
  source: string | null,
  subjectId: string | null,
): ChatSessionItem {
  if (sessionId) {
    const existing = mockSessions.find((item) => item.id === sessionId);
    if (existing) {
      return existing;
    }
  }
  const now = new Date().toISOString();
  const created: ChatSessionItem = {
    id: `session-${sessionSeq++}`,
    title: buildSessionTitle(question),
    subject_id: subjectId ?? "global",
    subject_name: getMockSubjectName(subjectId),
    source,
    created_at: now,
    updated_at: now,
    last_message_at: now,
  };
  mockSessions.unshift(created);
  return created;
}

function touchSession(sessionId: string, question: string) {
  const target = mockSessions.find((item) => item.id === sessionId);
  if (!target) return;
  const now = new Date().toISOString();
  target.updated_at = now;
  target.last_message_at = now;
  if (target.title === "新会话") {
    target.title = buildSessionTitle(question);
  }
}

function pushHistory(
  sessionId: string,
  turnId: string,
  question: string,
  answer: string,
  contexts: ChatContextItem[] | null,
  source: string | null,
  anchorId: string | null,
  selectedText: string | null,
  subjectId: string | null,
) {
  const now = new Date();
  turnSessionMap.set(turnId, sessionId);
  const sessionItem = mockSessions.find((item) => item.id === sessionId);
  if (sessionItem && source && anchorId && selectedText) {
    sessionItem.source = source;
    sessionItem.anchor_id = anchorId;
    sessionItem.selected_text = selectedText;
    sessionItem.subject_id = subjectId ?? sessionItem.subject_id ?? "global";
    sessionItem.subject_name = getMockSubjectName(sessionItem.subject_id ?? null);
  }
  mockTurns.unshift({
    turn_id: turnId,
    session_id: sessionId,
    subject_id: subjectId ?? "global",
    source,
    anchor_id: anchorId,
    selected_text: selectedText,
    created_at: now.toISOString(),
  });
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
  touchSession(sessionId, question);
}

function listSessionItems(subjectId: string | null = null, includeAllSubjects = false) {
  const normalizedSubjectId = subjectId ?? "global";
  return [...mockSessions]
    .filter((item) => includeAllSubjects || (item.subject_id ?? "global") === normalizedSubjectId)
    .map((item) => {
      const messageCount = mockHistory.filter((entry) => turnSessionMap.get(entry.turn_id) === item.id).length;
      const selectionTurn = mockTurns.find((turn) =>
        turn.session_id === item.id &&
        typeof turn.anchor_id === "string" &&
        turn.anchor_id.trim().length > 0
      );
      return {
        ...item,
        source: item.source ?? selectionTurn?.source ?? null,
        anchor_id: item.anchor_id ?? selectionTurn?.anchor_id ?? null,
        selected_text: item.selected_text ?? selectionTurn?.selected_text ?? null,
        subject_id: item.subject_id ?? "global",
        subject_name: item.subject_name ?? getMockSubjectName(item.subject_id ?? null),
        message_count: messageCount,
      };
    })
    .sort((a, b) => b.last_message_at.localeCompare(a.last_message_at));
}

async function streamChatResponse(request: Request, subjectId: string | null = "global") {
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
  const selectedText = typeof body.selected_text === "string"
    ? body.selected_text
    : typeof body.selection_context?.selected_text === "string"
      ? body.selection_context.selected_text
      : selectedContext;
  const source = typeof body.source === "string" ? body.source : null;
  const anchorId = typeof body.anchor_id === "string" ? body.anchor_id : null;
  const askedSessionId = typeof body.session_id === "string" && body.session_id.trim()
    ? body.session_id.trim()
    : null;
  const sessionItem = resolveSession(askedSessionId, question, source, subjectId);
  const turnId = `turn-${turnSeq++}`;
  const answer = buildMockAnswer(question, selectedContext);
  const chunks = chunkText(answer);
  const contexts = mockContexts;

  pushHistory(sessionItem.id, turnId, question, answer, contexts, source, anchorId, selectedText || null, subjectId);

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
        encoder.encode(
          `event: done\ndata: ${JSON.stringify({
            turn_id: turnId,
            session_id: sessionItem.id,
            session_title: sessionItem.title,
            contexts,
          })}\n\n`,
        ),
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

function buildHistoryPayload(sessionId: string | null) {
  const items = (sessionId
    ? mockHistory.filter((item) => turnSessionMap.get(item.turn_id) === sessionId)
    : mockHistory
  ).sort((left, right) => left.created_at.localeCompare(right.created_at));
  return {
    code: 0,
    message: "ok",
    data: {
      items,
      total: items.length,
      page: 1,
      size: 100,
      pages: 1,
    },
  };
}

async function clearHistoryPayload(request: Request) {
  let sessionId: string | null = null;
  try {
    const body = (await request.json()) as { session_id?: unknown };
    if (typeof body.session_id === "string" && body.session_id.trim()) {
      sessionId = body.session_id.trim();
    }
  } catch {
    sessionId = null;
  }

  if (!sessionId) {
    const deletedCount = mockHistory.length;
    mockHistory.length = 0;
    turnSessionMap.clear();
    mockTurns.length = 0;
    mockSessions.length = 0;
    nextMessageId = 1;
    return {
      code: 0,
      message: "ok",
      data: { cleared: true, deleted_count: deletedCount },
    };
  }

  const keepItems = mockHistory.filter((item) => turnSessionMap.get(item.turn_id) !== sessionId);
  const deletedCount = mockHistory.length - keepItems.length;
  mockHistory.length = 0;
  mockHistory.push(...keepItems);

  for (const [turnId, mappedSessionId] of turnSessionMap.entries()) {
    if (mappedSessionId === sessionId) {
      turnSessionMap.delete(turnId);
    }
  }
  const nextTurns = mockTurns.filter((item) => item.session_id !== sessionId);
  mockTurns.length = 0;
  mockTurns.push(...nextTurns);

  return {
    code: 0,
    message: "ok",
    data: { cleared: true, deleted_count: deletedCount },
  };
}

export const chatHandlers = [
  http.post("/api/v1/subjects/:subject/chat/send", async ({ request, params }) =>
    streamChatResponse(request, getParamText(params.subject))),
  http.post("/api/v1/subjects/:subject/chats/send", async ({ request, params }) =>
    streamChatResponse(request, getParamText(params.subject))),

  http.post("/api/v1/subjects/:subject/chat/list", async ({ request }) => {
    const body = (await request.json()) as { session_id?: unknown };
    const sessionId = typeof body.session_id === "string" ? body.session_id : null;
    return HttpResponse.json(buildHistoryPayload(sessionId));
  }),
  http.post("/api/v1/subjects/:subject/chats/list", async ({ request }) => {
    const body = (await request.json()) as { session_id?: unknown };
    const sessionId = typeof body.session_id === "string" ? body.session_id : null;
    return HttpResponse.json(buildHistoryPayload(sessionId));
  }),

  http.post("/api/v1/subjects/:subject/chat/clear", async ({ request }) => HttpResponse.json(await clearHistoryPayload(request))),
  http.post("/api/v1/subjects/:subject/chats/clear", async ({ request }) => HttpResponse.json(await clearHistoryPayload(request))),

  http.post("/api/v1/chats/sessions/list", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { include_all_subjects?: unknown };
    const items = listSessionItems(null, body.include_all_subjects === true);
    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        items,
        total: items.length,
        page: 1,
        size: 100,
        pages: 1,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/chats/sessions/list", ({ params }) => {
    const subjectId = getParamText(params.subject) || "global";
    const items = listSessionItems(subjectId, false);
    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        items,
        total: items.length,
        page: 1,
        size: 100,
        pages: 1,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/chats/sessions/create", async ({ request, params }) => {
    const body = (await request.json()) as { title?: unknown; source?: unknown };
    const title = typeof body.title === "string" && body.title.trim() ? body.title.trim() : "新会话";
    const source = typeof body.source === "string" ? body.source : null;
    const now = new Date().toISOString();
    const subjectId = getParamText(params.subject) || "global";
    const created: ChatSessionItem = {
      id: `session-${sessionSeq++}`,
      title,
      subject_id: subjectId,
      subject_name: getMockSubjectName(subjectId),
      source,
      created_at: now,
      updated_at: now,
      last_message_at: now,
    };
    mockSessions.unshift(created);
    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        session: {
          ...created,
          message_count: 0,
        },
      },
    });
  }),

  http.post("/api/v1/chats/sessions/delete", async ({ request }) => {
    const body = (await request.json()) as { session_id?: unknown };
    const sessionId = typeof body.session_id === "string" ? body.session_id : "";
    if (!sessionId) {
      return HttpResponse.json(
        { code: 400, message: "session_id 不能为空", data: null },
        { status: 400 },
      );
    }

    const before = mockHistory.length;
    const keepItems = mockHistory.filter((item) => turnSessionMap.get(item.turn_id) !== sessionId);
    mockHistory.length = 0;
    mockHistory.push(...keepItems);
    for (const [turnId, mappedSessionId] of turnSessionMap.entries()) {
      if (mappedSessionId === sessionId) {
        turnSessionMap.delete(turnId);
      }
    }
    const nextTurns = mockTurns.filter((item) => item.session_id !== sessionId);
    mockTurns.length = 0;
    mockTurns.push(...nextTurns);
    const nextSessions = mockSessions.filter((item) => item.id !== sessionId);
    mockSessions.length = 0;
    mockSessions.push(...nextSessions);

    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        deleted: true,
        deleted_message_count: before - keepItems.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/chats/sessions/delete", async ({ request }) => {
    const body = (await request.json()) as { session_id?: unknown };
    const sessionId = typeof body.session_id === "string" ? body.session_id : "";
    if (!sessionId) {
      return HttpResponse.json(
        { code: 400, message: "session_id 不能为空", data: null },
        { status: 400 },
      );
    }

    const before = mockHistory.length;
    const keepItems = mockHistory.filter((item) => turnSessionMap.get(item.turn_id) !== sessionId);
    mockHistory.length = 0;
    mockHistory.push(...keepItems);
    for (const [turnId, mappedSessionId] of turnSessionMap.entries()) {
      if (mappedSessionId === sessionId) {
        turnSessionMap.delete(turnId);
      }
    }
    const nextTurns = mockTurns.filter((item) => item.session_id !== sessionId);
    mockTurns.length = 0;
    mockTurns.push(...nextTurns);
    const nextSessions = mockSessions.filter((item) => item.id !== sessionId);
    mockSessions.length = 0;
    mockSessions.push(...nextSessions);

    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        deleted: true,
        deleted_message_count: before - keepItems.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/chats/threads/list", async ({ request }) => {
    const body = (await request.json()) as { source?: unknown };
    const source = typeof body.source === "string" ? body.source : null;

    const items = mockTurns
      .filter((turn) => (source ? turn.source === source : true))
      .filter((turn) => typeof turn.anchor_id === "string" && turn.anchor_id.trim().length > 0)
      .sort((left, right) => right.created_at.localeCompare(left.created_at))
      .map((turn) => ({
        ...turn,
        messages: mockHistory
          .filter((message) => message.turn_id === turn.turn_id)
          .sort((left, right) => left.created_at.localeCompare(right.created_at)),
      }));

    return HttpResponse.json({
      code: 0,
      message: "ok",
      data: {
        items,
        total: items.length,
        page: 1,
        size: 100,
        pages: 1,
      },
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
