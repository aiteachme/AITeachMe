import { useEffect, useRef, useState } from "react";
import {
  clearChatApiApiV1CoursesCourseIdChatsClearPost,
  getSendChatApiV1CoursesCourseIdChatsSendPostUrl,
  listChatApiApiV1CoursesCourseIdChatsListPost,
} from "../api/generated/chats";
import type { ChatContextItem, ChatMessageItem, ChatSendRequest } from "../api/generated/model";
import { getApiErrorMessage, postSseJson } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

export type ChatMessageStatus = "ready" | "streaming" | "error" | "interrupted";

export interface ChatClientAction {
  type: string;
  payload?: unknown;
  [key: string]: unknown;
}

export interface ChatSessionMessage {
  localId: string;
  role: "user" | "assistant";
  content: string;
  attachedFileIds?: string[] | null;
  attachedFileCount?: number;
  turnId: string | null;
  contexts: ChatContextItem[] | null;
  createdAt: string | null;
  completedAt?: string | null;
  elapsedMs?: number | null;
  status: ChatMessageStatus;
  statusDetail?: string | null;
  statusStage?: string | null;
  activeToolName?: string | null;
  activeToolDisplayName?: string | null;
  toolRunCount?: number;
  toolRunningCount?: number;
  runningToolCallIds?: string[];
  completedToolCallIds?: string[];
  toolRuns?: ChatMessageToolRun[];
  clientActions?: ChatClientAction[];
  errorDetail: string | null;
}

export interface ChatMessageToolRun {
  id: string;
  position: number;
  status: "running" | "completed" | "failed";
  toolName: string | null;
  toolDisplayName: string | null;
  detail: string | null;
}

const HOME_INTAKE_CREATE_TOOL_RUN_ID = "home_intake_create_course";
const HOME_INTAKE_CREATE_TOOL_NAME = "create_course_from_home_intake";
const HOME_INTAKE_CREATE_TOOL_DISPLAY_NAME = "\u521b\u5efa\u5b66\u79d1";
const OPEN_BUILD_PLANNER_ACTION_TYPE = "open_build_planner";
const HOME_INTAKE_CREATE_RESPONSE_RE = /^\s*\u5df2\u521b\u5efa\u300c[^\u300d]+\u300d\uff0c\u6b63\u5728\u6253\u5f00\u6784\u5efa\u89c4\u5212\u9875\u3002?\s*$/;

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

interface ChatMessageStatusPayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
  stage: string;
  detail: string;
  elapsedMs: number | null;
  toolCallId: string | null;
  toolName: string | null;
  toolDisplayName: string | null;
}

interface ChatMessageDonePayload {
  input: ChatSendRequest;
  localThreadId: string;
  assistantLocalId: string;
  sessionId: string | null;
  sessionTitle: string | null;
  turnId: string;
  elapsedMs: number | null;
  clientActions: ChatClientAction[];
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
  abortOnUnmount?: boolean;
  abortOnCourseChange?: boolean;
  onSessionResolved?: (sessionId: string) => void;
  onMessageStart?: (payload: ChatMessageLifecyclePayload) => void;
  onMessageSessionResolved?: (payload: ChatMessageSessionPayload) => void;
  onMessageToken?: (payload: ChatMessageTokenPayload) => void;
  onMessageStatus?: (payload: ChatMessageStatusPayload) => void;
  onMessageDone?: (payload: ChatMessageDonePayload) => void;
  onMessageError?: (payload: ChatMessageErrorPayload) => void;
  onMessageSettled?: (payload: ChatMessageSettledPayload) => void;
}

export function useChatSession(courseId: string, options: UseChatSessionOptions = {}) {
  const sessionId = options.sessionId ?? null;
  const enabled = options.enabled ?? true;
  const loadWithoutSession = options.loadWithoutSession ?? true;
  const preserveMessagesWithoutSession = options.preserveMessagesWithoutSession ?? false;
  const abortOnUnmount = options.abortOnUnmount ?? true;
  const abortOnCourseChange = options.abortOnCourseChange ?? true;
  const onSessionResolved = options.onSessionResolved;
  const onMessageStart = options.onMessageStart;
  const onMessageSessionResolved = options.onMessageSessionResolved;
  const onMessageToken = options.onMessageToken;
  const onMessageStatus = options.onMessageStatus;
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
  const abortOnUnmountRef = useRef(abortOnUnmount);
  const abortOnCourseChangeRef = useRef(abortOnCourseChange);

  function setStreamingState(nextValue: boolean) {
    isStreamingRef.current = nextValue;
    setIsStreaming(nextValue);
  }

  function setMessagesSessionId(nextSessionId: string | null) {
    messagesSessionIdRef.current = nextSessionId;
    setMessagesSessionIdState(nextSessionId);
  }

  useEffect(() => {
    abortOnUnmountRef.current = abortOnUnmount;
    abortOnCourseChangeRef.current = abortOnCourseChange;
  }, [abortOnCourseChange, abortOnUnmount]);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      const requestedSessionId = sessionId;
      if (!enabled) {
        setHistoryLoaded(true);
        return;
      }

      if (!courseId) {
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
        const response = await listChatApiApiV1CoursesCourseIdChatsListPost(courseId, {
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
        setMessages(mapHistoryItemsToSessionMessages(items));
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
  }, [enabled, loadWithoutSession, preserveMessagesWithoutSession, sessionId, courseId]);

  useEffect(() => {
    return () => {
      if (abortOnUnmountRef.current) {
        abortControllerRef.current?.abort();
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      if (abortOnCourseChangeRef.current) {
        abortControllerRef.current?.abort();
      }
    };
  }, [courseId]);

  async function sendMessage(input: ChatSendRequest, sendOptions: SendMessageOptions = {}): Promise<SendMessageResult> {
    const question = input.question.trim();
    if (!courseId || !question || isStreamingRef.current) {
      return { accepted: false, sessionId: null };
    }

    const resolvedSessionId = input.session_id ?? sessionId ?? null;
    const userLocalId = buildLocalId("user");
    const assistantLocalId = buildLocalId("assistant");
    const localThreadId = sendOptions.localThreadId?.trim() || resolvedSessionId || `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();
    const attachedFileIds = normalizeChatAttachedFileIds(input.attached_file_ids);
    const userMessage: ChatSessionMessage = {
      localId: userLocalId,
      role: "user",
      content: question,
      attachedFileIds: attachedFileIds.length > 0 ? attachedFileIds : null,
      attachedFileCount: attachedFileIds.length,
      turnId: null,
      contexts: null,
      createdAt: now,
      completedAt: now,
      elapsedMs: null,
      status: "ready",
      statusStage: null,
      activeToolName: null,
      activeToolDisplayName: null,
      toolRunCount: 0,
      toolRunningCount: 0,
      runningToolCallIds: [],
      completedToolCallIds: [],
      toolRuns: [],
      clientActions: [],
      errorDetail: null,
    };
    const assistantMessage: ChatSessionMessage = {
      localId: assistantLocalId,
      role: "assistant",
      content: "",
      turnId: null,
      contexts: null,
      createdAt: now,
      completedAt: null,
      elapsedMs: null,
      status: "streaming",
      statusStage: null,
      activeToolName: null,
      activeToolDisplayName: null,
      toolRunCount: 0,
      toolRunningCount: 0,
      runningToolCallIds: [],
      completedToolCallIds: [],
      toolRuns: [],
      clientActions: [],
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
        getSendChatApiV1CoursesCourseIdChatsSendPostUrl(courseId),
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
                statusDetail: null,
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
            if (statusSessionId && statusSessionId !== streamSessionId) {
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
            }
            const elapsedMs = parseChatElapsedMs(payload);
            if (elapsedMs !== null) {
              setMessages((current) =>
                updateMessage(current, assistantLocalId, (message) => ({
                  ...message,
                  elapsedMs,
                })),
              );
            }
            const progressStatus = parseChatProgressStatus(payload);
            if (!progressStatus) {
              return;
            }
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                statusDetail: progressStatus.detail,
                statusStage: progressStatus.stage,
                activeToolName: progressStatus.toolName,
                activeToolDisplayName: progressStatus.toolDisplayName,
                ...deriveToolRunState(message, progressStatus),
                elapsedMs: progressStatus.elapsedMs ?? message.elapsedMs ?? null,
              })),
            );
            onMessageStatus?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
              ...progressStatus,
            });
          },
          onDone: (payload) => {
            const donePayload = parseChatDonePayload(payload);
            const completedAt = new Date().toISOString();
            terminalEventReceived = true;
            streamSessionId = donePayload.sessionId ?? streamSessionId;
            activeStreamSessionIdRef.current = streamSessionId;
            setMessagesSessionId(streamSessionId);
            if (donePayload.sessionId) {
              onSessionResolved?.(donePayload.sessionId);
            }
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => {
                const clientActionToolState = deriveClientActionToolRunState(message, donePayload.clientActions);
                return {
                  ...message,
                  ...clientActionToolState,
                  turnId: donePayload.turnId,
                  contexts: donePayload.contexts,
                  status: "ready",
                  statusDetail: null,
                  statusStage: null,
                  activeToolName: null,
                  activeToolDisplayName: null,
                  clientActions: donePayload.clientActions,
                  errorDetail: null,
                  createdAt: message.createdAt ?? new Date().toISOString(),
                  completedAt,
                  elapsedMs: donePayload.elapsedMs ?? computeElapsedMs(message.createdAt, completedAt),
                };
              }),
            );
            onMessageDone?.({
              input,
              localThreadId,
              assistantLocalId,
              sessionId: streamSessionId,
              sessionTitle: donePayload.sessionTitle,
              turnId: donePayload.turnId,
              elapsedMs: donePayload.elapsedMs ?? null,
              clientActions: donePayload.clientActions,
            });
          },
          onError: (payload) => {
            terminalEventReceived = true;
            streamFailedDetail = parseChatErrorDetail(payload);
            const completedAt = new Date().toISOString();
            setMessages((current) =>
              updateMessage(current, assistantLocalId, (message) => ({
                ...message,
                status: "error",
                statusDetail: null,
                statusStage: null,
                activeToolName: null,
                activeToolDisplayName: null,
                errorDetail: streamFailedDetail,
                completedAt,
                elapsedMs: message.elapsedMs ?? computeElapsedMs(message.createdAt, completedAt),
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
        const completedAt = new Date().toISOString();
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            statusDetail: null,
            statusStage: null,
            activeToolName: null,
            activeToolDisplayName: null,
            errorDetail: detail,
            completedAt,
            elapsedMs: message.elapsedMs ?? computeElapsedMs(message.createdAt, completedAt),
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
        const completedAt = new Date().toISOString();
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "interrupted",
            statusDetail: null,
            statusStage: null,
            activeToolName: null,
            activeToolDisplayName: null,
            errorDetail: "已停止生成",
            completedAt,
            elapsedMs: message.elapsedMs ?? computeElapsedMs(message.createdAt, completedAt),
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
        const completedAt = new Date().toISOString();
        setMessages((current) =>
          updateMessage(current, assistantLocalId, (message) => ({
            ...message,
            status: "error",
            statusDetail: null,
            statusStage: null,
            activeToolName: null,
            activeToolDisplayName: null,
            errorDetail: detail,
            completedAt,
            elapsedMs: message.elapsedMs ?? computeElapsedMs(message.createdAt, completedAt),
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
    if (!courseId) {
      return;
    }

    abortStream();
    try {
      if (sessionId) {
        await clearChatApiApiV1CoursesCourseIdChatsClearPost(courseId, { session_id: sessionId });
      } else {
        await clearChatApiApiV1CoursesCourseIdChatsClearPost(courseId, {});
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

function mapHistoryItemsToSessionMessages(items: ChatMessageItem[]): ChatSessionMessage[] {
  return items.map((item, index) => mapHistoryItemToSessionMessage(item, items[index - 1] ?? null));
}

function mapHistoryItemToSessionMessage(item: ChatMessageItem, previousItem: ChatMessageItem | null): ChatSessionMessage {
  const completedAt = item.role === "assistant" ? item.created_at : null;
  const elapsedMs = item.role === "assistant" && previousItem?.role === "user"
    ? computeElapsedMs(previousItem.created_at, item.created_at)
    : null;
  const clientActions = item.role === "assistant"
    ? resolvePersistedClientActions(item, previousItem)
    : [];

  const mappedMessage: ChatSessionMessage = {
    localId: `history-${item.id}`,
    role: item.role,
    content: item.content,
    attachedFileIds: null,
    attachedFileCount: 0,
    turnId: item.turn_id,
    contexts: item.contexts ?? null,
    createdAt: item.created_at,
    completedAt,
    elapsedMs,
    status: "ready",
    statusStage: null,
    activeToolName: null,
    activeToolDisplayName: null,
    toolRunCount: 0,
    toolRunningCount: 0,
    runningToolCallIds: [],
    completedToolCallIds: [],
    toolRuns: [],
    clientActions,
    errorDetail: null,
  };
  return restorePersistedToolRunState(mappedMessage);
}

function normalizeChatAttachedFileIds(fileIds: ChatSendRequest["attached_file_ids"] | undefined): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const fileId of fileIds ?? []) {
    const value = String(fileId || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

function resolvePersistedClientActions(
  item: ChatMessageItem,
  previousItem: ChatMessageItem | null,
): ChatClientAction[] {
  const parsedActions = parseClientActions(item.client_actions);
  if (parsedActions.length > 0) {
    return parsedActions;
  }
  return inferAskUserOptionsActions(previousItem?.content ?? "", item.content);
}

function inferAskUserOptionsActions(userQuestion: string, assistantContent: string): ChatClientAction[] {
  if (!looksLikeExplicitAskUserOptionsRequest(userQuestion)) {
    return [];
  }

  const { question, options } = extractNumberedOptions(assistantContent);
  if (options.length < 2) {
    return [];
  }

  return [{
    type: "ask_user_options",
    payload: {
      question: clipActionText(question || "\u8bf7\u9009\u62e9\u4e00\u4e2a\u9009\u9879", 240),
      options: options.slice(0, 6).map((option, index) => ({
        id: `option_${index + 1}`,
        label: clipActionText(option, 80),
        value: clipActionText(option, 160),
        description: "",
      })),
      allow_custom_response: true,
    },
  }];
}

function looksLikeExplicitAskUserOptionsRequest(value: string): boolean {
  const normalized = value.toLowerCase().replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }
  const markers = [
    "ask_user_options",
    "\u76f4\u63a5\u95ee\u6211",
    "\u7528\u9009\u9879\u95ee\u6211",
    "\u4f7f\u7528\u9009\u9879\u95ee\u6211",
    "\u7ed9\u6211\u51e0\u4e2a\u9009\u9879",
    "\u7ed9\u51e0\u4e2a\u9009\u9879",
    "\u95ee\u6211\u95ee\u9898",
  ];
  return markers.some((marker) => normalized.includes(marker)) ||
    (normalized.includes("\u9009\u9879") && normalized.includes("\u95ee") && normalized.includes("\u6211"));
}

function extractNumberedOptions(content: string): { question: string; options: string[] } {
  const optionPattern = /^\s*(?:[-*]\s*)?(?:\d{1,2}|[a-fA-F])[\.)\u3001\uff09]\s*(.+?)\s*$/;
  const questionLines: string[] = [];
  const options: string[] = [];
  let seenOption = false;

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const match = line.match(optionPattern);
    if (match) {
      seenOption = true;
      const option = match[1]?.replace(/\s+/g, " ").replace(/^[*\-_]+|[*\-_]+$/g, "").trim();
      if (option) {
        options.push(option);
      }
      continue;
    }
    if (!seenOption) {
      questionLines.push(line);
    }
  }

  return { question: questionLines.join(" ").trim(), options };
}

function clipActionText(value: string, maxChars: number): string {
  const text = value.trim();
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxChars - 1)).trimEnd()}...`;
}

function restorePersistedToolRunState(message: ChatSessionMessage): ChatSessionMessage {
  if (message.role !== "assistant" || !HOME_INTAKE_CREATE_RESPONSE_RE.test(message.content)) {
    return message;
  }
  return {
    ...message,
    ...deriveClientActionToolRunState(message, [{ type: OPEN_BUILD_PLANNER_ACTION_TYPE }]),
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

function computeElapsedMs(startAt: string | null | undefined, endAt: string | null | undefined): number | null {
  if (!startAt || !endAt) {
    return null;
  }
  const start = Date.parse(startAt);
  const end = Date.parse(endAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    return null;
  }
  return end - start;
}

function parseChatElapsedMs(payload: unknown): number | null {
  if (!isRecord(payload)) {
    return null;
  }
  if (typeof payload.elapsed_ms === "number" && Number.isFinite(payload.elapsed_ms) && payload.elapsed_ms >= 0) {
    return Math.round(payload.elapsed_ms);
  }
  if (typeof payload.elapsed_s === "number" && Number.isFinite(payload.elapsed_s) && payload.elapsed_s >= 0) {
    return Math.round(payload.elapsed_s * 1000);
  }
  return null;
}

function parseChatDonePayload(payload: unknown): {
  turnId: string;
  sessionId: string | null;
  sessionTitle: string | null;
  contexts: ChatContextItem[] | null;
  elapsedMs: number | null;
  clientActions: ChatClientAction[];
} {
  if (!isRecord(payload)) {
    return {
      turnId: "",
      sessionId: null,
      sessionTitle: null,
      contexts: null,
      elapsedMs: null,
      clientActions: [],
    };
  }

  return {
    turnId: typeof payload.turn_id === "string" ? payload.turn_id : "",
    sessionId: typeof payload.session_id === "string" ? payload.session_id : null,
    sessionTitle: typeof payload.session_title === "string" ? payload.session_title : null,
    contexts: Array.isArray(payload.contexts) ? (payload.contexts as ChatContextItem[]) : null,
    elapsedMs: parseChatElapsedMs(payload),
    clientActions: parseClientActions(payload.client_actions ?? payload.actions),
  };
}

function parseClientActions(value: unknown): ChatClientAction[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is ChatClientAction => {
    return isRecord(item) && typeof item.type === "string" && item.type.trim().length > 0;
  });
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

function parseChatProgressStatus(payload: unknown): {
  stage: string;
  detail: string;
  elapsedMs: number | null;
  toolCallId: string | null;
  toolName: string | null;
  toolDisplayName: string | null;
} | null {
  if (!isRecord(payload)) {
    return null;
  }
  const stage = typeof payload.stage === "string" ? payload.stage.trim() : "";
  if (
    !stage ||
    (stage !== "answering" && stage !== "home_intake" && !stage.startsWith("tool_call_"))
  ) {
    return null;
  }
  const detail = typeof payload.detail === "string" ? payload.detail.trim() : "";
  if (!detail) {
    return null;
  }
  const toolName = typeof payload.tool_name === "string" && payload.tool_name.trim()
    ? payload.tool_name.trim()
    : null;
  const toolDisplayName = typeof payload.tool_display_name === "string" && payload.tool_display_name.trim()
    ? payload.tool_display_name.trim()
    : null;
  const toolCallId = typeof payload.tool_call_id === "string" && payload.tool_call_id.trim()
    ? payload.tool_call_id.trim()
    : null;
  return { stage, detail, elapsedMs: parseChatElapsedMs(payload), toolCallId, toolName, toolDisplayName };
}

function deriveToolRunState(
  message: ChatSessionMessage,
  progressStatus: {
    stage: string;
    detail: string;
    toolCallId: string | null;
    toolName: string | null;
    toolDisplayName: string | null;
  },
): Partial<ChatSessionMessage> {
  if (!progressStatus.stage.startsWith("tool_call_")) {
    return {};
  }
  const existingCompleted = message.completedToolCallIds ?? [];
  const existingRunning = message.runningToolCallIds ?? [];
  const fallbackKey = progressStatus.toolName || "tool";
  const toolCallId = progressStatus.toolCallId
    || (
      (progressStatus.stage === "tool_call_completed" || progressStatus.stage === "tool_call_failed")
      && existingRunning.length === 1
      ? existingRunning[0]
      : `${fallbackKey}-${existingCompleted.length + existingRunning.length + 1}`
    );
  let runningToolCallIds = existingRunning;
  let completedToolCallIds = existingCompleted;
  let toolRuns = message.toolRuns ?? [];

  if (progressStatus.stage === "tool_call_started") {
    runningToolCallIds = addUnique(existingRunning, toolCallId);
    toolRuns = upsertToolRun(toolRuns, {
      id: toolCallId,
      position: message.content.length,
      status: "running",
      toolName: progressStatus.toolName,
      toolDisplayName: progressStatus.toolDisplayName,
      detail: progressStatus.detail,
    });
  }
  if (progressStatus.stage === "tool_call_completed" || progressStatus.stage === "tool_call_failed") {
    runningToolCallIds = existingRunning.filter((item) => item !== toolCallId);
    completedToolCallIds = addUnique(existingCompleted, toolCallId);
    toolRuns = upsertToolRun(toolRuns, {
      id: toolCallId,
      position: message.content.length,
      status: progressStatus.stage === "tool_call_failed" ? "failed" : "completed",
      toolName: progressStatus.toolName,
      toolDisplayName: progressStatus.toolDisplayName,
      detail: progressStatus.detail,
    });
  }

  return {
    runningToolCallIds,
    completedToolCallIds,
    toolRunningCount: runningToolCallIds.length,
    toolRunCount: completedToolCallIds.length,
    toolRuns,
  };
}

function deriveClientActionToolRunState(
  message: ChatSessionMessage,
  clientActions: ChatClientAction[],
): Partial<ChatSessionMessage> {
  if (!clientActions.some((action) => action.type === OPEN_BUILD_PLANNER_ACTION_TYPE)) {
    return {};
  }

  const existingToolRun = (message.toolRuns ?? []).find((run) => run.id === HOME_INTAKE_CREATE_TOOL_RUN_ID);
  const runningToolCallIds = (message.runningToolCallIds ?? []).filter(
    (id) => id !== HOME_INTAKE_CREATE_TOOL_RUN_ID,
  );
  const completedToolCallIds = addUnique(message.completedToolCallIds ?? [], HOME_INTAKE_CREATE_TOOL_RUN_ID);
  const toolRuns = upsertToolRun(message.toolRuns ?? [], {
    id: HOME_INTAKE_CREATE_TOOL_RUN_ID,
    position: existingToolRun?.position ?? 0,
    status: "completed",
    toolName: HOME_INTAKE_CREATE_TOOL_NAME,
    toolDisplayName: HOME_INTAKE_CREATE_TOOL_DISPLAY_NAME,
    detail: "\u5df2\u5b8c\u6210\u521b\u5efa\u5b66\u79d1",
  });

  return {
    runningToolCallIds,
    completedToolCallIds,
    toolRunningCount: runningToolCallIds.length,
    toolRunCount: completedToolCallIds.length,
    toolRuns,
  };
}

function addUnique(values: string[], value: string): string[] {
  return values.includes(value) ? values : [...values, value];
}

function upsertToolRun(
  runs: ChatMessageToolRun[],
  nextRun: ChatMessageToolRun,
): ChatMessageToolRun[] {
  const existingIndex = runs.findIndex((run) => run.id === nextRun.id);
  if (existingIndex < 0) {
    return [...runs, nextRun];
  }
  return runs.map((run, index) => {
    if (index !== existingIndex) {
      return run;
    }
    return {
      ...run,
      status: nextRun.status,
      toolName: nextRun.toolName ?? run.toolName,
      toolDisplayName: nextRun.toolDisplayName ?? run.toolDisplayName,
      detail: nextRun.detail ?? run.detail,
    };
  });
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
