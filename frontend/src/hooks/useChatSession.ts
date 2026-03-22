import { useEffect, useRef, useState } from "react";
import {
  clearChatHistory,
  listChatHistory,
  streamChatResponse,
  type ChatContextItem,
  type ChatHistoryItem,
  type ChatSendInput,
} from "../api/chatApi";
import { getApiErrorMessage } from "../api/client";

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
}

export function useChatSession(subjectId: string) {
  const [messages, setMessages] = useState<ChatSessionMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      if (!subjectId) {
        setMessages([]);
        setHistoryError(null);
        setHistoryLoaded(true);
        return;
      }

      setHistoryLoaded(false);
      try {
        const items = await listChatHistory(subjectId);
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

    loadHistory();
    return () => {
      cancelled = true;
      abortControllerRef.current?.abort();
    };
  }, [subjectId]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  async function sendMessage(input: ChatSendInput): Promise<SendMessageResult> {
    const question = input.question.trim();
    if (!subjectId || !question || isStreaming) {
      return { accepted: false };
    }

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

    try {
      await streamChatResponse(
        subjectId,
        {
          ...input,
          question,
        },
        async (event) => {
          if (event.type === "token") {
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                content: `${message.content}${event.content}`,
              })),
            );
            return;
          }

          if (event.type === "done") {
            terminalEventReceived = true;
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                turnId: event.turnId,
                contexts: event.contexts,
                status: "ready",
                errorDetail: null,
                createdAt: message.createdAt ?? new Date().toISOString(),
              })),
            );
            return;
          }

          terminalEventReceived = true;
          setMessages((current) =>
            updateMessage(current, assistantLocalId, (message) => ({
              ...message,
              status: "error",
              errorDetail: event.detail,
            })),
          );
        },
        controller.signal,
      );

      if (!terminalEventReceived && !controller.signal.aborted) {
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            errorDetail: "服务端没有返回完成事件，请稍后重试。",
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

    return { accepted: true };
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
      await clearChatHistory(subjectId);
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

function mapHistoryItemToSessionMessage(item: ChatHistoryItem): ChatSessionMessage {
  return {
    localId: `history-${item.id}`,
    role: item.role,
    content: item.content,
    turnId: item.turnId,
    contexts: item.contexts,
    createdAt: item.createdAt,
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
