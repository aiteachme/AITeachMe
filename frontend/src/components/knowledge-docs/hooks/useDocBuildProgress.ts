/* ------------------------------------------------------------------ */
/*  useDocBuildProgress — Animated progress bar logic                  */
/* ------------------------------------------------------------------ */

import { useState, useEffect } from "react";
import type { DocGenBuildStatus } from "../types";
import {
  resolveDocBuildStatusText,
  resolveDocBuildProgressFloor,
  resolveDocBuildProgressCap,
} from "../utils";

export interface DocBuildProgressState {
  buildProgress: number;
  buildStatusText: string;
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

  const [buildProgress, setBuildProgress] = useState(0);
  const [buildStatusText, setBuildStatusText] = useState("正在整理知识文档...");

  useEffect(() => {
    const nextStatusText = resolveDocBuildStatusText(buildMeta, hasLiveDocMarkdown, hasDraftDocMarkdown);
    const progressFloor = resolveDocBuildProgressFloor(buildMeta, hasDraftDocMarkdown);
    setBuildStatusText(nextStatusText);

    if (buildStatus === "completed" || isRequestedBuildReady) {
      setBuildProgress(100);
      return;
    }

    if (isBuildFailure) {
      setBuildProgress(progressFloor);
      return;
    }

    if (!isBuildActive && !isWaitingForRequestedBuild) {
      setBuildProgress(progressFloor);
      return;
    }

    const progressCap = resolveDocBuildProgressCap(buildMeta, hasDraftDocMarkdown);
    setBuildProgress((prev) => {
      const base = prev > 0 ? prev : progressFloor;
      return Math.max(base, progressFloor);
    });

    const timer = window.setInterval(() => {
      setBuildProgress((prev) => {
        if (prev >= progressCap) return progressCap;
        if (prev < 20) return Math.min(progressCap, prev + 6);
        if (prev < 50) return Math.min(progressCap, prev + 4);
        if (prev < 75) return Math.min(progressCap, prev + 2.5);
        return Math.min(progressCap, prev + 1.2);
      });
    }, 600);

    return () => window.clearInterval(timer);
  }, [
    buildMeta,
    buildStatus,
    hasDraftDocMarkdown,
    hasLiveDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
  ]);

  return { buildProgress, buildStatusText };
}
