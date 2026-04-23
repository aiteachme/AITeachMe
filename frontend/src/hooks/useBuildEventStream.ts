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

import { useEffect, useRef, useState } from "react";
import type { KnowledgeBuildRuntimeResponse } from "../lib/knowledgeBuildRuntime";

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

interface UseBuildEventStreamOptions {
  subjectId: string;
  enabled: boolean;
  /** Called when the stream signals build completed/failed/cancelled */
  onDone?: (status: string) => void;
}

export function useBuildEventStream({
  subjectId,
  enabled,
  onDone,
}: UseBuildEventStreamOptions) {
  const [snapshot, setSnapshot] = useState<KnowledgeBuildRuntimeResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!enabled || !subjectId) {
      setSnapshot(null);
      setConnected(false);
      return;
    }

    const url = `${API_BASE_URL}/api/v1/subjects/${encodeURIComponent(subjectId)}/knowledge/build/stream`;
    const es = new EventSource(url, { withCredentials: true });

    es.addEventListener("snapshot", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as KnowledgeBuildRuntimeResponse;
        setSnapshot(data);
        setConnected(true);
      } catch {
        // ignore malformed events
      }
    });

    es.addEventListener("done", (e: MessageEvent) => {
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
      // EventSource will auto-reconnect; we just mark disconnected
      setConnected(false);
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [subjectId, enabled]);

  return { snapshot, connected };
}
