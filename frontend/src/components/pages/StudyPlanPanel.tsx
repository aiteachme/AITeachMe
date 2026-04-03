import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, ListChecks, Loader2, Route, Target } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type { ApiResponse } from "../../api/types";

interface StudyPlanRequest {
  item_id?: string;
  completed?: boolean;
}

interface StudyPlanItem {
  id: string;
  title: string;
  summary: string;
  duration_minutes: number;
  depends_on_ids: string[];
  theme_titles: string[];
  unit_ids: number[];
  doc_anchor?: string | null;
  completed: boolean;
}

interface StudyPlanPhase {
  id: string;
  title: string;
  summary: string;
  duration_minutes: number;
  completed_items: number;
  total_items: number;
  items: StudyPlanItem[];
}

export interface StudyPlanData {
  subject: string;
  generated_at: string;
  digest_mode?: string | null;
  mode_reason?: string | null;
  total_items: number;
  completed_items: number;
  phases: StudyPlanPhase[];
}

async function requestStudyPlan(subject: string, payload: StudyPlanRequest = {}): Promise<StudyPlanData> {
  const response = await apiClient<ApiResponse<StudyPlanData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/study-plan`,
    data: payload,
  });
  return (
    response.data ?? {
      subject,
      generated_at: new Date().toISOString(),
      total_items: 0,
      completed_items: 0,
      phases: [],
    }
  );
}

function modeLabel(mode?: string | null): string {
  if (mode === "sprint") {
    return "速成课";
  }
  if (mode === "systematic") {
    return "系统课";
  }
  return "学习计划";
}

function minutesLabel(minutes: number): string {
  if (minutes <= 0) {
    return "灵活安排";
  }
  if (minutes < 60) {
    return `${minutes} 分钟`;
  }
  const hours = Math.floor(minutes / 60);
  const remain = minutes % 60;
  return remain > 0 ? `${hours} 小时 ${remain} 分钟` : `${hours} 小时`;
}

export function StudyPlanPanel({
  subject,
  compact = false,
  className = "",
}: {
  subject: string;
  compact?: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();

  const studyPlanQuery = useQuery({
    queryKey: ["study-plan", subject],
    queryFn: () => requestStudyPlan(subject),
    enabled: Boolean(subject),
  });

  const checklistMutation = useMutation({
    mutationFn: ({ itemId, completed }: { itemId: string; completed: boolean }) =>
      requestStudyPlan(subject, {
        item_id: itemId,
        completed,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["study-plan", subject], data);
    },
  });

  if (!subject) {
    return null;
  }

  if (studyPlanQuery.isLoading) {
    return (
      <section className={`rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm ${className}`.trim()}>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在整理学习计划...
        </div>
      </section>
    );
  }

  if (studyPlanQuery.isError) {
    return (
      <section className={`rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4 shadow-sm ${className}`.trim()}>
        <p className="text-sm text-rose-700">{getApiErrorMessage(studyPlanQuery.error, "获取学习计划失败。")}</p>
      </section>
    );
  }

  const studyPlan = studyPlanQuery.data;
  if (!studyPlan) {
    return null;
  }

  const visiblePhases = compact ? studyPlan.phases.slice(0, 2) : studyPlan.phases;
  const progressRatio = studyPlan.total_items > 0 ? studyPlan.completed_items / studyPlan.total_items : 0;

  return (
    <section className={`rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm ${className}`.trim()}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-slate-900">
            <ListChecks className="h-4 w-4 text-emerald-600" />
            <p className="text-sm font-semibold">学习计划 + Checklist</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {studyPlan.mode_reason?.trim() ||
              "系统会根据当前的主题树、先修关系和 digest 模式，给出可执行的学习顺序。"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] text-slate-600">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium">{modeLabel(studyPlan.digest_mode)}</span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1">
            {studyPlan.completed_items}/{studyPlan.total_items} 已完成
          </span>
        </div>
      </div>

      <div className="mt-4">
        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#0f766e_0%,#22c55e_100%)] transition-[width] duration-300"
            style={{ width: `${Math.round(progressRatio * 100)}%` }}
          />
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {visiblePhases.map((phase) => (
          <div key={phase.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-900">{phase.title}</p>
                <p className="mt-1 text-xs leading-5 text-slate-600">{phase.summary}</p>
              </div>
              <div className="space-y-1 text-[11px] text-slate-500">
                <div className="flex items-center justify-end gap-1">
                  <Clock3 className="h-3 w-3" />
                  <span>{minutesLabel(phase.duration_minutes)}</span>
                </div>
                <div className="flex items-center justify-end gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  <span>
                    {phase.completed_items}/{phase.total_items}
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-3 space-y-2">
              {(compact ? phase.items.slice(0, 2) : phase.items).map((item) => {
                const disabled =
                  checklistMutation.isPending && checklistMutation.variables?.itemId === item.id;
                return (
                  <label
                    key={item.id}
                    className={`flex gap-3 rounded-lg border px-3 py-2 transition-colors ${
                      item.completed ? "border-emerald-200 bg-emerald-50/70" : "border-slate-200 bg-white"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={item.completed}
                      disabled={disabled}
                      onChange={() =>
                        checklistMutation.mutate({
                          itemId: item.id,
                          completed: !item.completed,
                        })
                      }
                      className="mt-0.5 rounded border-slate-300"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-slate-800">{item.title}</p>
                        {item.doc_anchor ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                            <Target className="h-3 w-3" />
                            #{item.doc_anchor}
                          </span>
                        ) : null}
                      </div>

                      <p className="mt-1 text-xs leading-5 text-slate-600">{item.summary}</p>

                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                        <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5">
                          <Clock3 className="h-3 w-3" />
                          {minutesLabel(item.duration_minutes)}
                        </span>
                        {item.depends_on_ids.length > 0 ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5">
                            <Route className="h-3 w-3" />
                            先完成上一阶段
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
