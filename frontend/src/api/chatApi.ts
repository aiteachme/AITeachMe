import { apiClient } from "./client";

interface ApiResponse<T> {
  code: number;
  data: T;
  message: string;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

type ChatRole = "user" | "assistant";

interface ChatContextItemResponse {
  chunk_id: number;
  document_id: number;
  title: string;
  header_path: string;
  score: number;
}

interface ChatHistoryItemResponse {
  id: number;
  turn_id: string;
  role: ChatRole;
  content: string;
  contexts: ChatContextItemResponse[] | null;
  created_at: string;
}

interface ChunkContextResponseData {
  chunk_id: number;
  document_id: number;
  document_title: string;
  chunk_title: string;
  chunk_header_path: string;
  chunk_content: string;
}

export interface ChatContextItem {
  chunkId: number;
  documentId: number;
  title: string;
  headerPath: string;
  score: number;
}

export interface ChatHistoryItem {
  id: number;
  turnId: string;
  role: ChatRole;
  content: string;
  contexts: ChatContextItem[] | null;
  createdAt: string;
}

export interface ChatChunkContext {
  chunkId: number;
  documentId: number;
  documentTitle: string;
  chunkTitle: string;
  chunkHeaderPath: string;
  chunkContent: string;
}

export interface ChatSendInput {
  question: string;
  selected_context?: string | null;
  source_chunk_id?: number | null;
}

export interface ChatClearResult {
  cleared: boolean;
  deleted_count: number;
}

export type ChatStreamEvent =
  | { type: "token"; content: string }
  | { type: "done"; turnId: string; contexts: ChatContextItem[] | null }
  | { type: "error"; detail: string; errorCode: string };

type ChatStreamHandler = (event: ChatStreamEvent) => void | Promise<void>;

const SSE_BLOCK_DELIMITER = /\r?\n\r?\n/;

export async function listChatHistory(subject: string): Promise<ChatHistoryItem[]> {
  const response = await apiClient<ApiResponse<PaginatedData<ChatHistoryItemResponse>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/chats/list`,
    data: { page: 1, size: 100 },
  });

  return response.data.items
    .map(normalizeChatHistoryItem)
    .sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

export async function clearChatHistory(subject: string): Promise<ChatClearResult> {
  const response = await apiClient<ApiResponse<ChatClearResult>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/chats/clear`,
    data: {},
  });
  return response.data;
}

export async function fetchChatChunkContext(
  subject: string,
  chunkId: number,
): Promise<ChatChunkContext> {
  const response = await apiClient<ApiResponse<ChunkContextResponseData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/chunks/context`,
    data: { chunk_id: chunkId },
  });
  return normalizeChunkContext(response.data);
}

export async function streamChatResponse(
  subject: string,
  input: ChatSendInput,
  onEvent: ChatStreamHandler,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${resolveBaseUrl()}/api/v1/subjects/${subject}/chats/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readResponseError(response));
  }
  if (!response.body) {
    throw new Error("服务端未返回可读取的流式响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.rest;

    for (const event of parsed.events) {
      await onEvent(event);
      if (event.type === "done" || event.type === "error") {
        return;
      }
    }
  }

  const trailing = parseSseBuffer(buffer, { flush: true });
  for (const event of trailing.events) {
    await onEvent(event);
    if (event.type === "done" || event.type === "error") {
      return;
    }
  }
}

function normalizeChatHistoryItem(item: ChatHistoryItemResponse): ChatHistoryItem {
  return {
    id: item.id,
    turnId: item.turn_id,
    role: item.role,
    content: item.content,
    contexts: item.contexts?.map(normalizeChatContextItem) ?? null,
    createdAt: item.created_at,
  };
}

function normalizeChatContextItem(item: ChatContextItemResponse): ChatContextItem {
  return {
    chunkId: item.chunk_id,
    documentId: item.document_id,
    title: item.title,
    headerPath: item.header_path,
    score: item.score,
  };
}

function normalizeChunkContext(item: ChunkContextResponseData): ChatChunkContext {
  return {
    chunkId: item.chunk_id,
    documentId: item.document_id,
    documentTitle: item.document_title,
    chunkTitle: item.chunk_title,
    chunkHeaderPath: item.chunk_header_path,
    chunkContent: item.chunk_content,
  };
}

function resolveBaseUrl(): string {
  return import.meta.env.VITE_API_URL ?? "";
}

async function readResponseError(response: Response): Promise<string> {
  const fallback = `请求失败 (${response.status})`;
  const raw = await response.text();
  if (!raw.trim()) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(raw) as {
      message?: string;
      detail?: string;
      error_code?: string;
    };
    return parsed.message?.trim() || parsed.detail?.trim() || fallback;
  } catch {
    return raw.trim() || fallback;
  }
}

function parseSseBuffer(
  buffer: string,
  options?: { flush?: boolean },
): { events: ChatStreamEvent[]; rest: string } {
  const blocks = buffer.split(SSE_BLOCK_DELIMITER);
  const flush = options?.flush ?? false;
  const rest = flush ? "" : blocks.pop() ?? "";

  return {
    events: blocks.map(parseSseBlock).filter((event): event is ChatStreamEvent => event !== null),
    rest,
  };
}

function parseSseBlock(block: string): ChatStreamEvent | null {
  const lines = block
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return null;
  }

  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  const rawData = dataLines.join("\n");
  if (!rawData || rawData === "[DONE]") {
    return null;
  }

  const payload = JSON.parse(rawData) as Record<string, unknown>;
  if (eventName === "token") {
    return {
      type: "token",
      content: String(payload.content ?? ""),
    };
  }
  if (eventName === "done") {
    return {
      type: "done",
      turnId: String(payload.turn_id ?? ""),
      contexts: Array.isArray(payload.contexts)
        ? payload.contexts.map((item) => normalizeChatContextItem(item as ChatContextItemResponse))
        : null,
    };
  }
  if (eventName === "error") {
    return {
      type: "error",
      detail: String(payload.detail ?? "请求失败，请稍后重试。"),
      errorCode: String(payload.error_code ?? "chat_stream_error"),
    };
  }
  return null;
}
