/* ------------------------------------------------------------------ */
/*  BuildMaterialPipeline — Source file processing status cards        */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { FileText, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
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
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center gap-2">
        <FileText className="w-4 h-4 text-stone-400" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
          材料处理
        </h3>
        <span className="text-[11px] text-stone-400">{files.length} 份</span>
        {isFetching && <Loader2 className="w-3 h-3 animate-spin text-stone-300" />}
      </div>

      <div className="space-y-2">
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
              transition={{ delay: index * 0.05, duration: 0.3 }}
              className={cn(
                "rounded-xl border px-3.5 py-2.5 transition-all",
                hasError
                  ? "border-rose-200/60 bg-rose-50/30"
                  : isDone
                    ? "border-emerald-200/60 bg-emerald-50/20"
                    : "border-stone-200/70 bg-white/60",
              )}
            >
              <div className="flex items-center gap-2.5">
                {/* Icon */}
                <div className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center shrink-0",
                  hasError
                    ? "bg-rose-100 text-rose-500"
                    : isDone
                      ? "bg-emerald-100 text-emerald-600"
                      : "bg-stone-100 text-stone-400",
                )}>
                  {hasError ? (
                    <AlertCircle className="w-4 h-4" />
                  ) : isDone ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : (
                    <FileText className="w-4 h-4" />
                  )}
                </div>

                {/* Info */}
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-stone-700 truncate font-medium">
                    {file.filename}
                  </p>
                  <p className={cn(
                    "text-[11px] mt-0.5",
                    hasError ? "text-rose-500" : "text-stone-400",
                  )}>
                    {hasError ? file.error_message : label}
                  </p>
                </div>

                {/* Progress */}
                {!hasError && !isDone && (
                  <span className="text-[11px] font-medium text-stone-400 shrink-0">
                    {progress}%
                  </span>
                )}
              </div>

              {/* Progress bar */}
              {!hasError && !isDone && (
                <div className="mt-2 h-0.5 rounded-full bg-stone-100 overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.5, ease: "easeOut" }}
                    className="h-full rounded-full bg-sky-400"
                  />
                </div>
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
