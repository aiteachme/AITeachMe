import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Gauge,
  MessageCircle,
  Sparkles,
  Target,
  Trophy,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileText,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
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
  MasteryOverviewResponse,
  ReviewTaskResponse,
  StudyPlanStepResponse,
  ExamHistoryItem,
  ExamGenerateResponse,
  MasteryStateResponse,
} from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/utils";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";
import {
  buildExamTitle,
} from "../components/exams";
import { formatModeLabel } from "../components/exams/examDisplay";
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

const pageShellClass = "mx-auto min-h-full w-full max-w-[1400px] px-6 pb-24 sm:px-8 lg:px-12 pt-8";



function getKnowledgeUnitName(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">) {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

function sortByNewestTimestamp<T>(items: T[], getTimestamp: (item: T) => string | null | undefined) {
  return [...items].sort((left, right) =>
    new Date(getTimestamp(right) ?? 0).getTime() - new Date(getTimestamp(left) ?? 0).getTime(),
  );
}

function RecentPaperRow({
  item,
  onOpen,
}: {
  item: ExamHistoryItem;
  onOpen: () => void;
}) {
  const scoreText =
    item.status === "graded" && item.score_obtained != null && item.total_score != null
      ? `${item.score_obtained}/${item.total_score} 分`
      : `${item.total_items} 题`;
  
  const dotColor =
    item.status === "graded"
      ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]"
      : item.status === "generating"
        ? "bg-indigo-500 animate-pulse shadow-[0_0_6px_rgba(99,102,241,0.4)]"
        : item.status === "failed"
          ? "bg-rose-500 shadow-[0_0_6px_rgba(239,68,68,0.4)]"
          : "bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.4)]";

  return (
    <div className="group flex items-center justify-between py-3.5 border-b border-slate-100/60 dark:border-slate-800/20 last:border-0 transition-colors duration-200">
      <div className="min-w-0 flex-1 flex items-center gap-3">
        <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", dotColor)} />
        <div className="min-w-0">
          <p className="truncate text-[14px] font-medium text-slate-800 dark:text-slate-200 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors duration-200">{buildExamTitle(item)}</p>
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-555 font-light">
            {formatModeLabel(item.exam_mode)} · {scoreText}
          </p>
        </div>
      </div>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={onOpen}
        className="h-8 shrink-0 px-3 text-xs font-semibold text-slate-500 group-hover:text-indigo-600 dark:text-slate-400 dark:group-hover:text-indigo-400 hover:bg-transparent"
      >
        进入
        <ArrowRight className="h-3.5 w-3.5 ml-1 transition-transform group-hover:translate-x-0.5" />
      </Button>
    </div>
  );
}

function FocusStateRow({ state }: { state: MasteryStateResponse }) {
  const score = clamp01(state.mastery_score);
  const tone = masteryTone(score);

  return (
    <div className="py-3.5 border-b border-slate-100/60 dark:border-slate-805/20 last:border-0">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-[14px] font-medium text-slate-800 dark:text-slate-200">
            {getKnowledgeUnitName(state)}
          </p>
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500 font-light">
            {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次
          </p>
        </div>
        <span className={cn("shrink-0 text-xs font-semibold", tone.text)}>
          {formatPercent(score)}
        </span>
      </div>
      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800/40">
        <div className={cn("h-full rounded-full transition-all duration-700 ease-out", tone.bar)} style={{ width: `${Math.max(5, score * 100)}%` }} />
      </div>
    </div>
  );
}

function ReviewTaskRow({
  task,
  onOpenSourceExam,
  onComplete,
  isCompleting,
}: {
  task: ReviewTaskResponse;
  onOpenSourceExam: (paperId: number) => void;
  onComplete: () => void;
  isCompleting: boolean;
}) {
  const dueSoon = isReviewDueSoon(task);

  return (
    <div className="group flex items-center justify-between py-3.5 border-b border-slate-100/60 dark:border-slate-800/20 last:border-0 transition-colors duration-200">
      <div className="min-w-0 flex-1 pr-3">
        <div className="flex items-center gap-2">
          <p className="truncate text-[14px] font-medium text-slate-800 dark:text-slate-200">
            {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
          </p>
          {dueSoon && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-semibold text-amber-705 ring-1 ring-amber-500/10 dark:bg-amber-500/10 dark:text-amber-300">
              优先
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500 font-light">
          {formatToken(task.knowledge_unit_type, "知识点")} · {formatDateTime(task.scheduled_at)}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {task.source_exam_paper_id && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onOpenSourceExam(task.source_exam_paper_id as number)}
            className="h-8 px-2.5 text-[11px] font-medium text-slate-450 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-400 hover:bg-transparent"
          >
            来源
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onComplete}
          disabled={isCompleting}
          className="h-7.5 rounded-full px-3 text-[11px] font-medium border-slate-200 text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900/60"
        >
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
  
  const [isProfileExpanded, setIsProfileExpanded] = useState(false);
  const [recentlyCompletedReviews, setRecentlyCompletedReviews] = useState<ReviewTaskResponse[]>([]);

  useEffect(() => {
    setRecentlyCompletedReviews([]);
  }, [courseId]);

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
          description: "学习画像与待复习列表已实时刷新。",
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

  const generateExam = useGenerateExamApiV1CoursesCourseIdExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse<ExamGenerateResponse>(response);
        if (!courseId || !created?.exam_paper_id) return;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId, { page: 1, size: 8 }),
        });
        navigate(buildCourseSubPath(courseId, "exams", created.exam_paper_id));
        toast({
          title: "考试已创建",
          description: `已准备 ${created.num_questions} 题，正在进入作答页。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "创建考试失败",
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
    .filter((note) => !/：0\s*(个|项)/.test(note) && !conversationNotes.includes(note))
    .slice(0, 4), [profileNotes, conversationNotes]);

  const latestPapers = useMemo(
    () => sortByNewestTimestamp(historyItems, (item) => item.created_at).slice(0, 5),
    [historyItems],
  );
  
  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;
  const weakCount = courseProfile?.weak_knowledge_unit_count ?? mastery?.weak_knowledge_unit_count ?? 0;
  const focusUnitIds = new Set(courseProfile?.focus_knowledge_unit_ids ?? []);
  
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

  const focusNames = focusStates.map(getKnowledgeUnitName).slice(0, 3).join("、");

  const startProfileExam = () => {
    if (!courseId || generateExam.isPending) return;
    const profileMode = courseProfile?.recommended_exam_mode === "paper_exam" ? "paper_exam" : "web_practice";
    generateExam.mutate({
      courseId,
      data: {
        exam_mode: profileMode,
        num_questions: Math.min(80, Math.max(1, courseProfile?.recommended_question_count ?? 8)),
        user_prompt: focusNames ? `重点覆盖：${focusNames}` : undefined,
      },
    });
  };

  const planItems = useMemo(() => {
    const PLAN_LABEL_BY_KEY: Record<string, string> = {
      locate: "定位",
      review: "复习",
      practice: "训练",
      reflect: "复盘",
    };
    const dueTasks = reviewTasks.filter(isReviewDueSoon);
    const weakStates = [...states]
      .sort((left, right) => left.mastery_score - right.mastery_score || right.review_priority - left.review_priority)
      .slice(0, 3);
    const focusNamesPlan = weakStates
      .map((state) => state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`)
      .slice(0, 2)
      .join("、");
    const qTypes = courseProfile?.recommended_question_types?.slice(0, 2).map((item) => formatToken(item)).join("、");
    
    const fallbackPlanItems = [
      {
        key: "locate",
        label: "定位",
        title: dueTasks.length ? "先处理高优先级复习" : "锁定薄弱知识点",
        detail: dueTasks.length
          ? `优先完成 ${Math.min(dueTasks.length, 3)} 个高优先级复习任务，避免遗忘继续扩大。`
          : focusNamesPlan
            ? `先看 ${focusNamesPlan}，确认这几个点是否真的理解。`
            : "先做一次短练习，让系统拿到可诊断的数据。",
      },
      {
        key: "practice",
        label: "训练",
        title: "做一轮专项练习",
        detail: `${formatToken(courseProfile?.recommended_exam_mode, "网页练习")} · 约 ${courseProfile?.recommended_question_count ?? 10} 题 · ${formatToken(courseProfile?.difficulty_focus, "中等")}难度${qTypes ? ` · ${qTypes}` : ""}。`,
      },
      {
        key: "reflect",
        label: "复盘",
        title: "带着错题回到知识库",
        detail: "练完后把错题、卡点或划选内容拿去伴读追问，画像会继续沉淀你的讲解偏好。",
      },
    ];

    return studyPlan?.length
      ? studyPlan.map((item) => ({
        key: item.key,
        label: PLAN_LABEL_BY_KEY[item.key] ?? "计划",
        title: item.title,
        detail: item.detail,
      }))
      : fallbackPlanItems;
  }, [studyPlan, reviewTasks, states, courseProfile]);

  const statItems = [
    {
      label: "掌握度",
      value: formatPercent(courseProfile?.avg_mastery),
      detail: `${states.length} 个知识点`,
      icon: <Gauge className="h-5 w-5" strokeWidth={1.25} />,
      iconClass: "bg-indigo-50/50 text-indigo-500 ring-1 ring-indigo-100/30 dark:bg-indigo-950/20 dark:text-indigo-400",
    },
    {
      label: "正确率",
      value: formatPercent(attemptAccuracy),
      detail: `${totalAttempts} 次作答`,
      icon: <Trophy className="h-5 w-5" strokeWidth={1.25} />,
      iconClass: "bg-violet-50/50 text-violet-500 ring-1 ring-violet-100/30 dark:bg-violet-950/20 dark:text-violet-400",
    },
    {
      label: "待复习",
      value: String(dueReviewCount),
      detail: `到期 ${dueReviewCount} 个`,
      icon: <CalendarClock className="h-5 w-5" strokeWidth={1.25} />,
      iconClass: "bg-rose-50/50 text-rose-500 ring-1 ring-rose-100/30 dark:bg-rose-950/20 dark:text-rose-400",
      valueClass: dueReviewCount > 0 ? "text-rose-600 dark:text-rose-400" : undefined,
    },
    {
      label: "稳定度",
      value: formatPercent(avgStability),
      detail: "基于艾宾浩斯遗忘模型",
      icon: <Activity className="h-5 w-5" strokeWidth={1.25} />,
      iconClass: "bg-emerald-50/50 text-emerald-500 ring-1 ring-emerald-100/30 dark:bg-emerald-950/20 dark:text-emerald-400",
    },
  ];

  if (!courseId) {
    return (
      <div className={pageShellClass}>
        <div className="mx-auto max-w-5xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          缺少课程标识，暂时无法加载学习画像。
        </div>
      </div>
    );
  }

  const isLoading = historyQuery.isLoading || masteryQuery.isLoading || reviewsQuery.isLoading;

  return (
    <div className={pageShellClass}>
      <div className="flex w-full flex-col gap-8">
        
        {/* Breadcrumb pill title */}
        <CoursePagePillTitle icon={BarChart3} label="学习画像" href={buildCoursePath(courseId, "nav")} />

        {/* Header Section */}
        <section className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl space-y-2">
            <h1 className="break-words text-3xl font-semibold text-slate-900 dark:text-slate-100 tracking-tight sm:text-[34px]">
              {courseName ?? "当前课程"}
            </h1>
            <p className="max-w-2xl text-[14px] font-light leading-relaxed text-slate-500 dark:text-slate-400">
              基于您的测验历史与复习习惯自动沉淀的多维诊断。在这里您可以查看学习重点，获取 AI 突击训练计划。
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap xl:justify-end shrink-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
              className="h-10 rounded-full px-5 text-xs font-semibold text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 bg-white hover:bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800"
            >
              看知识库
            </Button>
            <Button
              type="button"
              onClick={() => navigate(buildCoursePath(courseId, "exams"))}
              className="h-10 rounded-full px-6 text-xs font-semibold shadow-sm bg-indigo-650 text-white hover:bg-indigo-700"
            >
              去练习
              <ArrowRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </section>

        {(masteryQuery.error || reviewsQuery.error) && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "学习画像数据加载失败，请重试。")}
          </div>
        )}

        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        ) : (
          <>
            {/* 4-Column Core Metrics Grid */}
            <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {statItems.map((item) => (
                <div
                  key={item.label}
                  className="rounded-2xl border border-slate-200/50 bg-white dark:border-slate-800/60 dark:bg-[#0a0d16]/70 shadow-sm p-6 flex items-center gap-4 transition-all duration-350 hover:shadow-md hover:border-slate-350/60 dark:hover:border-slate-700/60"
                >
                  <span className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", item.iconClass)}>
                    {item.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{item.label}</p>
                    <p className={cn("mt-0.5 text-xl font-bold text-slate-900 dark:text-slate-100", item.valueClass)}>{item.value}</p>
                    <p className="truncate text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 font-light">{item.detail}</p>
                  </div>
                </div>
              ))}
            </section>

            {/* Today's Learning Plan (今日学习计划) */}
            {planItems.length > 0 && (
              <section className="space-y-4">
                <div className="border-b border-slate-100 dark:border-slate-800/50 pb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                    <CalendarClock className="h-4 w-4 text-slate-400" />
                    今日学习计划
                  </h3>
                  <span className="text-[11px] text-slate-400 dark:text-slate-500 font-light">按定位、练习、复盘排出下一步</span>
                </div>
                
                <div className="relative pl-6 border-l border-slate-100 dark:border-slate-800/60 ml-2.5 space-y-6 pt-1">
                  {planItems.map((item, index) => (
                    <div key={item.key} className="relative group">
                      {/* Timeline dot marker */}
                      <span className="absolute -left-[31px] top-1 flex h-5 w-5 items-center justify-center rounded-full bg-white dark:bg-[#0b0f19] border border-slate-200 dark:border-slate-800 text-[10px] font-bold text-slate-400 group-hover:border-indigo-400 group-hover:text-indigo-500 transition-all duration-300">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <div className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-4">
                        <span className="text-xs font-semibold text-slate-400 dark:text-slate-500 tracking-wider uppercase pt-0.5 sm:w-16 shrink-0">{item.label}</span>
                        <div className="min-w-0">
                          <h4 className="text-[14px] font-medium text-slate-900 dark:text-slate-100">{item.title}</h4>
                          <p className="mt-1 text-[13px] leading-relaxed text-slate-500 dark:text-slate-405 font-light">{item.detail}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Recent Exams & AI Insights Grid */}
            <div className="grid gap-8 lg:grid-cols-12 items-stretch">
              
              {/* Recent Exams List */}
              <div className="lg:col-span-7 flex flex-col">
                <div className="pb-3 border-b border-slate-100 dark:border-slate-800/50 mb-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                    <FileText className="h-4 w-4 text-slate-400" />
                    近期测验
                  </h3>
                </div>
                <div className="flex-1 flex flex-col justify-center min-h-[240px]">
                  {latestPapers.length ? (
                    <div className="flex flex-col justify-between h-full flex-1">
                      {latestPapers.map((item) => (
                        <RecentPaperRow
                          key={item.id}
                          item={item}
                          onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-8 text-center h-full flex-1 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
                      <div className="relative mb-3">
                        <div className="absolute inset-0 rounded-full bg-slate-500/5 blur-xl"></div>
                        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50 text-slate-400 ring-1 ring-slate-100 dark:bg-slate-800/30 dark:text-slate-500 dark:ring-slate-800/50">
                          <FileText className="h-5 w-5" strokeWidth={1.5} />
                        </div>
                      </div>
                      <p className="text-[13.5px] font-medium text-slate-700 dark:text-slate-300">暂无测验记录</p>
                      <p className="mt-1 text-xs text-slate-450 max-w-xs font-light leading-relaxed">完成闯关或练习后，测验数据将同步于此。</p>
                    </div>
                  )}
                </div>
              </div>

              {/* AI Insights Card */}
              <div className="lg:col-span-5 flex flex-col">
                <div className="pb-3 border-b border-slate-100 dark:border-slate-800/50 mb-3 invisible lg:visible h-9">
                  {/* Space alignment */}
                </div>
                <div className="flex-1 rounded-2xl border border-slate-200/55 bg-gradient-to-br from-indigo-500/[0.015] to-indigo-500/[0.06] dark:border-slate-800/60 dark:from-indigo-500/[0.01] dark:to-indigo-500/[0.03] p-6 flex flex-col justify-between shadow-sm min-h-[240px]">
                  <div>
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <div className="flex items-center gap-2">
                        <Sparkles className="h-4.5 w-4.5 text-indigo-500 dark:text-indigo-400" />
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">AI 学习洞察</h3>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        onClick={startProfileExam}
                        disabled={generateExam.isPending}
                        className="h-7.5 rounded-full px-3 text-[11px] font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-none transition-all flex items-center gap-1 shrink-0"
                      >
                        {generateExam.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Target className="h-3 w-3" />}
                        按画像开练
                      </Button>
                    </div>

                    <p className="text-[13px] leading-relaxed text-slate-500 dark:text-slate-400 font-light mb-5">
                      根据您的多维画像，AI 建议当前进行一轮 {formatToken(courseProfile?.recommended_exam_mode, "网页练习")}，约 {courseProfile?.recommended_question_count ?? 8} 题，覆盖推荐难度和薄弱点。
                    </p>

                    <div className="flex flex-wrap gap-1.5 mb-5">
                      {(courseProfile?.recommended_question_types ?? []).slice(0, 3).map((type) => (
                        <span key={type} className="rounded-full bg-slate-100/70 dark:bg-slate-900/55 px-2.5 py-0.5 text-[10.5px] font-medium text-slate-500 dark:text-slate-400 border border-slate-200/30 dark:border-slate-700/55">
                          {formatToken(type)}
                        </span>
                      ))}
                      {focusNames ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50/60 dark:bg-indigo-950/20 px-2.5 py-0.5 text-[10.5px] font-medium text-indigo-650 dark:text-indigo-400 border border-indigo-100/30 dark:border-indigo-900/20">
                          <Sparkles className="h-2.5 w-2.5 text-indigo-500" />
                          {focusNames}
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 border-t border-slate-100 dark:border-slate-800/40 pt-4">
                    <div className="flex flex-col">
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">平均掌握度</span>
                      <span className="text-sm font-bold text-slate-800 dark:text-slate-200 mt-0.5">{formatPercent(courseProfile?.avg_mastery)}</span>
                    </div>
                    <div className="flex flex-col border-l border-slate-100 dark:border-slate-800/80 pl-3">
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">薄弱知识点</span>
                      <span className="text-sm font-bold text-slate-800 dark:text-slate-200 mt-0.5">{weakCount} 个</span>
                    </div>
                    <div className="flex flex-col border-l border-slate-100 dark:border-slate-800/80 pl-3">
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">待复习</span>
                      <span className="text-sm font-bold text-slate-800 dark:text-slate-200 mt-0.5">{dueReviewCount} 个</span>
                    </div>
                  </div>
                </div>
              </div>

            </div>

            {/* Priority Units & Review Tasks Grid */}
            <div className="grid gap-8 lg:grid-cols-12 items-stretch">
              
              {/* Priority Units */}
              <div className="lg:col-span-7 flex flex-col">
                <div className="pb-3 border-b border-slate-100 dark:border-slate-800/50 mb-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                    <Target className="h-4 w-4 text-slate-400" />
                    优先知识点
                  </h3>
                </div>
                <div className="flex-1 flex flex-col justify-center min-h-[240px]">
                  {focusStates.length ? (
                    <div className="flex flex-col justify-between h-full flex-1">
                      {focusStates.map((state) => (
                        <FocusStateRow key={state.id} state={state} />
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-8 text-center h-full flex-1 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
                      <div className="relative mb-3">
                        <div className="absolute inset-0 rounded-full bg-slate-500/5 blur-xl"></div>
                        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50 text-slate-400 ring-1 ring-slate-100 dark:bg-slate-800/30 dark:text-slate-500 dark:ring-slate-800/50">
                          <Target className="h-5 w-5" strokeWidth={1.5} />
                        </div>
                      </div>
                      <p className="text-[13.5px] font-medium text-slate-700 dark:text-slate-300">暂无画像数据</p>
                      <p className="mt-1 text-xs text-slate-450 max-w-xs font-light leading-relaxed">系统推荐的优先突破点会在诊断数据生成后同步在此。</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Review Tasks */}
              <div className="lg:col-span-5 flex flex-col">
                <div className="pb-3 border-b border-slate-100 dark:border-slate-800/50 mb-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                    <CalendarClock className="h-4 w-4 text-slate-400" />
                    复习任务
                  </h3>
                </div>
                <div className="flex-1 flex flex-col justify-center min-h-[240px]">
                  {topReviewTasks.length ? (
                    <div className="flex flex-col justify-between h-full flex-1">
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
                        {visibleCompletedReviews.length > 0 && (
                          <div className="py-2.5 border-t border-slate-100/60 dark:border-slate-800/20 mt-1">
                            <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 mb-2">刚刚完成复习</p>
                            <div className="space-y-1.5">
                              {visibleCompletedReviews.map((task) => (
                                <div
                                  key={task.id}
                                  className="flex items-center gap-2 rounded-lg bg-emerald-50/60 dark:bg-emerald-950/20 px-3 py-1.5 text-xs text-emerald-700 dark:text-emerald-305 border border-emerald-100/40 dark:border-emerald-900/30"
                                >
                                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                                  <span className="truncate">
                                    {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    </div>
                  ) : visibleCompletedReviews.length ? (
                    <div className="py-4 text-center">
                      <p className="text-sm font-medium text-slate-905 dark:text-slate-100">本轮复习已完成。</p>
                      <div className="mt-3 space-y-2 max-w-sm mx-auto">
                        {visibleCompletedReviews.map((task) => (
                          <div
                            key={task.id}
                            className="flex items-center gap-2 rounded-lg bg-emerald-50/60 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                            <span className="truncate">
                              {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
                            </span>
                            <span className="ml-auto shrink-0 font-medium">已完成</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-8 text-center h-full flex-1 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
                      <div className="relative mb-3">
                        <div className="absolute inset-0 rounded-full bg-emerald-500/5 blur-xl"></div>
                        <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-505 ring-1 ring-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:ring-emerald-500/20">
                          <CheckCircle2 className="h-5 w-5" strokeWidth={1.5} />
                        </div>
                      </div>
                      <p className="text-[13.5px] font-medium text-slate-700 dark:text-slate-200">太棒了，暂无待办</p>
                      <p className="mt-1 text-xs text-slate-450 max-w-xs font-light leading-relaxed">当前没有需要复习的到期任务，继续保持！</p>
                    </div>
                  )}
                </div>
              </div>

            </div>

            {/* Collapse Details Panel */}
            <div className="border-t border-slate-100 dark:border-slate-800/80 pt-4">
              <button
                type="button"
                onClick={() => setIsProfileExpanded(!isProfileExpanded)}
                className="flex w-full items-center justify-between py-2 text-sm font-semibold text-slate-900 dark:text-slate-100 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors focus:outline-none"
              >
                <span className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-slate-400" />
                  更多画像细节 (掌握分布、题型正确率与对话记忆)
                </span>
                <span className="flex items-center gap-1 text-xs font-medium text-slate-400">
                  {isProfileExpanded ? (
                    <>
                      点击收起 <ChevronUp className="h-4 w-4" />
                    </>
                  ) : (
                    <>
                      展开详情 <ChevronDown className="h-4 w-4" />
                    </>
                  )}
                </span>
              </button>

              {isProfileExpanded && (
                <div className="grid gap-6 mt-4 border-t border-slate-100 dark:border-slate-800/80 pt-5 lg:grid-cols-3 animate-[fadeIn_0.3s_ease-out]">
                  {/* Mastery Distribution */}
                  <div className="rounded-xl border border-slate-150/80 dark:border-slate-850 p-4 bg-white dark:bg-[#0a0d16]">
                    <p className="text-[13px] font-semibold text-slate-900 dark:text-slate-100 mb-3">掌握分布</p>
                    <MasteryDistribution states={states} />
                  </div>

                  {/* Accuracy Rows */}
                  <div className="space-y-4 rounded-xl border border-slate-150/80 dark:border-slate-850 p-4 bg-white dark:bg-[#0a0d16]">
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

                  {/* Preference Row & Notes */}
                  <div className="space-y-3 rounded-xl border border-slate-150/80 dark:border-slate-850 p-4 bg-white dark:bg-[#0a0d16]">
                    <p className="text-[13px] font-semibold text-slate-900 dark:text-slate-100 mb-2">讲解风格与记忆</p>
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
                    <div className="space-y-2 pt-2">
                      {visibleProfileNotes.map((note) => (
                        <p key={note} className="rounded-lg bg-slate-50 dark:bg-slate-900/60 px-3 py-2 text-xs leading-relaxed text-slate-500 dark:text-slate-355 font-light border border-slate-150/30 dark:border-slate-800/40">
                          {note}
                        </p>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
