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

interface SendMessageOptions {
  localThreadId?: string | null;
}

interface ChatMessageLifecyclePayload {
  input: ChatSendRequest;
  question: string;
  localThreadId: string;
  userLocalId: string;
  assistantLocalId: string;
  sessionId: string | null;
  createdAt: string;
}

interface ChatMessageTokenPayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
  content: string;
}

interface ChatMessageDonePayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
  sessionTitle: string | null;
  turnId: string;
}

interface ChatMessageSessionPayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string;
}

interface ChatMessageErrorPayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
  detail: string;
}

interface ChatMessageSettledPayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
}

interface UseChatSessionOptions {
  sessionId?: string | null;
  enabled?: boolean;
  loadWithoutSession?: boolean;
  preserveMessagesWithoutSession?: boolean;
  onSessionResolved?: (sessionId: string) => void;
  onMessageStart?: (payload: ChatMessageLifecyclePayload) => void;
  onMessageSessionResolved?: (payload: ChatMessageSessionPayload) => void;
  onMessageToken?: (payload: ChatMessageTokenPayload) => void;
  onMessageDone?: (payload: ChatMessageDonePayload) => void;
  onMessageError?: (payload: ChatMessageErrorPayload) => void;
  onMessageSettled?: (payload: ChatMessageSettledPayload) => void;
}

export function useChatSession(subjectId: string, options: UseChatSessionOptions = {}) {
  const sessionId = options.sessionId ?? null;
  const enabled = options.enabled ?? true;
  const loadWithoutSession = options.loadWithoutSession ?? true;
  const preserveMessagesWithoutSession = options.preserveMessagesWithoutSession ?? false;
  const onSessionResolved = options.onSessionResolved;
  const onMessageStart = options.onMessageStart;
  const onMessageSessionResolved = options.onMessageSessionResolved;
  const onMessageToken = options.onMessageToken;
  const onMessageDone = options.onMessageDone;
  const onMessageError = options.onMessageError;
  const onMessageSettled = options.onMessageSettled;

  const [messages, setMessages] = useState<ChatSessionMessage[]>([]);
  const [messagesSessionId, setMessagesSessionIdState] = useState<string | null>(sessionId);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isStreamingRef = useRef(false);
  const streamSeqRef = useRef(0);
  const activeStreamSessionIdRef = useRef<string | null>(null);
  const messagesSessionIdRef = useRef<string | null>(sessionId);

  function setStreamingState(nextValue: boolean) {
    isStreamingRef.current = nextValue;
    setIsStreaming(nextValue);
  }

  function setMessagesSessionId(nextSessionId: string | null) {
    messagesSessionIdRef.current = nextSessionId;
    setMessagesSessionIdState(nextSessionId);
  }

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      const requestedSessionId = sessionId;
      if (!enabled) {
        setHistoryLoaded(true);
        return;
      }

      if (!subjectId) {
        setMessages([]);
        setMessagesSessionId(null);
        setHistoryError(null);
        setHistoryLoaded(true);
        return;
      }
      if (!sessionId && !loadWithoutSession) {
        if (!preserveMessagesWithoutSession) {
          setMessages([]);
          setMessagesSessionId(null);
        }
        setHistoryError(null);
        setHistoryLoaded(true);
        return;
      }
      if (
        isStreamingRef.current &&
        sessionId &&
        (sessionId === messagesSessionIdRef.current || sessionId === activeStreamSessionIdRef.current)
      ) {
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
        if (
          isStreamingRef.current &&
          requestedSessionId &&
          requestedSessionId === activeStreamSessionIdRef.current
        ) {
          setHistoryError(null);
          return;
        }
        setMessages(items.map(mapHistoryItemToSessionMessage));
        setMessagesSessionId(requestedSessionId);
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
    };
  }, [enabled, loadWithoutSession, preserveMessagesWithoutSession, sessionId, subjectId]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [subjectId]);

  async function sendMessage(input: ChatSendRequest, sendOptions: SendMessageOptions = {}): Promise<SendMessageResult> {
    const question = input.question.trim();
    if (!subjectId || !question || isStreamingRef.current) {
      return { accepted: false, sessionId: null };
    }

    const resolvedSessionId = input.session_id ?? sessionId ?? null;
    const userLocalId = buildLocalId("user");
    const assistantLocalId = buildLocalId("assistant");
    const localThreadId = sendOptions.localThreadId?.trim() || resolvedSessionId || `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
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
    setMessagesSessionId(resolvedSessionId);
    activeStreamSessionIdRef.current = resolvedSessionId;
    setStreamingState(true);
    setHistoryError(null);
    onMessageStart?.({
      input,
      question,
      localThreadId,
      userLocalId,
      assistantLocalId,
      sessionId: resolvedSessionId,
      createdAt: now,
    });

    const controller = new AbortController();
    const streamSeq = streamSeqRef.current + 1;
    streamSeqRef.current = streamSeq;
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
            setMessages((current) => {
              const hasUserMessage = current.some((message) => message.localId === userLocalId);
              const hasAssistantMessage = current.some((message) => message.localId === assistantLocalId);
              let baseMessages = current;
              if (!hasUserMessage) {
                baseMessages = [...baseMessages, userMessage];
              }
              if (!hasAssistantMessage) {
                baseMessages = [...baseMessages, assistantMessage];
              }
              return updateMessage(baseMessages, assistantLocalId, (message) => ({
                ...message,
                content: `${message.content}${event.content}`,
              }));
            });
            onMessageToken?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
              content: event.content,
            });
          },
          onStatus: (payload) => {
            const statusSessionId = parseChatStatusSessionId(payload);
            if (!statusSessionId || statusSessionId === streamSessionId) {
              return;
            }
            streamSessionId = statusSessionId;
            activeStreamSessionIdRef.current = streamSessionId;
            setMessagesSessionId(streamSessionId);
            onSessionResolved?.(streamSessionId);
            onMessageSessionResolved?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
            });
          },
          onDone: (payload) => {
            const donePayload = parseChatDonePayload(payload);
            terminalEventReceived = true;
            streamSessionId = donePayload.sessionId ?? streamSessionId;
            activeStreamSessionIdRef.current = streamSessionId;
            setMessagesSessionId(streamSessionId);
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
            onMessageDone?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
              sessionTitle: donePayload.sessionTitle,
              turnId: donePayload.turnId,
            });
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
            onMessageError?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
              detail: streamFailedDetail,
            });
          },
        },
      );

      if (!streamResult.aborted && streamResult.errorPayload && !streamFailedDetail) {
        streamFailedDetail = parseChatErrorDetail(streamResult.errorPayload);
      }

      if (!terminalEventReceived && !controller.signal.aborted) {
        const detail = streamFailedDetail ?? "服务端没有返回完成事件，请稍后重试。";
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            errorDetail: detail,
          })),
        );
        onMessageError?.({
          input,
          localThreadId,
          assistantLocalId,
          sessionId: streamSessionId,
          detail,
        });
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
        onMessageError?.({
          input,
          localThreadId,
          assistantLocalId,
          sessionId: streamSessionId,
          detail: "已停止生成",
        });
      } else {
        const detail = getApiErrorMessage(error, "发送消息失败");
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            errorDetail: detail,
          })),
        );
        onMessageError?.({
          input,
          localThreadId,
          assistantLocalId,
          sessionId: streamSessionId,
          detail,
        });
      }
    } finally {
      if (streamSeqRef.current === streamSeq) {
        setStreamingState(false);
        abortControllerRef.current = null;
        activeStreamSessionIdRef.current = null;
      }
      onMessageSettled?.({
        input,
        localThreadId,
        assistantLocalId,
        sessionId: streamSessionId,
      });
    }

    return {
      accepted: true,
      sessionId: streamSessionId ?? null,
    };
  }

  function abortStream() {
    abortControllerRef.current?.abort();
    setStreamingState(false);
    activeStreamSessionIdRef.current = null;
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
      setMessagesSessionId(sessionId ?? null);
      setHistoryError(null);
    } catch (error: unknown) {
      setHistoryError(getApiErrorMessage(error, "清空聊天记录失败"));
    }
  }

  function replaceMessages(nextMessages: ChatSessionMessage[], nextSessionId: string | null = sessionId) {
    setMessages((current) => {
      if (
        isStreamingRef.current &&
        nextMessages.length === 0 &&
        current.some((message) => message.status === "streaming")
      ) {
        return current;
      }
      return nextMessages;
    });
    setMessagesSessionId(nextSessionId);
    setHistoryError(null);
    setHistoryLoaded(true);
  }

  return {
    messages,
    messagesSessionId,
    historyLoaded,
    historyError,
    isStreaming,
    sendMessage,
    abortStream,
    clearHistory,
    replaceMessages,
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
  sessionTitle: string | null;
  contexts: ChatContextItem[] | null;
} {
  if (!isRecord(payload)) {
    return {
      turnId: "",
      sessionId: null,
      sessionTitle: null,
      contexts: null,
    };
  }

  return {
    turnId: typeof payload.turn_id === "string" ? payload.turn_id : "",
    sessionId: typeof payload.session_id === "string" ? payload.session_id : null,
    sessionTitle: typeof payload.session_title === "string" ? payload.session_title : null,
    contexts: Array.isArray(payload.contexts) ? (payload.contexts as ChatContextItem[]) : null,
  };
}

function parseChatStatusSessionId(payload: unknown): string | null {
  if (!isRecord(payload)) {
    return null;
  }
  if (payload.stage !== "session_resolved") {
    return null;
  }
  const sessionId = payload.session_id;
  return typeof sessionId === "string" && sessionId.trim() ? sessionId.trim() : null;
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
