import { motion } from "framer-motion";
import { CheckCircle2, Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { BuildPreviewChapterProgress } from "./types";
import { buildChapterStatusLabel } from "./utils";

interface Props {
  chapters: BuildPreviewChapterProgress[];
  className?: string;
}

const ACTIVE_STATUSES = new Set(["generating", "enhancing", "reviewing", "drafting", "researching"]);
const STABLE_STATUSES = new Set(["generated", "enhanced", "reviewed", "completed", "drafted", "researched"]);

function isActiveChapter(status: string | undefined): boolean {
  return ACTIVE_STATUSES.has((status ?? "").trim());
}

function isStableChapter(status: string | undefined): boolean {
  return STABLE_STATUSES.has((status ?? "").trim());
}

function renderMetricChips(chapter: BuildPreviewChapterProgress): string[] {
  const chips: string[] = [];

  if ((chapter.word_count ?? 0) > 0) {
    chips.push(`${chapter.word_count} 字`);
  }
  if ((chapter.source_count ?? 0) > 0) {
    chips.push(`${chapter.source_count} 条来源`);
  }
  if ((chapter.query_count ?? 0) > 0) {
    chips.push(`${chapter.query_count} 次检索`);
  }
  if ((chapter.local_hits ?? 0) > 0 || (chapter.web_hits ?? 0) > 0) {
    chips.push(`本地 ${chapter.local_hits ?? 0} / Web ${chapter.web_hits ?? 0}`);
  }
  if (chapter.fallback_used) {
    chips.push("使用 fallback");
  }

  return chips;
}

export function BuildChapterProgress({ chapters, className }: Props) {
  if (chapters.length === 0) return null;

  const stableCount = chapters.filter((chapter) => isStableChapter(chapter.status)).length;

  return (
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-stone-200/80 bg-white/92 p-4 shadow-[0_20px_60px_-48px_rgba(28,25,23,0.35)] backdrop-blur-sm md:p-5 dark:border-slate-800 dark:bg-slate-950/80 dark:shadow-[0_24px_60px_-42px_rgba(0,0,0,0.72)]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-stone-200/70 pb-3 dark:border-slate-800">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400 dark:text-slate-500">
            Chapter Board
          </p>
          <h3 className="mt-1 text-sm font-semibold text-stone-900 dark:text-slate-100">章节进度</h3>
        </div>
        <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
          {stableCount}/{chapters.length} 已稳定
        </span>
      </div>

      <div className="mt-4 space-y-2">
        {chapters.map((chapter, index) => {
          const active = isActiveChapter(chapter.status);
          const stable = isStableChapter(chapter.status);
          const metricChips = renderMetricChips(chapter);

          return (
            <motion.div
              key={chapter.chapter_index}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.035, duration: 0.24 }}
              className={cn(
                "rounded-2xl border px-3.5 py-3 transition-colors",
                active
                  ? "border-sky-200 bg-sky-50/70 dark:border-sky-500/30 dark:bg-sky-500/10"
                  : stable
                    ? "border-emerald-200/80 bg-emerald-50/40 dark:border-emerald-500/30 dark:bg-emerald-500/10"
                    : "border-stone-200/80 bg-stone-50/60 dark:border-slate-800 dark:bg-slate-900/70",
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border text-[11px] font-semibold",
                    active
                      ? "border-sky-200 bg-white text-sky-700 dark:border-sky-500/30 dark:bg-slate-950 dark:text-sky-300"
                      : stable
                        ? "border-emerald-200 bg-white text-emerald-700 dark:border-emerald-500/30 dark:bg-slate-950 dark:text-emerald-300"
                        : "border-stone-200 bg-white text-stone-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400",
                  )}
                >
                  {String(chapter.chapter_index).padStart(2, "0")}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 flex-1 text-sm font-medium text-stone-800 dark:text-slate-100">
                      {chapter.title}
                    </p>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                        active
                          ? "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
                          : stable
                            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                            : "bg-white text-stone-500 dark:bg-slate-950 dark:text-slate-400",
                      )}
                    >
                      {stable ? (
                        <CheckCircle2 className="h-3 w-3" />
                      ) : active ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <span className="h-1.5 w-1.5 rounded-full bg-current" />
                      )}
                      {buildChapterStatusLabel(chapter.status)}
                    </span>
                  </div>

                  {metricChips.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {metricChips.map((chip) => (
                        <span
                          key={`${chapter.chapter_index}-${chip}`}
                          className="rounded-full border border-stone-200/80 bg-white/90 px-2 py-0.5 text-[11px] text-stone-500 dark:border-slate-700 dark:bg-slate-950/90 dark:text-slate-400"
                        >
                          {chip}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-[12px] leading-5 text-stone-500 dark:text-slate-400">
                      章节已排队，等待本轮 research / write / review 状态回写。
                    </p>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
