import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  GraduationCap,
  Layers3,
  Plus,
  Sparkles,
  Target,
} from "lucide-react";
import { useParams } from "react-router-dom";

import {
  getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey,
  getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey,
  useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet,
  useExamHistoryApiV1SubjectsSubjectExamsHistoryGet,
  useGenerateExamApiV1SubjectsSubjectExamsGeneratePost,
  useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost,
} from "../api/generated/exams";
import type {
  ExamHistoryItem,
  ExamNodeLinkResponse,
  ExamPaperDetailResponse,
  ExamPaperItemResponse,
} from "../api/generated/model";
import { getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey } from "../api/generated/profile";
import { getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

const EXAM_MODES = [
  { value: "web_practice", label: "专项练习", description: "适合快速刷题，聚焦薄弱知识点。" },
  { value: "paper_exam", label: "整卷测试", description: "模拟完整考试节奏，适合阶段检验。" },
] as const;

const DIFFICULTIES = [
  { value: "easy", label: "基础" },
  { value: "medium", label: "标准" },
  { value: "hard", label: "挑战" },
] as const;

const STATUS_META: Record<
  string,
  { label: string; tone: string; accent: string }
> = {
  draft: {
    label: "待完成",
    tone: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
    accent: "from-amber-300 via-orange-300 to-pink-300",
  },
  submitted: {
    label: "已提交",
    tone: "bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200",
    accent: "from-sky-300 via-cyan-300 to-blue-300",
  },
  graded: {
    label: "已批改",
    tone: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
    accent: "from-emerald-300 via-teal-300 to-cyan-300",
  },
};

function formatDateTime(value?: string | null) {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatModeLabel(mode?: string | null) {
  return EXAM_MODES.find((item) => item.value === mode)?.label ?? "智能试卷";
}

function formatDifficultyLabel(value: string) {
  return DIFFICULTIES.find((item) => item.value === value)?.label ?? value;
}

function getStatusMeta(status?: string | null) {
  if (!status) return STATUS_META.draft;
  return STATUS_META[status] ?? STATUS_META.draft;
}

function buildExamTitle(item: ExamHistoryItem) {
  const modeLabel = formatModeLabel(item.exam_mode);
  return `${modeLabel} · ${formatDateTime(item.created_at)}`;
}

function buildKnowledgeLabel(item: ExamPaperItemResponse) {
  return (
    item.knowledge_unit_links
      ?.map((link: ExamNodeLinkResponse) => link.knowledge_unit_name)
      .filter(Boolean)
      .join(" · ") || "未标注知识点"
  );
}

function HeroOrb() {
  return (
    <div className="relative hidden h-[280px] w-[280px] shrink-0 items-center justify-center lg:flex">
      <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_30%,rgba(34,197,94,0.95),rgba(59,130,246,0.7)_38%,rgba(168,85,247,0.92)_64%,rgba(15,23,42,0.98)_90%)] shadow-[0_36px_80px_rgba(76,29,149,0.35)]" />
      <div className="absolute inset-[16%] rounded-full border-[18px] border-white/30" />
      <div className="absolute inset-[29%] rounded-full border-[14px] border-white/45" />
      <div className="absolute inset-[42%] rounded-full border-[12px] border-white/50" />
      <div className="absolute h-3.5 w-3.5 -translate-x-[118px] -translate-y-[68px] rounded-full bg-sky-200/90 shadow-[0_0_24px_rgba(125,211,252,0.85)]" />
      <div className="absolute h-5 w-5 translate-x-[124px] -translate-y-[78px] rounded-full bg-emerald-400/90 blur-[1px]" />
      <div className="absolute h-16 w-2 rotate-45 rounded-full bg-slate-900 shadow-[0_0_20px_rgba(15,23,42,0.35)]" />
      <div className="absolute h-0 w-0 translate-x-[47px] -translate-y-[45px] border-b-[17px] border-l-[38px] border-t-[17px] border-b-transparent border-l-emerald-400 border-t-transparent drop-shadow-[0_8px_18px_rgba(34,197,94,0.45)]" />
      <div className="absolute h-0 w-0 translate-x-[68px] -translate-y-[25px] rotate-12 border-b-[10px] border-l-[20px] border-t-[10px] border-b-transparent border-l-emerald-300 border-t-transparent" />
      <div className="absolute right-0 top-[60%] grid h-10 w-10 place-items-center rounded-full bg-white/75 shadow-lg backdrop-blur">
        <Plus className="h-5 w-5 text-sky-500" />
      </div>
    </div>
  );
}

export function ExamsPage() {
  const { subjectId } = useParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(null);
  const [examMode, setExamMode] = useState<(typeof EXAM_MODES)[number]["value"]>("web_practice");
  const [difficulty, setDifficulty] = useState<(typeof DIFFICULTIES)[number]["value"]>("medium");
  const [numQuestions, setNumQuestions] = useState(8);
  const [focusPrompt, setFocusPrompt] = useState("");
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const historyQuery = useExamHistoryApiV1SubjectsSubjectExamsHistoryGet(subjectId ?? "", { page: 1, size: 24 });
  const history = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data),
    [historyQuery.data],
  );
  const historyItems = history?.items ?? [];

  const selectedHistoryItem = useMemo(
    () => historyItems.find((item) => item.id === selectedPaperId) ?? null,
    [historyItems, selectedPaperId],
  );

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet(
    subjectId ?? "",
    selectedPaperId ?? 0,
    {
      query: {
        enabled: Boolean(subjectId && selectedPaperId),
      },
    },
  );
  const paper = useMemo<ExamPaperDetailResponse | null>(
    () => unwrapOrvalResponse<ExamPaperDetailResponse>(examDetailQuery.data),
    [examDetailQuery.data],
  );

  useEffect(() => {
    if (!paper?.items) return;
    setAnswers(
      Object.fromEntries(
        (paper.items ?? []).map((item: ExamPaperItemResponse) => [item.id, item.user_answer ?? ""]),
      ),
    );
  }, [paper?.id, paper?.items]);

  const completedCount = historyItems.filter((item) => item.status === "graded").length;
  const draftCount = historyItems.filter((item) => item.status !== "graded").length;

  const generateExam = useGenerateExamApiV1SubjectsSubjectExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id || !subjectId) return;
        setIsCreateOpen(false);
        setSelectedPaperId(created.exam_paper_id);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, created.exam_paper_id),
          }),
        ]);
        toast({
          title: "试卷已创建",
          description: `已生成 ${created.num_questions} 题，马上开始练习吧。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "创建失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const submitExam = useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost({
    mutation: {
      onSuccess: async (response) => {
        if (!subjectId || !selectedPaperId) return;
        const graded = unwrapOrvalResponse(response);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, selectedPaperId),
          }),
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey(subjectId),
          }),
        ]);
        toast({
          title: "交卷成功",
          description: `本次得分 ${graded?.score ?? 0}，掌握度已同步更新。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "交卷失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  if (!subjectId) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-[#f7f8fc] px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少学科标识，暂时无法加载考试中心。
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="min-h-[calc(100vh-4rem)] bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_55%,#eef3f8_100%)] px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <section className="overflow-hidden rounded-[36px] border border-white/70 bg-white/90 px-6 py-8 shadow-[0_25px_80px_rgba(15,23,42,0.08)] backdrop-blur sm:px-8 lg:px-10">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-600 shadow-sm">
                  <Sparkles className="h-4 w-4 text-sky-500" />
                  Exam Studio
                </div>

                <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-5xl">
                  所有考试卷都在这里
                </h1>

                <p className="mt-4 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">
                  一键创建新的练习卷，继续完成未做完的测试，也可以回看已经生成过的考卷与得分记录。
                </p>

                <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center">
                  <Button
                    size="lg"
                    className="h-14 rounded-full bg-black px-7 text-base font-semibold text-white shadow-[0_18px_40px_rgba(15,23,42,0.22)] hover:bg-slate-900"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    <Plus className="h-5 w-5" />
                    创建新考卷
                  </Button>

                  <div className="flex flex-wrap gap-3 text-sm text-slate-600">
                    <div className="rounded-full border border-slate-200 bg-white px-4 py-2 shadow-sm">
                      共 {historyItems.length} 份试卷
                    </div>
                    <div className="rounded-full border border-slate-200 bg-white px-4 py-2 shadow-sm">
                      已完成 {completedCount} 份
                    </div>
                    <div className="rounded-full border border-slate-200 bg-white px-4 py-2 shadow-sm">
                      待继续 {draftCount} 份
                    </div>
                  </div>
                </div>
              </div>

              <HeroOrb />
            </div>
          </section>

          <section className="grid gap-4 md:grid-cols-3">
            <div className="rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.05)]">
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-sky-100 text-sky-600">
                  <FileText className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">试卷总数</p>
                  <p className="text-2xl font-semibold text-slate-950">{historyItems.length}</p>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.05)]">
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-emerald-100 text-emerald-600">
                  <CheckCircle2 className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">已批改</p>
                  <p className="text-2xl font-semibold text-slate-950">{completedCount}</p>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.05)]">
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-violet-100 text-violet-600">
                  <Clock3 className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">待继续</p>
                  <p className="text-2xl font-semibold text-slate-950">{draftCount}</p>
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-[32px] border border-white/70 bg-white/88 p-4 shadow-[0_25px_80px_rgba(15,23,42,0.07)] sm:p-6">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-2 pb-5 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-sm font-medium uppercase tracking-[0.22em] text-slate-400">Generated Papers</p>
                <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-slate-950">
                  已生成的考卷
                </h2>
                <p className="mt-2 text-sm leading-7 text-slate-500">
                  点击卡片可以继续作答、查看分数或回看题目。
                </p>
              </div>

              <Button
                variant="outline"
                className="h-11 rounded-full border-slate-200 bg-white px-5"
                onClick={() => setIsCreateOpen(true)}
              >
                <Plus className="h-4 w-4" />
                新建考卷
              </Button>
            </div>

            <div className="mt-5 space-y-4">
              {historyQuery.isLoading && (
                <div className="rounded-[28px] border border-slate-200 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500">
                  正在加载试卷列表...
                </div>
              )}

              {historyQuery.error && (
                <div className="rounded-[28px] border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
                  {getApiErrorMessage(historyQuery.error, "加载试卷列表失败")}
                </div>
              )}

              {!historyQuery.isLoading && !historyQuery.error && historyItems.length === 0 && (
                <div className="rounded-[28px] border border-dashed border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] px-6 py-12 text-center">
                  <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-slate-900 text-white shadow-lg">
                    <GraduationCap className="h-6 w-6" />
                  </div>
                  <h3 className="mt-5 text-xl font-semibold text-slate-950">还没有考卷</h3>
                  <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-slate-500">
                    从这里创建第一份试卷。你可以选择专项练习或整卷测试，也可以输入想重点考察的知识范围。
                  </p>
                  <Button
                    size="lg"
                    className="mt-6 rounded-full bg-black px-6"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    <Plus className="h-5 w-5" />
                    创建第一份考卷
                  </Button>
                </div>
              )}

              {historyItems.map((item: ExamHistoryItem) => {
                const statusMeta = getStatusMeta(item.status);
                const scoreText =
                  item.score_obtained != null && item.total_score != null
                    ? `${item.score_obtained}/${item.total_score}`
                    : "未评分";

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedPaperId(item.id)}
                    className="group w-full rounded-[28px] border border-slate-200/80 bg-[linear-gradient(180deg,#ffffff_0%,#fbfcff_100%)] px-5 py-5 text-left transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_18px_45px_rgba(15,23,42,0.08)] sm:px-6"
                  >
                    <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                      <div className="flex min-w-0 items-start gap-4">
                        <div className={`mt-1 grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br ${statusMeta.accent} text-slate-950 shadow-lg`}>
                          <Target className="h-6 w-6" />
                        </div>

                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-3">
                            <h3 className="truncate text-xl font-semibold tracking-[-0.03em] text-slate-950">
                              {buildExamTitle(item)}
                            </h3>
                            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusMeta.tone}`}>
                              {statusMeta.label}
                            </span>
                          </div>

                          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-500">
                            <span className="inline-flex items-center gap-2">
                              <Layers3 className="h-4 w-4" />
                              {formatModeLabel(item.exam_mode)}
                            </span>
                            <span className="inline-flex items-center gap-2">
                              <FileText className="h-4 w-4" />
                              {item.total_items} 题
                            </span>
                            <span className="inline-flex items-center gap-2">
                              <CalendarDays className="h-4 w-4" />
                              创建于 {formatDateTime(item.created_at)}
                            </span>
                          </div>

                          <div className="mt-4 flex flex-wrap items-center gap-3">
                            <div className="rounded-full bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700">
                              得分：{scoreText}
                            </div>
                            <div className="rounded-full bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700">
                              学科：{item.subject}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-4 lg:justify-end">
                        <div className="text-sm text-slate-400">
                          {item.graded_at
                            ? `最近批改 ${formatDateTime(item.graded_at)}`
                            : item.submitted_at
                              ? `最近提交 ${formatDateTime(item.submitted_at)}`
                              : "点击继续查看"}
                        </div>
                        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-slate-100 text-slate-600 transition group-hover:bg-slate-900 group-hover:text-white">
                          <ChevronRight className="h-5 w-5" />
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      </div>

      <Modal
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="创建新考卷"
        className="max-w-2xl rounded-[28px]"
      >
        <div className="space-y-6">
          <div className="rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,#fbfcff_0%,#f5f8ff_100%)] p-5">
            <p className="text-sm font-medium text-sky-600">面向当前学科</p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-slate-950">{subjectId}</h3>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              选择出题模式、题量和难度后，系统会结合当前学科内容自动创建一份新考卷。
            </p>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-600">
              出题模式
              <select
                className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                value={examMode}
                onChange={(event) => setExamMode(event.target.value as typeof examMode)}
              >
                {EXAM_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
              <span className="mt-2 block text-xs leading-6 text-slate-400">
                {EXAM_MODES.find((item) => item.value === examMode)?.description}
              </span>
            </label>

            <label className="text-sm text-slate-600">
              难度
              <select
                className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                value={difficulty}
                onChange={(event) => setDifficulty(event.target.value as typeof difficulty)}
              >
                {DIFFICULTIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              <span className="mt-2 block text-xs leading-6 text-slate-400">
                当前选择：{formatDifficultyLabel(difficulty)}
              </span>
            </label>

            <label className="text-sm text-slate-600">
              题目数量
              <input
                className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                type="number"
                min={1}
                max={40}
                value={numQuestions}
                onChange={(event) => setNumQuestions(Math.min(40, Math.max(1, Number(event.target.value) || 1)))}
              />
              <span className="mt-2 block text-xs leading-6 text-slate-400">
                建议 5-15 题，练习节奏更轻盈。
              </span>
            </label>

            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-medium text-slate-700">智能策略</p>
              <p className="mt-2 text-sm leading-7 text-slate-500">
                系统会优先结合知识点覆盖与练习状态进行出题，适合作为当前学科的练习入口。
              </p>
            </div>
          </div>

          <label className="block text-sm text-slate-600">
            重点考察范围
            <textarea
              className="mt-2 min-h-32 w-full rounded-[24px] border border-slate-200 bg-white px-4 py-4 text-sm leading-7 text-slate-900 outline-none transition focus:border-slate-400"
              placeholder="例如：递归、动态规划、函数极限、SQL 聚合、近代史时间线"
              value={focusPrompt}
              onChange={(event) => setFocusPrompt(event.target.value)}
            />
          </label>

          {generateExam.error && (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {getApiErrorMessage(generateExam.error, "创建失败")}
            </div>
          )}

          <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-500">
              创建后会自动写入试卷列表，并立即可以打开作答。
            </p>
            <div className="flex gap-3">
              <Button variant="outline" className="rounded-full px-5" onClick={() => setIsCreateOpen(false)}>
                取消
              </Button>
              <Button
                className="rounded-full bg-black px-6"
                onClick={() =>
                  generateExam.mutate({
                    subject: subjectId,
                    data: {
                      exam_mode: examMode,
                      difficulty,
                      focus_prompt: focusPrompt.trim() || undefined,
                      num_questions: numQuestions,
                    },
                  })
                }
                disabled={generateExam.isPending}
              >
                {generateExam.isPending ? "创建中..." : "确认创建"}
                {!generateExam.isPending && <ArrowRight className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={selectedPaperId !== null}
        onClose={() => setSelectedPaperId(null)}
        title={selectedHistoryItem ? buildExamTitle(selectedHistoryItem) : "考卷详情"}
        className="max-w-5xl rounded-[28px]"
      >
        <div className="space-y-6">
          {selectedHistoryItem && (
            <div className="flex flex-wrap items-center gap-3">
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${getStatusMeta(selectedHistoryItem.status).tone}`}>
                {getStatusMeta(selectedHistoryItem.status).label}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">
                {formatModeLabel(selectedHistoryItem.exam_mode)}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">
                {selectedHistoryItem.total_items} 题
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">
                创建于 {formatDateTime(selectedHistoryItem.created_at)}
              </span>
            </div>
          )}

          {examDetailQuery.isLoading && (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500">
              正在加载考卷内容...
            </div>
          )}

          {examDetailQuery.error && (
            <div className="rounded-[24px] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {getApiErrorMessage(examDetailQuery.error, "加载考卷失败")}
            </div>
          )}

          {!examDetailQuery.isLoading && !paper && !examDetailQuery.error && (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500">
              暂无可展示的试卷内容。
            </div>
          )}

          {paper && (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm text-slate-500">题目数量</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-950">{paper.total_items}</p>
                </div>
                <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm text-slate-500">当前得分</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-950">
                    {paper.score_obtained ?? "--"} / {paper.total_score ?? "--"}
                  </p>
                </div>
                <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm text-slate-500">状态</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-950">
                    {getStatusMeta(paper.status).label}
                  </p>
                </div>
              </div>

              <div className="space-y-5">
                {(paper.items ?? []).map((item: ExamPaperItemResponse) => {
                  const answerValue = answers[item.id] ?? "";
                  const isChoice = item.question_type === "single_choice";

                  return (
                    <div
                      key={item.id}
                      className="rounded-[26px] border border-slate-200 bg-white px-5 py-5 shadow-sm"
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                            Q{item.item_order} · {item.question_type} · {formatDifficultyLabel(item.difficulty)}
                          </p>
                          <h3 className="mt-3 text-lg font-semibold leading-8 text-slate-950">
                            {item.stem}
                          </h3>
                        </div>
                        <div className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
                          {buildKnowledgeLabel(item)}
                        </div>
                      </div>

                      {isChoice ? (
                        <div className="mt-5 grid gap-3">
                          {(item.options ?? []).map((option: string) => (
                            <label
                              key={option}
                              className={`flex cursor-pointer items-center gap-3 rounded-2xl border px-4 py-4 text-sm transition ${
                                answerValue === option
                                  ? "border-slate-900 bg-slate-900 text-white"
                                  : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                              }`}
                            >
                              <input
                                type="radio"
                                name={`exam-item-${item.id}`}
                                checked={answerValue === option}
                                onChange={() => setAnswers((current) => ({ ...current, [item.id]: option }))}
                                disabled={paper.status === "graded"}
                              />
                              <span>{option}</span>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <textarea
                          className="mt-5 min-h-28 w-full rounded-[22px] border border-slate-200 bg-white px-4 py-4 text-sm leading-7 text-slate-900 outline-none transition focus:border-slate-400"
                          placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                          value={answerValue}
                          onChange={(event) =>
                            setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                          }
                          disabled={paper.status === "graded"}
                        />
                      )}

                      {paper.status === "graded" && (
                        <div className="mt-5 rounded-[22px] bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-600">
                          <p>你的答案：{item.user_answer || "未作答"}</p>
                          <p>正确答案：{item.correct_answer || "无标准答案"}</p>
                          <p>解析：{item.explanation || "暂无解析"}</p>
                          <p>结果：{item.is_correct ? "正确" : "需要继续巩固"}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="flex flex-col gap-3 border-t border-slate-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-slate-500">
                  {paper.status === "graded"
                    ? "这份试卷已经批改完成，可以继续查看解析。"
                    : "完成作答后提交，系统会同步更新成绩与掌握情况。"}
                </p>
                <Button
                  className="rounded-full bg-black px-6"
                  onClick={() =>
                    selectedPaperId &&
                    submitExam.mutate({
                      subject: subjectId,
                      examPaperId: selectedPaperId,
                      data: {
                        answers: (paper.items ?? []).map((item: ExamPaperItemResponse) => ({
                          exam_paper_item_id: item.id,
                          item_order: item.item_order,
                          answer: answers[item.id] ?? "",
                        })),
                      },
                    })
                  }
                  disabled={!selectedPaperId || paper.status === "graded" || submitExam.isPending}
                >
                  {paper.status === "graded"
                    ? "已完成批改"
                    : submitExam.isPending
                      ? "提交中..."
                      : "提交这份考卷"}
                </Button>
              </div>
            </>
          )}
        </div>
      </Modal>
    </>
  );
}
