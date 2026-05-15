import type { LucideIcon } from "lucide-react";

import { cn } from "../../lib/utils";

interface CoursePagePillTitleProps {
  icon: LucideIcon;
  label: string;
  className?: string;
}

export function CoursePagePillTitle({ icon: Icon, label, className }: CoursePagePillTitleProps) {
  return (
    <div className={cn("flex items-center justify-center pb-2 pt-6", className)}>
      <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/80 bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-zinc-500 shadow-sm dark:border-slate-800/80 dark:bg-slate-900 dark:text-slate-400">
        <Icon className="h-3 w-3 shrink-0" />
        <span>{label}</span>
      </div>
    </div>
  );
}
