import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  BarChart3,
  BookOpenCheck,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Gauge,
  ListChecks,
  Map,
  Sparkles,
  Target,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getMasteryOverviewApiV1CoursesCourseIdProfileMasteryGetQueryKey,
  getReviewTasksApiV1CoursesCourseIdProfileReviewsGetQueryKey,
  useCompleteReviewApiV1CoursesCourseIdProfileReviewsTaskIdCompletePost,
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
} from "../api/generated/profile";
import type { MasteryOverviewResponse, ReviewTaskResponse } from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/utils";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildCoursePath } from "../lib/courseNavigation";
import {
  AccuracyRows,
  FocusStateCard,
  MasteryDistribution,
  MasteryHeatmap,
  MetricTile,
  NextActionCard,
  Panel,
  PreferenceRow,
  PROFILE_SURFACE_CLASS,
  ProfileRiskMatrix,
  ProfileSignalStrip,
  ReviewTaskCard,
  average,
  buildNoteText,
  formatDateTime,
  formatPercent,
  formatToken,
  isReviewDueSoon,
} from "../components/profile";

const surfaceClass = PROFILE_SURFACE_CLASS;
const pageShellClass = "min-h-full px-4 pb-24 pt-20 sm:px-6 sm:pb-12 md:px-8 lg:pt-10";

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
  const dueSoonCount = reviewTasks.filter(isReviewDueSoon).length;
  const totalAttempts = states.reduce((sum, state) => sum + state.total_attempts, 0);
  const correctAttempts = states.reduce((sum, state) => sum + state.correct_attempts, 0);
  const attemptAccuracy = totalAttempts > 0 ? correctAttempts / totalAttempts : null;
  const avgConfidence = average(states.map((state) => state.confidence_score));
  const avgStability = average(states.map((state) => state.stability_score));
  const latestState = [...states]
    .filter((state) => state.last_attempt_at)
    .sort((left, right) => new Date(right.last_attempt_at ?? 0).getTime() - new Date(left.last_attempt_at ?? 0).getTime())[0];
  const profileNotes = [
    ...(courseProfile?.notes ?? []),
    ...(userProfile?.notes ?? []),
  ].map(buildNoteText);

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
      <div className="mx-auto flex w-full max-w-[1560px] flex-col gap-6">
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
          <div className={cn(surfaceClass, "p-5 sm:p-6")}>
            <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
                  <BarChart3 className="h-3.5 w-3.5" />
                  学习画像
                </div>
                <h1 className="mt-4 break-words text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                  {courseName ?? "当前课程"}
                </h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                  把测验、掌握度和复习任务压缩成可执行的学习计划，先看薄弱点，再进入针对性练习。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => navigate(buildCoursePath(courseId, "exams"))}
                  className="h-10 px-4"
                >
                  去练习
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
                  className="h-10 px-4"
                >
                  看知识库
                </Button>
              </div>
            </div>
          </div>

          <NextActionCard
            courseProfile={courseProfile}
            weakCount={mastery?.weak_knowledge_unit_count ?? 0}
            dueCount={dueSoonCount}
            onStartPractice={() => navigate(buildCoursePath(courseId, "exams"))}
          />
        </section>

        {(masteryQuery.error || reviewsQuery.error) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricTile
            label="平均掌握度"
            value={formatPercent(courseProfile?.avg_mastery)}
            hint={`已记录 ${states.length} 个知识点`}
            icon={<Gauge className="h-4 w-4" />}
            tone="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
          />
          <MetricTile
            label="综合正确率"
            value={formatPercent(attemptAccuracy)}
            hint={`累计 ${totalAttempts} 次作答`}
            icon={<Trophy className="h-4 w-4" />}
            tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300"
          />
          <MetricTile
            label="待复习"
            value={String(courseProfile?.pending_review_count ?? reviewTasks.length)}
            hint={`其中到期 ${courseProfile?.due_review_count ?? 0} 个`}
            icon={<CalendarClock className="h-4 w-4" />}
            tone="bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300"
          />
          <MetricTile
            label="稳定度"
            value={formatPercent(avgStability)}
            hint={`置信度 ${formatPercent(avgConfidence)} · 最近 ${formatDateTime(latestState?.last_attempt_at)}`}
            icon={<Activity className="h-4 w-4" />}
            tone="bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300"
          />
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="flex min-w-0 flex-col gap-6">
            <Panel
              title="掌握度分布"
              description="用颜色区分当前学习风险，补强区会优先进入练习和复习队列。"
              action={<TrendingUp className="h-5 w-5 text-slate-400" />}
            >
              <div className="mt-5">
                <ProfileSignalStrip states={states} reviewTasks={reviewTasks} />
              </div>
              <div className="mt-5">
                <ProfileRiskMatrix states={states} reviewTasks={reviewTasks} />
              </div>
              <MasteryDistribution states={states} />
            </Panel>

            <Panel
              title="知识掌握地图"
              description="按薄弱优先排列，数字是掌握度百分比。"
              action={<Map className="h-5 w-5 text-slate-400" />}
            >
              <MasteryHeatmap states={states} focusUnitIds={focusUnitIds} />
            </Panel>

            <Panel
              title="优先知识点"
              description="按推荐覆盖、低掌握度和复习优先级排序。"
              action={
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {sortedFocusStates.length} 个
                </span>
              }
            >
              <div className="mt-5 space-y-3">
                {masteryQuery.isLoading ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
                    正在加载画像数据...
                  </div>
                ) : sortedFocusStates.length ? (
                  sortedFocusStates.map((state) => (
                    <FocusStateCard
                      key={state.id}
                      state={state}
                      focused={focusUnitIds.has(state.knowledge_unit_id)}
                    />
                  ))
                ) : (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                    暂时没有薄弱知识点，已经可以进入更完整的综合练习。
                  </div>
                )}
              </div>
            </Panel>
          </div>

          <aside className="flex min-w-0 flex-col gap-6">
            <Panel
              title="复习队列"
              description="优先处理到期和高优先级任务。"
              action={<Clock3 className="h-5 w-5 text-slate-400" />}
            >
              <div className="mt-5 space-y-3">
                {reviewsQuery.isLoading ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
                    正在加载复习任务...
                  </div>
                ) : sortedReviewTasks.length ? (
                  sortedReviewTasks.map((task) => (
                    <ReviewTaskCard
                      key={task.id}
                      task={task}
                      disabled={completeReview.isPending}
                      onComplete={() => completeReview.mutate({ courseId, taskId: task.id })}
                    />
                  ))
                ) : (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                    当前没有待处理复习任务。
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="练习表现" description="从最近已批改题目中提取。">
              <div className="mt-5 space-y-6">
                <AccuracyRows
                  title="题型正确率"
                  values={courseProfile?.question_type_accuracy}
                  emptyText="还没有足够的题型表现数据。"
                />
                <AccuracyRows
                  title="难度正确率"
                  values={courseProfile?.difficulty_accuracy}
                  emptyText="完成几次不同难度练习后会显示。"
                />
              </div>
            </Panel>

            <Panel title="学习偏好" description="供伴读和诊断引擎选择讲解与出题风格。">
              <div className="mt-5 space-y-3">
                <PreferenceRow
                  label="常用题型"
                  value={userProfile?.preferred_question_types?.map((item) => formatToken(item)).join("、") || "暂无历史数据"}
                  icon={<BookOpenCheck className="h-4 w-4" />}
                />
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
                  label="学习节奏"
                  value={`${formatToken(userProfile?.pace_preference, "稳步推进")} · ${formatToken(userProfile?.consistency_level, "建立中")}`}
                  icon={<ListChecks className="h-4 w-4" />}
                />
              </div>
            </Panel>
          </aside>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="flex items-start gap-2 rounded-lg border border-emerald-200/80 bg-emerald-50/80 px-4 py-3 text-sm leading-6 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>当前画像基于知识点掌握状态、测验记录和复习任务生成，不会在聊天中隐式改写。</span>
          </div>
          <div className="rounded-lg border border-slate-200/80 bg-white/70 px-4 py-3 dark:border-slate-800/80 dark:bg-slate-900/70">
            <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
              <AlertCircle className="h-4 w-4 text-amber-500" />
              <p className="text-sm font-semibold">画像备注</p>
            </div>
            <div className="mt-3 space-y-2">
              {profileNotes.length ? profileNotes.map((note) => (
                <p key={note} className="rounded-lg bg-slate-50/80 px-3 py-2 text-sm leading-6 text-slate-600 dark:bg-slate-950/40 dark:text-slate-300">
                  {note}
                </p>
              )) : (
                <p className="rounded-lg bg-slate-50/80 px-3 py-2 text-sm leading-6 text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
                  还没有足够的行为数据，先完成几次练习会更准。
                </p>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
