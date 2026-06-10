import { useEffect, useId, type ReactNode } from "react";
import { X, type LucideIcon } from "lucide-react";

import { cn } from "../../lib/utils";

interface CourseOperationModalProps {
  eyebrow?: string;
  title: string;
  description?: string;
  icon: LucideIcon;
  tone?: "slate" | "blue" | "emerald" | "danger";
  sidebar?: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  className?: string;
}

export function CourseOperationModal({
  eyebrow,
  title,
  description,
  icon: _Icon,
  tone = "slate",
  sidebar,
  children,
  footer,
  onClose,
  className,
}: CourseOperationModalProps) {
  const titleId = useId();
  void _Icon;
  const hasEyebrow = Boolean(eyebrow?.trim());
  const hasDescription = Boolean(description?.trim());
  const eyebrowClass = tone === "danger" ? "text-red-600 dark:text-red-300" : "text-slate-500 dark:text-slate-400";

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
            "pointer-events-auto relative flex max-h-[calc(100dvh-1.5rem)] w-full max-w-[680px] flex-col overflow-hidden rounded-lg border border-slate-200/70 bg-white text-slate-950 shadow-[0_22px_72px_rgba(15,23,42,0.16)] dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100 dark:shadow-black/45",
            className,
          )}
        >
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 z-10 flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus-visible:ring-slate-700"
            aria-label="关闭面板"
          >
            <X className="h-4 w-4" />
          </button>

          <header className="shrink-0 px-5 pb-3 pt-5 pr-14 sm:px-6">
            {hasEyebrow ? <div className={cn("text-xs font-medium leading-5", eyebrowClass)}>{eyebrow}</div> : null}
            <h2 id={titleId} className={cn("text-xl font-semibold tracking-normal text-slate-950 dark:text-slate-50", hasEyebrow && "mt-1")}>
              {title}
            </h2>
            {hasDescription ? (
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
            ) : null}
          </header>

          {sidebar ? (
            <div className="shrink-0 px-5 pb-3 sm:px-6">
              {sidebar}
            </div>
          ) : null}

          <div className="flex min-h-0 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3 sm:px-6">{children}</div>
            <div className="shrink-0 bg-white px-5 pb-5 pt-3 dark:bg-slate-950 sm:px-6">
              {footer}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
