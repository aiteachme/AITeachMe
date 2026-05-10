import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Gauge,
  MessageCircle,
  Sparkles,
  Target,
  Trophy,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey,
  getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey,
  getStudyPlanApiV1CoursesCourseIdProfileStudyPlanGetQueryKey,
  useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost,
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
  useStudyPlanApiV1CoursesCourseIdProfileStudyPlanGet,
} from "../api/generated/profile";
import type { MasteryOverviewResponse, ReviewTaskResponse, StudyPlanStepResponse } from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/utils";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildCoursePath } from "../lib/courseNavigation";
import {
  AccuracyRows,
  LearningPlanPanel,
  MasteryDistribution,
  Panel,
  PreferenceRow,
  PROFILE_SURFACE_CLASS,
  average,
  buildNoteText,
  formatDateTime,
  formatPercent,
  formatToken,
} from "../components/profile";

const surfaceClass = PROFILE_SURFACE_CLASS;
const pageShellClass = "mx-auto min-h-full w-full max-w-[1500px] px-4 pb-24 pt-20 sm:px-6 sm:pt-8 lg:px-8 xl:px-10 lg:pt-10";

export function ProfilePage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { courseName } = useCourseDisplayName(courseId);
  const [recentlyCompletedReviews, setRecentlyCompletedReviews] = useState<ReviewTaskResponse[]>([]);

  const masteryQuery = useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet(courseId ?? "");
  const reviewsQuery = useReviewTasksApiV1CoursesCourseIdProfileReviewsGet(courseId ?? "");
  const studyPlanQuery = useStudyPlanApiV1CoursesCourseIdProfileStudyPlanGet(courseId ?? "");

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

  useEffect(() => {
    setRecentlyCompletedReviews([]);
  }, [courseId]);

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
            queryKey: getStudyPlanApiV1CoursesCourseIdProfileStudyPlanGetQueryKey(courseId ?? ""),
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
  const focusUnitIds = new Set(courseProfile?.focus_knowledge_unit_ids ?? []);
  const sortedFocusStates = [...states]
    .sort((left, right) =>
      Number(focusUnitIds.has(right.knowledge_unit_id)) - Number(focusUnitIds.has(left.knowledge_unit_id)) ||
      left.mastery_score - right.mastery_score ||
      right.review_priority - left.review_priority,
    )
    .slice(0, 8);
  const sortedReviewTasks = [...reviewTasks]
    .sort((left, right) => right.priority - left.priority)
    .slice(0, 8);
  const totalAttempts = states.reduce((sum, state) => sum + state.total_attempts, 0);
  const correctAttempts = states.reduce((sum, state) => sum + state.correct_attempts, 0);
  const attemptAccuracy = totalAttempts > 0 ? correctAttempts / totalAttempts : null;
  const avgStability = average(states.map((state) => state.stability_score));
  const latestState = [...states]
    .filter((state) => state.last_attempt_at)
    .sort((left, right) => new Date(right.last_attempt_at ?? 0).getTime() - new Date(left.last_attempt_at ?? 0).getTime())[0];
  const profileNotes = Array.from(new Set([
    ...(courseProfile?.notes ?? []),
    ...(userProfile?.notes ?? []),
  ].map(buildNoteText)));
  const conversationNotes = profileNotes
    .filter((note) => /^(近期对话|对话偏好|资料使用|学习意图)：/.test(note))
    .slice(0, 3);
  const visibleProfileNotes = profileNotes
    .filter((note) => !/：0\s*(个|项)/.test(note) && !conversationNotes.includes(note))
    .slice(0, 4);
  const hasProfileSignals = states.length > 0 || reviewTasks.length > 0 || visibleCompletedReviews.length > 0;
  const statItems = [
    {
      label: "掌握度",
      value: formatPercent(courseProfile?.avg_mastery),
      detail: `${states.length} 个知识点`,
      icon: <Gauge className="h-4 w-4" />,
    },
    {
      label: "正确率",
      value: formatPercent(attemptAccuracy),
      detail: `${totalAttempts} 次作答`,
      icon: <Trophy className="h-4 w-4" />,
    },
    {
      label: "待复习",
      value: String(courseProfile?.pending_review_count ?? reviewTasks.length),
      detail: `到期 ${courseProfile?.due_review_count ?? 0}`,
      icon: <CalendarClock className="h-4 w-4" />,
    },
    {
      label: "稳定度",
      value: formatPercent(avgStability),
      detail: `最近 ${formatDateTime(latestState?.last_attempt_at)}`,
      icon: <Activity className="h-4 w-4" />,
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

  return (
    <div className={pageShellClass}>
      <div className="flex w-full flex-col gap-7">
        <section className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
              <BarChart3 className="h-3.5 w-3.5" />
              学习画像
            </div>
            <div>
              <h1 className="break-words text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                {courseName ?? "当前课程"}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                根据测验、复习和近期对话更新学习节奏，只保留当前最值得执行的动作。
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
            <Button
              type="button"
              size="lg"
              onClick={() => navigate(buildCoursePath(courseId, "exams"))}
              className="w-full rounded-[10px] px-6 text-sm font-semibold sm:w-auto"
            >
              去练习
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="lg"
              variant="outline"
              onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
              className="w-full rounded-[10px] px-6 text-sm font-semibold sm:w-auto"
            >
              看知识库
            </Button>
          </div>
        </section>

        {(masteryQuery.error || reviewsQuery.error) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        )}

        {hasProfileSignals ? (
          <>
            <section className={cn(surfaceClass, "grid gap-0 overflow-hidden p-0 md:grid-cols-4")}>
              {statItems.map((item) => (
                <div key={item.label} className="flex items-center gap-3 border-b border-slate-200/70 px-5 py-4 last:border-b-0 md:border-b-0 md:border-r md:last:border-r-0 dark:border-slate-800/80">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                    {item.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</p>
                    <p className="mt-0.5 text-lg font-semibold text-slate-950 dark:text-slate-100">{item.value}</p>
                    <p className="truncate text-xs text-slate-400">{item.detail}</p>
                  </div>
                </div>
              ))}
            </section>

            <LearningPlanPanel
              courseProfile={courseProfile}
              states={states}
              reviewTasks={reviewTasks}
              studyPlan={studyPlan}
              onStartPractice={() => navigate(buildCoursePath(courseId, "exams"))}
              onOpenKnowledgeDocs={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
            />

            <Panel title="本周学习重点" description="默认只展示最需要处理的知识点和复习任务。">
              <div className="mt-5 grid gap-8 lg:grid-cols-2">
                <div>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">优先知识点</p>
                    <span className="text-xs text-slate-400">{sortedFocusStates.length} 个</span>
                  </div>
                  <div className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
                    {masteryQuery.isLoading ? (
                      <p className="py-4 text-sm text-slate-500 dark:text-slate-400">正在加载画像数据...</p>
                    ) : sortedFocusStates.length ? (
                      sortedFocusStates.slice(0, 5).map((state) => (
                        <div key={state.id} className="flex items-center justify-between gap-4 py-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                              {state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`}
                            </p>
                            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次
                            </p>
                          </div>
                          <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                            {formatPercent(state.mastery_score)}
                          </span>
                        </div>
                      ))
                    ) : (
                      <p className="py-4 text-sm text-slate-500 dark:text-slate-400">暂无薄弱知识点。</p>
                    )}
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">复习任务</p>
                    <Clock3 className="h-4 w-4 text-slate-400" />
                  </div>
                  <div className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
                    {reviewsQuery.isLoading ? (
                      <p className="py-4 text-sm text-slate-500 dark:text-slate-400">正在加载复习任务...</p>
                    ) : sortedReviewTasks.length ? (
                      <>
                        {sortedReviewTasks.slice(0, 4).map((task) => (
                          <div key={task.id} className="flex items-center justify-between gap-4 py-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                                {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
                              </p>
                              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                {formatToken(task.knowledge_unit_type, "知识点")} · {formatDateTime(task.scheduled_at)}
                              </p>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => completeReview.mutate({ courseId, taskId: task.id })}
                              disabled={completeReview.isPending}
                              className="h-8 shrink-0 px-3 text-xs"
                            >
                              完成
                            </Button>
                          </div>
                        ))}
                        {visibleCompletedReviews.length > 0 && (
                          <div className="py-3">
                            <p className="text-xs font-medium text-emerald-700 dark:text-emerald-300">刚刚完成</p>
                            <div className="mt-2 space-y-2">
                              {visibleCompletedReviews.map((task) => (
                                <div
                                  key={task.id}
                                  className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
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
                    ) : visibleCompletedReviews.length ? (
                      <div className="py-4">
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">本轮复习已完成。</p>
                        <div className="mt-3 space-y-2">
                          {visibleCompletedReviews.map((task) => (
                            <div
                              key={task.id}
                              className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                            >
                              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                              <span className="truncate">
                                {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
                              </span>
                              <span className="ml-auto shrink-0">已完成</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="py-4 text-sm text-slate-500 dark:text-slate-400">当前没有待处理复习任务。</p>
                    )}
                  </div>
                </div>
              </div>
            </Panel>

            <details className={cn(surfaceClass, "group overflow-hidden")}>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 text-sm font-semibold text-slate-900 outline-none transition hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60 sm:px-6">
                更多画像细节
                <span className="text-xs font-medium text-slate-400 group-open:hidden">已收起</span>
                <span className="hidden text-xs font-medium text-slate-400 group-open:inline">点击收起</span>
              </summary>
              <div className="grid gap-6 border-t border-slate-200/80 px-5 py-5 dark:border-slate-800/80 sm:px-6 lg:grid-cols-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">掌握分布</p>
                  <MasteryDistribution states={states} />
                </div>
                <div className="space-y-6">
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
                <div className="space-y-3">
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
                    <p key={note} className="rounded-lg bg-slate-50/80 px-3 py-2 text-sm leading-6 text-slate-600 dark:bg-slate-950/40 dark:text-slate-300">
                      {note}
                    </p>
                  ))}
                </div>
              </div>
            </details>
          </>
        ) : (
          <Panel title="画像正在建立" description="暂无测验、掌握度或复习记录，页面先保持轻量。">
            <div className="mt-5 flex flex-col gap-4 rounded-lg border border-dashed border-slate-200 bg-slate-50/80 px-5 py-6 dark:border-slate-800 dark:bg-slate-950/40 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">还没有可诊断的数据。</p>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
                  完成一次练习后，这里会展开学习重点和复习任务。
                </p>
              </div>
              <Button
                type="button"
                onClick={() => navigate(buildCoursePath(courseId, "exams"))}
                className="h-10 shrink-0 px-4"
              >
                去练习
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
