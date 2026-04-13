/* ------------------------------------------------------------------ */
/*  DocUpdatingBanner — Feishu-style updating banner                   */
/* ------------------------------------------------------------------ */

import { motion, AnimatePresence } from "framer-motion";
import { Loader2, Eye, FileEdit } from "lucide-react";
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
          "rounded-lg border border-[#D4E5FF] bg-[#F0F4FF] px-3.5 py-2.5",
          className,
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          {/* Status */}
          <div className="flex flex-col gap-1 min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {isFetching ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#3370FF] shrink-0" />
              ) : (
                <div className="w-1.5 h-1.5 rounded-full bg-[#3370FF] animate-pulse shrink-0" />
              )}
              <p className="text-[13px] text-[#1F2329] truncate font-medium">{statusText}</p>
              <span className="text-[12px] font-medium text-[#3370FF] shrink-0">{Math.round(progress)}%</span>
            </div>
            
            {/* Deep Research / Stage Desc */}
            {buildPreview?.current_stage_description && (
              <div className="pl-5 flex items-center">
                <p className="text-[11px] text-[#646A73] truncate flex items-center gap-1.5 bg-white/50 rounded-sm px-1.5 py-0.5 border border-white/60">
                   {buildPreview.current_stage_description}
                </p>
              </div>
            )}
          </div>

          {/* View toggle */}
          {showToggle && (
            <div className="flex items-center gap-0.5 rounded-md border border-[#DEE0E3] bg-white p-0.5">
              <button
                onClick={() => onViewModeChange("live")}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-all",
                  viewMode === "live"
                    ? "bg-[#3370FF] text-white"
                    : "text-[#646A73] hover:bg-[#F5F6F7]",
                )}
              >
                <Eye className="w-3 h-3" />
                正式版
              </button>
              <button
                onClick={() => onViewModeChange("draft")}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-all",
                  viewMode === "draft"
                    ? "bg-[#3370FF] text-white"
                    : "text-[#646A73] hover:bg-[#F5F6F7]",
                )}
              >
                <FileEdit className="w-3 h-3" />
                草稿
              </button>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div className="mt-2 h-[2px] rounded-full bg-[#D4E5FF] overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="h-full rounded-full bg-[#3370FF]"
          />
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
