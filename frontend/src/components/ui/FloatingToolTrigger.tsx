import type {
  ButtonHTMLAttributes,
  ReactNode,
} from "react";

import { cn } from "../../lib/utils";

interface FloatingToolTriggerProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  active?: boolean;
  icon: ReactNode;
  label: string;
  stackIndex: number;
}

export function FloatingToolTrigger({
  active = false,
  className,
  icon,
  label,
  stackIndex,
  style,
  type = "button",
  ...buttonProps
}: FloatingToolTriggerProps) {
  const safeStackIndex = Math.max(0, stackIndex);

  return (
    <button
      {...buttonProps}
      type={type}
      data-floating-tool-trigger="true"
      className={cn(
        "floating-tool-trigger group fixed z-[88] isolate inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200/70 bg-white/90 text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition-[transform,border-color,background-color,color,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-white active:translate-y-0 active:scale-[0.98] motion-reduce:transition-none motion-reduce:hover:translate-y-0 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100 dark:focus-visible:ring-offset-slate-950",
        active &&
          "border-indigo-200 bg-indigo-50/95 text-indigo-700 shadow-[0_14px_34px_-22px_rgba(79,70,229,0.45)] dark:border-indigo-500/40 dark:bg-indigo-500/12 dark:text-indigo-200",
        className,
      )}
      style={{
        bottom: `calc(1rem + env(safe-area-inset-bottom, 0px) + ${safeStackIndex * 3.25}rem)`,
        right: "calc(1rem + env(safe-area-inset-right, 0px))",
        ...style,
      }}
      aria-label={buttonProps["aria-label"] ?? label}
    >
      <span
        aria-hidden="true"
        className={cn(
          "floating-tool-trigger__label pointer-events-none absolute right-0 top-1/2 z-0 inline-flex h-11 items-center whitespace-nowrap rounded-full border border-slate-200/80 bg-white/95 pl-4 pr-[3.25rem] text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-20px_rgba(15,23,42,0.5)] backdrop-blur-md dark:border-slate-800/90 dark:bg-slate-950/95 dark:text-slate-200 dark:shadow-[0_18px_44px_-26px_rgba(0,0,0,0.9)]",
          active &&
            "border-indigo-200 bg-indigo-50/95 text-indigo-700 dark:border-indigo-500/40 dark:bg-indigo-500/12 dark:text-indigo-200",
        )}
      >
        {label}
      </span>
      <span className="relative z-10 inline-flex h-4 w-4 shrink-0 items-center justify-center">
        {icon}
      </span>
    </button>
  );
}
