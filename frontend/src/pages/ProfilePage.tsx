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
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildCourseSubPath } from "../lib/courseNavigation";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { cn } from "../lib/utils";

function clamp01(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(1, value));
}

function formatPercent(value: number | null | undefined): string {
  const normalized = clamp01(value);
  return normalized == null ? "--" : `${Math.round(normalized * 100)}%`;
}

function formatCount(value: number | null | undefined, loading = false): string {
  if (loading) return "--";
  if (value == null || !Number.isFinite(value)) return "--";
  return String(value);
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

function formatKnowledgeUnitName(name: string | null | undefined, knowledgeUnitId: number): string {
  const trimmed = name?.trim();
  return trimmed || `知识点 ${knowledgeUnitId}`;
}

function pickLatestTimestamp(...values: Array<string | null | undefined>): string | null {
  let latestValue: string | null = null;
  let latestTime = -Infinity;

  values.forEach((value) => {
    if (!value) return;
    const time = new Date(value).getTime();
    if (Number.isNaN(time) || time <= latestTime) return;
    latestTime = time;
    latestValue = value;
  });

  return latestValue;
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
  mixed: "混合训练",
};

const REASON_LABELS: Record<string, string> = {
  repeated_wrong: "反复出错",
  forgetting_due: "遗忘到期",
  low_mastery: "掌握偏低",
  review_due: "需要复习",
};

function getModeLabel(mode: string | null | undefined): string {
  return mode ? MODE_LABELS[mode] ?? "网页练习" : "网页练习";
}

function getDifficultyLabel(difficulty: string | null | undefined): string {
  return difficulty ? DIFFICULTY_LABELS[difficulty] ?? "标准训练" : "标准训练";
}

function formatMappedList(
  values: string[] | null | undefined,
  labels: Record<string, string>,
  fallback: string,
  unknownLabel: string,
): string {
  const mapped = (values ?? [])
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => labels[item] ?? unknownLabel);

  const deduped = [...new Set(mapped)];
  return deduped.length ? deduped.join(" / ") : fallback;
}

function localizeProfileNote(note: string): string | null {
  const trimmed = note.trim();
  if (!trimmed) return null;

  const [rawKey, ...rawValueParts] = trimmed.split(":");
  const value = rawValueParts.join(":").trim();
  if (!rawKey || !rawValueParts.length) {
    return /[A-Za-z]/.test(trimmed) ? null : trimmed;
  }

  const key = rawKey.trim().toLowerCase();
  if (key === "weak knowledgeunits") return `薄弱知识点：${value || "0"} 个`;
  if (key === "due reviews") return `到期复习：${value || "0"} 个`;
  if (key === "recommended exam mode") return `推荐练习模式：${getModeLabel(value)}`;
  if (key === "difficulty focus") return `难度聚焦：${getDifficultyLabel(value)}`;
  if (key === "active courses") return `活跃课程：${value || "0"} 门`;
  if (key === "dominant exam mode") return `常用练习模式：${getModeLabel(value)}`;
  if (key === "due reviews across courses") return `跨课程到期复习：${value || "0"} 个`;
  if (key === "recommended question types") {
    return `推荐题型：${formatMappedList(value.split(","), QUESTION_TYPE_LABELS, "单选题 / 简答题", "其他题型")}`;
  }
  if (key === "preferred question types") {
    return `常练题型：${formatMappedList(value.split(","), QUESTION_TYPE_LABELS, "单选题 / 简答题", "其他题型")}`;
  }

  return /[A-Za-z]/.test(trimmed) ? null : trimmed;
}

function getMasteryTone(score: number | null | undefined) {
  const normalized = clamp01(score) ?? 0;
  if (normalized < 0.4) {
    return {
      label: "待补强",
      text: "text-rose-700 dark:text-rose-300",
      bar: "bg-rose-500",
      badge: "border-rose-200 text-rose-700 dark:border-rose-500/30 dark:text-rose-300",
    };
  }
  if (normalized < 0.7) {
    return {
      label: "巩固中",
      text: "text-amber-700 dark:text-amber-300",
      bar: "bg-amber-500",
      badge: "border-amber-200 text-amber-700 dark:border-amber-500/30 dark:text-amber-300",
    };
  }
  return {
    label: "稳定",
    text: "text-emerald-700 dark:text-emerald-300",
    bar: "bg-emerald-500",
    badge: "border-emerald-200 text-emerald-700 dark:border-emerald-500/30 dark:text-emerald-300",
  };
}

function getProfileHealth(avgMastery: number | null | undefined, dueReviews: number) {
  const normalized = clamp01(avgMastery);
  if (normalized == null) {
    return {
      label: "画像建立中",
      hint: "先完成几次练习，系统会开始形成稳定判断。",
      className: "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300",
    };
  }
  if (dueReviews > 0 || normalized < 0.55) {
    return {
      label: "需要复习",
      hint: "优先处理到期复习和低掌握知识点。",
      className: "border-amber-300 text-amber-700 dark:border-amber-500/40 dark:text-amber-300",
    };
  }
  if (normalized < 0.78) {
    return {
      label: "稳步推进",
      hint: "继续用混合题型保持迁移能力。",
      className: "border-indigo-300 text-indigo-700 dark:border-indigo-500/40 dark:text-indigo-300",
    };
  }
  return {
    label: "状态良好",
    hint: "可以进入更综合、更贴近实战的练习。",
    className: "border-emerald-300 text-emerald-700 dark:border-emerald-500/40 dark:text-emerald-300",
  };
}

function SectionBlock({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("border-t border-slate-200 pt-6 dark:border-slate-800", className)}>
      {children}
    </section>
  );
}

function SectionHeader({
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
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md border border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
          {icon}
        </span>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-slate-950 dark:text-slate-100">{title}</h2>
          {description ? (
            <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

function HeaderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[96px]">
      <p className="text-[11px] font-medium text-slate-400 dark:text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-slate-100">{value}</p>
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
    <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-6 py-8 text-center dark:border-slate-800 dark:bg-slate-900/40">
      <div className="grid h-10 w-10 place-items-center rounded-md border border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
        {icon}
      </div>
      <p className="mt-4 text-base font-semibold text-slate-950 dark:text-slate-100">{title}</p>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
    </div>
  );
}

function DetailRow({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex items-start gap-3 border-t border-slate-100 py-3 first:border-t-0 first:pt-0 last:pb-0 dark:border-slate-800">
      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md border border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
          <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">{value}</p>
        </div>
        {hint ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{hint}</p> : null}
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
    <div className="border-t border-slate-100 py-4 first:border-t-0 first:pt-0 last:pb-0 dark:border-slate-800">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="max-w-full truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
              {formatKnowledgeUnitName(state.knowledge_unit_name, state.knowledge_unit_id)}
            </p>
            <span className={cn("rounded border px-2 py-0.5 text-[11px] font-semibold", tone.badge)}>
              {tone.label}
            </span>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            尝试 {state.total_attempts} 次 · 正确 {state.correct_attempts} 次 · 最近 {formatDateTime(state.last_attempt_at)}
          </p>
        </div>
        <div className="shrink-0 text-left sm:text-right">
          <p className={cn("text-base font-semibold", tone.text)}>{formatPercent(masteryScore)}</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">优先级 {formatPercent(priority)}</p>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <div className="h-1.5 overflow-hidden rounded-sm bg-slate-100 dark:bg-slate-900">
          <div className={cn("h-full", tone.bar)} style={{ width: `${Math.max(4, masteryScore * 100)}%` }} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span>准确率 {accuracy == null ? "--" : formatPercent(accuracy)}</span>
          <span>稳定度 {formatPercent(state.stability_score)}</span>
        </div>
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
  const reason = task.reason ? REASON_LABELS[task.reason] ?? "复习巩固" : "复习巩固";

  return (
    <div className="border-t border-slate-100 py-3 first:border-t-0 first:pt-0 last:pb-0 dark:border-slate-800">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
            {formatKnowledgeUnitName(task.knowledge_unit_name, task.knowledge_unit_id)}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {reason} · {formatDateTime(task.scheduled_at)}
          </p>
        </div>
        <Button size="sm" variant="outline" className="self-start rounded-md" onClick={onComplete} disabled={disabled}>
          完成复习
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
  const attemptedKnowledgeCount = states.filter((state) => state.total_attempts > 0).length;
  const weakStates = [...states]
    .sort((left, right) => {
      const leftMastery = clamp01(left.mastery_score) ?? 0;
      const rightMastery = clamp01(right.mastery_score) ?? 0;
      const leftPriority = clamp01(left.review_priority) ?? 0;
      const rightPriority = clamp01(right.review_priority) ?? 0;
      return leftMastery - rightMastery || rightPriority - leftPriority;
    })
    .slice(0, 8);

  const totalAttempts = states.reduce((sum, state) => sum + state.total_attempts, 0);
  const totalCorrect = states.reduce((sum, state) => sum + state.correct_attempts, 0);
  const overallAccuracy = totalAttempts ? clamp01(totalCorrect / totalAttempts) : null;
  const highestPriority = states.reduce((maxValue, state) => Math.max(maxValue, clamp01(state.review_priority) ?? 0), 0);
  const latestActivityAt = pickLatestTimestamp(
    ...states.map((state) => state.last_attempt_at),
    courseProfile?.generated_at,
    userProfile?.generated_at,
  );
  const health = getProfileHealth(avgMastery, dueReviewCount);
  const recommendedModeLabel = getModeLabel(courseProfile?.recommended_exam_mode);
  const difficultyLabel = getDifficultyLabel(courseProfile?.difficulty_focus);
  const paceLabel = userProfile?.pace_preference === "fast"
    ? "快速推进"
    : userProfile?.pace_preference === "slow"
      ? "稳扎稳打"
      : "稳定推进";
  const questionTypeLabel = formatMappedList(
    courseProfile?.recommended_question_types,
    QUESTION_TYPE_LABELS,
    "单选题 / 简答题",
    "其他题型",
  );
  const dominantModeLabel = userProfile?.dominant_exam_mode ? getModeLabel(userProfile.dominant_exam_mode) : recommendedModeLabel;
  const preferredModeLabel = formatMappedList(
    userProfile?.preferred_exam_modes,
    MODE_LABELS,
    dominantModeLabel,
    "其他模式",
  );
  const localizedNotes = [...(courseProfile?.notes ?? []), ...(userProfile?.notes ?? [])]
    .map(localizeProfileNote)
    .filter((note): note is string => Boolean(note));
  const supplementalNotes = localizedNotes.filter(
    (note) => !/^(薄弱知识点|到期复习|推荐练习模式|推荐题型|难度聚焦|活跃课程|常用练习模式|跨课程到期复习|常练题型)：/.test(note),
  );
  const primaryWeakUnit = weakStates[0]
    ? formatKnowledgeUnitName(weakStates[0].knowledge_unit_name, weakStates[0].knowledge_unit_id)
    : null;
  const reminderItems = [
    weakCount > 0 ? `当前有 ${weakCount} 个薄弱知识点，建议先从优先补强列表的第一项开始。` : "暂时没有明显薄弱点，保持当前练习节奏即可。",
    dueReviewCount > 0 ? `有 ${dueReviewCount} 个复习任务已经到期，建议先清掉再进入新练习。` : "当前没有到期复习任务，可以直接进入推荐练习。",
    `下一轮建议使用${recommendedModeLabel}，难度保持在${difficultyLabel}。`,
    ...supplementalNotes,
  ].slice(0, 4);
  const isMasteryLoading = masteryQuery.isLoading && !mastery;
  const isReviewLoading = reviewsQuery.isLoading && reviewTasks.length === 0;

  if (!courseId) {
    return (
      <div className="min-h-full px-6 pb-8 pt-20 lg:pt-8">
        <div className="mx-auto max-w-5xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少课程标识，暂时无法加载学习画像。
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full px-4 pb-10 pt-20 sm:px-6 lg:px-8 lg:pt-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="py-4">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
                <Brain className="h-3.5 w-3.5 text-indigo-500" />
                学习画像
              </div>
              <h1 className="mt-4 text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                {courseName ? `“${courseName}”的学习画像` : "学习画像"}
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                掌握情况、复习压力和下一步练习建议集中在这里，页面会尽量只保留真正影响行动的信息。
              </p>
              <div className="mt-6 flex flex-wrap gap-x-8 gap-y-3">
                <HeaderMetric label="平均掌握" value={isMasteryLoading ? "--" : formatPercent(avgMastery)} />
                <HeaderMetric label="待复习" value={formatCount(pendingReviewCount, isReviewLoading && !courseProfile && !userProfile)} />
                <HeaderMetric label="薄弱点" value={formatCount(weakCount, isMasteryLoading)} />
                <HeaderMetric label="最近更新" value={formatDateTime(latestActivityAt)} />
              </div>
            </div>

            <div className="flex flex-col items-start gap-3 xl:items-end">
              <span className={cn("inline-flex shrink-0 items-center rounded-md border px-3 py-1.5 text-sm font-semibold", health.className)}>
                {health.label}
              </span>
              <Button
                size="lg"
                className="!h-12 rounded-md bg-black px-6 text-sm font-semibold text-white hover:bg-slate-900 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
                onClick={() => navigate(buildCourseSubPath(courseId, "exams"))}
              >
                开始推荐练习
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>

        {masteryQuery.error || reviewsQuery.error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        ) : null}

        <section className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-8">
            <SectionBlock>
              <SectionHeader
                icon={<Target className="h-4 w-4" />}
                title="掌握概览"
                description={health.hint}
              />

              <div className="mt-6 grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
                <div className="border-l-2 border-indigo-500 pl-4">
                  <p className="text-sm font-medium text-slate-500 dark:text-slate-400">平均掌握度</p>
                  <p className="mt-3 text-4xl font-semibold text-slate-950 dark:text-slate-100">
                    {isMasteryLoading ? "--" : formatPercent(avgMastery)}
                  </p>
                  <div className="mt-4 h-1.5 overflow-hidden rounded-sm bg-slate-100 dark:bg-slate-900">
                    <div
                      className="h-full bg-indigo-500"
                      style={{ width: `${Math.max(4, (clamp01(avgMastery) ?? 0) * 100)}%` }}
                    />
                  </div>
                  <div className="mt-4 space-y-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    <p>已练习 {formatCount(totalAttempts, isMasteryLoading)} 次</p>
                    <p>已覆盖 {formatCount(attemptedKnowledgeCount, isMasteryLoading)} / {formatCount(states.length, isMasteryLoading)} 个知识点</p>
                  </div>
                </div>

                <div className="grid gap-x-8 gap-y-0 sm:grid-cols-2">
                  <DetailRow
                    icon={<Sparkles className="h-4 w-4" />}
                    label="稳定知识点"
                    value={formatCount(highConfidenceCount, isMasteryLoading)}
                    hint={states.length ? `共 ${states.length} 个知识点` : "等待更多练习数据"}
                  />
                  <DetailRow
                    icon={<Gauge className="h-4 w-4" />}
                    label="综合准确率"
                    value={isMasteryLoading ? "--" : formatPercent(overallAccuracy)}
                    hint={totalAttempts ? `基于 ${totalAttempts} 次作答统计` : "还没有可统计的作答记录"}
                  />
                  <DetailRow
                    icon={<Clock3 className="h-4 w-4" />}
                    label="最高复习优先级"
                    value={isMasteryLoading || states.length === 0 ? "--" : formatPercent(highestPriority)}
                    hint={dueReviewCount > 0 ? `${dueReviewCount} 个知识点已到复习时间` : "当前没有到期复习压力"}
                  />
                  <DetailRow
                    icon={<TrendingUp className="h-4 w-4" />}
                    label="最近学习活动"
                    value={formatDateTime(latestActivityAt)}
                    hint={attemptedKnowledgeCount > 0 ? `已练习 ${attemptedKnowledgeCount} 个知识点` : "完成练习后会显示最新记录"}
                  />
                </div>
              </div>
            </SectionBlock>

            <SectionBlock>
              <SectionHeader
                icon={<Sparkles className="h-4 w-4" />}
                title="优先补强"
                description={primaryWeakUnit ? `先从 ${primaryWeakUnit} 开始，最容易把效果做出来。` : "按掌握度和复习优先级排序，先处理最影响成绩的部分。"}
              />

              <div className="mt-5">
                {masteryQuery.isLoading ? (
                  <EmptyState
                    icon={<Loader2 className="h-5 w-5 animate-spin" />}
                    title="正在读取画像"
                    description="正在汇总掌握度、稳定度和复习优先级。"
                  />
                ) : weakStates.length === 0 ? (
                  <EmptyState
                    icon={<Sparkles className="h-5 w-5" />}
                    title="暂时还没有补强项"
                    description="完成几道练习后，这里会自动列出真正需要优先处理的知识点。"
                  />
                ) : (
                  <div>
                    {weakStates.map((state) => (
                      <KnowledgeUnitRow key={state.id} state={state} />
                    ))}
                  </div>
                )}
              </div>
            </SectionBlock>
          </div>

          <aside className="border-t border-slate-200 pt-6 dark:border-slate-800 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0">
            <div className="xl:sticky xl:top-6">
              <SectionHeader
                icon={<Gauge className="h-4 w-4" />}
                title="下一步怎么学"
                description="把画像结果收成一份马上能执行的动作清单。"
              />

              <div className="mt-5">
                <DetailRow
                  icon={<Zap className="h-4 w-4" />}
                  label="建议模式"
                  value={recommendedModeLabel}
                  hint={courseProfile?.recommended_question_count ? `建议先做 ${courseProfile.recommended_question_count} 题` : "先从一轮短练习开始"}
                />
                <DetailRow icon={<ListChecks className="h-4 w-4" />} label="推荐题型" value={questionTypeLabel} />
                <DetailRow icon={<Gauge className="h-4 w-4" />} label="难度聚焦" value={difficultyLabel} />
                <DetailRow icon={<TrendingUp className="h-4 w-4" />} label="学习节奏" value={paceLabel} />
                <DetailRow icon={<Layers3 className="h-4 w-4" />} label="常用模式" value={preferredModeLabel} />
              </div>

              <div className="mt-7 border-t border-slate-200 pt-5 dark:border-slate-800">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-100">
                    <Clock3 className="h-4 w-4 text-slate-400" />
                    待复习
                  </div>
                  <span className="text-sm font-semibold text-slate-500 dark:text-slate-400">
                    {formatCount(pendingReviewCount, isReviewLoading)}
                  </span>
                </div>
                <div className="mt-4">
                  {reviewsQuery.isLoading ? (
                    <EmptyState icon={<RefreshCw className="h-4 w-4 animate-spin" />} title="正在同步" description="马上同步最新安排。" />
                  ) : reviewTasks.length === 0 ? (
                    <EmptyState icon={<CheckCircle2 className="h-4 w-4" />} title="暂无待处理复习" description="继续练习后，系统会按遗忘风险生成复习安排。" />
                  ) : (
                    <div>
                      {reviewTasks.map((task) => (
                        <ReviewTaskRow
                          key={task.id}
                          task={task}
                          onComplete={() => completeReview.mutate({ courseId, taskId: task.id })}
                          disabled={completeReview.isPending}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-7 border-t border-slate-200 pt-5 dark:border-slate-800">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-100">
                  <AlertCircle className="h-4 w-4 text-slate-400" />
                  学习提醒
                </div>
                <div className="mt-4 space-y-3">
                  {reminderItems.map((note, index) => (
                    <p key={`${note}-${index}`} className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {note}
                    </p>
                  ))}
                </div>
              </div>
            </div>
          </aside>
        </section>
      </div>
    </div>
  );
}
