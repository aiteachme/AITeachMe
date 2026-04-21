/* ------------------------------------------------------------------ */
/*  BuildMaterialPipeline — Material intake panel for the workspace    */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, FileText, Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import { resolveFileProcessingLabel, resolveFileProgressScore } from "./utils";

interface Props {
  files: FileRecord[];
  isFetching: boolean;
  className?: string;
}

export function BuildMaterialPipeline({ files, isFetching, className }: Props) {
  if (files.length === 0 && !isFetching) return null;

  return (
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-stone-200/80 bg-white/92 p-4 shadow-[0_20px_60px_-48px_rgba(28,25,23,0.35)] backdrop-blur-sm md:p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-stone-200/70 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-2xl bg-stone-100 text-stone-500">
            <FileText className="h-4 w-4" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-stone-400">Material Intake</p>
            <h3 className="mt-1 text-sm font-semibold text-stone-900">材料处理</h3>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-stone-400" /> : null}
          <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] text-stone-500">
            {files.length} 份
          </span>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {files.map((file, index) => {
          const label = resolveFileProcessingLabel(file);
          const progress = resolveFileProgressScore(file);
          const hasError = Boolean(file.error_message?.trim());
          const isDone = Boolean(file.markdown_ready);

          return (
            <motion.div
              key={file.uid}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.04, duration: 0.24 }}
              className={cn(
                "rounded-2xl border px-3.5 py-3 transition-colors",
                hasError
                  ? "border-rose-200/80 bg-rose-50/60"
                  : isDone
                    ? "border-emerald-200/80 bg-emerald-50/40"
                    : "border-stone-200/80 bg-stone-50/60",
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl",
                    hasError
                      ? "bg-rose-100 text-rose-600"
                      : isDone
                        ? "bg-emerald-100 text-emerald-600"
                        : "bg-white text-stone-500",
                  )}
                >
                  {hasError ? (
                    <AlertCircle className="h-4 w-4" />
                  ) : isDone ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <FileText className="h-4 w-4" />
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="min-w-0 flex-1 truncate text-sm font-medium text-stone-800">{file.filename}</p>
                    {!hasError && !isDone ? (
                      <span className="shrink-0 text-[11px] font-medium text-stone-400">{progress}%</span>
                    ) : null}
                  </div>

                  <p className={cn("mt-1 text-[12px] leading-5", hasError ? "text-rose-600" : "text-stone-500")}>
                    {hasError ? file.error_message : label}
                  </p>

                  {!hasError && !isDone ? (
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.45, ease: "easeOut" }}
                        className="h-full rounded-full bg-gradient-to-r from-stone-400 via-sky-400 to-sky-500"
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
