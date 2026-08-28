/* ------------------------------------------------------------------ */
/*  BuildMaterialPipeline — Material intake panel for the workspace    */
/* ------------------------------------------------------------------ */

import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, FileText, Loader2 } from "lucide-react";

import { cn } from "../../lib/utils";
import type { FileRecord } from "../../api/generated/model";
import { CircularFileParseProgress } from "../files/FileParseProgress";

interface Props {
  files: FileRecord[];
  isFetching: boolean;
  className?: string;
}

export function BuildMaterialPipeline({ files, isFetching, className }: Props) {
  if (files.length === 0 && !isFetching) return null;

  return (
    <div className={cn("space-y-3", className)}>
      {isFetching ? <div className="flex items-center gap-2 text-sm text-zinc-400 dark:text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> 处理中...</div> : null}
        {files.map((file, index) => {
          const hasError = Boolean(file.error_message?.trim());
          const isDone = Boolean(file.markdown_ready);

          return (
            <motion.div
              key={file.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.04, duration: 0.24 }}
              className={cn(
                "rounded-xl border px-3.5 py-3 transition-colors",
                hasError
                  ? "border-rose-200 bg-rose-50/50 dark:border-rose-500/30 dark:bg-rose-500/10"
                  : isDone
                    ? "border-zinc-200 bg-zinc-50/50 hover:bg-zinc-100/50 dark:border-slate-800 dark:bg-slate-900/70 dark:hover:bg-slate-800/80"
                    : "border-zinc-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/80",
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                    hasError
                      ? "bg-rose-50 text-rose-500 border-rose-100 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
                      : isDone
                        ? "bg-zinc-100 text-zinc-500 border-zinc-200/80 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                        : "bg-white text-zinc-900 border-zinc-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
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
                    <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-zinc-800 dark:text-slate-100">{file.filename}</p>
                    <CircularFileParseProgress file={file} size={22} />
                  </div>

                  {hasError ? (
                    <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-rose-500 dark:text-rose-300">{file.error_message}</p>
                  ) : null}
                </div>
              </div>
            </motion.div>
          );
        })}
    </div>
  );
}
