import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Compass,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
  type LucideIcon,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
} from "../api/generated/exams";
import {
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
} from "../api/generated/profile";
import type {
  ExamGenerateResponse,
  ExamHistoryItem,
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
} from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";
import {
  MASTERY_DRILL_EXAM_MODE,
  MASTERY_DRILL_QUESTION_COUNT,
  buildExamTitle,
  loadCreateExamConfig,
  toExamGenerateRequest,
} from "../components/exams";
import { formatModeLabel } from "../components/exams/examDisplay";
import {
  PROFILE_SURFACE_CLASS,
  clamp01,
  formatDateTime as formatProfileDateTime,
  formatPercent,
  formatToken,
  isReviewDueSoon,
  masteryTone,
} from "../components/profile";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";

const pageShellClass = "mx-auto min-h-full w-full max-w-[1500px] px-4 pb-24 sm:px-6 lg:px-8 xl:px-10";
const alertClass = "rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";

const EXAM_STATUS_LABELS: Record<string, { label: string; className: string }> = {
  generating: {
    label: "生成中",
    className: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  },
  graded: {
    label: "已批改",
    className: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  },
  failed: {
    label: "生成失败",
    className: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  },
  submitted: {
    label: "已提交",
    className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  },
};

function formatExamStatus(status: string) {
  return EXAM_STATUS_LABELS[status] ?? {
    label: "待作答",
    className: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  };
}

function sortByNewestTimestamp<T>(items: T[], getTimestamp: (item: T) => string | null | undefined) {
  return [...items].sort((left, right) =>
    new Date(getTimestamp(right) ?? 0).getTime() - new Date(getTimestamp(left) ?? 0).getTime(),
  );
}

function getKnowledgeUnitName(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">) {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

function NavTile({
  icon: Icon,
  title,
  description,
  meta,
  onClick,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  meta: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        PROFILE_SURFACE_CLASS,
        "group flex min-h-40 w-full flex-col justify-between p-5 text-left transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md dark:hover:border-slate-700",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          <Icon className="h-4 w-4" />
        </span>
        <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-700 dark:text-slate-600 dark:group-hover:text-slate-200" />
      </div>
      <div className="mt-5 min-w-0">
        <h2 className="text-base font-semibold text-slate-950 dark:text-slate-100">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
        <p className="mt-4 truncate text-xs font-medium text-slate-400">{meta}</p>
      </div>
    </button>
  );
}

function RecentPaperRow({
  item,
  onOpen,
}: {
  item: ExamHistoryItem;
  onOpen: () => void;
}) {
  const status = formatExamStatus(item.status);
  const scoreText =
    item.status === "graded" && item.score_obtained != null && item.total_score != null
      ? `${item.score_obtained}/${item.total_score}`
      : `${item.total_items} 题`;
  const actionLabel =
    item.status === "graded"
      ? "查看"
      : item.status === "generating"
        ? "看进度"
        : item.status === "failed"
          ? "排查"
          : "直接考试";

  return (
    <div className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-100">{buildExamTitle(item)}</p>
          <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", status.className)}>
            {status.label}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {formatModeLabel(item.exam_mode)} · {scoreText}
        </p>
      </div>
      <Button type="button" size="sm" variant="outline" onClick={onOpen} className="h-8 shrink-0 px-3 text-xs">
        {actionLabel}
        <ArrowRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function FocusStateRow({ state }: { state: MasteryStateResponse }) {
  const score = clamp01(state.mastery_score);
  const tone = masteryTone(score);

  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
            {getKnowledgeUnitName(state)}
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次
          </p>
        </div>
        <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold", tone.bg, tone.text)}>
          {formatPercent(score)}
        </span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.max(5, score * 100)}%` }} />
      </div>
    </div>
  );
}

function ReviewTaskRow({
  task,
  onOpenSourceExam,
}: {
  task: ReviewTaskResponse;
  onOpenSourceExam: (paperId: number) => void;
}) {
  const dueSoon = isReviewDueSoon(task);

  return (
    <div className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
            {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
          </p>
          {dueSoon ? (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
              优先
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {formatToken(task.knowledge_unit_type, "知识点")} · {task.reason || "复习巩固"} · {formatProfileDateTime(task.scheduled_at)}
        </p>
      </div>
      {task.source_exam_paper_id ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onOpenSourceExam(task.source_exam_paper_id as number)}
          className="h-8 shrink-0 px-3 text-xs"
        >
          来源试卷
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      ) : null}
    </div>
  );
}

export function CourseDevNavigationPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { courseName } = useCourseDisplayName(courseId);

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

  const latestPapers = useMemo(
    () => sortByNewestTimestamp(historyItems, (item) => item.created_at).slice(0, 5),
    [historyItems],
  );
  const activePaperCount = useMemo(
    () => historyItems.filter((item) => item.status !== "graded").length,
    [historyItems],
  );
  const states = mastery?.knowledge_unit_states ?? [];
  const courseProfile = mastery?.course_profile;
  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;
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

  const generateExam = useGenerateExamApiV1CoursesCourseIdExamsGeneratePost({
    mutation: {
      onSuccess: async (response, variables) => {
        const created = unwrapOrvalResponse<ExamGenerateResponse>(response);
        if (!courseId || !created?.exam_paper_id) return;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId, { page: 1, size: 8 }),
        });
        navigate(buildCourseSubPath(courseId, "exams", created.exam_paper_id));
        toast({
          title: variables.data.exam_mode === MASTERY_DRILL_EXAM_MODE ? "闯关训练已开始" : "考试已创建",
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

  const startConfiguredExam = () => {
    if (!courseId || generateExam.isPending) return;
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(loadCreateExamConfig(courseId)),
    });
  };

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

  const startMasteryDrill = () => {
    if (!courseId || generateExam.isPending) return;
    generateExam.mutate({
      courseId,
      data: {
        exam_mode: MASTERY_DRILL_EXAM_MODE,
        num_questions: MASTERY_DRILL_QUESTION_COUNT,
      },
    });
  };

  if (!courseId) {
    return (
      <div className={pageShellClass}>
        <div className={alertClass}>缺少课程标识，暂时无法加载课程导航。</div>
      </div>
    );
  }

  return (
    <div className={pageShellClass}>
      <div className="flex w-full flex-col gap-7">
        <CoursePagePillTitle icon={Compass} label="DEV 导航" />

        <section className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                {courseName ?? "当前课程"}
              </h1>
              <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300">
                仅开发模式
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
              汇总课程的知识文档、训练中心和学习画像，方便调试时从一个页面进入最近试卷或按画像直接开练。
            </p>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
            <Button
              type="button"
              size="lg"
              onClick={startMasteryDrill}
              disabled={generateExam.isPending}
              className="w-full rounded-[10px] px-6 text-sm font-semibold sm:w-auto"
            >
              {generateExam.isPending && generateExam.variables?.data.exam_mode === MASTERY_DRILL_EXAM_MODE ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              直接闯关
            </Button>
            <Button
              type="button"
              size="lg"
              variant="outline"
              onClick={startConfiguredExam}
              disabled={generateExam.isPending}
              className="w-full rounded-[10px] px-6 text-sm font-semibold sm:w-auto"
            >
              {generateExam.isPending && generateExam.variables?.data.exam_mode !== MASTERY_DRILL_EXAM_MODE ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ClipboardCheck className="h-4 w-4" />
              )}
              按配置考试
            </Button>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <NavTile
            icon={BookOpen}
            title="知识文档"
            description="进入课程知识文档、讲义、交互图和知识图谱入口。"
            meta={`${states.length} 个画像知识点`}
            onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
          />
          <NavTile
            icon={FileText}
            title="训练中心"
            description="查看所有试卷，创建专项练习、整卷测试或题库调试。"
            meta={`${historyItems.length} 份最近记录，${activePaperCount} 份待完成`}
            onClick={() => navigate(buildCoursePath(courseId, "exams"))}
          />
          <NavTile
            icon={BarChart3}
            title="学习画像"
            description="查看掌握度、复习计划和偏好沉淀，直接从弱项开练。"
            meta={`平均掌握 ${formatPercent(courseProfile?.avg_mastery)}，待复习 ${courseProfile?.pending_review_count ?? reviewTasks.length}`}
            onClick={() => navigate(buildCoursePath(courseId, "profile"))}
          />
          <NavTile
            icon={Sparkles}
            title="资料构建"
            description="回到资料上传、计划确认和知识文档构建流程。"
            meta={courseProfile?.generated_at ? `画像更新 ${formatProfileDateTime(courseProfile.generated_at)}` : "从资料开始构建"}
            onClick={() => navigate(buildCoursePath(courseId, "build"))}
          />
        </section>

        {(historyQuery.error || masteryQuery.error || reviewsQuery.error) ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(historyQuery.error ?? masteryQuery.error ?? reviewsQuery.error, "课程导航数据加载失败")}
          </div>
        ) : null}

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
          <div className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">最近考卷</h2>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  待完成试卷可以直接进入作答页，已批改试卷可回看解析和画像更新。
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "exams"))}
                className="h-8 shrink-0 px-3 text-xs"
              >
                全部试卷
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>

            <div className="mt-5 divide-y divide-slate-100 dark:divide-slate-800">
              {historyQuery.isLoading ? (
                <p className="py-5 text-sm text-slate-500 dark:text-slate-400">正在加载最近考卷...</p>
              ) : latestPapers.length ? (
                latestPapers.map((item) => (
                  <RecentPaperRow
                    key={item.id}
                    item={item}
                    onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                  />
                ))
              ) : (
                <div className="flex flex-col gap-4 rounded-lg border border-dashed border-slate-200 bg-slate-50/80 px-5 py-6 dark:border-slate-800 dark:bg-slate-950/40 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">暂无最近考卷。</p>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">先创建一次专项练习或闯关训练。</p>
                  </div>
                  <Button type="button" size="sm" onClick={startConfiguredExam} disabled={generateExam.isPending}>
                    开始专项练习
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">画像快照</h2>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  最近一次画像信号和可直接执行的练习入口。
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={startProfileExam}
                disabled={generateExam.isPending}
                className="h-8 shrink-0 px-3 text-xs"
              >
                {generateExam.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Target className="h-3.5 w-3.5" />}
                按画像开练
              </Button>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {[
                { label: "掌握度", value: formatPercent(courseProfile?.avg_mastery) },
                { label: "薄弱点", value: String(courseProfile?.weak_knowledge_unit_count ?? mastery?.weak_knowledge_unit_count ?? 0) },
                { label: "到期复习", value: String(dueReviewCount) },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-slate-200/80 bg-slate-50/70 px-3 py-3 dark:border-slate-800/80 dark:bg-slate-950/40">
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</p>
                  <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-slate-100">{item.value}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 rounded-lg border border-slate-200/80 px-4 py-4 dark:border-slate-800/80">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">推荐练习</p>
                <RefreshCw className="h-4 w-4 text-slate-400" />
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                {formatToken(courseProfile?.recommended_exam_mode, "网页练习")} · 约 {courseProfile?.recommended_question_count ?? 8} 题 · {formatToken(courseProfile?.difficulty_focus, "中等")}难度
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(courseProfile?.recommended_question_types ?? []).slice(0, 4).map((type) => (
                  <span key={type} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {formatToken(type)}
                  </span>
                ))}
                {focusNames ? (
                  <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
                    {focusNames}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-2">
          <div className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">优先知识点</h2>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "profile"))}
                className="h-8 px-3 text-xs"
              >
                画像详情
              </Button>
            </div>
            <div className="mt-5 divide-y divide-slate-100 dark:divide-slate-800">
              {masteryQuery.isLoading ? (
                <p className="py-5 text-sm text-slate-500 dark:text-slate-400">正在加载画像...</p>
              ) : focusStates.length ? (
                focusStates.map((state) => <FocusStateRow key={state.id} state={state} />)
              ) : (
                <p className="rounded-lg bg-slate-50 px-4 py-4 text-sm text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
                  暂无知识点画像，完成一次练习后会出现薄弱点。
                </p>
              )}
            </div>
          </div>

          <div className={cn(PROFILE_SURFACE_CLASS, "p-5 sm:p-6")}>
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">复习任务</h2>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "profile"))}
                className="h-8 px-3 text-xs"
              >
                打开画像
              </Button>
            </div>
            <div className="mt-5 divide-y divide-slate-100 dark:divide-slate-800">
              {reviewsQuery.isLoading ? (
                <p className="py-5 text-sm text-slate-500 dark:text-slate-400">正在加载复习任务...</p>
              ) : topReviewTasks.length ? (
                topReviewTasks.map((task) => (
                  <ReviewTaskRow
                    key={task.id}
                    task={task}
                    onOpenSourceExam={(paperId) => navigate(buildCourseSubPath(courseId, "exams", paperId))}
                  />
                ))
              ) : (
                <div className="rounded-lg bg-slate-50 px-4 py-4 text-sm text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
                  <div className="flex items-center gap-2 font-medium text-slate-700 dark:text-slate-200">
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    当前没有高优先级复习任务。
                  </div>
                  <p className="mt-2">可以直接按画像开练，继续为画像补充数据。</p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
