/* ------------------------------------------------------------------ */
/*  useDocMarkdown - Data fetching & derived state for knowledge docs  */
/* ------------------------------------------------------------------ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";

import { apiClient } from "../../../api/client";
import type { FileRecord } from "../../../api/generated/model";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  buildRuntimeFailureBackoffMs,
  fetchKnowledgeBuildRuntime,
  hasKnowledgeBuildDraftFallback,
} from "../../../lib/knowledgeBuildRuntime";
import { formatDigestModeLabel } from "../../../lib/digestMode";
import type {
  ApiResponse,
  DocGenBuildStatus,
  DocGenGetResponse,
  DocViewMode,
  FilesListResponse,
  KnowledgeBuildMetrics,
  KnowledgeBuildPreview,
} from "../types";
import {
  ACTIVE_DOC_BUILD_STATUSES,
  TERMINAL_DOC_BUILD_READY_STATUSES,
  cleanKnowledgeMarkdownForDisplay,
  extractFirstMarkdownHeading,
  extractFirstMarkdownParagraph,
  formatDocTimestamp,
  parseIsoTimestamp,
} from "../utils";

export interface KnowledgeDocPublicationHeading {
  id: string;
  text: string;
  level: number;
  chunk_index: number;
}

interface KnowledgeDocPublicationChunkSummary {
  chunk_index: number;
  chapter_index: number;
  title: string;
  heading_id: string;
  char_count: number;
}

interface KnowledgeDocPublicationManifest {
  exists: boolean;
  publication_id: string | null;
  version_no: number;
  updated_at: string | null;
  chunks: KnowledgeDocPublicationChunkSummary[];
  headings: KnowledgeDocPublicationHeading[];
}

interface KnowledgeDocPublicationChunk {
  publication_id: string;
  version_no: number;
  chunk_index: number;
  chapter_index: number;
  title: string;
  markdown: string;
  headings: KnowledgeDocPublicationHeading[];
}

interface ChunkLoadInFlight {
  publicationId: string;
  generation: number;
  promise: Promise<void>;
}

async function fetchSourceFiles(courseId: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesListResponse>>({
    method: "GET",
    url: `/api/v1/courses/${courseId}/files`,
  });
  return response.data?.items ?? [];
}

async function fetchPublicationManifest(courseId: string): Promise<KnowledgeDocPublicationManifest> {
  const response = await apiClient<ApiResponse<KnowledgeDocPublicationManifest>>({
    method: "GET",
    url: `/api/v1/courses/${courseId}/knowledge/docs/manifest`,
  });
  return response.data;
}

async function fetchPublicationChunk(
  courseId: string,
  publicationId: string,
  chunkIndex: number,
): Promise<KnowledgeDocPublicationChunk> {
  const response = await apiClient<ApiResponse<KnowledgeDocPublicationChunk>>({
    method: "GET",
    url: `/api/v1/courses/${courseId}/knowledge/docs/publications/${encodeURIComponent(publicationId)}/chunks/${chunkIndex}`,
  });
  return response.data;
}

function hasPublishedDocument(data: DocGenGetResponse | undefined): boolean {
  return Boolean(data?.exists);
}

function hasRequestedPublishedDocument(
  data: DocGenGetResponse | undefined,
  {
    status,
    targetRequestedAtMs,
  }: {
    status: string;
    targetRequestedAtMs: number | null;
  },
): boolean {
  if (!hasPublishedDocument(data)) return false;
  if (targetRequestedAtMs === null) return true;

  const updatedAtMs = parseIsoTimestamp(data?.updated_at ?? null);
  if (updatedAtMs === null) {
    return TERMINAL_DOC_BUILD_READY_STATUSES.has(status);
  }
  return updatedAtMs >= targetRequestedAtMs;
}

function getHttpStatus(error: unknown): number | null {
  if (!error || typeof error !== "object") return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === "number" ? response.status : null;
}

const GRAPH_SYNC_BUILD_STAGES = new Set([
  "graph_pending",
  "manual_graph_requested",
  "queued_after_docgen",
  "graph_docs_sync",
]);
const VECTOR_STATUS_REFRESH_RETRY_DELAY_MS = 5000;
const VECTOR_STATUS_REFRESH_MAX_ATTEMPTS = 24;

export interface DocMarkdownState {
  courseId: string | undefined;
  requestedAt: string | null;
  docMarkdownQuery: ReturnType<typeof useQuery<DocGenGetResponse>>;
  liveMarkdown: string;
  draftMarkdown: string;
  buildMeta: DocGenBuildStatus | null;
  buildPreview: KnowledgeBuildPreview | null;
  buildMetrics: KnowledgeBuildMetrics | null;
  buildStatus: string | null;
  graphStatus: string | null;
  graphUnhealthy: boolean;
  trainingUnlocked: boolean;
  liveUpdatedAt: string | null;
  draftUpdatedAt: string | null;
  hasLiveDocMarkdown: boolean;
  hasDraftDocMarkdown: boolean;
  isBuildActive: boolean;
  isBuildFailure: boolean;
  isGraphSyncActive: boolean;
  isRequestedBuildReady: boolean;
  isWaitingForRequestedBuild: boolean;
  docViewMode: DocViewMode;
  setDocViewMode: (mode: DocViewMode) => void;
  effectiveDocViewMode: DocViewMode;
  renderedMarkdown: string;
  hasRenderedMarkdown: boolean;
  renderedDocUpdatedLabel: string | null;
  renderedDigestModeLabel: string;
  renderedChapterHighlights: string[];
  renderedCourseLabel: string;
  renderedDocTitle: string;
  renderedDocSummary: string;
  sourceFiles: FileRecord[];
  sourceFilesFetching: boolean;
  showDocLoadingState: boolean;
  showDocGeneratingState: boolean;
  showDocBuildFailureState: boolean;
  showDocEmptyState: boolean;
  showDocUpdatingBanner: boolean;
  publicationId: string | null;
  publicationHeadings: KnowledgeDocPublicationHeading[];
  loadedChunkCount: number;
  totalChunkCount: number;
  hasNextChunk: boolean;
  isLoadingNextChunk: boolean;
  publicationError: unknown;
  draftError: unknown;
  loadNextChunk: () => Promise<boolean>;
  ensureHeadingLoaded: (headingId: string) => Promise<boolean>;
  ensureAllChunksLoaded: () => Promise<string>;
  refreshDocument: () => Promise<void>;
}

export function useDocMarkdown(): DocMarkdownState {
  const { courseId } = useParams<{ courseId: string }>();
  const location = useLocation();
  const queryClient = useQueryClient();
  const requestedAt = useMemo(
    () => new URLSearchParams(location.search).get("requested_at"),
    [location.search],
  );
  const requestedAtMs = useMemo(() => parseIsoTimestamp(requestedAt), [requestedAt]);

  const [docViewMode, setDocViewMode] = useState<DocViewMode>("live");
  const [publicationChunks, setPublicationChunks] = useState<KnowledgeDocPublicationChunk[]>([]);
  const [publicationError, setPublicationError] = useState<unknown>(null);
  const [isLoadingNextChunk, setIsLoadingNextChunk] = useState(false);
  const [terminalRefreshRetryNonce, setTerminalRefreshRetryNonce] = useState(0);
  const lastTerminalDocRefreshKeyRef = useRef<string | null>(null);
  const lastPublicationMetadataRefreshKeyRef = useRef<string | null>(null);
  const publicationManifestRef = useRef<KnowledgeDocPublicationManifest | undefined>(undefined);
  const publicationChunksRef = useRef<KnowledgeDocPublicationChunk[]>([]);
  const activePublicationIdRef = useRef<string | null>(null);
  const publicationGenerationRef = useRef(0);
  const chunkLoadInFlightRef = useRef<ChunkLoadInFlight | null>(null);
  const publicationMountedRef = useRef(true);
  const terminalRefreshRetryTimerRef = useRef<number | null>(null);
  const terminalRefreshRetryKeyRef = useRef<string | null>(null);
  const terminalRefreshAttemptRef = useRef(0);

  useEffect(() => {
    publicationMountedRef.current = true;
    return () => {
      publicationMountedRef.current = false;
      publicationGenerationRef.current += 1;
      activePublicationIdRef.current = null;
      chunkLoadInFlightRef.current = null;
      if (terminalRefreshRetryTimerRef.current !== null) {
        window.clearTimeout(terminalRefreshRetryTimerRef.current);
        terminalRefreshRetryTimerRef.current = null;
      }
      lastTerminalDocRefreshKeyRef.current = null;
      terminalRefreshRetryKeyRef.current = null;
      terminalRefreshAttemptRef.current = 0;
    };
  }, []);

  const docMarkdownQuery = useQuery<DocGenGetResponse>({
    queryKey: ["docgen-content", courseId, requestedAt, "metadata"],
    queryFn: async () => {
      if (!courseId) {
        throw new Error("缺少课程 ID，无法加载知识文档。");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
        params: {
          include_markdown: false,
          include_draft: false,
        },
      });
      return response.data;
    },
    enabled: Boolean(courseId),
    staleTime: 30000,
    refetchInterval: (query) => {
      const data = query.state.data;
      const build = data?.build;
      const status = (build?.status ?? "").trim();
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(build?.requested_at ?? null);
      const hasRequestedLiveDoc = hasRequestedPublishedDocument(data, { status, targetRequestedAtMs });
      if (hasRequestedLiveDoc) return false;

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) return 2500;
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) return 1200;
      if (status === "failed" || status === "cancelled") return false;
      if (!status || status === "idle") return false;
      return 2500;
    },
  });

  const runtimeQuery = useQuery({
    queryKey: courseId
      ? [...buildKnowledgeBuildRuntimeQueryKey(courseId), requestedAt]
      : ["knowledge-build-runtime-empty"],
    queryFn: () => fetchKnowledgeBuildRuntime(courseId as string),
    enabled: Boolean(courseId),
    refetchInterval: (query) => {
      const failureBackoff = buildRuntimeFailureBackoffMs(query.state.fetchFailureCount);
      if (failureBackoff !== null) return failureBackoff;
      const statuses = [
        query.state.data?.aggregate?.status,
        query.state.data?.docgen?.status,
        query.state.data?.graph?.status,
        query.state.data?.graph_status,
      ].map((status) => (status ?? "").trim());
      if (statuses.some((status) => ACTIVE_DOC_BUILD_STATUSES.has(status) || status === "pending")) {
        return 2500;
      }

      const docgen = query.state.data?.docgen ?? query.state.data?.aggregate;
      const status = (docgen?.status ?? "").trim();
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(docgen?.requested_at ?? null);
      const hasRequestedLiveDoc = hasRequestedPublishedDocument(docMarkdownQuery.data, {
        status,
        targetRequestedAtMs,
      });
      if (hasRequestedLiveDoc) return false;

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) return 2500;
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) return 1200;
      if (status === "failed" || status === "cancelled") return false;
      if (!status || status === "idle") return false;
      return 2500;
    },
  });

  const publicationManifestQuery = useQuery<KnowledgeDocPublicationManifest>({
    queryKey: ["docgen-publication-manifest", courseId],
    queryFn: () => fetchPublicationManifest(courseId as string),
    enabled: Boolean(courseId),
    staleTime: 30000,
  });
  publicationManifestRef.current = publicationManifestQuery.data;
  const refetchPublicationManifest = publicationManifestQuery.refetch;

  const buildMeta = runtimeQuery.data?.docgen ?? docMarkdownQuery.data?.build ?? runtimeQuery.data?.aggregate ?? null;
  const buildPreview = runtimeQuery.data?.docgen_preview ?? docMarkdownQuery.data?.build_preview ?? null;
  const buildMetrics = runtimeQuery.data?.docgen_metrics ?? docMarkdownQuery.data?.build_metrics ?? null;
  const buildStatus = buildMeta?.status ?? null;
  const buildStage = (buildMeta?.stage ?? "").trim();
  const graphStatus = (runtimeQuery.data?.graph_status ?? runtimeQuery.data?.graph?.status ?? null)?.trim() || null;
  const graphStage = (runtimeQuery.data?.graph?.stage ?? "").trim();
  const graphUnhealthy = Boolean(runtimeQuery.data?.graph_unhealthy);
  const trainingUnlocked = Boolean(runtimeQuery.data?.training_unlocked);
  const draftAvailable = Boolean(
    docMarkdownQuery.data?.build?.draft_available || hasKnowledgeBuildDraftFallback(runtimeQuery.data),
  );

  const draftMarkdownQuery = useQuery<DocGenGetResponse>({
    queryKey: ["docgen-draft-content", courseId, buildMeta?.requested_at ?? ""],
    queryFn: async () => {
      if (!courseId) {
        throw new Error("缺少课程 ID，无法加载知识文档草稿。");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
        params: {
          include_markdown: false,
          include_draft: true,
        },
      });
      return response.data;
    },
    enabled: Boolean(courseId && draftAvailable),
    staleTime: 5000,
    refetchInterval: docViewMode === "draft" && buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus)
      ? 5000
      : false,
  });

  const resetPublicationChunks = useCallback((publicationId: string | null) => {
    publicationGenerationRef.current += 1;
    activePublicationIdRef.current = publicationId;
    publicationChunksRef.current = [];
    if (!publicationMountedRef.current) return;
    setPublicationChunks([]);
    setPublicationError(null);
  }, []);

  const ensureChunkIndexLoaded = useCallback(async (
    targetChunkIndex: number,
    throwOnError = false,
  ): Promise<boolean> => {
    if (!courseId) return false;

    while (true) {
      if (!publicationMountedRef.current) return false;
      const manifest = publicationManifestRef.current;
      const publicationId = manifest?.publication_id ?? null;
      if (!manifest?.exists || !publicationId || manifest.chunks.length === 0) return false;
      if (activePublicationIdRef.current !== publicationId) return false;

      const boundedTarget = Math.min(Math.max(0, targetChunkIndex), manifest.chunks.length - 1);
      if (publicationChunksRef.current.length > boundedTarget) return true;

      const existingRequest = chunkLoadInFlightRef.current;
      if (existingRequest) {
        if (
          existingRequest.publicationId === publicationId &&
          existingRequest.generation === publicationGenerationRef.current
        ) {
          try {
            await existingRequest.promise;
          } catch (error) {
            if (throwOnError) throw error;
            return false;
          }
          continue;
        }
        chunkLoadInFlightRef.current = null;
      }

      const generation = publicationGenerationRef.current;
      const nextChunkIndex = publicationChunksRef.current.length;
      setIsLoadingNextChunk(true);

      let requestPromise: Promise<void>;
      requestPromise = queryClient.fetchQuery({
        queryKey: ["docgen-publication-chunk", courseId, publicationId, generation, nextChunkIndex],
        queryFn: async () => {
          const chunk = await fetchPublicationChunk(courseId, publicationId, nextChunkIndex);
          if (
            chunk.publication_id !== publicationId ||
            chunk.version_no !== manifest.version_no ||
            chunk.chunk_index !== nextChunkIndex
          ) {
            throw new Error("知识文档章节响应与当前发布版本不一致。");
          }
          return chunk;
        },
        staleTime: Number.POSITIVE_INFINITY,
        retry: (failureCount, error) => getHttpStatus(error) !== 409 && failureCount < 2,
      }).then((chunk) => {
        if (
          !publicationMountedRef.current ||
          activePublicationIdRef.current !== publicationId ||
          publicationGenerationRef.current !== generation
        ) {
          return;
        }
        const current = publicationChunksRef.current;
        if (current.length !== nextChunkIndex) return;
        const next = [...current, chunk];
        publicationChunksRef.current = next;
        setPublicationChunks(next);
        setPublicationError(null);
      }).catch((error) => {
        if (
          publicationMountedRef.current &&
          activePublicationIdRef.current === publicationId &&
          publicationGenerationRef.current === generation
        ) {
          setPublicationError(error);
          if (getHttpStatus(error) === 409) {
            void refetchPublicationManifest();
          }
        }
        throw error;
      }).finally(() => {
        if (
          publicationMountedRef.current &&
          chunkLoadInFlightRef.current?.promise === requestPromise
        ) {
          chunkLoadInFlightRef.current = null;
          setIsLoadingNextChunk(false);
        }
      });

      chunkLoadInFlightRef.current = { publicationId, generation, promise: requestPromise };
      try {
        await requestPromise;
      } catch (error) {
        if (throwOnError) throw error;
        return false;
      }
    }
  }, [courseId, queryClient, refetchPublicationManifest]);

  const loadNextChunk = useCallback(async (): Promise<boolean> => {
    const nextIndex = publicationChunksRef.current.length;
    return ensureChunkIndexLoaded(nextIndex);
  }, [ensureChunkIndexLoaded]);

  const ensureHeadingLoaded = useCallback(async (headingId: string): Promise<boolean> => {
    const normalizedId = headingId.trim();
    if (!normalizedId) return false;
    if (docViewMode === "draft") return true;
    const manifest = publicationManifestRef.current;
    const heading = manifest?.headings.find((item) => item.id === normalizedId);
    if (!heading) return false;
    return ensureChunkIndexLoaded(heading.chunk_index, true);
  }, [docViewMode, ensureChunkIndexLoaded]);

  const ensureAllChunksLoaded = useCallback(async (): Promise<string> => {
    if (docViewMode === "draft") {
      return cleanKnowledgeMarkdownForDisplay(draftMarkdownQuery.data?.draft_markdown ?? "");
    }
    while (true) {
      if (!publicationMountedRef.current) return "";
      const manifest = publicationManifestRef.current;
      if (!manifest?.exists || !manifest.publication_id || manifest.chunks.length === 0) {
        return cleanKnowledgeMarkdownForDisplay(draftMarkdownQuery.data?.draft_markdown ?? "");
      }
      const publicationId = manifest.publication_id;
      const totalChunks = manifest.chunks.length;
      const loaded = await ensureChunkIndexLoaded(totalChunks - 1, true);
      const currentManifest = publicationManifestRef.current;
      if (
        !loaded &&
        currentManifest?.publication_id === publicationId &&
        currentManifest.chunks.length === totalChunks
      ) {
        throw new Error("知识文档尚未完整加载，请重试。");
      }
      if (
        loaded &&
        currentManifest?.publication_id === publicationId &&
        currentManifest.chunks.length === totalChunks &&
        activePublicationIdRef.current === publicationId &&
        publicationChunksRef.current.length === totalChunks
      ) {
        return cleanKnowledgeMarkdownForDisplay(
          publicationChunksRef.current.map((chunk) => chunk.markdown).join(""),
        );
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    }
  }, [docViewMode, draftMarkdownQuery.data?.draft_markdown, ensureChunkIndexLoaded]);

  const refreshDocument = useCallback(async (): Promise<void> => {
    const previousLoadedChunkCount = publicationChunksRef.current.length;
    const metadataResult = await docMarkdownQuery.refetch();
    if (metadataResult.isError) {
      throw metadataResult.error ?? new Error("知识文档状态刷新失败。");
    }
    if (!publicationMountedRef.current) return;
    if (draftAvailable) {
      const draftResult = await draftMarkdownQuery.refetch();
      if (draftResult.isError) {
        throw draftResult.error ?? new Error("知识文档草稿刷新失败。");
      }
      if (!publicationMountedRef.current) return;
    }
    const manifestResult = await refetchPublicationManifest();
    if (manifestResult.isError) {
      throw manifestResult.error ?? new Error("知识文档发布清单刷新失败。");
    }
    if (!publicationMountedRef.current) return;
    const publicationId = manifestResult.data?.publication_id ?? null;
    resetPublicationChunks(publicationId);
    publicationManifestRef.current = manifestResult.data;
    const totalChunks = manifestResult.data?.chunks.length ?? 0;
    if (publicationId && totalChunks > 0) {
      const targetChunkIndex = Math.max(0, Math.min(previousLoadedChunkCount - 1, totalChunks - 1));
      const loaded = await ensureChunkIndexLoaded(targetChunkIndex);
      if (!loaded && publicationMountedRef.current) {
        throw new Error("知识文档章节刷新失败。");
      }
    }
  }, [
    docMarkdownQuery.refetch,
    draftAvailable,
    draftMarkdownQuery.refetch,
    ensureChunkIndexLoaded,
    refetchPublicationManifest,
    resetPublicationChunks,
  ]);

  const publicationId = publicationManifestQuery.data?.publication_id ?? null;
  useEffect(() => {
    if (activePublicationIdRef.current === publicationId) return;
    resetPublicationChunks(publicationId);
    if (publicationId) {
      void ensureChunkIndexLoaded(0);
    }
  }, [ensureChunkIndexLoaded, publicationId, resetPublicationChunks]);

  useEffect(() => {
    if (!courseId || !docMarkdownQuery.data?.exists) return;
    const metadataUpdatedAt = docMarkdownQuery.data.updated_at ?? null;
    if (!metadataUpdatedAt) return;
    const metadataUpdatedAtMs = parseIsoTimestamp(metadataUpdatedAt);
    const manifestUpdatedAtMs = parseIsoTimestamp(publicationManifestQuery.data?.updated_at ?? null);
    if (metadataUpdatedAtMs !== null && metadataUpdatedAtMs === manifestUpdatedAtMs) return;
    const refreshKey = `${courseId}:${metadataUpdatedAt}`;
    if (lastPublicationMetadataRefreshKeyRef.current === refreshKey) return;
    lastPublicationMetadataRefreshKeyRef.current = refreshKey;
    void refetchPublicationManifest().then((result) => {
      if (result.isError && lastPublicationMetadataRefreshKeyRef.current === refreshKey) {
        lastPublicationMetadataRefreshKeyRef.current = null;
      }
    });
  }, [
    courseId,
    docMarkdownQuery.data?.exists,
    docMarkdownQuery.data?.updated_at,
    publicationManifestQuery.data?.updated_at,
    refetchPublicationManifest,
  ]);

  const visiblePublicationChunks = activePublicationIdRef.current === publicationId
    ? publicationChunks
    : [];
  const rawLiveMarkdown = useMemo(
    () => visiblePublicationChunks.map((chunk) => chunk.markdown).join(""),
    [visiblePublicationChunks],
  );
  const rawDraftMarkdown = draftMarkdownQuery.data?.draft_markdown ?? "";
  const liveMarkdown = useMemo(
    () => cleanKnowledgeMarkdownForDisplay(rawLiveMarkdown),
    [rawLiveMarkdown],
  );
  const draftMarkdown = useMemo(
    () => cleanKnowledgeMarkdownForDisplay(rawDraftMarkdown),
    [rawDraftMarkdown],
  );
  const liveUpdatedAt = publicationManifestQuery.data?.updated_at ?? docMarkdownQuery.data?.updated_at ?? null;
  const draftUpdatedAt = draftMarkdownQuery.data?.draft_updated_at ?? docMarkdownQuery.data?.draft_updated_at ?? null;
  const hasLiveDocMarkdown = Boolean(publicationManifestQuery.data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftDocMarkdown = Boolean(draftMarkdown.trim().length > 0);

  const buildRequestedAtMs = useMemo(
    () => parseIsoTimestamp(buildMeta?.requested_at),
    [buildMeta?.requested_at],
  );
  const targetRequestedAtMs =
    buildStatus && buildStatus !== "idle"
      ? requestedAtMs ?? buildRequestedAtMs
      : null;
  const fallbackRequestedBuildReady = hasRequestedPublishedDocument(docMarkdownQuery.data, {
    status: buildStatus ?? "",
    targetRequestedAtMs,
  });
  const isRuntimeDocumentReady = runtimeQuery.data?.docs_ready === true;
  const isRequestedBuildReady =
    targetRequestedAtMs !== null
      ? fallbackRequestedBuildReady
      : typeof runtimeQuery.data?.docs_ready === "boolean"
        ? isRuntimeDocumentReady
        : fallbackRequestedBuildReady;
  const isBuildActive = Boolean(!isRequestedBuildReady && buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus));
  const isGraphSyncActive = Boolean(
    (graphStatus && (ACTIVE_DOC_BUILD_STATUSES.has(graphStatus) || graphStatus === "pending")) ||
    GRAPH_SYNC_BUILD_STAGES.has(graphStage) ||
    GRAPH_SYNC_BUILD_STAGES.has(buildStage),
  );
  const isBuildFailure = buildStatus === "failed" || buildStatus === "cancelled";
  const isBuildReadyStatus = Boolean(buildStatus && TERMINAL_DOC_BUILD_READY_STATUSES.has(buildStatus));
  const isWaitingForRequestedBuild =
    !isRequestedBuildReady &&
    !isBuildFailure &&
    Boolean(
      draftAvailable ||
      isBuildActive ||
      isBuildReadyStatus ||
      targetRequestedAtMs !== null
    );

  useEffect(() => {
    const vectorStatus = docMarkdownQuery.data?.vector_status;
    const vectorNotice = vectorStatus?.notice?.trim() ?? "";
    if (
      !courseId ||
      !trainingUnlocked ||
      vectorStatus?.mode === "disabled" ||
      !vectorNotice
    ) return;

    let cancelled = false;
    let attemptCount = 0;
    let retryTimer: number | null = null;
    const refreshVectorStatus = async () => {
      attemptCount += 1;
      const result = await docMarkdownQuery.refetch();
      if (cancelled) return;
      const refreshedStatus = result.data?.vector_status;
      const shouldRetry = Boolean(
        result.isError ||
        (
          refreshedStatus?.mode !== "disabled" &&
          refreshedStatus?.notice?.trim()
        ),
      );
      if (shouldRetry && attemptCount < VECTOR_STATUS_REFRESH_MAX_ATTEMPTS) {
        retryTimer = window.setTimeout(refreshVectorStatus, VECTOR_STATUS_REFRESH_RETRY_DELAY_MS);
      }
    };

    void refreshVectorStatus();
    return () => {
      cancelled = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
    };
  }, [
    courseId,
    docMarkdownQuery.data?.vector_status?.mode,
    docMarkdownQuery.data?.vector_status?.notice,
    docMarkdownQuery.refetch,
    runtimeQuery.data?.build_group_id,
    runtimeQuery.data?.graph?.finished_at,
    trainingUnlocked,
  ]);

  useEffect(() => {
    if (!courseId || docMarkdownQuery.isFetching) return;
    if (!isBuildReadyStatus) return;
    const terminalRequestedAtMs = parseIsoTimestamp(buildMeta?.requested_at ?? null);
    const currentPublicationUpdatedAtMs = parseIsoTimestamp(publicationManifestQuery.data?.updated_at ?? null);
    if (
      publicationId &&
      (
        terminalRequestedAtMs === null ||
        (currentPublicationUpdatedAtMs !== null && currentPublicationUpdatedAtMs >= terminalRequestedAtMs)
      )
    ) {
      return;
    }
    const refreshKey = [
      courseId,
      requestedAt ?? "",
      buildStatus ?? "",
      buildMeta?.requested_at ?? "",
    ].join(":");
    if (terminalRefreshRetryKeyRef.current !== refreshKey) {
      terminalRefreshRetryKeyRef.current = refreshKey;
      terminalRefreshAttemptRef.current = 0;
      if (terminalRefreshRetryTimerRef.current !== null) {
        window.clearTimeout(terminalRefreshRetryTimerRef.current);
        terminalRefreshRetryTimerRef.current = null;
      }
    }
    if (lastTerminalDocRefreshKeyRef.current === refreshKey) return;
    lastTerminalDocRefreshKeyRef.current = refreshKey;
    terminalRefreshAttemptRef.current += 1;
    void refreshDocument().then(() => {
      if (terminalRefreshRetryKeyRef.current === refreshKey) {
        terminalRefreshAttemptRef.current = 0;
      }
    }).catch(() => {
      if (lastTerminalDocRefreshKeyRef.current === refreshKey) {
        lastTerminalDocRefreshKeyRef.current = null;
      }
      if (
        publicationMountedRef.current &&
        terminalRefreshRetryKeyRef.current === refreshKey &&
        terminalRefreshAttemptRef.current < 3 &&
        terminalRefreshRetryTimerRef.current === null
      ) {
        const retryDelayMs = 1500 * (2 ** Math.max(0, terminalRefreshAttemptRef.current - 1));
        terminalRefreshRetryTimerRef.current = window.setTimeout(() => {
          terminalRefreshRetryTimerRef.current = null;
          if (
            publicationMountedRef.current &&
            terminalRefreshRetryKeyRef.current === refreshKey
          ) {
            setTerminalRefreshRetryNonce((value) => value + 1);
          }
        }, retryDelayMs);
      }
    });
  }, [
    buildMeta?.requested_at,
    buildStatus,
    courseId,
    docMarkdownQuery.isFetching,
    isBuildReadyStatus,
    publicationId,
    publicationManifestQuery.data?.updated_at,
    refreshDocument,
    requestedAt,
    terminalRefreshRetryNonce,
  ]);

  const effectiveDocViewMode: DocViewMode =
    !hasLiveDocMarkdown && hasDraftDocMarkdown
      ? "draft"
      : docViewMode === "draft" && hasDraftDocMarkdown
        ? "draft"
        : "live";
  const renderedMarkdown = effectiveDocViewMode === "draft" ? draftMarkdown : liveMarkdown;
  const hasRenderedMarkdown = Boolean(renderedMarkdown.trim());
  const renderedDocUpdatedLabel = useMemo(
    () => formatDocTimestamp(effectiveDocViewMode === "draft" ? draftUpdatedAt : liveUpdatedAt),
    [draftUpdatedAt, effectiveDocViewMode, liveUpdatedAt],
  );

  const renderedDigestModeLabel = formatDigestModeLabel(buildPreview?.digest_mode);
  const renderedChapterHighlights = useMemo(
    () => (buildPreview?.latest_chapter_titles ?? []).slice(0, 4),
    [buildPreview?.latest_chapter_titles],
  );
  const renderedCourseLabel = (courseId ?? "知识文档").replace(/[-_]+/g, " ");
  const renderedDocTitle = useMemo(
    () => extractFirstMarkdownHeading(renderedMarkdown) ?? renderedChapterHighlights[0] ?? renderedCourseLabel,
    [renderedChapterHighlights, renderedMarkdown, renderedCourseLabel],
  );
  const renderedDocSummary = useMemo(
    () => extractFirstMarkdownParagraph(renderedMarkdown) ?? buildPreview?.plan?.trim() ?? "正在整理知识文档...",
    [buildPreview?.plan, renderedMarkdown],
  );

  const sourceFilesQuery = useQuery({
    queryKey: ["knowledge-build-source-files", courseId],
    enabled: Boolean(courseId) && (isBuildActive || isWaitingForRequestedBuild),
    queryFn: () => fetchSourceFiles(courseId as string),
    refetchInterval: ({ state }) => {
      if (!courseId || (!isBuildActive && !isWaitingForRequestedBuild)) return false;
      return state.dataUpdatedAt ? 2500 : 1200;
    },
  });

  const sourceFiles = useMemo(() => {
    const items = sourceFilesQuery.data ?? [];
    if (items.length === 0) return [];
    const selectedFileIds = new Set(docMarkdownQuery.data?.source_file_ids ?? []);
    const filtered =
      selectedFileIds.size > 0
        ? items.filter((file) => selectedFileIds.has(file.id))
        : items.filter(
            (file) =>
              Boolean(file.markdown_ready) ||
              Boolean(file.asset_ready) ||
              Boolean(file.digest_current_step?.trim()) ||
              file.status === "processing" ||
              Boolean(file.error_message?.trim()),
          );
    return [...filtered]
      .sort((a, b) => {
        const aTime = parseIsoTimestamp(a.latest_updated_at) ?? 0;
        const bTime = parseIsoTimestamp(b.latest_updated_at) ?? 0;
        return bTime - aTime;
      })
      .slice(0, 6);
  }, [docMarkdownQuery.data?.source_file_ids, sourceFilesQuery.data]);

  useEffect(() => {
    if (!hasLiveDocMarkdown && hasDraftDocMarkdown) {
      setDocViewMode("draft");
      return;
    }
    if (hasLiveDocMarkdown && !hasDraftDocMarkdown) {
      setDocViewMode("live");
      return;
    }
    if (isBuildReadyStatus && hasLiveDocMarkdown) {
      setDocViewMode("live");
    }
  }, [hasDraftDocMarkdown, hasLiveDocMarkdown, isBuildReadyStatus]);

  const firstPublicationChunkLoading = Boolean(
    publicationManifestQuery.data?.exists &&
    visiblePublicationChunks.length === 0 &&
    !publicationManifestQuery.isError &&
    !publicationError,
  );
  const hasPublicationLoadError = publicationManifestQuery.isError || Boolean(publicationError);
  const showDocLoadingState =
    !docMarkdownQuery.isError &&
    !draftMarkdownQuery.isError &&
    !hasPublicationLoadError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    (
      docMarkdownQuery.isLoading ||
      publicationManifestQuery.isLoading ||
      firstPublicationChunkLoading ||
      (!runtimeQuery.data && runtimeQuery.isLoading)
    );
  const showDocGeneratingState =
    !docMarkdownQuery.isError &&
    !hasPublicationLoadError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    (isBuildActive || isWaitingForRequestedBuild);
  const showDocBuildFailureState =
    !docMarkdownQuery.isError &&
    !hasPublicationLoadError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    isBuildFailure;
  const showDocEmptyState =
    !docMarkdownQuery.isError &&
    !hasPublicationLoadError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    !isBuildActive &&
    !isWaitingForRequestedBuild &&
    !isBuildFailure;
  const showDocUpdatingBanner =
    !docMarkdownQuery.isError &&
    !hasPublicationLoadError &&
    hasRenderedMarkdown &&
    !isGraphSyncActive &&
    (effectiveDocViewMode === "draft" || isWaitingForRequestedBuild);

  const totalChunkCount = publicationManifestQuery.data?.chunks.length ?? 0;
  const loadedChunkCount = visiblePublicationChunks.length;
  const hasNextChunk = effectiveDocViewMode === "live" && loadedChunkCount < totalChunkCount;

  return {
    courseId,
    requestedAt,
    docMarkdownQuery,
    liveMarkdown,
    draftMarkdown,
    buildMeta,
    buildPreview,
    buildMetrics,
    buildStatus,
    graphStatus,
    graphUnhealthy,
    trainingUnlocked,
    liveUpdatedAt,
    draftUpdatedAt,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isGraphSyncActive,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
    docViewMode,
    setDocViewMode,
    effectiveDocViewMode,
    renderedMarkdown,
    hasRenderedMarkdown,
    renderedDocUpdatedLabel,
    renderedDigestModeLabel,
    renderedChapterHighlights,
    renderedCourseLabel,
    renderedDocTitle,
    renderedDocSummary,
    sourceFiles,
    sourceFilesFetching: sourceFilesQuery.isFetching,
    showDocLoadingState,
    showDocGeneratingState,
    showDocBuildFailureState,
    showDocEmptyState,
    showDocUpdatingBanner,
    publicationId,
    publicationHeadings: publicationManifestQuery.data?.headings ?? [],
    loadedChunkCount,
    totalChunkCount,
    hasNextChunk,
    isLoadingNextChunk,
    publicationError: publicationManifestQuery.error ?? publicationError,
    draftError: draftAvailable ? draftMarkdownQuery.error : null,
    loadNextChunk,
    ensureHeadingLoaded,
    ensureAllChunksLoaded,
    refreshDocument,
  };
}
