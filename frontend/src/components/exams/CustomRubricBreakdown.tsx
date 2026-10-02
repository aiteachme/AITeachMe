import { cn } from "../../lib/utils";

type RubricCriterion = {
  key: string;
  label: string;
  weight: number;
  scoreRatio: number;
  evidence: string[];
  note: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function parseCriteria(value: unknown): RubricCriterion[] {
  const detail = asRecord(value);
  if (!detail || !Array.isArray(detail.criteria)) return [];
  return detail.criteria.flatMap((raw): RubricCriterion[] => {
    const item = asRecord(raw);
    if (!item) return [];
    const key = String(item.key ?? "").trim();
    const label = String(item.label ?? key).trim();
    const weight = Number(item.weight);
    const scoreRatio = Number(item.score_ratio);
    if (!key || !Number.isFinite(weight) || !Number.isFinite(scoreRatio)) return [];
    return [{
      key,
      label: label || key,
      weight: Math.max(0, Math.min(1, weight)),
      scoreRatio: Math.max(0, Math.min(1, scoreRatio)),
      evidence: Array.isArray(item.evidence_spans) && item.evidence_spans.length
        ? item.evidence_spans.flatMap((rawSpan) => {
          const span = asRecord(rawSpan);
          return span && typeof span.quote === "string" ? [`${span.field_label ? `${span.field_label}：` : ""}${span.quote}`] : [];
        })
        : Array.isArray(item.evidence)
        ? item.evidence.map((entry) => String(entry ?? "").trim()).filter(Boolean)
        : [],
      note: String(item.note ?? "").trim(),
    }];
  });
}

export function CustomRubricBreakdown({
  detail,
  compact = false,
  className,
}: {
  detail?: unknown;
  compact?: boolean;
  className?: string;
}) {
  const criteria = parseCriteria(detail);
  if (!criteria.length) return null;

  return (
    <section className={cn("border-t border-slate-100 pt-3 dark:border-slate-800", className)}>
      <h3 className={cn(
        "font-semibold text-slate-500 dark:text-slate-400",
        compact ? "text-xs" : "text-xs uppercase tracking-wider",
      )}>
        评分维度
      </h3>
      <div className={cn("mt-2 grid", compact ? "gap-1.5" : "gap-2.5")}>
        {criteria.map((criterion) => (
          <div key={criterion.key} className="break-inside-auto">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {criterion.label}
                <span className="ml-1 text-slate-400">{Math.round(criterion.weight * 100)}%</span>
              </span>
              <span className="shrink-0 tabular-nums text-slate-600 dark:text-slate-300">
                得分 {Math.round(criterion.scoreRatio * 100)}%
              </span>
            </div>
            {criterion.evidence.length > 0 ? (
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-5 text-slate-500 dark:text-slate-400">
                依据：{criterion.evidence.join("；")}
              </p>
            ) : criterion.note ? (
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-5 text-slate-500 dark:text-slate-400">
                {criterion.note}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
