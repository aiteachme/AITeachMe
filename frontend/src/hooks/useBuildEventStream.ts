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
  subjectId: string;
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

const PREVIEW_FLUSH_INTERVAL_MS = 180;

export function useBuildEventStream({
  subjectId,
  enabled,
  onDone,
}: UseBuildEventStreamOptions) {
  const [snapshot, setSnapshot] = useState<KnowledgeBuildRuntimeResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [previewStreams, setPreviewStreams] = useState<Record<number, BuildPreviewStreamState>>({});
  const [buildEvents, setBuildEvents] = useState<BuildStreamRecentEvent[]>([]);
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

  useEffect(() => {
    if (!enabled || !subjectId) {
      setSnapshot(null);
      setConnected(false);
      previewStreamsRef.current = {};
      clearPreviewFlushTimer();
      setPreviewStreams({});
      setBuildEvents([]);
      return;
    }

    const url = buildApiUrl(`/api/v1/subjects/${encodeURIComponent(subjectId)}/knowledge/build/stream`);
    previewStreamsRef.current = {};
    clearPreviewFlushTimer();
    setPreviewStreams({});
    setBuildEvents([]);
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

    es.addEventListener("done", (e: MessageEvent) => {
      flushPreviewStreams();
      try {
        const data = JSON.parse(e.data);
        onDoneRef.current?.(data.status ?? "completed");
      } catch {
        onDoneRef.current?.("completed");
      }
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
  }, [subjectId, enabled, clearPreviewFlushTimer, flushPreviewStreams, schedulePreviewFlush]);

  return { snapshot, connected, previewStreams, buildEvents };
}
