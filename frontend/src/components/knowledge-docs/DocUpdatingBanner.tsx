import { AnimatePresence, motion } from "framer-motion";
import { Eye, FileEdit, Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { DocViewMode, KnowledgeBuildPreview } from "./types";

interface Props {
  progress: number;
  statusText: string;
  isFetching: boolean;
  viewMode: DocViewMode;
  hasLiveVersion: boolean;
  hasDraftVersion: boolean;
  liveUpdatedAt: string | null;
  draftUpdatedAt: string | null;
  buildPreview: KnowledgeBuildPreview | null;
  onViewModeChange: (mode: DocViewMode) => void;
  className?: string;
}

export function DocUpdatingBanner({
  progress,
  statusText,
  isFetching,
  viewMode,
  hasLiveVersion,
  hasDraftVersion,
  buildPreview,
  onViewModeChange,
  className,
}: Props) {
  const showToggle = hasLiveVersion && hasDraftVersion;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.25 }}
        className={cn(
          "rounded-lg border border-indigo-200 bg-indigo-50 px-3.5 py-2.5 dark:border-indigo-500/20 dark:bg-indigo-500/10",
          className,
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {isFetching ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-600 dark:text-indigo-300" />
              ) : (
                <div className="build-live-dot h-1.5 w-1.5 text-indigo-600 dark:text-indigo-300" />
              )}
              <p className="truncate text-[13px] font-medium text-[#1F2329] dark:text-slate-100">
                {statusText}
              </p>
              <span className="shrink-0 text-[12px] font-medium text-indigo-600 dark:text-indigo-300">
                {Math.round(progress)}%
              </span>
            </div>

            {buildPreview?.current_stage_description ? (
              <div className="pl-5 pt-1">
                <p className="flex items-center gap-1.5 rounded-sm border border-white/60 bg-white/50 px-1.5 py-0.5 text-[11px] text-[#646A73] dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400">
                  {buildPreview.current_stage_description}
                </p>
              </div>
            ) : null}
          </div>

          {showToggle ? (
            <div className="flex items-center gap-0.5 rounded-md border border-[#DEE0E3] bg-white p-0.5 dark:border-slate-700 dark:bg-slate-950">
              <button
                type="button"
                onClick={() => onViewModeChange("live")}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-all",
                  viewMode === "live"
                    ? "bg-indigo-600 text-white"
                    : "text-[#646A73] hover:bg-[#F5F6F7] dark:text-slate-300 dark:hover:bg-slate-800",
                )}
              >
                <Eye className="h-3 w-3" />
                正式版
              </button>
              <button
                type="button"
                onClick={() => onViewModeChange("draft")}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-all",
                  viewMode === "draft"
                    ? "bg-indigo-600 text-white"
                    : "text-[#646A73] hover:bg-[#F5F6F7] dark:text-slate-300 dark:hover:bg-slate-800",
                )}
              >
                <FileEdit className="h-3 w-3" />
                草稿
              </button>
            </div>
          ) : null}
        </div>

        <div className="mt-2 h-[2px] overflow-hidden rounded-full bg-blue-200/70 dark:bg-slate-800">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="h-full rounded-full bg-blue-600 progress-bar-active progress-bar-breathing dark:bg-blue-400"
          />
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
