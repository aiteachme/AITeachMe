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
      hint: "完成练习以生成画像",
      className: "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300",
    };
  }
  if (dueReviews > 0 || normalized < 0.55) {
    return {
      label: "需要复习",
      hint: "需处理到期复习和薄弱点",
      className: "border-amber-300 text-amber-700 dark:border-amber-500/40 dark:text-amber-300",
    };
  }
  if (normalized < 0.78) {
    return {
      label: "稳步推进",
      hint: "建议进行混合训练",
      className: "border-indigo-300 text-indigo-700 dark:border-indigo-500/40 dark:text-indigo-300",
    };
  }
  return {
    label: "状态良好",
    hint: "建议进行综合实战练习",
    className: "border-emerald-300 text-emerald-700 dark:border-emerald-500/40 dark:text-emerald-300",
  };
}

function SectionBlock({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-3xl bg-white p-7 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] ring-1 ring-slate-900/5 dark:bg-slate-900/40 dark:ring-slate-800/60", className)}>
      {children}
    </section>
  );
}

function SectionHeader({ title }: { title: string }) {
  return <h2 className="mb-6 text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">{title}</h2>;
}

function MetricCard({ label, value, icon, colorClass = "bg-indigo-50 text-indigo-500 dark:bg-indigo-500/10 dark:text-indigo-400" }: { label: string; value: string; icon?: ReactNode; colorClass?: string }) {
  return (
    <div className="group flex flex-col rounded-2xl border border-slate-200/60 bg-slate-50/50 p-5 transition-all hover:border-slate-300/80 hover:bg-white hover:shadow-sm dark:border-slate-800/60 dark:bg-slate-900/30 dark:hover:bg-slate-900/60">
      <div className="flex items-center gap-3">
        {icon && (
          <div className={cn("grid h-8 w-8 place-items-center rounded-lg ring-1 ring-black/5 dark:ring-white/10", colorClass)}>
            {icon}
          </div>
        )}
        <p className="text-sm font-medium text-slate-600 dark:text-slate-400 group-hover:text-slate-900 dark:group-hover:text-slate-200 transition-colors">{label}</p>
      </div>
      <p className="mt-4 text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">{value}</p>
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
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-6 py-10 text-center dark:border-slate-800 dark:bg-slate-900/40">
      <div className="text-slate-400 dark:text-slate-500">{icon}</div>
      <p className="mt-3 text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{description}</p>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-100 last:border-0 dark:border-slate-800/50">
      <span className="text-sm text-slate-600 dark:text-slate-400">{label}</span>
      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate ml-4 rounded-md bg-slate-100 px-2.5 py-1 dark:bg-slate-800/60">{value}</span>
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
    weakCount > 0 ? `发现 ${weakCount} 个薄弱点，建议优先补强。` : "暂无明显薄弱点。",
    dueReviewCount > 0 ? `有 ${dueReviewCount} 个复习已到期，建议优先完成。` : "当前无到期复习任务。",
    `建议下一轮：${recommendedModeLabel}（${difficultyLabel}难度）。`,
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
    <div className="mx-auto max-w-7xl min-h-full px-4 pb-24 pt-8 sm:px-6 lg:px-8 lg:pt-10">
      <div className="flex flex-col gap-8">
        <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 sm:text-4xl">
              {courseName ?? "学习画像"}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm font-medium text-slate-500">
              <span className="flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400">
                <Target className="h-4 w-4" /> 掌握度 {isMasteryLoading ? "--" : formatPercent(avgMastery)}
              </span>
              <span className="h-1 w-1 rounded-full bg-slate-300 dark:bg-slate-700" />
              <span>待复习 {formatCount(pendingReviewCount, isReviewLoading)}</span>
              <span className="h-1 w-1 rounded-full bg-slate-300 dark:bg-slate-700" />
              <span>薄弱点 {formatCount(weakCount, isMasteryLoading)}</span>
            </div>
          </div>
          
          <Button
            size="lg"
            className="!h-11 rounded-full px-6 font-semibold shadow-[0_2px_10px_-4px_rgba(0,0,0,0.2)] dark:shadow-[0_2px_10px_-4px_rgba(255,255,255,0.2)]"
            onClick={() => navigate(buildCourseSubPath(courseId, "exams"))}
          >
            开始练习
            <ArrowRight className="h-4 w-4" />
          </Button>
        </section>

        {reminderItems.length > 0 && (
          <div className="flex items-center gap-3 rounded-2xl bg-indigo-50 px-5 py-3.5 text-sm font-medium text-indigo-900 dark:bg-indigo-500/10 dark:text-indigo-200">
            <Sparkles className="h-4 w-4 shrink-0 text-indigo-500" />
            <span className="truncate">{reminderItems[0]}</span>
          </div>
        )}

        <div className="grid gap-8 lg:grid-cols-[1fr_320px] xl:grid-cols-[1fr_360px]">
          <div className="space-y-8">
            <SectionBlock>
              <SectionHeader title="核心指标" />
              <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <MetricCard 
                  label="准确率" 
                  value={isMasteryLoading ? "--" : formatPercent(overallAccuracy)} 
                  icon={<Target className="h-4 w-4" />}
                  colorClass="bg-blue-50 text-blue-500 dark:bg-blue-500/10 dark:text-blue-400"
                />
                <MetricCard 
                  label="稳定知识点" 
                  value={formatCount(highConfidenceCount, isMasteryLoading)} 
                  icon={<Sparkles className="h-4 w-4" />}
                  colorClass="bg-amber-50 text-amber-500 dark:bg-amber-500/10 dark:text-amber-400"
                />
                <MetricCard 
                  label="复习压力" 
                  value={dueReviewCount > 0 ? "高" : "低"} 
                  icon={<Clock3 className="h-4 w-4" />}
                  colorClass="bg-rose-50 text-rose-500 dark:bg-rose-500/10 dark:text-rose-400"
                />
                <MetricCard 
                  label="覆盖率" 
                  value={`${attemptedKnowledgeCount}/${states.length}`} 
                  icon={<Layers3 className="h-4 w-4" />}
                  colorClass="bg-emerald-50 text-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-400"
                />
              </div>
            </SectionBlock>

            <SectionBlock>
              <SectionHeader title="优先攻克" />
              <div className="mt-5">
                {masteryQuery.isLoading ? (
                  <EmptyState icon={<Loader2 className="h-5 w-5 animate-spin" />} title="正在分析数据" description="..." />
                ) : weakStates.length === 0 ? (
                  <EmptyState icon={<Sparkles className="h-5 w-5" />} title="状态良好" description="暂无优先补强项" />
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

          <aside className="space-y-8">
            <SectionBlock className="!p-5">
              <SectionHeader title="练习建议" />
              <div className="mt-4 space-y-1">
                <DetailRow label="模式" value={recommendedModeLabel} />
                <DetailRow label="题型" value={questionTypeLabel} />
                <DetailRow label="难度" value={difficultyLabel} />
              </div>
            </SectionBlock>
            
            <SectionBlock className="!p-5">
              <SectionHeader title="待复习" />
              <div className="mt-4">
                {reviewsQuery.isLoading ? (
                  <EmptyState icon={<RefreshCw className="h-4 w-4 animate-spin" />} title="同步中" description="..." />
                ) : reviewTasks.length === 0 ? (
                  <EmptyState icon={<CheckCircle2 className="h-4 w-4" />} title="暂无任务" description="无待复习项" />
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
            </SectionBlock>
          </aside>
        </div>
      </div>
    </div>
  );
}
