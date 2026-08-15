import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  const titleId = React.useId();
  React.useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  const content = (
    <div className="fixed inset-0 z-[120]">
      <div
        className="absolute inset-0 modal-backdrop"
        onClick={onClose}
      />
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-3 sm:p-6">
        <div
          className={cn(
            "pointer-events-auto relative flex max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white text-zinc-900 shadow-[0_16px_40px_rgba(15,23,42,0.12)] ring-1 ring-zinc-200/70 dark:bg-slate-950 dark:text-slate-100 dark:shadow-[0_24px_64px_-28px_rgba(0,0,0,0.7)] dark:ring-slate-800/80 sm:max-h-[85vh]",
            className
          )}
          role="dialog"
          aria-modal="true"
          aria-labelledby={title ? titleId : undefined}
        >
          {title && (
            <div className="flex shrink-0 items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-slate-800 sm:px-6 sm:py-4">
              <h2 id={titleId} className="truncate pr-4 text-[15px] font-semibold text-zinc-900 dark:text-slate-100">{title}</h2>
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-900 active:scale-95 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-100 sm:h-8 sm:w-8"
                aria-label="关闭弹窗"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</div>
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(content, document.body);
}
