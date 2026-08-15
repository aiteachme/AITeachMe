import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Gauge,
  Loader2,
  MessageCircle,
  Sparkles,
  Target,
  Trophy,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
} from "../api/generated/exams";
import {
  getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey,
  getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey,
  getStudyPlanApiV1CoursesCourseIdProfileStudyPlanGetQueryKey,
  useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost,
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
  useStudyPlanApiV1CoursesCourseIdProfileStudyPlanGet,
} from "../api/generated/profile";
import type {
  ExamHistoryItem,
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
  StudyPlanStepResponse,
} from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import {
  AccuracyRows,
  MasteryDistribution,
  PreferenceRow,
  average,
  buildNoteText,
  clamp01,
  formatDateTime,
  formatPercent,
  formatToken,
  isReviewDueSoon,
  masteryTone,
} from "../components/profile";
import {
  COURSE_PAGE_CONTENT_CLASS,
  COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS,
  COURSE_PAGE_SHELL_CLASS,
  CoursePageHeader,
} from "../components/course/CoursePageHeader";
import { buildExamTitle } from "../components/exams";
import { formatModeLabel } from "../components/exams/examDisplay";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import {
  buildCoursePath,
  buildCourseSubPath,
} from "../lib/courseNavigation";
import {
  buildLearningActivityEvents,
  formatLearningActivityKind,
  formatLearningActivityTime,
  getLatestLearningActivity,
} from "../lib/learningActivity";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { cn } from "../lib/utils";

const pageShellClass = COURSE_PAGE_SHELL_CLASS;
const PROFILE_PROMPT_STORAGE_PREFIX = "aiteachme.profile.userPrompt.v1";

function getKnowledgeUnitName(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">) {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

function sortByNewestTimestamp<T>(items: T[], getTimestamp: (item: T) => string | null | undefined) {
  return [...items].sort((left, right) =>
    new Date(getTimestamp(right) ?? 0).getTime() - new Date(getTimestamp(left) ?? 0).getTime(),
  );
}

function getProfilePromptStorageKey(courseId: string) {
  return `${PROFILE_PROMPT_STORAGE_PREFIX}.${courseId}`;
}

function readProfilePrompt(courseId?: string): string {
  if (!courseId || typeof window === "undefined") {
    return "";
  }
  try {
    return window.localStorage.getItem(getProfilePromptStorageKey(courseId)) ?? "";
  } catch {
    return "";
  }
}

function saveProfilePrompt(courseId: string | undefined, value: string) {
  if (!courseId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(getProfilePromptStorageKey(courseId), value);
  } catch {
    // Local prompt notes are optional; storage failures should not block the page.
  }
}

function getPlanTimeLabel(index: number): string {
  return ["先看", "再练", "复盘", "补充"][index] ?? "安排";
}

function getPaperScoreText(item: ExamHistoryItem): string {
  if (item.status === "graded" && item.score_obtained != null && item.total_score != null) {
    return `${item.score_obtained}/${item.total_score} 分`;
  }
  return `${item.total_items} 题`;
}

function SectionHeading({
  icon,
  title,
  detail,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-3 dark:border-slate-800">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-950 dark:text-slate-100">
          <span className="text-slate-400 dark:text-slate-500">{icon}</span>
          {title}
        </h2>
        {detail ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</p> : null}
      </div>
      {action}
    </div>
  );
}

function EmptyBlock({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-5 py-8 text-center dark:border-slate-800 dark:bg-slate-900/30">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-500">
        {icon}
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</p>
      <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
  );
}

function SummaryMetric({
  label,
  value,
  hint,
  icon,
  tone = "slate",
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  tone?: "indigo" | "emerald" | "rose" | "slate";
}) {
  const toneClass = {
    indigo: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300",
    emerald: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
    slate: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300",
  }[tone];

  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{label}</p>
          <p className="mt-1 text-2xl font-black tabular-nums text-slate-950 dark:text-slate-50">{value}</p>
        </div>
        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", toneClass)}>
          {icon}
        </span>
      </div>
      <p className="mt-3 truncate text-xs text-slate-500 dark:text-slate-400">{hint}</p>
    </div>
  );
}

function WeakSpotSummary({
  states,
}: {
  states: MasteryStateResponse[];
}) {
  const previewStates = states.slice(0, 3);

  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">优先补哪里</p>
          <p className="mt-1 text-sm font-bold text-slate-950 dark:text-slate-50">
            {previewStates.length ? "先看这几个知识点" : "还没有明确要补的点"}
          </p>
        </div>
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
          <Target className="h-5 w-5" />
        </span>
      </div>

      {previewStates.length ? (
        <div className="mt-3 space-y-2">
          {previewStates.map((state) => {
            const score = clamp01(state.mastery_score);
            return (
              <div key={state.id} className="flex items-center justify-between gap-3 border-t border-slate-100 py-2 first:border-t-0 dark:border-slate-800">
                <span className="min-w-0 truncate text-xs font-semibold text-slate-700 dark:text-slate-300">
                  {getKnowledgeUnitName(state)}
                </span>
                <span className="shrink-0 text-xs font-black tabular-nums text-rose-600 dark:text-rose-300">
                  {formatPercent(score)}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          完成一次练习后，系统会把需要优先补的知识点排出来。
        </p>
      )}

      <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
        {previewStates.length
          ? "下方「知识点掌握」会按优先级展开。"
          : "暂无可诊断的薄弱范围。"}
      </p>
    </div>
  );
}

function ProfileUnavailable({
  message,
  onOpenKnowledgeDocs,
  onOpenExams,
}: {
  message: string;
  onOpenKnowledgeDocs: () => void;
  onOpenExams: () => void;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-950/75">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs font-bold text-slate-500 dark:text-slate-400">
            <BarChart3 className="h-4 w-4" />
            课程画像
          </p>
          <h2 className="mt-3 text-2xl font-black tracking-normal text-slate-950 dark:text-slate-50">
            画像数据暂时不可用
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-400">
            {message} 系统不会基于缺失数据生成学习建议。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onOpenKnowledgeDocs}
            className="h-10 rounded-lg bg-white px-4 text-sm font-semibold dark:bg-slate-950"
          >
            <BookOpen className="h-4 w-4" />
            回看知识库
          </Button>
          <Button
            type="button"
            onClick={onOpenExams}
            className="h-10 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
          >
            <FileText className="h-4 w-4" />
            去练习中心
          </Button>
        </div>
      </div>
    </section>
  );
}

function NextStepPanel({
  title,
  detail,
  courseProfile,
  focusStates,
  dueReviewCount,
  onOpenExams,
}: {
  title: string;
  detail: string;
  courseProfile: MasteryOverviewResponse["course_profile"];
  focusStates: MasteryStateResponse[];
  dueReviewCount: number;
  onOpenExams: () => void;
}) {
  const questionTypes = courseProfile?.recommended_question_types?.slice(0, 3) ?? [];
  const suggestedCount = courseProfile?.recommended_question_count ?? 8;
  const previewStates = focusStates.slice(0, 3);

  return (
    <section className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950/75 sm:p-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs font-bold text-indigo-600 dark:text-indigo-300">
            <Sparkles className="h-4 w-4" />
            下一步建议
          </p>
          <h2 className="mt-3 text-2xl font-black leading-tight tracking-normal text-slate-950 dark:text-slate-50">
            {title}
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-400">{detail}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            onClick={onOpenExams}
            className="h-10 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
          >
            <FileText className="h-4 w-4" />
            去练习中心
          </Button>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {formatToken(courseProfile?.recommended_exam_mode, "网页练习")}
        </span>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          约 {suggestedCount} 题
        </span>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {formatToken(courseProfile?.difficulty_focus, "中等")}难度
        </span>
        {questionTypes.map((type) => (
          <span key={type} className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
            {formatToken(type)}
          </span>
        ))}
      </div>

      {previewStates.length ? (
        <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
          <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">优先补的知识点</p>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            {previewStates.map((state) => (
              <div key={state.id} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900/50">
                <p className="truncate text-xs font-bold text-slate-800 dark:text-slate-200">
                  {getKnowledgeUnitName(state)}
                </p>
                <p className="mt-1 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                  掌握 {formatPercent(state.mastery_score)}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            完整排序在下方「知识点掌握」中查看。
          </p>
        </div>
      ) : null}

      <div className="mt-auto grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
        <div>
          <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">复习提醒</p>
          <p className="mt-1 text-lg font-black tabular-nums text-slate-950 dark:text-slate-50">{dueReviewCount}</p>
        </div>
        <div>
          <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">建议题量</p>
          <p className="mt-1 text-lg font-black tabular-nums text-slate-950 dark:text-slate-50">{suggestedCount}</p>
        </div>
      </div>
    </section>
  );
}

function LearningPlan({
  planItems,
}: {
  planItems: Array<{ key: string; label: string; title: string; detail: string }>;
}) {
  if (!planItems.length) {
    return null;
  }

  return (
    <section className="border-t border-slate-200 py-6 dark:border-slate-800">
      <SectionHeading
        icon={<CalendarClock className="h-4 w-4" />}
        title="今日行动"
        detail="按定位、练习、复盘排好顺序。"
      />
      <ol className="mt-4 space-y-3">
        {planItems.slice(0, 4).map((item, index) => (
          <li key={item.key} className="grid gap-3 border-b border-slate-100 px-1 py-3 last:border-b-0 dark:border-slate-800 sm:grid-cols-[5rem_minmax(0,1fr)]">
            <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-slate-100 text-[11px] font-black tabular-nums text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="text-xs font-bold text-slate-500 dark:text-slate-400">{item.label}</span>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-950 dark:text-slate-100">{item.title}</p>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{item.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function RecentPaperRow({
  item,
  onOpen,
}: {
  item: ExamHistoryItem;
  onOpen: () => void;
}) {
  const isGenerating = item.status === "generating";
  const dotColor = item.status === "graded"
    ? "bg-emerald-500"
    : isGenerating
      ? "bg-indigo-500"
      : item.status === "failed"
        ? "bg-rose-500"
        : "bg-amber-500";

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full items-center justify-between gap-4 rounded-lg px-3 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", dotColor, isGenerating && "animate-pulse")} />
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{buildExamTitle(item)}</p>
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {formatModeLabel(item.exam_mode)} · {formatDateTime(item.created_at)} · {getPaperScoreText(item)}
        </p>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-indigo-500" />
    </button>
  );
}

function FocusStateRow({ state }: { state: MasteryStateResponse }) {
  const score = clamp01(state.mastery_score);
  const tone = masteryTone(score);
  const accuracy = state.total_attempts > 0 ? state.correct_attempts / state.total_attempts : null;

  return (
    <div className="border-b border-slate-100 px-1 py-3 last:border-b-0 dark:border-slate-800">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{getKnowledgeUnitName(state)}</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {formatToken(state.knowledge_unit_type, "知识点")} · 正确 {state.correct_attempts}/{state.total_attempts} · 稳定度 {formatPercent(state.stability_score)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <span className={cn("text-sm font-black tabular-nums", tone.text)}>{formatPercent(score)}</span>
          <p className="mt-1 text-[11px] font-semibold text-slate-400 dark:text-slate-500">
            {accuracy == null ? "暂无作答" : `正确率 ${formatPercent(accuracy)}`}
          </p>
        </div>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.max(4, score * 100)}%` }} />
      </div>
    </div>
  );
}

function ReviewTaskRow({
  task,
  onOpenSourceExam,
  onComplete,
  isCompleting,
  completed = false,
}: {
  task: ReviewTaskResponse;
  onOpenSourceExam: (paperId: number) => void;
  onComplete?: () => void;
  isCompleting: boolean;
  completed?: boolean;
}) {
  const dueSoon = !completed && isReviewDueSoon(task);

  return (
    <div className={cn(
      "border-b px-1 py-3 last:border-b-0",
      completed
        ? "border-emerald-100 dark:border-emerald-500/20"
        : "border-slate-100 dark:border-slate-800",
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
            </p>
            {dueSoon ? (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                优先
              </span>
            ) : null}
            {completed ? (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                已完成
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {formatToken(task.knowledge_unit_type, "知识点")} · {formatDateTime(task.scheduled_at)}
          </p>
        </div>
        {completed ? (
          <span className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-emerald-200 bg-white px-3 text-xs font-semibold text-emerald-700 dark:border-emerald-500/20 dark:bg-slate-950 dark:text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            已完成
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onComplete}
            disabled={isCompleting}
            className="h-8 shrink-0 rounded-lg px-3 text-xs"
          >
            标记完成
          </Button>
        )}
      </div>
      {completed ? (
        <p className="mt-3 text-xs leading-5 text-emerald-700 dark:text-emerald-300">
          已记录到本轮复习，后续画像会按新的练习结果重新排序。
        </p>
      ) : null}
      {task.source_exam_paper_id ? (
        <button
          type="button"
          onClick={() => onOpenSourceExam(task.source_exam_paper_id as number)}
          className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-slate-500 transition hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-300"
        >
          查看来源试卷
          <ArrowRight className="h-3 w-3" />
        </button>
      ) : null}
    </div>
  );
}

export function ProfilePage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { courseName } = useCourseDisplayName(courseId);

  const [isProfileExpanded, setIsProfileExpanded] = useState(false);
  const [recentlyCompletedReviews, setRecentlyCompletedReviews] = useState<ReviewTaskResponse[]>([]);
  const [profilePromptState, setProfilePromptState] = useState(() => ({
    courseId: courseId ?? "",
    value: readProfilePrompt(courseId),
  }));
  const profilePrompt = profilePromptState.courseId === (courseId ?? "") ? profilePromptState.value : "";

  useEffect(() => {
    setRecentlyCompletedReviews([]);
    setProfilePromptState({
      courseId: courseId ?? "",
      value: readProfilePrompt(courseId),
    });
  }, [courseId]);

  useEffect(() => {
    if (profilePromptState.courseId !== (courseId ?? "")) {
      return;
    }
    saveProfilePrompt(courseId, profilePromptState.value);
  }, [courseId, profilePromptState]);

  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(
    courseId ?? "",
    { page: 1, size: 8 },
    { query: { enabled: Boolean(courseId) } },
  );
  const masteryQuery = useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } },
  );
  const reviewsQuery = useReviewTasksApiV1CoursesCourseIdProfileReviewsGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } },
  );
  const studyPlanQuery = useStudyPlanApiV1CoursesCourseIdProfileStudyPlanGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } },
  );

  const historyItems = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data)?.items ?? [],
    [historyQuery.data],
  );
  const mastery = useMemo<MasteryOverviewResponse | null>(
    () => unwrapOrvalResponse<MasteryOverviewResponse>(masteryQuery.data),
    [masteryQuery.data],
  );
  const reviewTasks = useMemo<ReviewTaskResponse[]>(
    () => unwrapOrvalResponse<ReviewTaskResponse[]>(reviewsQuery.data) ?? [],
    [reviewsQuery.data],
  );
  const studyPlan = useMemo<StudyPlanStepResponse[]>(
    () => unwrapOrvalResponse<StudyPlanStepResponse[]>(studyPlanQuery.data) ?? [],
    [studyPlanQuery.data],
  );

  const reviewTaskById = useMemo(() => new Map(reviewTasks.map((task) => [task.id, task])), [reviewTasks]);
  const pendingReviewTaskIds = useMemo(() => new Set(reviewTasks.map((task) => task.id)), [reviewTasks]);
  const visibleCompletedReviews = useMemo(
    () => recentlyCompletedReviews.filter((task) => !pendingReviewTaskIds.has(task.id)).slice(0, 3),
    [pendingReviewTaskIds, recentlyCompletedReviews],
  );

  const completeReview = useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost({
    mutation: {
      onSuccess: async (response, variables) => {
        if (!courseId) return;
        const completedTask =
          unwrapOrvalResponse<ReviewTaskResponse>(response) ?? reviewTaskById.get(variables.taskId);
        if (completedTask) {
          setRecentlyCompletedReviews((current) => [
            completedTask,
            ...current.filter((task) => task.id !== completedTask.id),
          ].slice(0, 3));
        }
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey(courseId),
          }),
          queryClient.invalidateQueries({
            queryKey: getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey(courseId),
          }),
          queryClient.invalidateQueries({
            queryKey: getStudyPlanApiV1CoursesCourseIdProfileStudyPlanGetQueryKey(courseId),
          }),
        ]);
        toast({
          title: "已完成复习任务",
          description: "已保留在本轮完成记录中，课程画像会同步刷新。",
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

  const courseProfile = mastery?.course_profile;
  const userProfile = mastery?.user_profile;
  const states = mastery?.knowledge_unit_states ?? [];

  const totalAttempts = useMemo(() => states.reduce((sum, state) => sum + state.total_attempts, 0), [states]);
  const correctAttempts = useMemo(() => states.reduce((sum, state) => sum + state.correct_attempts, 0), [states]);
  const attemptAccuracy = useMemo(() => totalAttempts > 0 ? correctAttempts / totalAttempts : null, [totalAttempts, correctAttempts]);
  const avgStability = useMemo(() => average(states.map((state) => state.stability_score)), [states]);

  const profileNotes = useMemo(() => Array.from(new Set([
    ...(courseProfile?.notes ?? []),
    ...(userProfile?.notes ?? []),
  ].map(buildNoteText))), [courseProfile?.notes, userProfile?.notes]);
  const conversationNotes = useMemo(() => profileNotes
    .filter((note) => /^(近期对话|对话偏好|资料使用|学习意图)：/.test(note))
    .slice(0, 3), [profileNotes]);
  const visibleProfileNotes = useMemo(() => profileNotes
    .filter((note) => !/：\s*(一|二)项$/.test(note) && !conversationNotes.includes(note))
    .slice(0, 4), [profileNotes, conversationNotes]);

  const latestPapers = useMemo(
    () => sortByNewestTimestamp(historyItems, (item) => item.created_at).slice(0, 5),
    [historyItems],
  );
  const learningActivityEvents = useMemo(
    () => buildLearningActivityEvents({ exams: historyItems, masteryStates: states }),
    [historyItems, states],
  );
  const latestLearningActivity = useMemo(
    () => getLatestLearningActivity(learningActivityEvents),
    [learningActivityEvents],
  );

  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;
  const focusUnitIds = useMemo(
    () => new Set(courseProfile?.focus_knowledge_unit_ids ?? []),
    [courseProfile?.focus_knowledge_unit_ids],
  );

  const focusStates = useMemo(
    () =>
      [...states]
        .sort((left, right) =>
          Number(focusUnitIds.has(right.knowledge_unit_id)) - Number(focusUnitIds.has(left.knowledge_unit_id)) ||
          left.mastery_score - right.mastery_score ||
          right.review_priority - left.review_priority,
        )
        .slice(0, 5),
    [focusUnitIds, states],
  );

  const topReviewTasks = useMemo(
    () => [...reviewTasks].sort((left, right) => right.priority - left.priority).slice(0, 4),
    [reviewTasks],
  );

  const latestLearningTitle = latestLearningActivity
    ? latestLearningActivity.label
    : topReviewTasks[0]
      ? topReviewTasks[0].knowledge_unit_name?.trim() || `知识点 #${topReviewTasks[0].knowledge_unit_id}`
      : "暂无最近学习";
  const latestLearningDetail = latestLearningActivity
    ? `${formatLearningActivityKind(latestLearningActivity.kind)} · ${formatLearningActivityTime(latestLearningActivity.occurredAt)}`
    : topReviewTasks[0]
      ? `复习建议 · ${formatDateTime(topReviewTasks[0].scheduled_at)}`
      : "完成一次练习后，系统会自动更新画像。";
  const smartRecommendationTitle = topReviewTasks[0]
    ? `先回顾：${topReviewTasks[0].knowledge_unit_name?.trim() || `知识点 #${topReviewTasks[0].knowledge_unit_id}`}`
    : focusStates[0]
      ? `优先突破：${getKnowledgeUnitName(focusStates[0])}`
      : "先做一次短测验";
  const smartRecommendationDetail = topReviewTasks[0]
    ? "这个知识点最近需要回顾，先看掌握记录和来源试卷，再决定是否进入练习中心。"
    : focusStates[0]
      ? `当前掌握度 ${formatPercent(focusStates[0].mastery_score)}，建议先回看相关讲义，再做一轮短练习。`
      : "系统还需要更多测验或练习数据，才能判断优先补哪里。";

  const openPracticeCenter = () => {
    if (!courseId) {
      return;
    }
    navigate(buildCoursePath(courseId, "exams"));
  };

  const planItems = useMemo(() => {
    const labelByKey: Record<string, string> = {
      locate: "定位",
      review: "复习",
      practice: "练习",
      reflect: "复盘",
    };
    const dueTasks = reviewTasks.filter(isReviewDueSoon);
    const weakStates = [...states]
      .sort((left, right) => left.mastery_score - right.mastery_score || right.review_priority - left.review_priority)
      .slice(0, 3);
    const focusNamesPlan = weakStates
      .map(getKnowledgeUnitName)
      .slice(0, 2)
      .join("、");
    const qTypes = courseProfile?.recommended_question_types?.slice(0, 2).map((item) => formatToken(item)).join("、");

    const fallbackPlanItems = [
      {
        key: "locate",
        label: "定位",
        title: dueTasks.length ? "先处理到期复习" : "确认今天的薄弱范围",
        detail: dueTasks.length
          ? `优先完成 ${Math.min(dueTasks.length, 3)} 个复习任务，避免遗忘继续扩大。`
          : focusNamesPlan
            ? `先看 ${focusNamesPlan}，确认这些点是否真的理解。`
            : "先做一次短练习，让系统拿到可诊断的数据。",
      },
      {
        key: "practice",
        label: "练习",
        title: "做一轮画像练习",
        detail: `${formatToken(courseProfile?.recommended_exam_mode, "网页练习")} · 约 ${courseProfile?.recommended_question_count ?? 10} 题 · ${formatToken(courseProfile?.difficulty_focus, "中等")}难度${qTypes ? ` · ${qTypes}` : ""}。`,
      },
      {
        key: "reflect",
        label: "复盘",
        title: "把错题带回知识库",
        detail: "练完后先看错因，再回到讲义对应位置，补掉定义、条件或步骤上的缺口。",
      },
    ];

    return studyPlan?.length
      ? studyPlan.map((item, index) => ({
        key: item.key,
        label: labelByKey[item.key] ?? getPlanTimeLabel(index),
        title: item.title,
        detail: item.detail,
      }))
      : fallbackPlanItems;
  }, [studyPlan, reviewTasks, states, courseProfile]);

  if (!courseId) {
    return (
      <div className={cn(pageShellClass, "pt-8")}>
        <div className="mx-auto max-w-5xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          缺少课程标识，暂时无法加载课程画像。
        </div>
      </div>
    );
  }

  const isLoading = historyQuery.isLoading || masteryQuery.isLoading || reviewsQuery.isLoading;
  const hasCriticalProfileError = Boolean(masteryQuery.error);

  return (
    <div className={pageShellClass}>
      <div className={`${COURSE_PAGE_CONTENT_CLASS} gap-5`}>
        <CoursePageHeader
          title={courseName ?? "当前课程"}
          description="用测验、复习和知识点掌握记录，判断现在最该补哪里。"
          actions={
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
                className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}
              >
                <BookOpen className="h-4 w-4 shrink-0" />
                看知识库
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "exams"))}
                className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}
              >
                <FileText className="h-4 w-4 shrink-0" />
                练习中心
              </Button>
            </>
          }
        />

        {reviewsQuery.error && !hasCriticalProfileError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(reviewsQuery.error, "复习任务加载失败，请重试。")}
          </div>
        )}

        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        ) : hasCriticalProfileError ? (
          <ProfileUnavailable
            message={getApiErrorMessage(masteryQuery.error, "课程画像数据加载失败，请重试。")}
            onOpenKnowledgeDocs={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
            onOpenExams={() => navigate(buildCoursePath(courseId, "exams"))}
          />
        ) : (
          <>
            <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.55fr)]">
              <NextStepPanel
                title={smartRecommendationTitle}
                detail={smartRecommendationDetail}
                courseProfile={courseProfile}
                focusStates={focusStates}
                dueReviewCount={dueReviewCount}
                onOpenExams={openPracticeCenter}
              />

              <section className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/70">
                <div className="border-b border-r border-slate-200 dark:border-slate-800">
                  <SummaryMetric
                    label="平均掌握"
                    value={formatPercent(courseProfile?.avg_mastery)}
                    hint="按已诊断记录统计"
                    icon={<Gauge className="h-5 w-5" />}
                    tone="indigo"
                  />
                </div>
                <div className="border-b border-slate-200 dark:border-slate-800">
                  <SummaryMetric
                    label="做题正确"
                    value={formatPercent(attemptAccuracy)}
                    hint={`${totalAttempts} 次作答`}
                    icon={<Trophy className="h-5 w-5" />}
                    tone="emerald"
                  />
                </div>
                <div className="col-span-2 border-b border-slate-200 dark:border-slate-800">
                  <WeakSpotSummary states={focusStates} />
                </div>
                <div className="col-span-2">
                  <SummaryMetric
                    label="复习提醒"
                    value={String(dueReviewCount)}
                    hint="需要回顾的知识点"
                    icon={<CalendarClock className="h-5 w-5" />}
                    tone={dueReviewCount > 0 ? "rose" : "slate"}
                  />
                </div>
              </section>
            </div>

            <div id="profile-mastery-section" className="grid scroll-mt-24 gap-4 xl:grid-cols-2">
              <section className="border-t border-slate-200 py-6 dark:border-slate-800">
                <SectionHeading
                  icon={<Target className="h-4 w-4" />}
                  title="知识点掌握"
                  detail="按掌握度、复习优先级和课程重点排序。"
                  action={
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
                      className="h-8 rounded-lg px-3 text-xs"
                    >
                      <BookOpen className="h-3.5 w-3.5" />
                      看知识库
                    </Button>
                  }
                />
                <div className="mt-4">
                  {focusStates.length ? (
                    focusStates.map((state) => <FocusStateRow key={state.id} state={state} />)
                  ) : (
                    <EmptyBlock
                      icon={<Target className="h-5 w-5" />}
                      title="还没有掌握度判断"
                      detail="完成一次练习后，系统会根据作答更新每个知识点的掌握度。"
                    />
                  )}
                </div>
              </section>

              <section className="border-t border-slate-200 py-6 dark:border-slate-800">
                <SectionHeading
                  icon={<CalendarClock className="h-4 w-4" />}
                  title="复习安排"
                  detail="需要回顾和刚完成的任务会保留在这里。"
                />
                <div className="mt-4">
                  {topReviewTasks.length ? (
                    <>
                      {topReviewTasks.map((task) => (
                        <ReviewTaskRow
                          key={task.id}
                          task={task}
                          onOpenSourceExam={(paperId) => navigate(buildCourseSubPath(courseId, "exams", paperId))}
                          onComplete={() => completeReview.mutate({ courseId, taskId: task.id })}
                          isCompleting={completeReview.isPending}
                        />
                      ))}
                      {visibleCompletedReviews.length > 0 ? (
                        visibleCompletedReviews.map((task) => (
                          <ReviewTaskRow
                            key={`completed-${task.id}`}
                            task={task}
                            onOpenSourceExam={(paperId) => navigate(buildCourseSubPath(courseId, "exams", paperId))}
                            isCompleting={false}
                            completed
                          />
                        ))
                      ) : null}
                    </>
                  ) : visibleCompletedReviews.length ? (
                    visibleCompletedReviews.map((task) => (
                      <ReviewTaskRow
                        key={`completed-${task.id}`}
                        task={task}
                        onOpenSourceExam={(paperId) => navigate(buildCourseSubPath(courseId, "exams", paperId))}
                        isCompleting={false}
                        completed
                      />
                    ))
                  ) : (
                    <EmptyBlock
                      icon={<CheckCircle2 className="h-5 w-5" />}
                      title="暂无待办"
                      detail="当前没有到期复习任务，继续保持练习节奏。"
                    />
                  )}
                </div>
              </section>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
              <LearningPlan planItems={planItems} />

              <section className="border-t border-slate-200 py-6 dark:border-slate-800">
                <SectionHeading
                  icon={<FileText className="h-4 w-4" />}
                  title="最近测验"
                  detail={latestLearningTitle ? `${latestLearningTitle} · ${latestLearningDetail}` : undefined}
                  action={(
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate(buildCoursePath(courseId, "exams"))}
                      className="h-8 px-2 text-xs"
                    >
                      全部
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  )}
                />
                <div className="mt-3 space-y-1">
                  {latestPapers.length ? (
                    latestPapers.map((item) => (
                      <RecentPaperRow
                        key={item.id}
                        item={item}
                        onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                      />
                    ))
                  ) : (
                    <EmptyBlock
                      icon={<FileText className="h-5 w-5" />}
                      title="暂无测验记录"
                      detail="完成一次测验后，这里会显示分数和进入入口。"
                    />
                  )}
                </div>
              </section>
            </div>

            <section className="border-y border-slate-200 dark:border-slate-800">
              <button
                type="button"
                onClick={() => setIsProfileExpanded(!isProfileExpanded)}
                className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-sm font-bold text-slate-950 transition hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60"
              >
                <span className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-slate-400" />
                  更多画像细节
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-slate-500 dark:text-slate-400">
                  {isProfileExpanded ? "收起" : "展开"}
                  {isProfileExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </span>
              </button>

              {isProfileExpanded ? (
                <div className="grid gap-4 border-t border-slate-200 p-5 dark:border-slate-800 lg:grid-cols-3">
                  <div className="rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                    <p className="text-sm font-bold text-slate-950 dark:text-slate-100">掌握分布</p>
                    <MasteryDistribution states={states} />
                    <p className="mt-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      稳定度 {formatPercent(avgStability)}，作为遗忘风险参考，不作为首要判断。
                    </p>
                  </div>

                  <div className="space-y-4 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                    <AccuracyRows
                      title="题型正确率"
                      values={courseProfile?.question_type_accuracy}
                      emptyText="暂无题型表现数据。"
                    />
                    <AccuracyRows
                      title="难度正确率"
                      values={courseProfile?.difficulty_accuracy}
                      emptyText="暂无难度表现数据。"
                    />
                  </div>

                  <div className="space-y-3 rounded-lg border border-slate-100 p-4 dark:border-slate-800">
                    <p className="text-sm font-bold text-slate-950 dark:text-slate-100">偏好与备注</p>
                    <label className="block">
                      <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">我的学习偏好</span>
                      <textarea
                        value={profilePrompt}
                        onChange={(event) =>
                          setProfilePromptState({
                            courseId: courseId ?? "",
                            value: event.target.value,
                          })
                        }
                        rows={3}
                        maxLength={600}
                        placeholder="例如：先看例题再总结规律，多提醒易错点。"
                        className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-200 dark:placeholder:text-slate-600 dark:focus:border-indigo-500/40 dark:focus:bg-slate-950 dark:focus:ring-indigo-500/10"
                      />
                    </label>
                    <PreferenceRow
                      label="推荐题型"
                      value={courseProfile?.recommended_question_types?.map((item) => formatToken(item)).join("、") || "单选题、简答题"}
                      icon={<Target className="h-4 w-4" />}
                    />
                    <PreferenceRow
                      label="讲解风格"
                      value={formatToken(userProfile?.explanation_style, "平衡讲解")}
                      icon={<Sparkles className="h-4 w-4" />}
                    />
                    <PreferenceRow
                      label="对话记忆"
                      value={conversationNotes.length ? conversationNotes.join("；") : "暂无足够对话信号"}
                      icon={<MessageCircle className="h-4 w-4" />}
                    />
                    {visibleProfileNotes.map((note) => (
                      <p key={note} className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                        {note}
                      </p>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
