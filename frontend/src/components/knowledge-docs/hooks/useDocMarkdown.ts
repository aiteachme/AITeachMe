/* ------------------------------------------------------------------ */
/*  useDocMarkdown — Data fetching & derived state for knowledge docs  */
/* ------------------------------------------------------------------ */

import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";

import { apiClient } from "../../../api/client";
import type { FileRecord } from "../../../api/generated/model";
import type {
  ApiResponse,
  DocGenGetResponse,
  FilesListResponse,
  DocViewMode,
  DocGenBuildStatus,
  KnowledgeBuildPreview,
  KnowledgeBuildMetrics,
} from "../types";
import {
  ACTIVE_DOC_BUILD_STATUSES,
  parseIsoTimestamp,
  formatDocTimestamp,
  extractFirstMarkdownHeading,
  extractFirstMarkdownParagraph,
  cleanKnowledgeMarkdownForDisplay,
} from "../utils";

async function fetchSourceFiles(subjectId: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesListResponse>>({
    method: "GET",
    url: `/api/v1/subjects/${subjectId}/files`,
  });
  return response.data?.items ?? [];
}

export interface DocMarkdownState {
  subjectId: string | undefined;
  requestedAt: string | null;

  /* Query */
  docMarkdownQuery: ReturnType<typeof useQuery<DocGenGetResponse>>;

  /* Raw data */
  liveMarkdown: string;
  draftMarkdown: string;
  buildMeta: DocGenBuildStatus | null;
  buildPreview: KnowledgeBuildPreview | null;
  buildMetrics: KnowledgeBuildMetrics | null;
  buildStatus: string | null;
  liveUpdatedAt: string | null;
  draftUpdatedAt: string | null;

  /* Derived booleans */
  hasLiveDocMarkdown: boolean;
  hasDraftDocMarkdown: boolean;
  isBuildActive: boolean;
  isBuildFailure: boolean;
  isRequestedBuildReady: boolean;
  isWaitingForRequestedBuild: boolean;

  /* View mode */
  docViewMode: DocViewMode;
  setDocViewMode: (mode: DocViewMode) => void;
  effectiveDocViewMode: DocViewMode;
  renderedMarkdown: string;
  hasRenderedMarkdown: boolean;

  /* Display metadata */
  renderedDocUpdatedLabel: string | null;
  renderedDigestModeLabel: string;
  renderedChapterHighlights: string[];
  renderedSubjectLabel: string;
  renderedDocTitle: string;
  renderedDocSummary: string;

  /* Source files */
  sourceFiles: FileRecord[];
  sourceFilesFetching: boolean;

  /* Show states */
  showDocGeneratingState: boolean;
  showDocBuildFailureState: boolean;
  showDocEmptyState: boolean;
  showDocUpdatingBanner: boolean;
}

export function useDocMarkdown(): DocMarkdownState {
  const { subjectId } = useParams<{ subjectId: string }>();
  const location = useLocation();
  const requestedAt = useMemo(
    () => new URLSearchParams(location.search).get("requested_at"),
    [location.search],
  );
  const requestedAtMs = useMemo(
    () => parseIsoTimestamp(requestedAt),
    [requestedAt],
  );

  const [docViewMode, setDocViewMode] = useState<DocViewMode>("live");

  const docMarkdownQuery = useQuery<DocGenGetResponse>({
    queryKey: ["docgen-content", subjectId, requestedAt],
    queryFn: async () => {
      if (!subjectId) {
        throw new Error("缺少学科 ID，无法加载知识文档。");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/knowledge/docs`,
      });
      return response.data;
    },
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const data = query.state.data;
      const build = data?.build;
      const buildStatus = build?.status ?? null;
      if (buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus)) return 2500;
      if (buildStatus === "failed" || buildStatus === "cancelled" || buildStatus === "completed") return false;
      if (!buildStatus || buildStatus === "idle") return false;
      const requestedBuildMs = parseIsoTimestamp(build?.requested_at) ?? requestedAtMs;
      if (requestedBuildMs === null) return false;
      const updatedAtMs = parseIsoTimestamp(data?.updated_at);
      const isReady = updatedAtMs !== null && updatedAtMs >= requestedBuildMs;
      return isReady ? false : 2500;
    },
  });

  const liveMarkdown = cleanKnowledgeMarkdownForDisplay(docMarkdownQuery.data?.markdown ?? "");
  const draftMarkdown = cleanKnowledgeMarkdownForDisplay(docMarkdownQuery.data?.draft_markdown ?? "");
  const buildMeta = docMarkdownQuery.data?.build ?? null;
  const buildPreview = docMarkdownQuery.data?.build_preview ?? null;
  const buildMetrics = docMarkdownQuery.data?.build_metrics ?? null;
  const buildStatus = buildMeta?.status ?? null;
  const liveUpdatedAt = docMarkdownQuery.data?.updated_at ?? null;
  const draftUpdatedAt = docMarkdownQuery.data?.draft_updated_at ?? null;
  const hasLiveDocMarkdown = Boolean(docMarkdownQuery.data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftDocMarkdown = Boolean(draftMarkdown.trim().length > 0);

  const buildRequestedAtMs = useMemo(
    () => parseIsoTimestamp(buildMeta?.requested_at),
    [buildMeta?.requested_at],
  );
  const publishedUpdatedAtMs = useMemo(
    () => parseIsoTimestamp(liveUpdatedAt),
    [liveUpdatedAt],
  );
  const targetRequestedAtMs =
    buildStatus && buildStatus !== "idle"
      ? requestedAtMs ?? buildRequestedAtMs
      : null;
  const isBuildActive = Boolean(buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus));
  const isBuildFailure = buildStatus === "failed" || buildStatus === "cancelled";
  const isRequestedBuildReady =
    targetRequestedAtMs !== null
      ? publishedUpdatedAtMs !== null && publishedUpdatedAtMs >= targetRequestedAtMs
      : buildStatus === "completed" && hasLiveDocMarkdown;
  const isWaitingForRequestedBuild =
    targetRequestedAtMs !== null && !isRequestedBuildReady && !isBuildFailure;

  const effectiveDocViewMode: DocViewMode =
    !hasLiveDocMarkdown && hasDraftDocMarkdown
      ? "draft"
      : docViewMode === "draft" && hasDraftDocMarkdown
        ? "draft"
        : "live";
  const renderedMarkdown = effectiveDocViewMode === "draft"
      ? draftMarkdown
      : liveMarkdown;
  const hasRenderedMarkdown = Boolean(renderedMarkdown.trim());
  const renderedDocUpdatedLabel = useMemo(
    () => formatDocTimestamp(effectiveDocViewMode === "draft" ? draftUpdatedAt : liveUpdatedAt),
    [draftUpdatedAt, effectiveDocViewMode, liveUpdatedAt],
  );

  const renderedDigestMode = buildMeta?.digest_mode ?? buildPreview?.digest_mode ?? null;
  const renderedDigestModeLabel =
    renderedDigestMode === "systematic"
      ? "系统课"
      : renderedDigestMode === "sprint"
        ? "速成课"
        : "知识文档";
  const renderedChapterHighlights = (buildPreview?.latest_chapter_titles ?? []).slice(0, 4);
  const renderedSubjectLabel = (subjectId ?? "知识文档").replace(/[-_]+/g, " ");
  const renderedDocTitle =
    extractFirstMarkdownHeading(renderedMarkdown) ??
    renderedChapterHighlights[0] ??
    renderedSubjectLabel;
  const renderedDocSummary =
    extractFirstMarkdownParagraph(renderedMarkdown) ??
    buildPreview?.plan_summary?.trim() ??
    "正在整理知识文档...";

  /* Source files */
  const sourceFilesQuery = useQuery({
    queryKey: ["knowledge-build-source-files", subjectId],
    enabled: Boolean(subjectId) && (isBuildActive || isWaitingForRequestedBuild),
    queryFn: () => fetchSourceFiles(subjectId as string),
    refetchInterval: ({ state }) => {
      if (!subjectId || (!isBuildActive && !isWaitingForRequestedBuild)) return false;
      return state.dataUpdatedAt ? 2500 : 1200;
    },
  });
  const sourceFiles = useMemo(() => {
    const items = sourceFilesQuery.data ?? [];
    if (items.length === 0) return [];
    const selectedFileUids = new Set(docMarkdownQuery.data?.source_file_uids ?? []);
    const filtered =
      selectedFileUids.size > 0
        ? items.filter((file) => selectedFileUids.has(file.uid))
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
  }, [docMarkdownQuery.data?.source_file_uids, sourceFilesQuery.data]);

  /* Auto view mode switching */
  useEffect(() => {
    if (!hasLiveDocMarkdown && hasDraftDocMarkdown) { setDocViewMode("draft"); return; }
    if (hasLiveDocMarkdown && !hasDraftDocMarkdown) { setDocViewMode("live"); return; }
    if (buildStatus === "completed" && hasLiveDocMarkdown) { setDocViewMode("live"); }
  }, [buildStatus, hasDraftDocMarkdown, hasLiveDocMarkdown]);

  /* Show state derivation */
  const showDocGeneratingState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    (isBuildActive || isWaitingForRequestedBuild);
  const showDocBuildFailureState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    isBuildFailure;
  const showDocEmptyState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !isBuildActive &&
    !isWaitingForRequestedBuild &&
    !isBuildFailure;
  const showDocUpdatingBanner =
    !docMarkdownQuery.isError &&
    hasRenderedMarkdown &&
    (isBuildActive || effectiveDocViewMode === "draft" || (!hasLiveDocMarkdown && hasDraftDocMarkdown));

  return {
    subjectId,
    requestedAt,
    docMarkdownQuery,
    liveMarkdown,
    draftMarkdown,
    buildMeta,
    buildPreview,
    buildMetrics,
    buildStatus,
    liveUpdatedAt,
    draftUpdatedAt,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
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
    renderedSubjectLabel,
    renderedDocTitle,
    renderedDocSummary,
    sourceFiles,
    sourceFilesFetching: sourceFilesQuery.isFetching,
    showDocGeneratingState,
    showDocBuildFailureState,
    showDocEmptyState,
    showDocUpdatingBanner,
  };
}
