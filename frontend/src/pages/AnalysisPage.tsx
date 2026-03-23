import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Award, BookOpen, Loader2, Target, TrendingUp, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import {
  apiGetMasteryOverviewApiV1SubjectsSubjectMasteryGet,
  apiGetReviewTasksApiV1SubjectsSubjectReviewTasksGet,
} from "../api/generated/assessment";
import {
  graphNodesQueryApiV1SubjectsSubjectKnowledgeGraphNodesQueryPost,
  unitsQueryApiV1SubjectsSubjectKnowledgeUnitsQueryPost,
} from "../api/generated/knowledge";
import type {
  KnowledgeNodeResponse,
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
  TeachingUnitResponse,
} from "../api/generated/model";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

interface DisplayMasteryState extends MasteryStateResponse {
  display_name: string;
}

const WEAK_THRESHOLD = 0.8;

const PAPER_CARD = "rounded-2xl border border-slate-200 bg-white shadow-sm transition-all";

function PageWrapper({ children, title, subtitle, badgeText }: { children: React.ReactNode, title: React.ReactNode, subtitle?: string, badgeText?: string }) {
  return (
    <div className="flex-1 w-full flex flex-col items-center px-4 pt-16 md:pt-20 pb-16 relative overflow-x-hidden min-h-[100dvh] bg-slate-50/50">
      <div className="absolute inset-0 overflow-hidden pointer-events-none block">
        <div className="absolute -top-[10%] -left-[10%] h-[500px] w-[500px] animate-pulse rounded-full bg-blue-500/10 blur-3xl" style={{ animationDuration: "7s" }} />
        <div className="absolute bottom-0 -right-[5%] h-[600px] w-[600px] animate-pulse rounded-full bg-slate-800/5 blur-3xl" style={{ animationDuration: "11s" }} />
      </div>
      <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: "easeOut" }} className="relative z-10 w-full max-w-5xl space-y-6">
        <div className="mb-10 text-center">
          {badgeText && (
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
              <Sparkles className="h-3.5 w-3.5" />
              {badgeText}
            </div>
          )}
          <h1 className="mb-3 text-3xl font-extrabold tracking-tight text-slate-900 md:text-4xl">{title}</h1>
          {subtitle && <p className="mx-auto max-w-2xl text-sm text-slate-500 md:text-base">{subtitle}</p>}
        </div>
        {children}
      </motion.div>
    </div>
  );
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value * 100)));
}

function formatReason(reason?: string | null): string {
  const mapping: Record<string, string> = {
    forgetting_due: "到期遗忘",
    repeated_wrong: "重复错误",
    prereq_gap: "前置薄弱",
    newly_learned: "新学知识待巩固",
  };
  if (!reason) return "";
  return mapping[reason] ?? reason;
}

function formatDate(value: string): string {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleDateString("zh-CN");
}

function extractApiError(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object") {
    return fallback;
  }

  const maybeMessage = (data as { message?: unknown }).message;
  if (typeof maybeMessage === "string" && maybeMessage.trim()) {
    return maybeMessage;
  }

  const maybeDetail = (data as { detail?: unknown }).detail;
  if (Array.isArray(maybeDetail) && maybeDetail.length > 0) {
    const first = maybeDetail[0] as { msg?: unknown };
    if (typeof first?.msg === "string" && first.msg.trim()) {
      return first.msg;
    }
  }

  return fallback;
}

async function fetchMasteryOverview(subject: string): Promise<MasteryOverviewResponse> {
  const res = await apiGetMasteryOverviewApiV1SubjectsSubjectMasteryGet(subject);
  const data = unwrapOrvalResponse(res);
  if (res.status !== 200 || !data) {
    throw new Error(extractApiError(res.data, "掌握度数据加载失败"));
  }
  return data;
}

async function fetchReviewTasks(subject: string): Promise<ReviewTaskResponse[]> {
  const res = await apiGetReviewTasksApiV1SubjectsSubjectReviewTasksGet(subject);
  if (res.status !== 200) {
    throw new Error(extractApiError(res.data, "复习任务加载失败"));
  }
  return unwrapOrvalResponse(res) ?? [];
}

async function fetchKnowledgeNodes(subject: string): Promise<KnowledgeNodeResponse[]> {
  const size = 100;
  const merged: KnowledgeNodeResponse[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const res = await graphNodesQueryApiV1SubjectsSubjectKnowledgeGraphNodesQueryPost(subject, {
      page,
      size,
    });
    if (res.status !== 200) {
      throw new Error(extractApiError(res.data, "知识点映射加载失败"));
    }
    const payload = unwrapOrvalResponse(res);
    const items = payload?.items ?? [];
    merged.push(...items);
    if (page >= (payload?.pages ?? page) || items.length < size) {
      break;
    }
  }
  return merged;
}

async function fetchTeachingUnits(subject: string): Promise<TeachingUnitResponse[]> {
  const size = 100;
  const merged: TeachingUnitResponse[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const res = await unitsQueryApiV1SubjectsSubjectKnowledgeUnitsQueryPost(subject, {
      page,
      size,
    });
    if (res.status !== 200) {
      throw new Error(extractApiError(res.data, "教学单元映射加载失败"));
    }
    const payload = unwrapOrvalResponse(res);
    const items = payload?.items ?? [];
    merged.push(...items);
    if (page >= (payload?.pages ?? page) || items.length < size) {
      break;
    }
  }
  return merged;
}

export function AnalysisPage() {
  const { subjectId = "" } = useParams();

  const {
    data: overview,
    isLoading: masteryLoading,
    error: masteryError,
  } = useQuery({
    queryKey: ["analysis-mastery-overview", subjectId],
    queryFn: () => fetchMasteryOverview(subjectId),
    enabled: !!subjectId,
  });

  const {
    data: reviewTasks = [],
    isLoading: tasksLoading,
    error: tasksError,
  } = useQuery({
    queryKey: ["analysis-review-tasks", subjectId],
    queryFn: () => fetchReviewTasks(subjectId),
    enabled: !!subjectId,
  });

  const { data: knowledgeNodes = [] } = useQuery({
    queryKey: ["analysis-knowledge-nodes", subjectId],
    queryFn: () => fetchKnowledgeNodes(subjectId),
    enabled: !!subjectId,
    retry: 0,
  });

  const { data: teachingUnits = [] } = useQuery({
    queryKey: ["analysis-teaching-units", subjectId],
    queryFn: () => fetchTeachingUnits(subjectId),
    enabled: !!subjectId,
    retry: 0,
  });

  const isLoading = masteryLoading || tasksLoading;

  const hasNodeStates = (overview?.node_states?.length ?? 0) > 0;
  const baseStates = hasNodeStates
    ? overview?.node_states ?? []
    : overview?.unit_states ?? [];

  const nodeNameMap = useMemo(
    () => new Map<number, string>((knowledgeNodes ?? []).map((n) => [n.id, n.canonical_name])),
    [knowledgeNodes]
  );
  const unitNameMap = useMemo(
    () => new Map<number, string>((teachingUnits ?? []).map((u) => [u.id, u.canonical_name])),
    [teachingUnits]
  );

  const displayStates = useMemo<DisplayMasteryState[]>(() => {
    return [...baseStates]
      .map((state) => {
        const mappedName = hasNodeStates
          ? nodeNameMap.get(state.target_id)
          : unitNameMap.get(state.target_id);
        return {
          ...state,
          display_name:
            mappedName ??
            (hasNodeStates ? `知识点 #${state.target_id}` : `教学单元 #${state.target_id}`),
        };
      })
      .sort((a, b) => {
        if (a.mastery_score !== b.mastery_score) {
          return a.mastery_score - b.mastery_score;
        }
        if (a.review_priority !== b.review_priority) {
          return b.review_priority - a.review_priority;
        }
        return b.total_attempts - a.total_attempts;
      });
  }, [baseStates, hasNodeStates, nodeNameMap, unitNameMap]);

  const weakStates = useMemo(
    () => displayStates.filter((item) => item.mastery_score < WEAK_THRESHOLD).slice(0, 5),
    [displayStates]
  );

  const overallMastery = useMemo(() => {
    if (!displayStates.length) return null;
    const attempted = displayStates.filter((item) => item.total_attempts > 0);
    if (attempted.length > 0) {
      const totalAttempts = attempted.reduce((sum, item) => sum + item.total_attempts, 0);
      const totalCorrect = attempted.reduce((sum, item) => sum + item.correct_attempts, 0);
      return totalAttempts > 0 ? totalCorrect / totalAttempts : null;
    }
    return displayStates.reduce((sum, item) => sum + item.mastery_score, 0) / displayStates.length;
  }, [displayStates]);

  const weakCount = hasNodeStates
    ? overview?.weak_node_count ?? weakStates.length
    : overview?.weak_unit_count ?? weakStates.length;

  const suggestions = useMemo(() => {
    const pendingTasks = [...reviewTasks]
      .filter((task) => task.status === "pending")
      .sort((a, b) => {
        if (a.priority !== b.priority) {
          return b.priority - a.priority;
        }
        return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime();
      });

    if (pendingTasks.length > 0) {
      return pendingTasks.slice(0, 3).map((task) => {
        const mappedName =
          task.target_granularity === "node"
            ? nodeNameMap.get(task.target_id)
            : unitNameMap.get(task.target_id);
        const displayName =
          mappedName ??
          (task.target_granularity === "node"
            ? `知识点 #${task.target_id}`
            : `教学单元 #${task.target_id}`);
        const reason = formatReason(task.reason);
        const reasonText = reason ? `（${reason}）` : "";
        return `优先复习「${displayName}」${reasonText}，建议在 ${formatDate(task.scheduled_at)} 前完成。`;
      });
    }

    if (weakStates.length > 0) {
      return weakStates.slice(0, 2).map((item) => {
        return `优先加强「${item.display_name}」，当前掌握度约 ${clampPercent(
          item.mastery_score
        )}%，建议先做针对性练习再复盘错因。`;
      });
    }

    return ["当前没有明显薄弱项，建议保持练习频率并定期回顾重点章节。"];
  }, [reviewTasks, weakStates, nodeNameMap, unitNameMap]);

  const errorMessage = masteryError
    ? masteryError instanceof Error
      ? masteryError.message
      : "掌握度数据加载失败，请稍后重试"
    : tasksError
    ? tasksError instanceof Error
      ? tasksError.message
      : "复习任务加载失败，请稍后重试"
    : "";

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32 text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        加载中...
      </div>
    );
  }

  return (
    <PageWrapper
      title="数据分析引擎"
      subtitle="基于微观作答记录与能力模型状态生成您的个性化学习画像"
      badgeText="洞悉学习轨迹"
    >
      <div className="space-y-8">
        {!!errorMessage && (
          <Card className={PAPER_CARD}>
          <CardContent className="pt-6">
            <p className="text-sm text-amber-700">{errorMessage}</p>
          </CardContent>
        </Card>
      )}

        <div className="grid gap-6 md:grid-cols-3">
          <Card className={PAPER_CARD}>
            <CardHeader className="pb-3">
            <CardDescription>总体掌握度</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <p className="text-3xl font-bold text-slate-900">
                {overallMastery != null ? `${clampPercent(overallMastery)}%` : "--"}
              </p>
              <TrendingUp className="h-8 w-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

          <Card className={PAPER_CARD}>
            <CardHeader className="pb-3">
            <CardDescription>已覆盖知识点</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">{displayStates.length}</p>
                <p className="mt-1 text-xs text-slate-500">个</p>
              </div>
              <Target className="h-8 w-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

          <Card className={PAPER_CARD}>
            <CardHeader className="pb-3">
            <CardDescription>薄弱知识点</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-orange-500">{weakCount}</p>
                <p className="mt-1 text-xs text-slate-500">需加强</p>
              </div>
              <Award className="h-8 w-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>
      </div>

        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className={PAPER_CARD}>
            <CardHeader>
            <CardTitle>知识点掌握度</CardTitle>
            <CardDescription>各知识点学习情况</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {displayStates.length === 0 && (
              <p className="py-4 text-center text-sm text-slate-400">暂无数据</p>
            )}
            {displayStates.map((item) => {
              const pct = clampPercent(item.mastery_score);
              return (
                <div key={`${item.granularity}-${item.target_id}`}>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-medium text-slate-700">
                      {item.display_name}
                    </span>
                    <span className="shrink-0 text-sm text-slate-500">
                      {pct}% · {item.correct_attempts}/{item.total_attempts}
                    </span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full bg-slate-900 transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

          <div className="space-y-6">
            <Card className={PAPER_CARD}>
              <CardHeader>
              <CardTitle>薄弱知识点</CardTitle>
              <CardDescription>需要加强练习的内容</CardDescription>
            </CardHeader>
            <CardContent>
              {weakStates.length === 0 && (
                <p className="py-4 text-center text-sm text-slate-400">暂无数据</p>
              )}
              <div className="space-y-3">
                {weakStates.map((item) => (
                  <div
                    key={`${item.granularity}-${item.target_id}`}
                    className="flex items-center justify-between rounded-lg bg-slate-50 p-3"
                  >
                    <span className="text-sm font-medium text-slate-700">{item.display_name}</span>
                    <span className="text-sm font-medium text-orange-600">
                      {clampPercent(item.mastery_score)}%
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

            <Card className={PAPER_CARD}>
              <CardHeader>
              <CardTitle>复习建议</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {suggestions.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-slate-600">
                    <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                    {item}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </PageWrapper>
  );
}
