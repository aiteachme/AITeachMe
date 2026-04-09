/* ------------------------------------------------------------------ */
/*  useDocComments — Comment threads, SSE streaming, history loading   */
/* ------------------------------------------------------------------ */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type {
  Comment,
  CommentThreadView,
  ApiResponse,
  PaginatedData,
  ThreadTurnItem,
} from "../types";
import { apiClient, getApiErrorMessage, postSseJson } from "../../../api/client";
import { parseDoneSessionId, moveRecordKey, THREAD_HISTORY_PAGE_SIZE } from "../utils";

export interface DocCommentsState {
  comments: Comment[];
  setComments: React.Dispatch<React.SetStateAction<Comment[]>>;
  threadSessionIds: Record<string, string>;
  threadDrafts: Record<string, string>;
  threadStreaming: Record<string, boolean>;
  activeCommentThreadId: string | null;
  setActiveCommentThreadId: (id: string | null) => void;
  pinnedThreadId: string | null;
  setPinnedThreadId: (id: string | null) => void;
  threadHistoryLoaded: boolean;
  threadHistoryError: string | null;
  activeStreamingCount: number;

  /* Thread views */
  commentThreads: CommentThreadView[];
  commentThreadIds: string[];
  commentThreadById: Map<string, CommentThreadView>;
  commentsByThread: Map<string, Comment[]>;
  threadCountByAnchor: Map<string, number>;

  /* Actions */
  updateThreadDraft: (threadId: string, value: string) => void;
  createLocalThreadId: (anchorId: string) => string;
  streamAssistantReply: (threadId: string, anchorId: string, selectedText: string, question: string) => Promise<void>;
  sendThreadReply: (threadId: string, anchorId: string, selectedText: string) => void;

  /* Refs */
  threadRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  streamControllersRef: React.MutableRefObject<Map<string, AbortController>>;
}

export function useDocComments(
  subjectId: string | undefined,
  tocOrderMap: Map<string, number>,
): DocCommentsState {
  const [comments, setComments] = useState<Comment[]>([]);
  const [threadSessionIds, setThreadSessionIds] = useState<Record<string, string>>({});
  const [threadDrafts, setThreadDrafts] = useState<Record<string, string>>({});
  const [threadStreaming, setThreadStreaming] = useState<Record<string, boolean>>({});
  const [activeCommentThreadId, setActiveCommentThreadId] = useState<string | null>(null);
  const [pinnedThreadId, setPinnedThreadId] = useState<string | null>(null);
  const [threadHistoryLoaded, setThreadHistoryLoaded] = useState(false);
  const [threadHistoryError, setThreadHistoryError] = useState<string | null>(null);

  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const streamControllersRef = useRef(new Map<string, AbortController>());

  /* Load thread history */
  useEffect(() => {
    let cancelled = false;

    async function loadThreadHistory() {
      if (!subjectId) {
        setComments([]);
        setThreadSessionIds({});
        setActiveCommentThreadId(null);
        setThreadHistoryError(null);
        setThreadHistoryLoaded(true);
        return;
      }

      setThreadHistoryLoaded(false);
      setThreadHistoryError(null);
      try {
        const items: ThreadTurnItem[] = [];
        let page = 1;
        let totalPages = 1;
        while (page <= totalPages) {
          if (cancelled) return;
          const response = await apiClient<ApiResponse<PaginatedData<ThreadTurnItem>>>({
            method: "POST",
            url: `/api/v1/subjects/${subjectId}/chats/threads/list`,
            data: { page, size: THREAD_HISTORY_PAGE_SIZE, source: "quick_chat" },
          });
          const payload = response.data;
          const pageItems = payload?.items ?? [];
          items.push(...pageItems);
          totalPages = Math.max(1, payload?.pages ?? page);
          page += 1;
          if (pageItems.length < THREAD_HISTORY_PAGE_SIZE) break;
        }

        if (cancelled) return;

        const nextComments: Comment[] = [];
        const nextSessionIds: Record<string, string> = {};
        const selectedTextByThread = new Map<string, string>();

        for (const turn of items) {
          const anchorId = turn.anchor_id?.trim();
          const threadId = turn.session_id?.trim();
          if (!anchorId || !threadId) continue;
          nextSessionIds[threadId] = threadId;

          const selectedText = turn.selected_text?.trim() ?? "";
          if (selectedText && !selectedTextByThread.has(threadId)) {
            selectedTextByThread.set(threadId, selectedText);
          }
          const resolvedSelectedText = selectedText || selectedTextByThread.get(threadId) || "";
          for (const message of turn.messages ?? []) {
            if (message.role !== "user" && message.role !== "assistant") continue;
            const createdAtTs = Date.parse(message.created_at);
            nextComments.push({
              id: `history-${message.id}`,
              threadId,
              sessionId: threadId,
              anchorId,
              selectedText: resolvedSelectedText,
              role: message.role,
              content: message.content,
              createdAt: Number.isFinite(createdAtTs) ? createdAtTs : Date.now(),
            });
          }
        }

        nextComments.sort((left, right) => left.createdAt - right.createdAt);
        setComments(nextComments);
        setThreadSessionIds(nextSessionIds);
      } catch (error: unknown) {
        if (cancelled) return;
        setComments([]);
        setThreadSessionIds({});
        setActiveCommentThreadId(null);
        setThreadHistoryError(getApiErrorMessage(error, "加载划词问答历史失败"));
      } finally {
        if (!cancelled) setThreadHistoryLoaded(true);
      }
    }

    void loadThreadHistory();
    return () => { cancelled = true; };
  }, [subjectId]);

  /* Cleanup stream controllers */
  useEffect(() => {
    return () => {
      for (const controller of streamControllersRef.current.values()) {
        controller.abort();
      }
      streamControllersRef.current.clear();
    };
  }, []);

  /* Derived */
  const activeStreamingCount = useMemo(
    () => Object.values(threadStreaming).filter(Boolean).length,
    [threadStreaming],
  );

  const commentsByThread = useMemo(() => {
    const map = new Map<string, Comment[]>();
    for (const item of comments) {
      const list = map.get(item.threadId) ?? [];
      list.push(item);
      map.set(item.threadId, list);
    }
    for (const list of map.values()) {
      list.sort((left, right) => left.createdAt - right.createdAt);
    }
    return map;
  }, [comments]);

  const commentThreads = useMemo<CommentThreadView[]>(
    () =>
      Array.from(commentsByThread.entries())
        .map(([threadId, threadComments]) => {
          const anchorId = threadComments.find((item) => item.anchorId)?.anchorId ?? "";
          const selectedText = threadComments.find((item) => item.selectedText)?.selectedText ?? "";
          const createdAt = threadComments[0]?.createdAt ?? 0;
          return { threadId, anchorId, selectedText, comments: threadComments, createdAt };
        })
        .filter((item) => item.anchorId)
        .sort((left, right) => {
          const leftOrder = tocOrderMap.get(left.anchorId) ?? Number.MAX_SAFE_INTEGER;
          const rightOrder = tocOrderMap.get(right.anchorId) ?? Number.MAX_SAFE_INTEGER;
          if (leftOrder !== rightOrder) return leftOrder - rightOrder;
          return left.createdAt - right.createdAt;
        }),
    [commentsByThread, tocOrderMap],
  );

  const commentThreadIds = useMemo(() => commentThreads.map((item) => item.threadId), [commentThreads]);
  const commentThreadById = useMemo(
    () => new Map(commentThreads.map((item) => [item.threadId, item] as const)),
    [commentThreads],
  );
  const threadCountByAnchor = useMemo(() => {
    const next = new Map<string, number>();
    for (const item of commentThreads) {
      next.set(item.anchorId, (next.get(item.anchorId) ?? 0) + 1);
    }
    return next;
  }, [commentThreads]);

  /* Actions */
  const updateThreadDraft = useCallback((threadId: string, value: string) => {
    setThreadDrafts((prev) => {
      if (prev[threadId] === value) return prev;
      return { ...prev, [threadId]: value };
    });
  }, []);

  const createLocalThreadId = useCallback(
    (anchorId: string) => `local-${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    [],
  );

  const rebindThreadIdToSession = useCallback((threadId: string, candidateSessionId: string | null): string => {
    const resolvedSessionId = candidateSessionId?.trim() ?? "";
    if (!resolvedSessionId) return threadId;
    if (threadId === resolvedSessionId) {
      setThreadSessionIds((prev) => {
        if (prev[threadId] === resolvedSessionId) return prev;
        return { ...prev, [threadId]: resolvedSessionId };
      });
      setComments((prev) => {
        let changed = false;
        const next = prev.map((item) => {
          if (item.threadId !== threadId || item.sessionId === resolvedSessionId) return item;
          changed = true;
          return { ...item, sessionId: resolvedSessionId };
        });
        return changed ? next : prev;
      });
      return resolvedSessionId;
    }

    setComments((prev) =>
      prev.map((item) =>
        item.threadId === threadId
          ? { ...item, threadId: resolvedSessionId, sessionId: resolvedSessionId }
          : item,
      ),
    );
    setThreadSessionIds((prev) => {
      const withCurrent =
        prev[threadId] === resolvedSessionId ? prev : { ...prev, [threadId]: resolvedSessionId };
      return moveRecordKey(withCurrent, threadId, resolvedSessionId, (_, existing) => existing ?? resolvedSessionId);
    });
    setThreadDrafts((prev) =>
      moveRecordKey(prev, threadId, resolvedSessionId, (incoming, existing) => existing ?? incoming),
    );
    setThreadStreaming((prev) =>
      moveRecordKey(prev, threadId, resolvedSessionId, (incoming, existing) => Boolean(existing || incoming)),
    );
    setActiveCommentThreadId((prev) => (prev === threadId ? resolvedSessionId : prev));

    const controller = streamControllersRef.current.get(threadId);
    if (controller) {
      streamControllersRef.current.delete(threadId);
      streamControllersRef.current.set(resolvedSessionId, controller);
    }

    return resolvedSessionId;
  }, []);

  const streamAssistantReply = useCallback(
    async (threadId: string, anchorId: string, selectedText: string, question: string) => {
      const text = question.trim();
      if (!text) return;

      const baseId = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
      const userId = `${baseId}-user`;
      const assistantId = `${baseId}-assistant`;
      const now = Date.now();

      setComments((prev) => [
        ...prev,
        {
          id: userId, threadId, sessionId: threadSessionIds[threadId] ?? null,
          anchorId, selectedText, role: "user", content: text, createdAt: now,
        },
        {
          id: assistantId, threadId, sessionId: threadSessionIds[threadId] ?? null,
          anchorId, selectedText, role: "assistant", content: "", createdAt: now + 1, streaming: true,
        },
      ]);
      setThreadStreaming((prev) => ({ ...prev, [threadId]: true }));

      const previousController = streamControllersRef.current.get(threadId);
      if (previousController) previousController.abort();
      const controller = new AbortController();
      streamControllersRef.current.set(threadId, controller);
      let boundThreadId = threadId;

      const appendAssistantDelta = (delta: string) => {
        if (!delta) return;
        setComments((prev) =>
          prev.map((item) => (item.id === assistantId ? { ...item, content: item.content + delta } : item)),
        );
      };

      const replaceAssistantContent = (content: string) => {
        setComments((prev) =>
          prev.map((item) => (item.id === assistantId ? { ...item, content } : item)),
        );
      };

      const bindSessionToThread = (candidateSessionId: string | null) => {
        boundThreadId = rebindThreadIdToSession(boundThreadId, candidateSessionId);
      };

      try {
        const subject = subjectId ?? "demo";
        const result = await postSseJson(
          `/api/v1/subjects/${subject}/chats/send`,
          {
            question: text,
            source: "quick_chat",
            session_id: threadSessionIds[threadId] ?? undefined,
            anchor_id: anchorId,
            selected_context: selectedText || undefined,
          },
          {
            signal: controller.signal,
            onToken: ({ content }) => appendAssistantDelta(content),
            onDone: (payload) => bindSessionToThread(parseDoneSessionId(payload)),
            onError: (payload) => {
              const detail =
                payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
                  ? payload.detail
                  : "请求失败，请重试。";
              replaceAssistantContent(detail);
            },
          },
        );
        bindSessionToThread(parseDoneSessionId(result.donePayload));
        if (!result.aborted && !result.receivedToken && !result.errorPayload) {
          replaceAssistantContent("已收到问题，但当前没有返回内容。");
        }
      } catch (err: unknown) {
        if (!(err instanceof Error) || err.name !== "AbortError") {
          const detail = err instanceof Error && err.message.trim() ? err.message.trim() : "请求失败，请重试。";
          replaceAssistantContent(detail);
        }
      } finally {
        setComments((prev) =>
          prev.map((item) => (item.id === assistantId ? { ...item, streaming: false } : item)),
        );
        let activeControllerThreadId: string | null = null;
        for (const [key, value] of streamControllersRef.current.entries()) {
          if (value === controller) { activeControllerThreadId = key; break; }
        }
        if (activeControllerThreadId) {
          streamControllersRef.current.delete(activeControllerThreadId);
          setThreadStreaming((prev) => ({ ...prev, [activeControllerThreadId]: false }));
        } else if (boundThreadId) {
          setThreadStreaming((prev) => ({ ...prev, [boundThreadId]: false }));
        }
      }
    },
    [rebindThreadIdToSession, subjectId, threadSessionIds],
  );

  const sendThreadReply = useCallback(
    (threadId: string, anchorId: string, selectedText: string) => {
      if (threadStreaming[threadId]) return;
      const question = (threadDrafts[threadId] ?? "").trim();
      if (!question) return;
      setThreadDrafts((prev) => ({ ...prev, [threadId]: "" }));
      setActiveCommentThreadId(threadId);
      setPinnedThreadId(threadId);
      void streamAssistantReply(threadId, anchorId, selectedText, question);
    },
    [streamAssistantReply, threadDrafts, threadStreaming],
  );

  return {
    comments,
    setComments,
    threadSessionIds,
    threadDrafts,
    threadStreaming,
    activeCommentThreadId,
    setActiveCommentThreadId,
    pinnedThreadId,
    setPinnedThreadId,
    threadHistoryLoaded,
    threadHistoryError,
    activeStreamingCount,
    commentThreads,
    commentThreadIds,
    commentThreadById,
    commentsByThread,
    threadCountByAnchor,
    updateThreadDraft,
    createLocalThreadId,
    streamAssistantReply,
    sendThreadReply,
    threadRefs,
    streamControllersRef,
  };
}
