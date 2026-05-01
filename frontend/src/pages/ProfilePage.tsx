import { useMemo, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRight,
  Brain,
  CheckCircle2,
  Clock3,
  Gauge,
  Layers3,
  ListChecks,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey,
  getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey,
  useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost,
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
} from "../api/generated/profile";
import type { MasteryOverviewResponse, MasteryStateResponse, ReviewTaskResponse } from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/utils";
import { buildCourseSubPath } from "../lib/courseNavigation";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";

function clamp01(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(1, value));
}

function formatPercent(value: number | null | undefined): string {
  const normalized = clamp01(value);
  return normalized == null ? "--" : `${Math.round(normalized * 100)}%`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无记录";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getAccuracy(state: MasteryStateResponse): number | null {
  if (!state.total_attempts) return null;
  return clamp01(state.correct_attempts / state.total_attempts);
}

const MODE_LABELS: Record<string, string> = {
  web_practice: "网页练习",
  paper: "整卷练习",
  paper_exam: "整卷练习",
  practice: "专项练习",
  quick_check: "快速检查",
  diagnostic: "诊断测验",
  weakpoint_boost: "弱点强化",
  review: "复习巩固",
  mock_final: "模拟考试",
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  fill_blank: "填空题",
  short_answer: "简答题",
  calculation: "计算题",
  proof: "证明题",
};

const DIFFICULTY_LABELS: Record<string, string> = {
  easy: "基础巩固",
  medium: "标准训练",
  hard: "拔高突破",
};

const REASON_LABELS: Record<string, string> = {
  repeated_wrong: "反复出错",
  forgetting_due: "遗忘到期",
  low_mastery: "掌握偏低",
  review_due: "需要复习",
};

function formatMappedList(values: string[] | null | undefined, labels: Record<string, string>, fallback: string): string {
  const normalized = (values ?? []).map((item) => item.trim()).filter(Boolean);
  return normalized.length ? normalized.map((item) => labels[item] ?? item).join(" / ") : fallback;
}

function getMasteryTone(score: number | null | undefined) {
  const normalized = clamp01(score) ?? 0;
  if (normalized < 0.4) {
    return {
      label: "待补强",
      text: "text-rose-700 dark:text-rose-300",
      bar: "bg-rose-500",
      ring: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/25",
    };
  }
  if (normalized < 0.7) {
    return {
      label: "巩固中",
      text: "text-amber-700 dark:text-amber-300",
      bar: "bg-amber-500",
      ring: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/25",
    };
  }
  return {
    label: "稳定",
    text: "text-emerald-700 dark:text-emerald-300",
    bar: "bg-emerald-500",
    ring: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/25",
  };
}

function getProfileHealth(avgMastery: number | null | undefined, dueReviews: number) {
  const normalized = clamp01(avgMastery);
  if (normalized == null) {
    return {
      label: "画像建立中",
      hint: "先完成几次练习，系统会开始形成稳定判断。",
      className: "border-slate-200 bg-white text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300",
    };
  }
  if (dueReviews > 0 || normalized < 0.55) {
    return {
      label: "需要复习",
      hint: "优先处理到期复习和低掌握知识点。",
      className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
    };
  }
  if (normalized < 0.78) {
    return {
      label: "稳步推进",
      hint: "继续用混合题型保持迁移能力。",
      className: "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300",
    };
  }
  return {
    label: "状态良好",
    hint: "可以进入更综合、更贴近实战的练习。",
    className: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300",
  };
}

function ShellCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950",
        className,
      )}
    >
      {children}
    </section>
  );
}

function SectionTitle({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          {icon}
        </span>
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-[-0.02em] text-slate-950 dark:text-slate-100">{title}</h2>
          {description ? (
            <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-[180px] flex-col items-center justify-center rounded-[24px] border border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center dark:border-slate-800 dark:bg-slate-900/60">
      <div className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-slate-500 shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
        {icon}
      </div>
      <p className="mt-4 text-base font-semibold text-slate-950 dark:text-slate-100">{title}</p>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
    </div>
  );
}

function CompactEmpty({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/60">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white text-slate-500 shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:text-slate-400 dark:ring-slate-800">
          {icon}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</p>
        </div>
      </div>
    </div>
  );
}

function StrategyRow({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-50 text-slate-500 dark:bg-slate-900 dark:text-slate-400">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium text-slate-400 dark:text-slate-500">{label}</p>
        <p className="mt-0.5 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{value}</p>
      </div>
    </div>
  );
}

function KnowledgeUnitRow({ state }: { state: MasteryStateResponse }) {
  const masteryScore = clamp01(state.mastery_score) ?? 0;
  const priority = clamp01(state.review_priority) ?? 0;
  const accuracy = getAccuracy(state);
  const tone = getMasteryTone(masteryScore);

  return (
    <div className="border-t border-slate-100 px-6 py-4 first:border-t-0 dark:border-slate-800">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="max-w-full truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
              {state.knowledge_unit_name ?? `KnowledgeUnit ${state.knowledge_unit_id}`}
            </p>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1", tone.ring)}>
              {tone.label}
            </span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            尝试 {state.total_attempts} 次 · 正确 {state.correct_attempts} 次 · 最近 {formatDateTime(state.last_attempt_at)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-4 text-sm md:justify-end">
          <span className={cn("font-semibold", tone.text)}>{formatPercent(masteryScore)}</span>
          <span className="text-xs text-slate-500 dark:text-slate-400">优先级 {formatPercent(priority)}</span>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
          <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.max(4, masteryScore * 100)}%` }} />
        </div>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          准确率 {accuracy == null ? "--" : formatPercent(accuracy)}
        </span>
      </div>
    </div>
  );
}

function ReviewTaskRow({
  task,
  onComplete,
  disabled,
}: {
  task: ReviewTaskResponse;
  onComplete: () => void;
  disabled: boolean;
}) {
  const reason = task.reason ? REASON_LABELS[task.reason] ?? task.reason : "复习巩固";

  return (
    <div className="border-t border-slate-100 px-5 py-4 first:border-t-0 dark:border-slate-800">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
            {task.knowledge_unit_name ?? `KnowledgeUnit ${task.knowledge_unit_id}`}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {reason} · {formatDateTime(task.scheduled_at)}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={onComplete} disabled={disabled}>
          完成
        </Button>
      </div>
    </div>
  );
}

export function ProfilePage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { courseName } = useCourseDisplayName(courseId);

  const masteryQuery = useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet(courseId ?? "");
  const reviewsQuery = useReviewTasksApiV1CoursesCourseIdProfileReviewsGet(courseId ?? "");

  const mastery = useMemo<MasteryOverviewResponse | null>(
    () => unwrapOrvalResponse<MasteryOverviewResponse>(masteryQuery.data),
    [masteryQuery.data],
  );
  const reviewTasks = useMemo<ReviewTaskResponse[]>(
    () => unwrapOrvalResponse<ReviewTaskResponse[]>(reviewsQuery.data) ?? [],
    [reviewsQuery.data],
  );

  const completeReview = useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost({
    mutation: {
      onSuccess: async () => {
        if (!courseId) return;
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey(courseId),
          }),
          queryClient.invalidateQueries({
            queryKey: getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey(courseId),
          }),
        ]);
        toast({
          title: "已完成复习任务",
          description: "画像和待复习列表已刷新。",
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "完成复习失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const states = mastery?.knowledge_unit_states ?? [];
  const courseProfile = mastery?.course_profile;
  const userProfile = mastery?.user_profile;
  const avgMastery = courseProfile?.avg_mastery ?? (states.length
    ? states.reduce((sum, state) => sum + (clamp01(state.mastery_score) ?? 0), 0) / states.length
    : null);
  const weakCount = mastery?.weak_knowledge_unit_count ?? courseProfile?.weak_knowledge_unit_count ?? 0;
  const pendingReviewCount = courseProfile?.pending_review_count ?? userProfile?.pending_review_count ?? reviewTasks.length;
  const dueReviewCount = courseProfile?.due_review_count ?? userProfile?.due_review_count ?? reviewTasks.length;
  const highConfidenceCount = states.filter((state) => (clamp01(state.mastery_score) ?? 0) >= 0.7).length;
  const weakStates = [...states]
    .sort((left, right) => {
      const leftMastery = clamp01(left.mastery_score) ?? 0;
      const rightMastery = clamp01(right.mastery_score) ?? 0;
      const leftPriority = clamp01(left.review_priority) ?? 0;
      const rightPriority = clamp01(right.review_priority) ?? 0;
      return leftMastery - rightMastery || rightPriority - leftPriority;
    })
    .slice(0, 8);
  const health = getProfileHealth(avgMastery, dueReviewCount);
  const recommendedMode = courseProfile?.recommended_exam_mode ?? "web_practice";
  const recommendedModeLabel = MODE_LABELS[recommendedMode] ?? recommendedMode;
  const difficulty = courseProfile?.difficulty_focus ?? "medium";
  const difficultyLabel = DIFFICULTY_LABELS[difficulty] ?? difficulty;
  const noteItems = [...(courseProfile?.notes ?? []), ...(userProfile?.notes ?? [])].filter(Boolean);

  if (!courseId) {
    return (
      <div className="min-h-full px-6 pb-8 pt-20 lg:pt-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少课程标识，暂时无法加载学习画像。
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full px-4 pb-6 pt-20 sm:px-6 lg:px-8 lg:pt-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="overflow-hidden px-2 py-4 sm:px-4 lg:px-6">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-sm font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-800/80 dark:text-slate-300">
                <Brain className="h-4 w-4 text-indigo-500" />
                Learning Profile
              </div>

              <h1 className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-slate-950 dark:text-slate-100 sm:text-5xl">
                学习画像
              </h1>

              <p className="mt-4 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-400 sm:text-lg">
                {courseName ? `「${courseName}」的掌握度、复习压力和下一轮练习建议，会在这里收束成一条清晰路径。` : "掌握度、复习压力和下一轮练习建议，会在这里收束成一条清晰路径。"}
              </p>

              <div className="mt-7 flex flex-wrap gap-x-7 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
                <span>
                  平均掌握 <b className="font-semibold text-slate-950 dark:text-slate-100">{formatPercent(avgMastery)}</b>
                </span>
                <span>
                  知识点 <b className="font-semibold text-slate-950 dark:text-slate-100">{states.length}</b>
                </span>
                <span>
                  待复习 <b className="font-semibold text-slate-950 dark:text-slate-100">{pendingReviewCount}</b>
                </span>
                <span>
                  薄弱点 <b className="font-semibold text-slate-950 dark:text-slate-100">{weakCount}</b>
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col lg:items-end">
              <span className={cn("inline-flex items-center justify-center rounded-full border px-3 py-1.5 text-sm font-semibold shadow-sm", health.className)}>
                {health.label}
              </span>
              <Button
                size="lg"
                className="!h-12 rounded-[10px] bg-black px-6 text-sm font-semibold text-white hover:bg-slate-900 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
                onClick={() => navigate(buildCourseSubPath(courseId, "exams"))}
              >
                开始推荐练习
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>

        {masteryQuery.error || reviewsQuery.error ? (
          <div className="rounded-[28px] border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        ) : null}

        <ShellCard>
          <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.62fr)]">
            <div className="min-w-0">
              <div className="border-b border-slate-100 px-6 py-6 dark:border-slate-800">
                <SectionTitle
                  icon={<Target className="h-4 w-4" />}
                  title="当前掌握路径"
                  description={health.hint}
                  action={
                    <span className="hidden rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-900 dark:text-slate-300 sm:inline-flex">
                      {difficultyLabel}
                    </span>
                  }
                />

                <div className="mt-7 grid gap-7 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-end">
                  <div>
                    <p className="text-5xl font-semibold tracking-[-0.05em] text-slate-950 dark:text-slate-100">
                      {formatPercent(avgMastery)}
                    </p>
                    <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">平均掌握度</p>
                  </div>
                  <div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
                      <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.max(4, (clamp01(avgMastery) ?? 0) * 100)}%` }} />
                    </div>
                    <div className="mt-5 grid gap-4 border-t border-slate-100 pt-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-400 sm:grid-cols-3">
                      <span>稳定知识点 <b className="font-semibold text-slate-950 dark:text-slate-100">{highConfidenceCount}</b></span>
                      <span>到期复习 <b className="font-semibold text-slate-950 dark:text-slate-100">{dueReviewCount}</b></span>
                      <span>推荐 <b className="font-semibold text-slate-950 dark:text-slate-100">{recommendedModeLabel}</b></span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="px-0 py-2">
                <div className="flex items-center justify-between gap-4 px-6 py-3">
                  <h3 className="text-sm font-semibold text-slate-950 dark:text-slate-100">优先补强</h3>
                  <span className="text-xs text-slate-500 dark:text-slate-400">按掌握度和复习优先级排序</span>
                </div>

                {masteryQuery.isLoading ? (
                  <div className="px-6 pb-6">
                    <EmptyState
                      icon={<Loader2 className="h-5 w-5 animate-spin" />}
                      title="正在读取画像"
                      description="正在汇总掌握度、稳定度和复习优先级。"
                    />
                  </div>
                ) : null}

                {!masteryQuery.isLoading && weakStates.length === 0 ? (
                  <div className="px-6 pb-6">
                    <EmptyState
                      icon={<Sparkles className="h-5 w-5" />}
                      title="画像还在等待答题数据"
                      description="完成几道练习后，这里会出现真正需要优先补强的知识点。"
                    />
                  </div>
                ) : null}

                {weakStates.map((state) => (
                  <KnowledgeUnitRow key={state.id} state={state} />
                ))}
              </div>
            </div>

            <aside className="border-t border-slate-100 bg-slate-50/45 dark:border-slate-800 dark:bg-slate-900/35 xl:border-l xl:border-t-0">
              <div className="px-5 py-5">
                <SectionTitle
                  icon={<Sparkles className="h-4 w-4" />}
                  title="下一轮建议"
                  description="把画像结果转成可以直接行动的练习参数。"
                />
                <div className="mt-5 space-y-4">
                  <StrategyRow icon={<Zap className="h-4 w-4" />} label="练习模式" value={recommendedModeLabel} />
                  <StrategyRow
                    icon={<ListChecks className="h-4 w-4" />}
                    label="推荐题型"
                    value={formatMappedList(courseProfile?.recommended_question_types, QUESTION_TYPE_LABELS, "单选题 / 简答题")}
                  />
                  <StrategyRow icon={<Gauge className="h-4 w-4" />} label="难度聚焦" value={difficultyLabel} />
                  <StrategyRow
                    icon={<TrendingUp className="h-4 w-4" />}
                    label="学习节奏"
                    value={userProfile?.pace_preference === "fast" ? "快速推进" : userProfile?.pace_preference === "slow" ? "稳扎稳打" : "稳定推进"}
                  />
                  <StrategyRow
                    icon={<Layers3 className="h-4 w-4" />}
                    label="常用模式"
                    value={formatMappedList(userProfile?.preferred_exam_modes, MODE_LABELS, MODE_LABELS[userProfile?.dominant_exam_mode ?? ""] ?? recommendedModeLabel)}
                  />
                </div>
              </div>

              <div className="border-t border-slate-100 px-5 py-5 dark:border-slate-800">
                <SectionTitle icon={<Clock3 className="h-4 w-4" />} title="待复习" />
                <div className="mt-4">
                  {reviewsQuery.isLoading ? (
                    <CompactEmpty icon={<RefreshCw className="h-4 w-4 animate-spin" />} title="正在同步" description="马上同步最新安排。" />
                  ) : null}
                  {!reviewsQuery.isLoading && reviewTasks.length === 0 ? (
                    <CompactEmpty icon={<CheckCircle2 className="h-4 w-4" />} title="暂无待处理复习" description="继续练习后，系统会按遗忘风险生成复习安排。" />
                  ) : null}
                </div>
              </div>

              {reviewTasks.length ? (
                <div className="border-t border-slate-100 dark:border-slate-800">
                  {reviewTasks.map((task) => (
                    <ReviewTaskRow
                      key={task.id}
                      task={task}
                      onComplete={() => completeReview.mutate({ courseId, taskId: task.id })}
                      disabled={completeReview.isPending}
                    />
                  ))}
                </div>
              ) : null}

              <div className="border-t border-slate-100 px-5 py-5 dark:border-slate-800">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-100">
                  <AlertCircle className="h-4 w-4 text-slate-400" />
                  画像备注
                </div>
                <div className="mt-3 space-y-3">
                  {noteItems.length ? noteItems.map((note, index) => (
                    <p key={`${note}-${index}`} className="text-sm leading-6 text-slate-600 dark:text-slate-400">
                      {note}
                    </p>
                  )) : (
                    <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
                      完成几次练习后会出现更具体的诊断。
                    </p>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </ShellCard>
      </div>
    </div>
  );
}
