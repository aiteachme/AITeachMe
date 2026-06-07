import { useEffect, useId, type ReactNode } from "react";
import { X, type LucideIcon } from "lucide-react";

import { cn } from "../../lib/utils";

type CourseOperationTone = "slate" | "blue" | "emerald" | "danger";

interface CourseOperationModalProps {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tone?: CourseOperationTone;
  sidebar?: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  className?: string;
}

const toneStyles: Record<
  CourseOperationTone,
  {
    icon: string;
    eyebrow: string;
    rail: string;
    railLine: string;
  }
> = {
  slate: {
    icon: "bg-slate-950 text-white dark:bg-slate-100 dark:text-slate-950",
    eyebrow: "text-slate-500 dark:text-slate-400",
    rail: "border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-900/35",
    railLine: "bg-slate-900 dark:bg-slate-200",
  },
  blue: {
    icon: "bg-slate-950 text-white dark:bg-slate-100 dark:text-slate-950",
    eyebrow: "text-sky-700 dark:text-sky-300",
    rail: "border-sky-100 bg-sky-50/55 dark:border-sky-900/35 dark:bg-sky-950/10",
    railLine: "bg-sky-600 dark:bg-sky-300",
  },
  emerald: {
    icon: "bg-slate-950 text-white dark:bg-slate-100 dark:text-slate-950",
    eyebrow: "text-emerald-700 dark:text-emerald-300",
    rail: "border-emerald-100 bg-emerald-50/50 dark:border-emerald-900/35 dark:bg-emerald-950/10",
    railLine: "bg-emerald-600 dark:bg-emerald-300",
  },
  danger: {
    icon: "bg-red-600 text-white dark:bg-red-500 dark:text-white",
    eyebrow: "text-red-700 dark:text-red-300",
    rail: "border-red-100 bg-red-50/55 dark:border-red-900/40 dark:bg-red-950/12",
    railLine: "bg-red-600 dark:bg-red-400",
  },
};

export function CourseOperationModal({
  eyebrow,
  title,
  description,
  icon: Icon,
  tone = "slate",
  sidebar,
  children,
  footer,
  onClose,
  className,
}: CourseOperationModalProps) {
  const titleId = useId();
  const styles = toneStyles[tone];

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[120]">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-3 sm:p-6">
        <section
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className={cn(
            "pointer-events-auto relative grid max-h-[calc(100dvh-1.5rem)] w-full max-w-4xl overflow-hidden rounded-[22px] border border-slate-200 bg-white text-slate-950 shadow-[0_28px_90px_rgba(15,23,42,0.18)] dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100 dark:shadow-[0_30px_90px_rgba(0,0,0,0.58)] md:grid-cols-[290px_minmax(0,1fr)]",
            className,
          )}
        >
          <button
            type="button"
            onClick={onClose}
            className="absolute right-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus-visible:ring-slate-700"
            aria-label="关闭面板"
          >
            <X className="h-4 w-4" />
          </button>

          <aside className={cn("border-b px-5 py-5 md:border-b-0 md:border-r md:px-6 md:py-6", styles.rail)}>
            <div className={cn("mb-5 h-1 w-10 rounded-full", styles.railLine)} />
            <div className={cn("flex h-11 w-11 items-center justify-center rounded-2xl shadow-sm", styles.icon)}>
              <Icon className="h-5 w-5" />
            </div>
            <div className={cn("mt-6 text-xs font-semibold uppercase tracking-[0.16em]", styles.eyebrow)}>
              {eyebrow}
            </div>
            <h2 id={titleId} className="mt-2 text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
              {title}
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p>
            {sidebar ? <div className="mt-7">{sidebar}</div> : null}
          </aside>

          <div className="flex min-h-0 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6 sm:py-6">{children}</div>
            <div className="shrink-0 border-t border-slate-100 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-950 sm:px-6">
              {footer}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

