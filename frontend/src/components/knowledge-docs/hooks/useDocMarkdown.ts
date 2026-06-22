/* ------------------------------------------------------------------ */
/*  useDocMarkdown - Data fetching & derived state for knowledge docs  */
/* ------------------------------------------------------------------ */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";

import { apiClient } from "../../../api/client";
import type { FileRecord } from "../../../api/generated/model";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  buildRuntimeFailureBackoffMs,
  fetchKnowledgeBuildRuntime,
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

async function fetchSourceFiles(courseId: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesListResponse>>({
    method: "GET",
    url: `/api/v1/courses/${courseId}/files`,
  });
  return response.data?.items ?? [];
}

function hasLiveMarkdown(data: DocGenGetResponse | undefined): boolean {
  const liveMarkdown = cleanKnowledgeMarkdownForDisplay(data?.markdown ?? "");
  return Boolean(data?.exists && liveMarkdown.trim().length > 0);
}

function hasRequestedLiveMarkdown(
  data: DocGenGetResponse | undefined,
  {
    status,
    targetRequestedAtMs,
  }: {
    status: string;
    targetRequestedAtMs: number | null;
  },
): boolean {
  if (!hasLiveMarkdown(data)) return false;
  if (targetRequestedAtMs === null) return true;

  const updatedAtMs = parseIsoTimestamp(data?.updated_at ?? null);
  if (updatedAtMs === null) {
    return TERMINAL_DOC_BUILD_READY_STATUSES.has(status);
  }
  return updatedAtMs >= targetRequestedAtMs;
}

const GRAPH_SYNC_BUILD_STAGES = new Set([
  "graph_pending",
  "manual_graph_requested",
  "queued_after_docgen",
  "graph_docs_sync",
  "graph_ready",
]);

const GRAPH_DOC_READY_STATUSES = new Set(["completed", "partial_failed", "failed", "cancelled", "skipped"]);

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
}

export function useDocMarkdown(): DocMarkdownState {
  const { courseId } = useParams<{ courseId: string }>();
  const location = useLocation();
  const requestedAt = useMemo(
    () => new URLSearchParams(location.search).get("requested_at"),
    [location.search],
  );
  const requestedAtMs = useMemo(() => parseIsoTimestamp(requestedAt), [requestedAt]);

  const [docViewMode, setDocViewMode] = useState<DocViewMode>("live");
  const lastTerminalDocRefreshKeyRef = useRef<string | null>(null);

  const docMarkdownQuery = useQuery<DocGenGetResponse>({
    queryKey: ["docgen-content", courseId, requestedAt],
    queryFn: async () => {
      if (!courseId) {
        throw new Error("缺少课程 ID，无法加载知识文档。");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
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
      const hasRequestedLiveDoc = hasRequestedLiveMarkdown(data, { status, targetRequestedAtMs });
      if (hasRequestedLiveDoc) return false;

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) return 2500;
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) {
        return 1200;
      }
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
      const hasRequestedLiveDoc = hasRequestedLiveMarkdown(docMarkdownQuery.data, {
        status,
        targetRequestedAtMs,
      });
      if (hasRequestedLiveDoc) return false;

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) return 2500;
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) {
        return 1200;
      }
      if (status === "failed" || status === "cancelled") return false;
      if (!status || status === "idle") return false;
      return 2500;
    },
  });

  const rawLiveMarkdown = docMarkdownQuery.data?.markdown ?? "";
  const rawDraftMarkdown = docMarkdownQuery.data?.draft_markdown ?? "";
  const liveMarkdown = useMemo(
    () => cleanKnowledgeMarkdownForDisplay(rawLiveMarkdown),
    [rawLiveMarkdown],
  );
  const draftMarkdown = useMemo(
    () => cleanKnowledgeMarkdownForDisplay(rawDraftMarkdown),
    [rawDraftMarkdown],
  );
  const buildMeta = runtimeQuery.data?.aggregate ?? runtimeQuery.data?.docgen ?? docMarkdownQuery.data?.build ?? null;
  const buildPreview = runtimeQuery.data?.docgen_preview ?? docMarkdownQuery.data?.build_preview ?? null;
  const buildMetrics = runtimeQuery.data?.docgen_metrics ?? docMarkdownQuery.data?.build_metrics ?? null;
  const buildStatus = buildMeta?.status ?? null;
  const buildStage = (buildMeta?.stage ?? "").trim();
  const graphStatus = (runtimeQuery.data?.graph_status ?? runtimeQuery.data?.graph?.status ?? null)?.trim() || null;
  const graphUnhealthy = Boolean(runtimeQuery.data?.graph_unhealthy);
  const trainingUnlocked = Boolean(runtimeQuery.data?.training_unlocked);
  const liveUpdatedAt = docMarkdownQuery.data?.updated_at ?? null;
  const draftUpdatedAt = docMarkdownQuery.data?.draft_updated_at ?? null;
  const hasLiveDocMarkdown = Boolean(docMarkdownQuery.data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftDocMarkdown = Boolean(draftMarkdown.trim().length > 0);

  const buildRequestedAtMs = useMemo(
    () => parseIsoTimestamp(buildMeta?.requested_at),
    [buildMeta?.requested_at],
  );
  const targetRequestedAtMs =
    buildStatus && buildStatus !== "idle"
      ? requestedAtMs ?? buildRequestedAtMs
      : null;
  const fallbackRequestedBuildReady = hasRequestedLiveMarkdown(docMarkdownQuery.data, {
    status: buildStatus ?? "",
    targetRequestedAtMs,
  });
  const isRuntimeDocumentReady =
    runtimeQuery.data?.docs_ready === true &&
    (graphStatus === null || GRAPH_DOC_READY_STATUSES.has(graphStatus));
  const isRequestedBuildReady =
    typeof runtimeQuery.data?.docs_ready === "boolean"
      ? isRuntimeDocumentReady
      : fallbackRequestedBuildReady;
  const isBuildActive = Boolean(!isRequestedBuildReady && buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus));
  const isGraphSyncActive = Boolean(isBuildActive && GRAPH_SYNC_BUILD_STAGES.has(buildStage));
  const isBuildFailure = buildStatus === "failed" || buildStatus === "cancelled";
  const isBuildReadyStatus = Boolean(buildStatus && TERMINAL_DOC_BUILD_READY_STATUSES.has(buildStatus));
  const isWaitingForRequestedBuild =
    !isRequestedBuildReady &&
    !isBuildFailure &&
    Boolean(
      hasDraftDocMarkdown ||
      isBuildActive ||
      isBuildReadyStatus ||
      targetRequestedAtMs !== null
    );

  useEffect(() => {
    if (!courseId || isRequestedBuildReady || docMarkdownQuery.isFetching) return;
    const shouldRefreshDoc = isBuildReadyStatus;
    if (!shouldRefreshDoc) return;
    const refreshKey = [
      courseId,
      requestedAt ?? "",
      buildStatus ?? "",
      buildMeta?.requested_at ?? "",
    ].join(":");
    if (lastTerminalDocRefreshKeyRef.current === refreshKey) return;
    lastTerminalDocRefreshKeyRef.current = refreshKey;
    void docMarkdownQuery.refetch();
  }, [
    buildMeta?.requested_at,
    buildStatus,
    docMarkdownQuery.isFetching,
    docMarkdownQuery.refetch,
    isBuildReadyStatus,
    isRequestedBuildReady,
    requestedAt,
    courseId,
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

  const showDocLoadingState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    (docMarkdownQuery.isLoading || (!runtimeQuery.data && runtimeQuery.isLoading));
  const showDocGeneratingState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    (isBuildActive || isWaitingForRequestedBuild);
  const showDocBuildFailureState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    isBuildFailure;
  const showDocEmptyState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !showDocLoadingState &&
    !isBuildActive &&
    !isWaitingForRequestedBuild &&
    !isBuildFailure;
  const showDocUpdatingBanner =
    !docMarkdownQuery.isError &&
    hasRenderedMarkdown &&
    !isGraphSyncActive &&
    (effectiveDocViewMode === "draft" || isWaitingForRequestedBuild);

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
  };
}
