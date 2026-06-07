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
    accent: string;
    summary: string;
  }
> = {
  slate: {
    icon: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300",
    eyebrow: "text-slate-500 dark:text-slate-400",
    accent: "bg-slate-900 dark:bg-slate-200",
    summary: "border-slate-100 bg-slate-50/75 dark:border-slate-800 dark:bg-slate-900/35",
  },
  blue: {
    icon: "border-sky-100 bg-sky-50 text-sky-700 dark:border-sky-900/45 dark:bg-sky-950/25 dark:text-sky-300",
    eyebrow: "text-sky-700 dark:text-sky-300",
    accent: "bg-sky-600 dark:bg-sky-300",
    summary: "border-sky-100 bg-sky-50/55 dark:border-sky-900/35 dark:bg-sky-950/10",
  },
  emerald: {
    icon: "border-emerald-100 bg-emerald-50 text-emerald-700 dark:border-emerald-900/45 dark:bg-emerald-950/25 dark:text-emerald-300",
    eyebrow: "text-emerald-700 dark:text-emerald-300",
    accent: "bg-emerald-600 dark:bg-emerald-300",
    summary: "border-emerald-100 bg-emerald-50/50 dark:border-emerald-900/35 dark:bg-emerald-950/10",
  },
  danger: {
    icon: "border-red-100 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/25 dark:text-red-300",
    eyebrow: "text-red-700 dark:text-red-300",
    accent: "bg-red-600 dark:bg-red-400",
    summary: "border-red-100 bg-red-50/55 dark:border-red-900/40 dark:bg-red-950/10",
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
            "pointer-events-auto relative flex max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-950 shadow-2xl shadow-slate-950/10 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100 dark:shadow-black/45",
            className,
          )}
        >
          <div className={cn("h-1 shrink-0", styles.accent)} />
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus-visible:ring-slate-700"
            aria-label="关闭面板"
          >
            <X className="h-4 w-4" />
          </button>

          <header className="flex shrink-0 items-start gap-4 border-b border-slate-100 px-5 py-4 pr-14 dark:border-slate-800 sm:px-6 sm:py-5">
            <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border", styles.icon)}>
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className={cn("text-xs font-medium", styles.eyebrow)}>{eyebrow}</div>
              <h2 id={titleId} className="mt-1 text-xl font-semibold text-slate-950 dark:text-slate-50">
                {title}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p>
            </div>
          </header>

          {sidebar ? (
            <div className={cn("shrink-0 border-b px-5 py-3 dark:border-slate-800 sm:px-6", styles.summary)}>
              {sidebar}
            </div>
          ) : null}

          <div className="flex min-h-0 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6 sm:py-6">{children}</div>
            <div className="shrink-0 border-t border-slate-100 bg-slate-50/70 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/35 sm:px-6">
              {footer}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
