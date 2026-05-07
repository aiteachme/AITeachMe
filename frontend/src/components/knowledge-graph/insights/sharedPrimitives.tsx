import type { ReactNode } from "react";

export function ChartPanel({
  title,
  meta,
  description,
  className = "",
  bodyClassName = "",
  children,
}: {
  title: string;
  meta?: ReactNode;
  description?: string;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`overflow-hidden rounded-lg border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950 ${className}`}
    >
      <div className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5 dark:border-slate-800">
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-5 text-slate-900 dark:text-slate-100">{title}</p>
          {description ? (
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</p>
          ) : null}
        </div>
        {meta ? (
          <div className="shrink-0 text-[11px] font-medium tabular-nums text-slate-500 dark:text-slate-400">{meta}</div>
        ) : null}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function CategoryBar({
  segments,
  height = 14,
  showLegend = true,
}: {
  segments: Array<{ key: string; label: string; color: string; count: number; tooltip?: string }>;
  height?: number;
  showLegend?: boolean;
}) {
  const total = segments.reduce((sum, item) => sum + item.count, 0) || 1;
  return (
    <div>
      <div className="flex overflow-hidden rounded-full" style={{ height }}>
        {segments.map((segment) => {
          const percent = (segment.count / total) * 100;
          if (percent < 0.5) return null;
          return (
            <div
              key={segment.key}
              title={segment.tooltip ?? `${segment.label} · ${segment.count} (${percent.toFixed(1)}%)`}
              style={{ backgroundColor: segment.color, width: `${percent}%` }}
            />
          );
        })}
      </div>
      {showLegend ? (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5">
          {segments.map((segment) => (
            <div key={segment.key} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: segment.color }} />
              <span className="text-[11px] text-slate-600 dark:text-slate-300">{segment.label}</span>
              <span className="text-[11px] font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                {segment.count}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
