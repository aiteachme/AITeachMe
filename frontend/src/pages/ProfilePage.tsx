import { useMemo, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BarChart3, BookOpenCheck, CalendarClock, CheckCircle2, Clock3, Gauge, Sparkles, Target } from "lucide-react";
import { useParams } from "react-router-dom";

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
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";

const surfaceClass =
  "rounded-lg border border-slate-200/80 bg-white/85 shadow-sm dark:border-slate-800/80 dark:bg-slate-900/80";

function formatPercent(value?: number | null): string {
  return value != null && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "--";
}

function formatToken(value?: string | null, fallback = "--"): string {
  const text = String(value ?? "").trim();
  return text ? text.replace(/_/g, " ") : fallback;
}

function StatTile({
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
    <div className={cn(surfaceClass, "p-4")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">{value}</p>
        </div>
        <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", tone)}>
          {icon}
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-slate-400">{hint}</p>
    </div>
  );
}

function ProfileInfoRow({
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
        <p className="mt-1 break-words text-sm font-medium leading-5 text-slate-900 dark:text-slate-100">{value}</p>
      </div>
    </div>
  );
}

export function ProfilePage() {
  const { courseId } = useParams();
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
  const weakStates = [...states]
    .sort((left, right) => left.mastery_score - right.mastery_score)
    .slice(0, 8);

  if (!courseId) {
    return (
      <div className="min-h-full pb-24 sm:pb-12">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          缺少课程标识，暂时无法加载学习画像。
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full pb-24 sm:pb-12">
      <div className="flex flex-col gap-6">
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
                汇总知识点掌握度、测验表现和复习任务，帮你看清当前学习状态和下一步练习重点。
              </p>
            </div>
          </div>

          <div className={cn(surfaceClass, "max-w-xl px-4 py-3")}>
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">下一次练习建议</p>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  使用 {formatToken(courseProfile?.recommended_exam_mode, "web practice")}，约{" "}
                  {courseProfile?.recommended_question_count ?? 10} 题，重点覆盖{" "}
                  {formatToken(courseProfile?.difficulty_focus, "medium")} 难度。
                </p>
              </div>
            </div>
          </div>
        </section>

        {(masteryQuery.error || reviewsQuery.error) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="平均掌握度"
            value={formatPercent(courseProfile?.avg_mastery)}
            hint={`已记录 ${states.length} 个知识点`}
            icon={<Gauge className="h-4 w-4" />}
            tone="bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
          />
          <StatTile
            label="薄弱知识点"
            value={String(mastery?.weak_knowledge_unit_count ?? 0)}
            hint="优先覆盖低掌握度和高复习优先级知识点"
            icon={<Target className="h-4 w-4" />}
            tone="bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300"
          />
          <StatTile
            label="待复习"
            value={String(courseProfile?.pending_review_count ?? reviewTasks.length)}
            hint={`其中到期 ${courseProfile?.due_review_count ?? 0} 个`}
            icon={<CalendarClock className="h-4 w-4" />}
            tone="bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300"
          />
          <StatTile
            label="学习节奏"
            value={formatToken(userProfile?.pace_preference, "steady")}
            hint={`稳定度 ${formatToken(userProfile?.consistency_level, "building")}`}
            icon={<BookOpenCheck className="h-4 w-4" />}
            tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300"
          />
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
          <div className={cn(surfaceClass, "p-5 sm:p-6")}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">重点知识点</h2>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">按掌握度从低到高排序，适合优先进入练习。</p>
              </div>
              <div className="shrink-0 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                推荐难度 {formatToken(courseProfile?.difficulty_focus, "medium")}
              </div>
            </div>

            <div className="mt-5 space-y-3">
              {masteryQuery.isLoading && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
                  正在加载画像数据...
                </div>
              )}

              {!masteryQuery.isLoading && weakStates.length === 0 && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                  暂时没有薄弱知识点，已经可以进入更完整的综合练习。
                </div>
              )}

              {weakStates.map((state: MasteryStateResponse) => {
                const masteryScore = Math.max(0, Math.min(1, state.mastery_score));
                const reviewPriority = Math.round(state.review_priority * 100);
                return (
                  <div key={state.id} className="rounded-lg border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800/80 dark:bg-slate-950/30">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div className="min-w-0">
                        <p className="text-base font-medium text-slate-900 dark:text-slate-100">
                          {state.knowledge_unit_name ?? `KnowledgeUnit ${state.knowledge_unit_id}`}
                        </p>
                        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                          {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次 · 正确{" "}
                          {state.correct_attempts} 次
                        </p>
                      </div>
                      <div className="shrink-0 text-sm font-medium text-slate-600 dark:text-slate-300">
                        优先级 {Number.isFinite(reviewPriority) ? `${reviewPriority}%` : "--"}
                      </div>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          masteryScore < 0.4 && "bg-rose-500",
                          masteryScore >= 0.4 && masteryScore < 0.7 && "bg-amber-500",
                          masteryScore >= 0.7 && "bg-emerald-500",
                        )}
                        style={{ width: `${Math.max(6, masteryScore * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col gap-6">
            <section className={cn(surfaceClass, "p-5 sm:p-6")}>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">个性化建议</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">根据历史练习偏好生成，数据越多越准确。</p>
              <div className="mt-4 space-y-3">
                <ProfileInfoRow
                  label="常用题型"
                  value={userProfile?.preferred_question_types?.map((item) => formatToken(item)).join(", ") || "暂无历史数据"}
                  icon={<BookOpenCheck className="h-4 w-4" />}
                />
                <ProfileInfoRow
                  label="推荐题型"
                  value={courseProfile?.recommended_question_types?.map((item) => formatToken(item)).join(", ") || "single choice, short answer"}
                  icon={<Target className="h-4 w-4" />}
                />
                <ProfileInfoRow
                  label="讲解风格"
                  value={formatToken(userProfile?.explanation_style, "balanced")}
                  icon={<Sparkles className="h-4 w-4" />}
                />
                <ProfileInfoRow
                  label="常用模式"
                  value={userProfile?.preferred_exam_modes?.map((item) => formatToken(item)).join(", ") || formatToken(userProfile?.dominant_exam_mode)}
                  icon={<Gauge className="h-4 w-4" />}
                />
              </div>
            </section>

            <section className={cn(surfaceClass, "p-5 sm:p-6")}>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-100">待复习任务</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">完成后会立即刷新画像</p>
                </div>
                <Clock3 className="h-5 w-5 text-slate-400 dark:text-slate-500" />
              </div>

              <div className="mt-5 space-y-3">
                {reviewsQuery.isLoading && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
                    正在加载复习任务...
                  </div>
                )}

                {!reviewsQuery.isLoading && reviewTasks.length === 0 && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                    当前没有待处理复习任务。
                  </div>
                )}

                {reviewTasks.map((task: ReviewTaskResponse) => (
                  <div key={task.id} className="rounded-lg border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800/80 dark:bg-slate-950/30">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {task.knowledge_unit_name ?? `KnowledgeUnit ${task.knowledge_unit_id}`}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {task.reason || "复习巩固"} · {formatToken(task.knowledge_unit_type, "知识点")}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        onClick={() => completeReview.mutate({ courseId, taskId: task.id })}
                        disabled={completeReview.isPending}
                      >
                        完成
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className={cn(surfaceClass, "p-5 sm:p-6")}>
              <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                <AlertCircle className="h-4 w-4 text-amber-500" />
                <h2 className="text-lg font-semibold">画像备注</h2>
              </div>
              <div className="mt-4 space-y-2">
                {(courseProfile?.notes ?? userProfile?.notes ?? []).map((note: string) => (
                  <div key={note} className="rounded-lg bg-slate-50/80 px-4 py-3 text-sm leading-6 text-slate-600 dark:bg-slate-950/40 dark:text-slate-300">
                    {note}
                  </div>
                ))}
                {!(courseProfile?.notes?.length || userProfile?.notes?.length) && (
                  <div className="rounded-lg bg-slate-50/80 px-4 py-3 text-sm leading-6 text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">
                    还没有足够的行为数据，先完成几次练习会更准。
                  </div>
                )}
              </div>
            </section>
          </div>
        </section>

        <div className="flex items-start gap-2 rounded-lg border border-emerald-200/80 bg-emerald-50/80 px-4 py-3 text-sm leading-6 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <span>当前画像基于知识点掌握状态、测验记录和复习任务生成。</span>
        </div>
      </div>
    </div>
  );
}
