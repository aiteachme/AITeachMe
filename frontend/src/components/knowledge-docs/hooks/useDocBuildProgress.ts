/* ------------------------------------------------------------------ */
/*  useDocBuildProgress — backend-persisted progress state             */
/* ------------------------------------------------------------------ */

import type { DocGenBuildStatus } from "../types";
import {
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

  if (buildStatus === "completed" || isRequestedBuildReady) {
    return { buildProgress: 100, buildStatusText };
  }

  const fallbackProgress = resolveDocBuildProgressFloor(buildMeta, hasDraftDocMarkdown);
  const persistedProgress = clampProgress(Number(buildMeta?.progress_pct ?? fallbackProgress));

  if (isBuildFailure || (!isBuildActive && !isWaitingForRequestedBuild)) {
    return { buildProgress: persistedProgress, buildStatusText };
  }

  return {
    buildProgress: Math.max(persistedProgress, fallbackProgress),
    buildStatusText,
  };
}
