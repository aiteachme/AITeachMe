import { CheckCircle2, CircleAlert } from "lucide-react";

import { cn } from "../../lib/utils";

interface ProgressFile {
  error_message?: string | null;
  markdown_ready?: boolean;
  parse_progress?: { percent?: number } | null;
  status?: string;
}

export function fileParseProgressPercent(file: ProgressFile): number {
  if (file.error_message?.trim() || file.status === "failed") return 100;
  if (file.markdown_ready) return 100;
  const value = Number(file.parse_progress?.percent);
  return Number.isFinite(value) ? Math.max(0, Math.min(99, Math.round(value))) : 2;
}

export function CircularFileParseProgress({
  file,
  size = 20,
  className,
}: {
  file: ProgressFile;
  size?: number;
  className?: string;
}) {
  const failed = Boolean(file.error_message?.trim()) || file.status === "failed";
  if (failed) {
    return <CircleAlert className={cn("shrink-0 text-rose-500", className)} style={{ width: size, height: size }} />;
  }
  if (file.markdown_ready) {
    return <CheckCircle2 className={cn("shrink-0 text-emerald-500", className)} style={{ width: size, height: size }} />;
  }

  const progress = fileParseProgressPercent(file);
  return (
    <span
      role="progressbar"
      aria-label={`文件解析进度 ${progress}%`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress}
      title={`解析进度 ${progress}%`}
      className={cn("relative inline-flex shrink-0 items-center justify-center rounded-full", className)}
      style={{
        width: size,
        height: size,
        background: `conic-gradient(rgb(79 70 229) ${progress * 3.6}deg, rgb(226 232 240) 0deg)`,
      }}
    >
      <span
        className="rounded-full bg-white dark:bg-slate-900"
        style={{ width: Math.max(size - 5, 4), height: Math.max(size - 5, 4) }}
      />
    </span>
  );
}
