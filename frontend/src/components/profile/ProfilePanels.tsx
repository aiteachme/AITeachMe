import type { ReactNode } from "react";
import {
  ArrowRight,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  Flame,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import type {
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
  StudyPlanStepResponse,
} from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import {
  clamp01,
  formatDateTime,
  formatPercent,
  formatToken,
  isReviewDueSoon,
  masteryTone,
} from "./profileDisplay";

export const PROFILE_SURFACE_CLASS =
  "rounded-lg border border-slate-200/80 bg-white/90 shadow-sm dark:border-slate-800/80 dark:bg-slate-900/80";

export function MetricTile({
  label,
  value,
  hint,
  icon,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  icon: ReactNode;
  tone: string;
}) {
  return (
    <div className={cn(PROFILE_SURFACE_CLASS, "p-4")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
          <p className="mt-2 truncate text-2xl font-semibold text-slate-950 dark:text-slate-100">{value}</p>
        </div>
        <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", tone)}>
          {icon}
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-slate-400">{hint}</p>
    </div>
  );
}

export function Panel({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">{title}</h2>
          {description ? <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function NextActionCard({
  courseProfile,
  weakCount,
  dueCount,
  onStartPractice,
}: {
  courseProfile: MasteryOverviewResponse["course_profile"];
  weakCount: number;
  dueCount: number;
  onStartPractice: () => void;
}) {
  const primaryAction = dueCount > 0
    ? "先处理高优先级复习"
    : weakCount > 0
      ? "先补强薄弱知识点"
      : "进入综合练习";
  const questionTypes = courseProfile?.recommended_question_types ?? [];

  return (
    <div className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Sparkles className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">下一次练习建议</p>
          <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
            {primaryAction} · {formatToken(courseProfile?.recommended_exam_mode, "网页练习")} · 约 {courseProfile?.recommended_question_count ?? 10} 题 · {formatToken(courseProfile?.difficulty_focus, "中等")} 难度。
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {questionTypes.slice(0, 3).map((item) => (
              <span key={item} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {formatToken(item)}
              </span>
            ))}
            {dueCount > 0 ? (
              <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                高优先级 {dueCount} 项
              </span>
            ) : null}
          </div>
          <Button type="button" size="sm" onClick={onStartPractice} className="mt-4 h-8 px-3 text-xs">
            开始练习
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export type LearningPlanStep = StudyPlanStepResponse;

const PLAN_LABEL_BY_KEY: Record<string, string> = {
  review: "复习",
  practice: "训练",
  reflect: "复盘",
};

export function LearningPlanPanel({
  courseProfile,
  states,
  reviewTasks,
  studyPlan,
  onStartPractice,
  onOpenKnowledgeDocs,
}: {
  courseProfile: MasteryOverviewResponse["course_profile"];
  states: MasteryStateResponse[];
  reviewTasks: ReviewTaskResponse[];
  studyPlan?: LearningPlanStep[];
  onStartPractice: () => void;
  onOpenKnowledgeDocs: () => void;
}) {
  const dueTasks = reviewTasks.filter(isReviewDueSoon);
  const weakStates = [...states]
    .sort((left, right) => left.mastery_score - right.mastery_score || right.review_priority - left.review_priority)
    .slice(0, 3);
  const focusNames = weakStates
    .map((state) => getKnowledgeUnitLabel(state))
    .slice(0, 2)
    .join("、");
  const questionTypes = courseProfile?.recommended_question_types?.slice(0, 2).map((item) => formatToken(item)).join("、");
  const fallbackPlanItems = [
    {
      key: "locate",
      label: "定位",
      title: dueTasks.length ? "先处理高优先级复习" : "锁定薄弱知识点",
      detail: dueTasks.length
        ? `优先完成 ${Math.min(dueTasks.length, 3)} 个高优先级复习任务，避免遗忘继续扩大。`
        : focusNames
          ? `先看 ${focusNames}，确认这几个点是否真的理解。`
          : "先做一次短练习，让系统拿到可诊断的数据。",
    },
    {
      key: "practice",
      label: "训练",
      title: "做一轮专项练习",
      detail: `${formatToken(courseProfile?.recommended_exam_mode, "网页练习")} · 约 ${courseProfile?.recommended_question_count ?? 10} 题 · ${formatToken(courseProfile?.difficulty_focus, "中等")}难度${questionTypes ? ` · ${questionTypes}` : ""}。`,
    },
    {
      key: "reflect",
      label: "复盘",
      title: "带着错题回到知识库",
      detail: "练完后把错题、卡点或划选内容拿去伴读追问，画像会继续沉淀你的讲解偏好。",
    },
  ];
  const planItems = studyPlan?.length
    ? studyPlan.map((item) => ({
      key: item.key,
      label: PLAN_LABEL_BY_KEY[item.key] ?? "计划",
      title: item.title,
      detail: item.detail,
    }))
    : fallbackPlanItems;

  return (
    <Panel
      title="今日学习计划"
      description="按复习、练习、伴读排出下一步，保留可直接执行的部分。"
      action={(
        <Button type="button" size="sm" onClick={onStartPractice} className="hidden h-8 shrink-0 px-3 text-xs sm:inline-flex">
          开始练习
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      )}
    >
      <ol className="mt-5 divide-y divide-slate-100 dark:divide-slate-800">
        {planItems.map((item, index) => (
          <li
            key={item.key}
            className="grid gap-3 py-4 first:pt-0 last:pb-0 sm:grid-cols-[5.5rem_minmax(0,1fr)] sm:items-start"
          >
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-white text-[11px] font-semibold tabular-nums text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span>{item.label}</span>
            </div>
            <div className="min-w-0">
              <p className="break-words text-sm font-semibold text-slate-950 dark:text-slate-100">{item.title}</p>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{item.detail}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap gap-2 sm:hidden">
        <Button type="button" size="sm" onClick={onStartPractice} className="h-8 px-3 text-xs">
          开始练习
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onOpenKnowledgeDocs} className="h-8 px-3 text-xs">
          打开知识库
        </Button>
      </div>
    </Panel>
  );
}

export function MasteryDistribution({ states }: { states: MasteryStateResponse[] }) {
  const weak = states.filter((state) => state.mastery_score < 0.4).length;
  const building = states.filter((state) => state.mastery_score >= 0.4 && state.mastery_score < 0.7).length;
  const stable = states.filter((state) => state.mastery_score >= 0.7).length;
  const total = Math.max(1, states.length);
  const items = [
    { label: "补强", count: weak, className: "bg-rose-500" },
    { label: "建立", count: building, className: "bg-amber-500" },
    { label: "稳定", count: stable, className: "bg-emerald-500" },
  ];

  return (
    <div className="mt-5">
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        {items.map((item) => (
          <span
            key={item.label}
            className={item.className}
            style={{ width: `${(item.count / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-lg border border-slate-200/80 px-3 py-3 dark:border-slate-800/80">
            <div className="flex items-center gap-2">
              <span className={cn("h-2.5 w-2.5 rounded-full", item.className)} />
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</span>
            </div>
            <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-slate-100">{item.count}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ProfileSignalStrip({
  states,
  reviewTasks,
}: {
  states: MasteryStateResponse[];
  reviewTasks: ReviewTaskResponse[];
}) {
  const lowMastery = states.filter((state) => state.mastery_score < 0.4).length;
  const lowConfidence = states.filter((state) => state.confidence_score < 0.45).length;
  const unstable = states.filter((state) => state.stability_score < 0.45).length;
  const dueSoon = reviewTasks.filter(isReviewDueSoon).length;
  const signals = [
    {
      label: "薄弱",
      value: lowMastery,
      hint: "掌握度低于 40%",
      icon: <Flame className="h-4 w-4" />,
      tone: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
    },
    {
      label: "低置信",
      value: lowConfidence,
      hint: "数据仍需练习校准",
      icon: <BrainCircuit className="h-4 w-4" />,
      tone: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300",
    },
    {
      label: "不稳定",
      value: unstable,
      hint: "容易遗忘或波动",
      icon: <ShieldCheck className="h-4 w-4" />,
      tone: "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300",
    },
    {
      label: "临近复习",
      value: dueSoon,
      hint: "24 小时内或高优先级",
      icon: <CalendarClock className="h-4 w-4" />,
      tone: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {signals.map((signal) => (
        <div key={signal.label} className="rounded-lg border border-slate-200/80 bg-white/70 px-3 py-3 dark:border-slate-800/80 dark:bg-slate-950/30">
          <div className="flex items-center justify-between gap-3">
            <span className={cn("flex h-8 w-8 items-center justify-center rounded-lg", signal.tone)}>{signal.icon}</span>
            <span className="text-lg font-semibold text-slate-950 dark:text-slate-100">{signal.value}</span>
          </div>
          <p className="mt-2 text-xs font-semibold text-slate-700 dark:text-slate-200">{signal.label}</p>
          <p className="mt-1 text-xs text-slate-400">{signal.hint}</p>
        </div>
      ))}
    </div>
  );
}

function getKnowledgeUnitLabel(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">): string {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

export function ProfileRiskMatrix({
  states,
  reviewTasks,
}: {
  states: MasteryStateResponse[];
  reviewTasks: ReviewTaskResponse[];
}) {
  const dueTaskUnitIds = new Set(
    reviewTasks
      .filter(isReviewDueSoon)
      .map((task) => task.knowledge_unit_id),
  );
  const sortedByRisk = [...states].sort((left, right) =>
    Number(dueTaskUnitIds.has(right.knowledge_unit_id)) - Number(dueTaskUnitIds.has(left.knowledge_unit_id)) ||
    right.review_priority - left.review_priority ||
    left.mastery_score - right.mastery_score,
  );
  const buckets = [
    {
      label: "立刻补强",
      hint: "低掌握或复习到期",
      icon: <Flame className="h-4 w-4" />,
      tone: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300",
      items: sortedByRisk.filter((state) => state.mastery_score < 0.4 || dueTaskUnitIds.has(state.knowledge_unit_id)),
    },
    {
      label: "继续校准",
      hint: "置信度还不够高",
      icon: <BrainCircuit className="h-4 w-4" />,
      tone: "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300",
      items: sortedByRisk.filter((state) => state.confidence_score < 0.55 && state.mastery_score >= 0.4),
    },
    {
      label: "防止遗忘",
      hint: "稳定度偏低",
      icon: <ShieldCheck className="h-4 w-4" />,
      tone: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
      items: sortedByRisk.filter((state) => state.stability_score < 0.55 && state.mastery_score >= 0.55),
    },
    {
      label: "相对稳定",
      hint: "可进入综合练习",
      icon: <CheckCircle2 className="h-4 w-4" />,
      tone: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300",
      items: sortedByRisk.filter((state) => state.mastery_score >= 0.7 && state.stability_score >= 0.65),
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
      {buckets.map((bucket) => (
        <div key={bucket.label} className={cn("rounded-lg border px-3 py-3", bucket.tone)}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">{bucket.label}</p>
              <p className="mt-1 text-xs opacity-80">{bucket.hint}</p>
            </div>
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/70 dark:bg-slate-950/35">
              {bucket.icon}
            </span>
          </div>
          <p className="mt-3 text-2xl font-semibold tabular-nums">{bucket.items.length}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {bucket.items.slice(0, 3).map((state) => (
              <span
                key={`${bucket.label}-${state.id}`}
                className="max-w-full truncate rounded-full bg-white/75 px-2 py-0.5 text-[11px] font-medium text-current ring-1 ring-black/5 dark:bg-slate-950/35"
                title={getKnowledgeUnitLabel(state)}
              >
                {getKnowledgeUnitLabel(state)}
              </span>
            ))}
            {!bucket.items.length ? (
              <span className="text-[11px] opacity-70">暂无</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

export function MasteryHeatmap({
  states,
  focusUnitIds,
}: {
  states: MasteryStateResponse[];
  focusUnitIds: Set<number>;
}) {
  const sortedStates = [...states]
    .sort((left, right) =>
      left.mastery_score - right.mastery_score ||
      right.review_priority - left.review_priority ||
      left.knowledge_unit_id - right.knowledge_unit_id,
    )
    .slice(0, 72);

  if (!sortedStates.length) {
    return (
      <p className="mt-5 rounded-lg bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
        暂无知识点掌握数据。
      </p>
    );
  }

  return (
    <div className="mt-5">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(42px,1fr))] gap-2">
        {sortedStates.map((state) => {
          const score = clamp01(state.mastery_score);
          const tone = masteryTone(score);
          const focused = focusUnitIds.has(state.knowledge_unit_id);
          return (
            <span
              key={state.id}
              title={`${getKnowledgeUnitLabel(state)}：${formatPercent(score)}，复习优先级 ${formatPercent(state.review_priority)}`}
              aria-label={`${getKnowledgeUnitLabel(state)} 掌握度 ${formatPercent(score)}`}
              className={cn(
                "grid aspect-square min-h-10 place-items-center rounded-lg border text-[11px] font-semibold tabular-nums",
                tone.bg,
                tone.text,
                focused ? "border-indigo-300 ring-2 ring-indigo-100 dark:border-indigo-500/50 dark:ring-indigo-500/20" : "border-slate-200/70 dark:border-slate-800/80",
              )}
            >
              {Math.round(score * 100)}
            </span>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-rose-500" />补强</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-500" />建立</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />稳定</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full ring-2 ring-indigo-200 dark:ring-indigo-500/40" />推荐覆盖</span>
      </div>
    </div>
  );
}

export function AccuracyRows({
  title,
  values,
  emptyText,
}: {
  title: string;
  values?: Record<string, number> | null;
  emptyText: string;
}) {
  const rows = Object.entries(values ?? {})
    .filter(([, value]) => Number.isFinite(value))
    .sort((a, b) => a[1] - b[1])
    .slice(0, 6);

  return (
    <div>
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</p>
      <div className="mt-3 space-y-3">
        {rows.length ? rows.map(([key, value]) => (
          <div key={key}>
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
              <span className="font-medium text-slate-600 dark:text-slate-300">{formatToken(key)}</span>
              <span className="text-slate-400">{formatPercent(value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div className="h-full rounded-full bg-slate-900 dark:bg-slate-100" style={{ width: `${Math.max(4, value * 100)}%` }} />
            </div>
          </div>
        )) : (
          <p className="rounded-lg bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
            {emptyText}
          </p>
        )}
      </div>
    </div>
  );
}

export function FocusStateCard({
  state,
  focused,
}: {
  state: MasteryStateResponse;
  focused: boolean;
}) {
  const masteryScore = clamp01(state.mastery_score);
  const priority = clamp01(state.review_priority);
  const tone = masteryTone(masteryScore);

  return (
    <div className={cn("rounded-lg border px-4 py-4", focused ? "border-indigo-200 bg-indigo-50/60 dark:border-indigo-500/30 dark:bg-indigo-500/10" : "border-slate-200/80 bg-white/70 dark:border-slate-800/80 dark:bg-slate-950/30")}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="break-words text-base font-semibold text-slate-950 dark:text-slate-100">
              {getKnowledgeUnitLabel(state)}
            </p>
            {focused ? (
              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
                推荐覆盖
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次 · 正确 {state.correct_attempts} 次
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", tone.bg, tone.text)}>
            {tone.label}
          </span>
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{formatPercent(masteryScore)}</span>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px] sm:items-center">
        <div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.max(5, masteryScore * 100)}%` }} />
          </div>
          <p className="mt-2 text-xs text-slate-400">最近作答：{formatDateTime(state.last_attempt_at)}</p>
        </div>
        <div className="text-left sm:text-right">
          <p className="text-xs text-slate-400">复习优先级</p>
          <p className="mt-1 text-sm font-semibold text-slate-700 dark:text-slate-200">{formatPercent(priority)}</p>
        </div>
      </div>
    </div>
  );
}

export function ReviewTaskCard({
  task,
  onComplete,
  disabled,
}: {
  task: ReviewTaskResponse;
  onComplete: () => void;
  disabled: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800/80 dark:bg-slate-950/30">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="break-words text-sm font-semibold text-slate-950 dark:text-slate-100">
            {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {formatToken(task.knowledge_unit_type, "知识点")} · {task.reason || "复习巩固"} · {formatDateTime(task.scheduled_at)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">间隔 {task.interval_days} 天</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">第 {task.repetition_count + 1} 轮</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">优先级 {formatPercent(task.priority)}</span>
          </div>
        </div>
        <Button size="sm" onClick={onComplete} disabled={disabled}>
          完成
        </Button>
      </div>
    </div>
  );
}

export function PreferenceRow({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-slate-200/80 bg-slate-50/70 px-3 py-3 dark:border-slate-800/80 dark:bg-slate-950/40">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 ring-1 ring-slate-200/80 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
        <p className="mt-1 break-words text-sm font-semibold leading-5 text-slate-900 dark:text-slate-100">{value}</p>
      </div>
    </div>
  );
}
