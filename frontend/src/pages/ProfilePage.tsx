import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Clock3, Sparkles } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey,
  getReviewTasksApiV1SubjectsSubjectProfileReviewsGetQueryKey,
  useCompleteReviewApiV1SubjectsSubjectProfileReviewsTaskIdCompletePost,
  useMasteryOverviewApiV1SubjectsSubjectProfileMasteryGet,
  useReviewTasksApiV1SubjectsSubjectProfileReviewsGet,
} from "../api/generated/profile";
import type { MasteryOverviewResponse, MasteryStateResponse, ReviewTaskResponse } from "../api/generated/model";
import { getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { cn } from "../lib/utils";

function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p>
      <p className="mt-2 text-sm text-slate-600">{hint}</p>
    </div>
  );
}

export function ProfilePage() {
  const { subjectId } = useParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const masteryQuery = useMasteryOverviewApiV1SubjectsSubjectProfileMasteryGet(subjectId ?? "");
  const reviewsQuery = useReviewTasksApiV1SubjectsSubjectProfileReviewsGet(subjectId ?? "");

  const mastery = useMemo<MasteryOverviewResponse | null>(
    () => unwrapOrvalResponse<MasteryOverviewResponse>(masteryQuery.data),
    [masteryQuery.data],
  );
  const reviewTasks = useMemo<ReviewTaskResponse[]>(
    () => unwrapOrvalResponse<ReviewTaskResponse[]>(reviewsQuery.data) ?? [],
    [reviewsQuery.data],
  );

  const completeReview = useCompleteReviewApiV1SubjectsSubjectProfileReviewsTaskIdCompletePost({
    mutation: {
      onSuccess: async () => {
        if (!subjectId) return;
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey(subjectId),
          }),
          queryClient.invalidateQueries({
            queryKey: getReviewTasksApiV1SubjectsSubjectProfileReviewsGetQueryKey(subjectId),
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
  const subjectProfile = mastery?.subject_profile;
  const userProfile = mastery?.user_profile;
  const weakStates = [...states]
    .sort((left, right) => left.mastery_score - right.mastery_score)
    .slice(0, 8);

  if (!subjectId) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900">
          缺少学科标识，暂时无法加载学习画像。
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-500">Profile</p>
              <h1 className="mt-1 text-3xl font-semibold text-slate-950">{subjectId}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                基于当前 KnowledgeUnit 掌握度、最近答题结果和待复习任务生成个性化画像。
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
              <Sparkles className="h-4 w-4" />
              推荐模式 {subjectProfile?.recommended_exam_mode ?? "web_practice"}，建议{" "}
              {subjectProfile?.recommended_question_count ?? 10} 题
            </div>
          </div>
        </section>

        {(masteryQuery.error || reviewsQuery.error) && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
            {getApiErrorMessage(masteryQuery.error ?? reviewsQuery.error, "画像加载失败")}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="平均掌握度"
            value={subjectProfile?.avg_mastery != null ? `${Math.round(subjectProfile.avg_mastery * 100)}%` : "--"}
            hint={`已记录 ${states.length} 个知识点`}
          />
          <StatTile
            label="薄弱知识点"
            value={String(mastery?.weak_knowledge_unit_count ?? 0)}
            hint="优先覆盖低掌握度和高复习优先级知识点"
          />
          <StatTile
            label="待复习"
            value={String(subjectProfile?.pending_review_count ?? reviewTasks.length)}
            hint={`其中到期 ${subjectProfile?.due_review_count ?? 0} 个`}
          />
          <StatTile
            label="学习节奏"
            value={userProfile?.pace_preference ?? "steady"}
            hint={`稳定度 ${userProfile?.consistency_level ?? "building"}`}
          />
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
          <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">重点知识点</h2>
                <p className="mt-1 text-sm text-slate-500">按掌握度从低到高排序</p>
              </div>
              <div className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                推荐难度 {subjectProfile?.difficulty_focus ?? "medium"}
              </div>
            </div>

            <div className="mt-5 space-y-3">
              {masteryQuery.isLoading && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                  正在加载画像数据...
                </div>
              )}

              {!masteryQuery.isLoading && weakStates.length === 0 && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700">
                  暂时没有薄弱知识点，已经可以进入更完整的综合练习。
                </div>
              )}

              {weakStates.map((state: MasteryStateResponse) => {
                const masteryScore = Math.max(0, Math.min(1, state.mastery_score));
                const reviewPriority = Math.round(state.review_priority * 100);
                return (
                  <div key={state.id} className="rounded-lg border border-slate-200 px-4 py-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="text-base font-medium text-slate-900">
                          {state.knowledge_unit_name ?? `KnowledgeUnit ${state.knowledge_unit_id}`}
                        </p>
                        <p className="mt-1 text-sm text-slate-500">
                          {state.knowledge_unit_type ?? "knowledge_unit"} · 尝试 {state.total_attempts} 次 · 正确{" "}
                          {state.correct_attempts} 次
                        </p>
                      </div>
                      <div className="text-sm text-slate-600">
                        优先级 {Number.isFinite(reviewPriority) ? `${reviewPriority}%` : "--"}
                      </div>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
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
            <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-950">个性化建议</h2>
              <div className="mt-4 space-y-3 text-sm text-slate-600">
                <div className="rounded-lg border border-slate-200 px-4 py-3">
                  常用题型 {userProfile?.preferred_question_types?.join(", ") || "暂无历史数据"}
                </div>
                <div className="rounded-lg border border-slate-200 px-4 py-3">
                  推荐题型 {subjectProfile?.recommended_question_types?.join(", ") || "single_choice, short_answer"}
                </div>
                <div className="rounded-lg border border-slate-200 px-4 py-3">
                  讲解风格 {userProfile?.explanation_style ?? "balanced"}
                </div>
                <div className="rounded-lg border border-slate-200 px-4 py-3">
                  常用模式 {userProfile?.preferred_exam_modes?.join(", ") || userProfile?.dominant_exam_mode || "--"}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-950">待复习任务</h2>
                  <p className="mt-1 text-sm text-slate-500">完成后会立即刷新画像</p>
                </div>
                <Clock3 className="h-5 w-5 text-slate-400" />
              </div>

              <div className="mt-5 space-y-3">
                {reviewsQuery.isLoading && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    正在加载复习任务...
                  </div>
                )}

                {!reviewsQuery.isLoading && reviewTasks.length === 0 && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700">
                    当前没有待处理复习任务。
                  </div>
                )}

                {reviewTasks.map((task: ReviewTaskResponse) => (
                  <div key={task.id} className="rounded-lg border border-slate-200 px-4 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium text-slate-900">
                          {task.knowledge_unit_name ?? `KnowledgeUnit ${task.knowledge_unit_id}`}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {task.reason || "复习巩固"} · {task.knowledge_unit_type ?? "knowledge_unit"}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        onClick={() => completeReview.mutate({ subject: subjectId, taskId: task.id })}
                        disabled={completeReview.isPending}
                      >
                        完成
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2 text-slate-900">
                <AlertCircle className="h-4 w-4 text-amber-500" />
                <h2 className="text-lg font-semibold">画像备注</h2>
              </div>
              <div className="mt-4 space-y-2">
                {(subjectProfile?.notes ?? userProfile?.notes ?? []).map((note: string) => (
                  <div key={note} className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    {note}
                  </div>
                ))}
                {!(subjectProfile?.notes?.length || userProfile?.notes?.length) && (
                  <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500">
                    还没有足够的行为数据，先完成几次练习会更准。
                  </div>
                )}
              </div>
            </section>
          </div>
        </section>

        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4" />
          当前画像完全基于 KnowledgeUnit 掌握状态，旧课程层残留已不参与任何逻辑。
        </div>
      </div>
    </div>
  );
}
