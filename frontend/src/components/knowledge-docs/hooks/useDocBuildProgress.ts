/* ------------------------------------------------------------------ */
/*  useDocBuildProgress — backend-persisted progress state             */
/* ------------------------------------------------------------------ */

import type { DocGenBuildStatus } from "../types";
import {
  TERMINAL_DOC_BUILD_READY_STATUSES,
  resolveDocBuildStatusText,
  resolveDocBuildProgressFloor,
} from "../utils";

export interface DocBuildProgressState {
  buildProgress: number;
  buildStatusText: string;
}

function clampProgress(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

export function useDocBuildProgress(opts: {
  buildMeta: DocGenBuildStatus | null;
  buildStatus: string | null;
  hasLiveDocMarkdown: boolean;
  hasDraftDocMarkdown: boolean;
  isBuildActive: boolean;
  isBuildFailure: boolean;
  isRequestedBuildReady: boolean;
  isWaitingForRequestedBuild: boolean;
}): DocBuildProgressState {
  const {
    buildMeta,
    buildStatus,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
  } = opts;

  const buildStatusText = resolveDocBuildStatusText(buildMeta, hasLiveDocMarkdown, hasDraftDocMarkdown);
  const fallbackProgress = resolveDocBuildProgressFloor(buildMeta, hasDraftDocMarkdown, hasLiveDocMarkdown);
  const rawPersistedProgress = clampProgress(Number(buildMeta?.progress_pct ?? fallbackProgress));
  const isBuildReadyStatus = Boolean(buildStatus && TERMINAL_DOC_BUILD_READY_STATUSES.has(buildStatus));
  const persistedProgress =
    isBuildReadyStatus && !hasLiveDocMarkdown
      ? Math.min(rawPersistedProgress, fallbackProgress)
      : rawPersistedProgress;
  const progressCeiling = !isRequestedBuildReady && (isBuildActive || isWaitingForRequestedBuild)
    ? isBuildReadyStatus
      ? 97
      : 99
    : 100;
  const visiblePersistedProgress = Math.min(persistedProgress, progressCeiling);
  const visibleFallbackProgress = Math.min(fallbackProgress, progressCeiling);

  if (isRequestedBuildReady || (isBuildReadyStatus && hasLiveDocMarkdown)) {
    return { buildProgress: 100, buildStatusText };
  }

  if (isBuildFailure || (!isBuildActive && !isWaitingForRequestedBuild)) {
    return { buildProgress: visiblePersistedProgress, buildStatusText };
  }

  return {
    buildProgress: Math.max(visiblePersistedProgress, visibleFallbackProgress),
    buildStatusText,
  };
}
