import { useEffect, useRef, useState } from "react";
import {
  clearChatApiApiV1SubjectsSubjectChatsClearPost,
  getSendChatApiV1SubjectsSubjectChatsSendPostUrl,
  listChatApiApiV1SubjectsSubjectChatsListPost,
} from "../api/generated/chats";
import type { ChatContextItem, ChatMessageItem, ChatSendRequest } from "../api/generated/model";
import { getApiErrorMessage, postSseJson } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

export type ChatMessageStatus = "ready" | "streaming" | "error" | "interrupted";

export interface ChatSessionMessage {
  localId: string;
  role: "user" | "assistant";
  content: string;
  turnId: string | null;
  contexts: ChatContextItem[] | null;
  createdAt: string | null;
  status: ChatMessageStatus;
  errorDetail: string | null;
}

interface SendMessageResult {
  accepted: boolean;
  sessionId: string | null;
}

interface UseChatSessionOptions {
  sessionId?: string | null;
  enabled?: boolean;
  loadWithoutSession?: boolean;
  onSessionResolved?: (sessionId: string) => void;
}

export function useChatSession(subjectId: string, options: UseChatSessionOptions = {}) {
  const sessionId = options.sessionId ?? null;
  const enabled = options.enabled ?? true;
  const loadWithoutSession = options.loadWithoutSession ?? true;
  const onSessionResolved = options.onSessionResolved;

  const [messages, setMessages] = useState<ChatSessionMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      if (!enabled) {
        setHistoryLoaded(true);
        return;
      }

      if (!subjectId) {
        setMessages([]);
        setHistoryError(null);
        setHistoryLoaded(true);
        return;
      }
      if (!sessionId && !loadWithoutSession) {
        setMessages([]);
        setHistoryError(null);
        setHistoryLoaded(true);
        return;
      }

      setHistoryLoaded(false);
      try {
        const response = await listChatApiApiV1SubjectsSubjectChatsListPost(subjectId, {
          page: 1,
          size: 100,
          session_id: sessionId ?? undefined,
        });
        const items = (unwrapOrvalResponse<{ items?: ChatMessageItem[] }>(response)?.items ?? [])
          .slice()
          .sort((left, right) => left.created_at.localeCompare(right.created_at));
        if (cancelled) {
          return;
        }
        setMessages(items.map(mapHistoryItemToSessionMessage));
        setHistoryError(null);
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }
        setHistoryError(getApiErrorMessage(error, "加载聊天记录失败"));
      } finally {
        if (!cancelled) {
          setHistoryLoaded(true);
        }
      }
    }

    void loadHistory();
    return () => {
      cancelled = true;
      abortControllerRef.current?.abort();
    };
  }, [enabled, loadWithoutSession, sessionId, subjectId]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  async function sendMessage(input: ChatSendRequest): Promise<SendMessageResult> {
    const question = input.question.trim();
    if (!subjectId || !question || isStreaming) {
      return { accepted: false, sessionId: null };
    }

    const resolvedSessionId = input.session_id ?? sessionId ?? null;
    const userLocalId = buildLocalId("user");
    const assistantLocalId = buildLocalId("assistant");
    const now = new Date().toISOString();
    const userMessage: ChatSessionMessage = {
      localId: userLocalId,
      role: "user",
      content: question,
      turnId: null,
      contexts: null,
      createdAt: now,
      status: "ready",
      errorDetail: null,
    };
    const assistantMessage: ChatSessionMessage = {
      localId: assistantLocalId,
      role: "assistant",
      content: "",
      turnId: null,
      contexts: null,
      createdAt: now,
      status: "streaming",
      errorDetail: null,
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setIsStreaming(true);
    setHistoryError(null);

    const controller = new AbortController();
    abortControllerRef.current = controller;
    let terminalEventReceived = false;
    let streamFailedDetail: string | null = null;
    let streamSessionId: string | null = resolvedSessionId;

    try {
      const streamResult = await postSseJson(
        getSendChatApiV1SubjectsSubjectChatsSendPostUrl(subjectId),
        {
          ...input,
          question,
          session_id: resolvedSessionId ?? undefined,
        },
        {
          signal: controller.signal,
          onToken: (event) => {
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                content: `${message.content}${event.content}`,
              })),
            );
          },
          onDone: (payload) => {
            const donePayload = parseChatDonePayload(payload);
            terminalEventReceived = true;
            streamSessionId = donePayload.sessionId ?? streamSessionId;
            if (donePayload.sessionId) {
              onSessionResolved?.(donePayload.sessionId);
            }
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                turnId: donePayload.turnId,
                contexts: donePayload.contexts,
                status: "ready",
                errorDetail: null,
                createdAt: message.createdAt ?? new Date().toISOString(),
              })),
            );
          },
          onError: (payload) => {
            terminalEventReceived = true;
            streamFailedDetail = parseChatErrorDetail(payload);
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                status: "error",
                errorDetail: streamFailedDetail,
              })),
            );
          },
        },
      );

      if (!streamResult.aborted && streamResult.errorPayload && !streamFailedDetail) {
        streamFailedDetail = parseChatErrorDetail(streamResult.errorPayload);
      }

      if (!terminalEventReceived && !controller.signal.aborted) {
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            errorDetail: streamFailedDetail ?? "服务端没有返回完成事件，请稍后重试。",
          })),
        );
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) {
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "interrupted",
            errorDetail: "已停止生成",
          })),
        );
      } else {
        const detail = getApiErrorMessage(error, "发送消息失败");
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            errorDetail: detail,
          })),
        );
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }

    return {
      accepted: true,
      sessionId: streamSessionId ?? null,
    };
  }

  function abortStream() {
    abortControllerRef.current?.abort();
  }

  async function clearHistory() {
    if (!subjectId) {
      return;
    }

    abortStream();
    try {
      if (sessionId) {
        await clearChatApiApiV1SubjectsSubjectChatsClearPost(subjectId, { session_id: sessionId });
      } else {
        await clearChatApiApiV1SubjectsSubjectChatsClearPost(subjectId, {});
      }
      setMessages([]);
      setHistoryError(null);
    } catch (error: unknown) {
      setHistoryError(getApiErrorMessage(error, "清空聊天记录失败"));
    }
  }

  return {
    messages,
    historyLoaded,
    historyError,
    isStreaming,
    sendMessage,
    abortStream,
    clearHistory,
  };
}

function mapHistoryItemToSessionMessage(item: ChatMessageItem): ChatSessionMessage {
  return {
    localId: `history-${item.id}`,
    role: item.role,
    content: item.content,
    turnId: item.turn_id,
    contexts: item.contexts ?? null,
    createdAt: item.created_at,
    status: "ready",
    errorDetail: null,
  };
}

function updateMessage(
  messages: ChatSessionMessage[],
  localId: string,
  updater: (message: ChatSessionMessage) => ChatSessionMessage,
): ChatSessionMessage[] {
  return messages.map((message) => (message.localId === localId ? updater(message) : message));
}

function buildLocalId(role: "user" | "assistant"): string {
  return `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseChatDonePayload(payload: unknown): {
  turnId: string;
  sessionId: string | null;
  contexts: ChatContextItem[] | null;
} {
  if (!isRecord(payload)) {
    return {
      turnId: "",
      sessionId: null,
      contexts: null,
    };
  }

  return {
    turnId: typeof payload.turn_id === "string" ? payload.turn_id : "",
    sessionId: typeof payload.session_id === "string" ? payload.session_id : null,
    contexts: Array.isArray(payload.contexts) ? (payload.contexts as ChatContextItem[]) : null,
  };
}

function parseChatErrorDetail(payload: unknown): string {
  if (!isRecord(payload)) {
    return "发送消息失败";
  }

  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }

  if (typeof payload.message === "string" && payload.message.trim()) {
    return payload.message;
  }

  return "发送消息失败";
}
