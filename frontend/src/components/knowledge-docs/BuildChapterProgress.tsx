/* ------------------------------------------------------------------ */
/*  BuildChapterProgress — Compact chapter status list                 */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { Check, Loader2, Search } from "lucide-react";
import { cn } from "../../lib/utils";
import type { BuildPreviewChapterProgress } from "./types";
import { buildChapterStatusLabel } from "./utils";

interface Props {
  chapters: BuildPreviewChapterProgress[];
  className?: string;
}

export function BuildChapterProgress({ chapters, className }: Props) {
  if (chapters.length === 0) return null;

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-stone-400">
        章节 · {chapters.length}
      </p>

      <div className="space-y-1">
        {chapters.map((chapter, index) => {
          const isActive = chapter.status === "drafting" || chapter.status === "researching";
          const isDone = chapter.status === "completed" || chapter.status === "drafted";
          const statusLabel = buildChapterStatusLabel(chapter.status);

          return (
            <motion.div
              key={chapter.chapter_index}
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.03, duration: 0.25 }}
              className={cn(
                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors",
                isActive ? "bg-sky-50/60" : "hover:bg-stone-50",
              )}
            >
              {/* Status dot/icon */}
              <span className="shrink-0">
                {isDone ? (
                  <Check className="w-3 h-3 text-emerald-500" strokeWidth={3} />
                ) : isActive ? (
                  chapter.status === "drafting" ? (
                    <Loader2 className="w-3 h-3 text-sky-500 animate-spin" />
                  ) : (
                    <Search className="w-3 h-3 text-amber-500" />
                  )
                ) : (
                  <span className="w-2 h-2 rounded-full bg-stone-200 block" />
                )}
              </span>

              {/* Title */}
              <span className={cn(
                "flex-1 min-w-0 truncate",
                isActive ? "text-sky-700 font-medium" : isDone ? "text-stone-600" : "text-stone-400",
              )}>
                <span className="text-stone-300 mr-1">{String(chapter.chapter_index + 1).padStart(2, "0")}</span>
                {chapter.title}
              </span>

              {/* Status label */}
              <span className={cn(
                "text-[10px] shrink-0",
                isActive ? "text-sky-500" : isDone ? "text-emerald-500" : "text-stone-300",
              )}>
                {statusLabel}
              </span>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
