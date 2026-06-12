import type { LucideIcon } from "lucide-react";
import { ChevronLeft } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "../../lib/utils";

interface CoursePagePillTitleProps {
  icon: LucideIcon;
  label: string;
  href?: string;
  className?: string;
}

export function CoursePagePillTitle({ icon: Icon, label, href, className }: CoursePagePillTitleProps) {
  const inner = (
    <div className={cn(
      "group inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-slate-500 shadow-[0_2px_10px_rgb(0,0,0,0.02)] transition-all dark:border-slate-800/80 dark:bg-slate-900 dark:text-slate-400",
      href && "hover:border-indigo-200 hover:text-indigo-600 hover:shadow-[0_4px_12px_rgba(79,70,229,0.1)] hover:-translate-y-0.5 cursor-pointer dark:hover:border-indigo-500/30 dark:hover:text-indigo-400"
    )}>
      {href && <ChevronLeft className="h-3.5 w-3.5 -ml-1 shrink-0 text-slate-400 transition-all group-hover:-translate-x-0.5 group-hover:text-indigo-500" />}
      <Icon className="h-3 w-3 shrink-0" />
      <span>{label}</span>
    </div>
  );

  return (
    <div className={cn("flex items-center justify-center pb-2 pt-6 z-10 relative", className)}>
      {href ? <Link to={href} className="focus:outline-none">{inner}</Link> : inner}
    </div>
  );
}
