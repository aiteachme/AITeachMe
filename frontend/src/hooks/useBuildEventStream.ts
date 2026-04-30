/**
 * useBuildEventStream — connect to the build SSE endpoint and
 * stream live snapshot updates into React state.
 *
 * Uses native EventSource (GET + cookies). Falls back gracefully
 * when the SSE connection fails or the build is not active.
 *
 * The SSE `snapshot` event carries the full KnowledgeBuildRuntimeResponse
 * shape (same as the POST /build/runtime endpoint).
 */

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import type { KnowledgeBuildRuntimeResponse } from "../lib/knowledgeBuildRuntime";
import {
  buildApiUrl,
  registerBackendEventSource,
  reportBackendConnectionIssue,
} from "../api/client";

interface UseBuildEventStreamOptions {
  courseId: string;
  enabled: boolean;
  /** Called when the stream signals build completed/failed/cancelled */
  onDone?: (status: string) => void;
}

export interface BuildPreviewStreamState {
  chapterIndex: number;
  title?: string;
  status?: string;
  text: string;
  fullLength: number;
  updatedAt?: string | null;
  revision: number;
}

export interface BuildStreamRecentEvent {
  stage?: string | null;
  chapter_index?: number | null;
  title?: string | null;
  summary?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface BuildStreamGraphDeltaEvent {
  stage?: string | null;
  build_revision_no?: number | null;
  unit_count?: number | null;
  edge_count?: number | null;
  created_unit_count?: number | null;
  updated_unit_count?: number | null;
  deprecated_unit_count?: number | null;
  created_edge_count?: number | null;
  updated_edge_count?: number | null;
  deprecated_edge_count?: number | null;
  emitted_at?: string | null;
  [key: string]: unknown;
}

interface BuildPreviewDeltaEvent {
  kind?: string;
  chapter_index?: number;
  title?: string;
  status?: string;
  mode?: "append" | "replace";
  base_length?: number;
  text?: string;
  full_length?: number;
  updated_at?: string | null;
}

const resolvePreviewFlushIntervalMs = () => {
  const parsed = Number(import.meta.env.VITE_BUILD_PREVIEW_FLUSH_INTERVAL_MS);
  if (!Number.isFinite(parsed)) return 160;
  return Math.min(500, Math.max(60, parsed));
};

const PREVIEW_FLUSH_INTERVAL_MS = resolvePreviewFlushIntervalMs();
const TERMINAL_PREVIEW_STATUSES = new Set(["generated", "completed", "enhanced", "reviewed"]);

export function useBuildEventStream({
  courseId,
  enabled,
  onDone,
}: UseBuildEventStreamOptions) {
  const [snapshot, setSnapshot] = useState<KnowledgeBuildRuntimeResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [previewStreams, setPreviewStreams] = useState<Record<number, BuildPreviewStreamState>>({});
  const [buildEvents, setBuildEvents] = useState<BuildStreamRecentEvent[]>([]);
  const [graphDeltas, setGraphDeltas] = useState<BuildStreamGraphDeltaEvent[]>([]);
  const onDoneRef = useRef(onDone);
  const previewStreamsRef = useRef<Record<number, BuildPreviewStreamState>>({});
  const previewFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  onDoneRef.current = onDone;

  const clearPreviewFlushTimer = useCallback(() => {
    if (previewFlushTimerRef.current) {
      clearTimeout(previewFlushTimerRef.current);
      previewFlushTimerRef.current = null;
    }
  }, []);

  const flushPreviewStreams = useCallback(() => {
    clearPreviewFlushTimer();
    const nextStreams = previewStreamsRef.current;
    startTransition(() => {
      setPreviewStreams(nextStreams);
    });
  }, [clearPreviewFlushTimer]);

  const schedulePreviewFlush = useCallback((immediate = false) => {
    if (immediate) {
      flushPreviewStreams();
      return;
    }
    if (previewFlushTimerRef.current) return;
    previewFlushTimerRef.current = setTimeout(flushPreviewStreams, PREVIEW_FLUSH_INTERVAL_MS);
  }, [flushPreviewStreams]);

  const mergeSnapshotPreviewStreams = useCallback((data: KnowledgeBuildRuntimeResponse) => {
    const chapterPreviews = data.docgen_preview?.chapter_previews ?? [];
    if (chapterPreviews.length === 0) return;

    let changed = false;
    let nextStreams = previewStreamsRef.current;
    for (const chapterPreview of chapterPreviews) {
      const chapterIndex = Number(chapterPreview.chapter_index ?? 0);
      const text = String(chapterPreview.excerpt ?? "");
      if (!chapterIndex || !text.trim()) continue;

      const current = nextStreams[chapterIndex];
      const status = String(chapterPreview.status ?? current?.status ?? "");
      const shouldReplace =
        !current ||
        text.length > current.text.length ||
        current.status !== status ||
        (TERMINAL_PREVIEW_STATUSES.has(status) && text !== current.text);
      if (!shouldReplace) continue;

      nextStreams = {
        ...nextStreams,
        [chapterIndex]: {
          chapterIndex,
          title: chapterPreview.title ?? current?.title,
          status,
          text,
          fullLength: text.length,
          updatedAt: chapterPreview.updated_at ?? current?.updatedAt ?? null,
          revision: (current?.revision ?? 0) + 1,
        },
      };
      changed = true;
    }

    if (changed) {
      previewStreamsRef.current = nextStreams;
      schedulePreviewFlush(true);
    }
  }, [schedulePreviewFlush]);

  useEffect(() => {
    if (!enabled || !courseId) {
      setSnapshot(null);
      setConnected(false);
      previewStreamsRef.current = {};
      clearPreviewFlushTimer();
      setPreviewStreams({});
      setBuildEvents([]);
      setGraphDeltas([]);
      return;
    }

    const url = buildApiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}/knowledge/build/stream`);
    previewStreamsRef.current = {};
    clearPreviewFlushTimer();
    setPreviewStreams({});
    setBuildEvents([]);
    setGraphDeltas([]);
    const es = new EventSource(url, { withCredentials: true });
    const unregisterEventSource = registerBackendEventSource(es);

    es.onopen = () => {
      setConnected(true);
    };

    es.addEventListener("ping", () => {
      setConnected(true);
    });

    es.addEventListener("snapshot", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as KnowledgeBuildRuntimeResponse;
        setSnapshot(data);
        mergeSnapshotPreviewStreams(data);
        setConnected(true);
      } catch {
        // ignore malformed events
      }
    });

    es.addEventListener("preview_delta", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as BuildPreviewDeltaEvent;
        const chapterIndex = Number(data.chapter_index ?? 0);
        const deltaText = data.text ?? "";
        if (!chapterIndex || !deltaText) return;
        const current = previewStreamsRef.current[chapterIndex];
        const currentText = current?.text ?? "";
        if (
          data.mode === "append" &&
          typeof data.base_length === "number" &&
          data.base_length >= 0 &&
          currentText.length !== data.base_length
        ) {
          return;
        }
        const nextText = data.mode === "append"
          ? `${currentText}${deltaText}`
          : deltaText;
        previewStreamsRef.current = {
          ...previewStreamsRef.current,
          [chapterIndex]: {
            chapterIndex,
            title: data.title ?? current?.title,
            status: data.status ?? current?.status,
            text: nextText,
            fullLength: Number(data.full_length ?? nextText.length),
            updatedAt: data.updated_at ?? current?.updatedAt ?? null,
            revision: (current?.revision ?? 0) + 1,
          },
        };
        schedulePreviewFlush(!current || data.mode !== "append");
        setConnected(true);
      } catch {
        // ignore malformed delta events
      }
    });

    es.addEventListener("build_event", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as BuildStreamRecentEvent;
        if (!data.summary && !data.stage) return;
        setBuildEvents((prev) => [data, ...prev].slice(0, 50));
        setConnected(true);
      } catch {
        // ignore malformed build events
      }
    });

    es.addEventListener("graph_delta", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as BuildStreamGraphDeltaEvent;
        setGraphDeltas((prev) => [data, ...prev].slice(0, 24));
        setConnected(true);
      } catch {
        // ignore malformed graph delta events
      }
    });

    es.addEventListener("done", (e: MessageEvent) => {
      flushPreviewStreams();
      try {
        const data = JSON.parse(e.data);
        onDoneRef.current?.(data.status ?? "completed");
      } catch {
        onDoneRef.current?.("completed");
      }
      unregisterEventSource();
      es.close();
      setConnected(false);
    });

    es.onerror = () => {
      reportBackendConnectionIssue("knowledge_build_stream_error");
      setConnected(false);
    };

    return () => {
      unregisterEventSource();
      es.close();
      clearPreviewFlushTimer();
      setConnected(false);
    };
  }, [courseId, enabled, clearPreviewFlushTimer, flushPreviewStreams, schedulePreviewFlush, mergeSnapshotPreviewStreams]);

  return { snapshot, connected, previewStreams, buildEvents, graphDeltas };
}
