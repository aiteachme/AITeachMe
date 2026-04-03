import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Award, BookOpen, Loader2, Target, TrendingUp, Sparkles } from "lucide-react";
import { motion } from "framer-motion";

import { apiClient } from "../api/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import type {
  KnowledgeNodeResponse,
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
  TeachingUnitResponse,
} from "../api/generated/model";
import type { ApiResponse } from "../api/types";
import { fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS } from "../lib/knowledgeOverview";

interface DisplayMasteryState extends MasteryStateResponse {
  display_name: string;
}

interface SubjectProfileSummary {
  generated_at: string;
  avg_unit_mastery?: number | null;
  avg_node_mastery?: number | null;
  weak_unit_count: number;
  weak_node_count: number;
  pending_review_count: number;
  due_review_count: number;
  preferred_question_types: string[];
  recommended_question_types: string[];
  recommended_exam_mode: string;
  recommended_question_count?: number | null;
  difficulty_focus: string;
  focus_teaching_unit_ids: number[];
  focus_node_ids: number[];
  question_type_accuracy: Record<string, number>;
  difficulty_accuracy: Record<string, number>;
  notes: string[];
}

interface UserProfileSummary {
  generated_at: string;
  active_subject_count: number;
  active_subject_ids: string[];
  recent_subject_ids: string[];
  preferred_question_types: string[];
  preferred_exam_modes: string[];
  dominant_exam_mode: string;
  explanation_style: string;
  pace_preference: string;
  consistency_level: string;
  pending_review_count: number;
  due_review_count: number;
  notes: string[];
}

type ExtendedMasteryOverviewResponse = MasteryOverviewResponse & {
  subject_profile?: SubjectProfileSummary | null;
  user_profile?: UserProfileSummary | null;
};

const WEAK_THRESHOLD = 0.8;
const PAPER_CARD = "rounded-2xl border border-slate-200 bg-white shadow-sm transition-all";

function PageWrapper({
  children,
  title,
  subtitle,
  badgeText,
}: {
  children: React.ReactNode;
  title: React.ReactNode;
  subtitle?: string;
  badgeText?: string;
}) {
  return (
    <div className="flex-1 w-full flex flex-col items-center px-4 pt-16 md:pt-20 pb-16 relative overflow-x-hidden min-h-[100dvh] bg-slate-50/50">
      <div className="absolute inset-0 overflow-hidden pointer-events-none block">
        <div
          className="absolute -top-[10%] -left-[10%] h-[500px] w-[500px] animate-pulse rounded-full bg-blue-500/10 blur-3xl"
          style={{ animationDuration: "7s" }}
        />
        <div
          className="absolute bottom-0 -right-[5%] h-[600px] w-[600px] animate-pulse rounded-full bg-slate-800/5 blur-3xl"
          style={{ animationDuration: "11s" }}
        />
      </div>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-5xl space-y-6"
      >
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
    forgetting_due: "遗忘到期",
    repeated_wrong: "重复错误",
    prereq_gap: "前置薄弱",
    newly_learned: "新学内容待巩固",
  };
  if (!reason) return "";
  return mapping[reason] ?? reason;
}

function formatDate(value?: string | null): string {
  if (!value) return "尽快";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleDateString("zh-CN");
}

function toSortableTime(value?: string | null): number {
  if (!value) return Number.MAX_SAFE_INTEGER;
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? Number.MAX_SAFE_INTEGER : timestamp;
}

function resolveMasteryTargetId(state: MasteryStateResponse): number {
  if (state.target_kind === "node") return state.knowledge_node_id ?? 0;
  return state.teaching_unit_id ?? 0;
}

function resolveReviewTaskTargetId(task: ReviewTaskResponse): number {
  if (task.target_kind === "node") return task.knowledge_node_id ?? 0;
  return task.teaching_unit_id ?? 0;
}

function formatQuestionTypeLabel(value?: string | null): string {
  const mapping: Record<string, string> = {
    single_choice: "单选题",
    fill_blank: "填空题",
    short_answer: "简答题",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatExamModeLabel(value?: string | null): string {
  const mapping: Record<string, string> = {
    web_practice: "测验",
    paper_exam: "考试卷",
    diagnostic: "诊断测验",
    practice: "日常练习",
    weakpoint_boost: "薄弱强化",
    review: "复习模式",
    mock_final: "模拟期末",
    real_exam: "正式考试",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatDifficultyFocus(value?: string | null): string {
  const mapping: Record<string, string> = {
    easy: "偏基础",
    medium: "中等强度",
    mixed: "混合梯度",
    hard: "偏挑战",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatExplanationStyle(value?: string | null): string {
  const mapping: Record<string, string> = {
    guided: "引导式",
    concise: "精炼式",
    balanced: "平衡式",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatPacePreference(value?: string | null): string {
  const mapping: Record<string, string> = {
    quick_cycle: "快节奏循环",
    steady: "稳步推进",
    deep_dive: "深度钻研",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatConsistencyLevel(value?: string | null): string {
  const mapping: Record<string, string> = {
    high: "高频稳定",
    steady: "比较稳定",
    building: "正在建立",
  };
  if (!value) return "--";
  return mapping[value] ?? value;
}

function formatLabelList(values: string[], fallback = "--"): string {
  return values.length > 0 ? values.join("、") : fallback;
}

async function fetchMasteryOverview(subject: string): Promise<ExtendedMasteryOverviewResponse> {
  const res = await apiClient<ApiResponse<ExtendedMasteryOverviewResponse>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/profile/mastery`,
  });
  return (
    res.data ?? {
      subject,
      user_id: "",
      weak_unit_count: 0,
      weak_node_count: 0,
      unit_states: [],
      node_states: [],
      subject_profile: null,
      user_profile: null,
    }
  );
}

async function fetchReviewTasks(subject: string): Promise<ReviewTaskResponse[]> {
  const res = await apiClient<ApiResponse<ReviewTaskResponse[]>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/profile/review/tasks`,
  });
  return res.data ?? [];
}

async function fetchKnowledgeMappings(
  subject: string,
): Promise<{ nodes: KnowledgeNodeResponse[]; units: TeachingUnitResponse[] }> {
  const overview = await fetchKnowledgeOverview(subject, OVERVIEW_INCLUDE_PRESETS.profileMappings);
  return {
    nodes: overview?.graph?.nodes ?? [],
    units: overview?.units ?? [],
  };
}

export function ProfilePage() {
  const { subjectId = "" } = useParams();

  const {
    data: overview,
    isLoading: masteryLoading,
    error: masteryError,
  } = useQuery({
    queryKey: ["profile-mastery-overview", subjectId],
    queryFn: () => fetchMasteryOverview(subjectId),
    enabled: !!subjectId,
  });

  const {
    data: reviewTasks = [],
    isLoading: tasksLoading,
    error: tasksError,
  } = useQuery({
    queryKey: ["profile-review-tasks", subjectId],
    queryFn: () => fetchReviewTasks(subjectId),
    enabled: !!subjectId,
  });

  const { data: knowledgeMappings } = useQuery({
    queryKey: ["profile-knowledge-mappings", subjectId],
    queryFn: () => fetchKnowledgeMappings(subjectId),
    enabled: !!subjectId,
    retry: 0,
  });

  const knowledgeNodes = knowledgeMappings?.nodes ?? [];
  const teachingUnits = knowledgeMappings?.units ?? [];
  const subjectProfile = overview?.subject_profile ?? null;
  const userProfile = overview?.user_profile ?? null;

  const isLoading = masteryLoading || tasksLoading;

  const hasNodeStates = (overview?.node_states?.length ?? 0) > 0;
  const baseStates = hasNodeStates ? overview?.node_states ?? [] : overview?.unit_states ?? [];

  const nodeNameMap = useMemo(
    () => new Map<number, string>(knowledgeNodes.map((n) => [n.id, n.canonical_name])),
    [knowledgeNodes],
  );
  const unitNameMap = useMemo(
    () => new Map<number, string>(teachingUnits.map((u) => [u.id, u.canonical_name])),
    [teachingUnits],
  );

  const displayStates = useMemo<DisplayMasteryState[]>(() => {
    return [...baseStates]
      .map((state) => {
        const targetId = resolveMasteryTargetId(state);
        const mappedName = hasNodeStates ? nodeNameMap.get(targetId) : unitNameMap.get(targetId);
        return {
          ...state,
          display_name:
            mappedName ?? (hasNodeStates ? `知识点 #${targetId}` : `教学单元 #${targetId}`),
        };
      })
      .sort((a, b) => {
        if (a.mastery_score !== b.mastery_score) return a.mastery_score - b.mastery_score;
        if (a.review_priority !== b.review_priority) return b.review_priority - a.review_priority;
        return b.total_attempts - a.total_attempts;
      });
  }, [baseStates, hasNodeStates, nodeNameMap, unitNameMap]);

  const weakStates = useMemo(
    () => displayStates.filter((item) => item.mastery_score < WEAK_THRESHOLD).slice(0, 5),
    [displayStates],
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
  const focusUnitNames = (subjectProfile?.focus_teaching_unit_ids ?? [])
    .slice(0, 4)
    .map((id) => unitNameMap.get(id) ?? `教学单元 #${id}`);
  const focusNodeNames = (subjectProfile?.focus_node_ids ?? [])
    .slice(0, 5)
    .map((id) => nodeNameMap.get(id) ?? `知识点 #${id}`);

  const suggestions = useMemo(() => {
    const pendingTasks = [...reviewTasks]
      .filter((task) => task.status === "pending")
      .sort((a, b) => {
        if (a.priority !== b.priority) return b.priority - a.priority;
        return toSortableTime(a.scheduled_at) - toSortableTime(b.scheduled_at);
      });

    if (pendingTasks.length > 0) {
      return pendingTasks.slice(0, 3).map((task) => {
        const targetId = resolveReviewTaskTargetId(task);
        const mappedName =
          task.target_kind === "node"
            ? nodeNameMap.get(targetId)
            : unitNameMap.get(targetId);
        const displayName =
          mappedName ??
          (task.target_kind === "node" ? `知识点 #${targetId}` : `教学单元 #${targetId}`);
        const reason = formatReason(task.reason);
        const reasonText = reason ? `（${reason}）` : "";
        return `优先复习「${displayName}」${reasonText}，建议在 ${formatDate(task.scheduled_at)} 前完成。`;
      });
    }

    if (weakStates.length > 0) {
      return weakStates.slice(0, 2).map((item) => {
        return `优先加强「${item.display_name}」，当前掌握度约 ${clampPercent(item.mastery_score)}%，建议先做针对练习再复盘错因。`;
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
      title="学习画像"
      subtitle="基于作答记录、复习任务与掌握度状态，为当前学科生成更清晰的学习 Profile。"
      badgeText="Profile"
    >
      <div className="space-y-8">
        {!!errorMessage && (
          <Card className={PAPER_CARD}>
            <CardContent className="pt-6">
              <p className="text-sm text-amber-700">{errorMessage}</p>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>{"学科级画像"}</CardTitle>
              <CardDescription>{"这门课当前更适合怎么学，怎么练。"}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p>
                {"推荐模式："}
                <span className="font-medium text-slate-900">{formatExamModeLabel(subjectProfile?.recommended_exam_mode)}</span>
                {" · "}
                {"建议题量："}
                <span className="font-medium text-slate-900">{subjectProfile?.recommended_question_count ?? "--"} {"题"}</span>
              </p>
              <p>
                {"题型偏向："}
                <span className="font-medium text-slate-900">{formatLabelList((subjectProfile?.recommended_question_types ?? []).map(formatQuestionTypeLabel))}</span>
              </p>
              <p>
                {"难度焦点："}
                <span className="font-medium text-slate-900">{formatDifficultyFocus(subjectProfile?.difficulty_focus)}</span>
              </p>
              <p>
                {"待复习："}
                <span className="font-medium text-slate-900">{subjectProfile?.due_review_count ?? 0}</span>
                {" / 总待处理 "}
                <span className="font-medium text-slate-900">{subjectProfile?.pending_review_count ?? 0}</span>
              </p>
              <p>
                {"聚焦单元："}
                <span className="font-medium text-slate-900">{formatLabelList(focusUnitNames)}</span>
              </p>
              <p>
                {"聚焦知识点："}
                <span className="font-medium text-slate-900">{formatLabelList(focusNodeNames)}</span>
              </p>
            </CardContent>
          </Card>

          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>{"用户级画像"}</CardTitle>
              <CardDescription>{"跨学科相对稳定的学习偏好。"}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p>
                {"偏好题型："}
                <span className="font-medium text-slate-900">{formatLabelList((userProfile?.preferred_question_types ?? []).map(formatQuestionTypeLabel))}</span>
              </p>
              <p>
                {"常用模式："}
                <span className="font-medium text-slate-900">{formatLabelList((userProfile?.preferred_exam_modes ?? []).map(formatExamModeLabel))}</span>
              </p>
              <p>
                {"讲解风格："}
                <span className="font-medium text-slate-900">{formatExplanationStyle(userProfile?.explanation_style)}</span>
              </p>
              <p>
                {"学习节奏："}
                <span className="font-medium text-slate-900">{formatPacePreference(userProfile?.pace_preference)}</span>
              </p>
              <p>
                {"稳定度："}
                <span className="font-medium text-slate-900">{formatConsistencyLevel(userProfile?.consistency_level)}</span>
              </p>
              <p>
                {"跨学科待复习："}
                <span className="font-medium text-slate-900">{userProfile?.due_review_count ?? 0}</span>
                {" / 总待处理 "}
                <span className="font-medium text-slate-900">{userProfile?.pending_review_count ?? 0}</span>
              </p>
            </CardContent>
          </Card>
        </div>

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
                  <p className="mt-1 text-xs text-slate-500">项</p>
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

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>知识点掌握度</CardTitle>
              <CardDescription>各知识点学习情况</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {displayStates.length === 0 && <p className="py-4 text-center text-sm text-slate-400">暂无数据</p>}
              {displayStates.map((item) => {
                const pct = clampPercent(item.mastery_score);
                const targetId = resolveMasteryTargetId(item);
                return (
                  <div key={`${item.target_kind}-${targetId}`}>
                    <div className="mb-1.5 flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-medium text-slate-700">{item.display_name}</span>
                      <span className="shrink-0 text-sm text-slate-500">
                        {pct}% · {item.correct_attempts}/{item.total_attempts}
                      </span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-slate-900 transition-all" style={{ width: `${pct}%` }} />
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
                {weakStates.length === 0 && <p className="py-4 text-center text-sm text-slate-400">暂无数据</p>}
                <div className="space-y-3">
                  {weakStates.map((item) => (
                    <div
                      key={`${item.target_kind}-${resolveMasteryTargetId(item)}`}
                      className="flex items-center justify-between rounded-lg bg-slate-50 p-3"
                    >
                      <span className="text-sm font-medium text-slate-700">{item.display_name}</span>
                      <span className="text-sm font-medium text-orange-600">{clampPercent(item.mastery_score)}%</span>
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
      </div>
    </PageWrapper>
  );
}
