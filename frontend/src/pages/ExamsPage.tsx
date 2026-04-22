import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  FileText,
  GraduationCap,
  Layers3,
  Plus,
  Sparkles,
  Target,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

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
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
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

const STATUS_META: Record<string, { label: string; tone: string; accent: string }> = {
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
    label: "已完成",
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

function buildExamTitle(item: Pick<ExamHistoryItem, "exam_mode" | "created_at">) {
  return `${formatModeLabel(item.exam_mode)} · ${formatDateTime(item.created_at)}`;
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
      <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_30%,rgba(34,197,94,0.95),rgba(59,130,246,0.7)_38%,rgba(168,85,247,0.92)_64%,rgba(15,23,42,0.98)_90%)]" />
      <div className="absolute inset-[16%] rounded-full border-[18px] border-white/30" />
      <div className="absolute inset-[29%] rounded-full border-[14px] border-white/45" />
      <div className="absolute inset-[42%] rounded-full border-[12px] border-white/50" />
      <div className="absolute h-3.5 w-3.5 -translate-x-[118px] -translate-y-[68px] rounded-full bg-sky-200/90" />
      <div className="absolute h-5 w-5 translate-x-[124px] -translate-y-[78px] rounded-full bg-emerald-400/90 blur-[1px]" />
      <div className="absolute h-16 w-2 rotate-45 rounded-full bg-slate-900" />
      <div className="absolute h-0 w-0 translate-x-[47px] -translate-y-[45px] border-b-[17px] border-l-[38px] border-t-[17px] border-b-transparent border-l-emerald-400 border-t-transparent" />
      <div className="absolute h-0 w-0 translate-x-[68px] -translate-y-[25px] rotate-12 border-b-[10px] border-l-[20px] border-t-[10px] border-b-transparent border-l-emerald-300 border-t-transparent" />
      <div className="absolute right-0 top-[60%] grid h-10 w-10 place-items-center rounded-full bg-white/75 backdrop-blur">
        <Plus className="h-5 w-5 text-sky-500" />
      </div>
    </div>
  );
}

function ExamMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={className} style={{ overflowWrap: "anywhere" }}>
      <MarkdownViewer content={content} variant="default" />
    </div>
  );
}

function hasAnsweredQuestion(item: ExamPaperItemResponse, answers: Record<number, string>) {
  const value = answers[item.id] ?? "";
  return value.trim().length > 0;
}

function ExamStageHeader({
  currentStep,
  onBack,
}: {
  currentStep: 1 | 2 | 3;
  onBack: () => void;
}) {
  const steps = [1, 2, 3] as const;

  return (
    <div className="bg-transparent">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 px-5 py-4 sm:px-8">
        <button
          type="button"
          onClick={onBack}
          className="justify-self-start inline-flex items-center gap-3 text-base font-medium text-slate-900 transition hover:text-slate-600"
        >
          <ArrowLeft className="h-5 w-5" />
          返回考卷列表
        </button>

        <div className="col-start-2 flex items-center justify-center gap-1.5 sm:gap-2.5">
          {steps.map((step, index) => {
            const isActive = step === currentStep;
            const isCompleted = step < currentStep;

            return (
              <div key={step} className="flex items-center gap-1.5 sm:gap-2.5">
                <div
                  className={`grid h-7 w-7 place-items-center rounded-lg text-xs font-semibold transition sm:h-8 sm:w-8 sm:text-sm ${
                    isActive
                      ? "bg-violet-500 text-white shadow-[0_10px_24px_rgba(139,92,246,0.28)]"
                      : isCompleted
                        ? "bg-slate-900 text-white"
                        : "bg-slate-200 text-slate-700"
                  }`}
                >
                  {step}
                </div>
                {index < steps.length - 1 && (
                  <div
                    className="h-px w-10 sm:w-16"
                    style={{
                      backgroundImage:
                        "repeating-linear-gradient(to right, rgb(203 213 225 / 1) 0 8px, transparent 8px 13px)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="justify-self-end" />
      </div>
    </div>
  );
}

interface CreateExamModalProps {
  open: boolean;
  subjectId: string;
  onClose: () => void;
  onCreated: (paperId: number) => void;
}

function CreateExamModal({ open, subjectId, onClose, onCreated }: CreateExamModalProps) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [examMode, setExamMode] = useState<(typeof EXAM_MODES)[number]["value"]>("web_practice");
  const [difficulty, setDifficulty] = useState<(typeof DIFFICULTIES)[number]["value"]>("medium");
  const [numQuestions, setNumQuestions] = useState(8);
  const [focusPrompt, setFocusPrompt] = useState("");

  const generateExam = useGenerateExamApiV1SubjectsSubjectExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id) return;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
        });
        onClose();
        onCreated(created.exam_paper_id);
        toast({
          title: "试卷已创建",
          description: `已生成 ${created.num_questions} 题，马上开始考试。`,
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

  return (
    <Modal open={open} onClose={onClose} title="创建新考卷" className="max-w-2xl rounded-[28px]">
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
          <p className="text-sm text-slate-500">创建后会自动写入试卷列表，并直接进入考试页面。</p>
          <div className="flex gap-3">
            <Button variant="outline" className="rounded-full px-5" onClick={onClose}>
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
  );
}

interface ExamPaperWorkspaceProps {
  subjectId: string;
  paperId: number;
  backHref: string;
}

function ExamPaperWorkspace({ subjectId, paperId, backHref }: ExamPaperWorkspaceProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [pageScale, setPageScale] = useState(1);

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet(subjectId, paperId, {
    query: {
      enabled: Boolean(subjectId && paperId),
    },
  });

  const paper = useMemo<ExamPaperDetailResponse | null>(
    () => unwrapOrvalResponse<ExamPaperDetailResponse>(examDetailQuery.data),
    [examDetailQuery.data],
  );
  const currentStep: 1 | 2 | 3 = paper?.status === "graded" ? 2 : 1;

  useEffect(() => {
    if (!paper?.items) return;
    setAnswers(
      Object.fromEntries(
        (paper.items ?? []).map((item: ExamPaperItemResponse) => [item.id, item.user_answer ?? ""]),
      ),
    );
  }, [paper?.id, paper?.items]);

  const submitExam = useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost({
    mutation: {
      onSuccess: async (response) => {
        const graded = unwrapOrvalResponse(response);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, paperId),
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
        window.scrollTo({ top: 0, behavior: "smooth" });
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

  return (
    <div className="relative min-h-[calc(100vh-4rem)]">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[linear-gradient(180deg,#ffffff_0%,#f7f9fc_36%,#eef3f8_100%)]" />
      <ExamStageHeader currentStep={currentStep} onBack={() => navigate(backHref)} />

      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl space-y-6">
          {examDetailQuery.isLoading && (
            <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
              正在加载考卷内容...
            </div>
          )}

          {examDetailQuery.error && (
            <div className="rounded-[28px] border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
              {getApiErrorMessage(examDetailQuery.error, "加载考卷失败")}
            </div>
          )}

          {!examDetailQuery.isLoading && !paper && !examDetailQuery.error && (
            <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
              这份考卷不存在，或者已经无法访问。
            </div>
          )}

          {paper && (
            <>
              <aside className="hidden lg:block">
                <div className="fixed left-2 top-28 z-20 w-[112px] rounded-[28px] border border-slate-200/80 bg-white/92 px-3 py-4 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur xl:left-3 xl:w-[136px] 2xl:w-[184px]">
                  <div className="mb-3 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    题目导航
                  </div>
                  <div
                    className="grid gap-2"
                    style={{ gridTemplateColumns: "repeat(auto-fit, minmax(2rem, 1fr))" }}
                  >
                    {(paper.items ?? []).map((item) => {
                      const isAnswered = hasAnsweredQuestion(item, answers);
                      const navTone =
                        paper.status === "graded"
                          ? item.is_correct
                            ? "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 hover:bg-emerald-100"
                            : "bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200 hover:bg-rose-100"
                          : isAnswered
                            ? "bg-slate-900 text-white hover:bg-slate-800"
                            : "bg-slate-100 text-slate-600 hover:bg-slate-200";

                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() =>
                            document
                              .getElementById(`exam-question-${item.item_order}`)
                              ?.scrollIntoView({ behavior: "smooth", block: "start" })
                          }
                          className={`grid aspect-square w-full max-w-8 justify-self-center place-items-center rounded-lg text-xs font-semibold transition ${navTone}`}
                          aria-label={`跳转到第 ${item.item_order} 题`}
                        >
                          {item.item_order}
                        </button>
                      );
                    })}
                  </div>

                  <div className="mt-4 space-y-2 px-2 text-xs text-slate-500">
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${paper.status === "graded" ? "bg-emerald-500" : "bg-slate-900"}`} />
                      <span>{paper.status === "graded" ? "正确" : "已作答"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${paper.status === "graded" ? "bg-rose-500" : "bg-slate-400"}`} />
                      <span>{paper.status === "graded" ? "错误 / 未作答" : "未作答"}</span>
                    </div>
                  </div>
                </div>
              </aside>

              <aside className="hidden lg:block">
                <div className="fixed right-4 top-28 z-20 flex flex-col gap-3 xl:right-6">
                <button
                  type="button"
                    onClick={() => setPageScale((current) => Math.min(1.4, Number((current + 0.05).toFixed(2))))}
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                  aria-label="放大页面"
                >
                    <ZoomIn className="h-5.5 w-5.5" />
                </button>

                <button
                  type="button"
                    onClick={() => setPageScale((current) => Math.max(0.7, Number((current - 0.05).toFixed(2))))}
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                  aria-label="缩小页面"
                >
                    <ZoomOut className="h-5.5 w-5.5" />
                </button>
                </div>
              </aside>

              <div
                className="space-y-8 transition-all duration-150"
                style={{
                  zoom: pageScale,
                }}
              >
                <section className="px-1 py-2 text-center">
                  <h1 className="text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">
                    {buildExamTitle(paper)}
                  </h1>
                </section>

                <section
                  className="space-y-8"
                  style={
                    pageScale < 1
                      ? {
                          width: `${pageScale * 100}%`,
                          marginLeft: "auto",
                          marginRight: "auto",
                        }
                      : undefined
                  }
                >
                  {(paper.items ?? []).map((item: ExamPaperItemResponse) => {
                    const answerValue = answers[item.id] ?? "";
                    const isChoice = item.question_type === "single_choice";
                    const isGraded = paper.status === "graded";
                    const isCorrect = item.is_correct === true;

                    return (
                      <div
                        key={item.id}
                        id={`exam-question-${item.item_order}`}
                        data-question-anchor="true"
                        data-question-order={item.item_order}
                        className="scroll-mt-28 rounded-[36px] border border-slate-200/80 bg-white px-5 py-8 shadow-sm sm:px-8 sm:py-10"
                      >
                        <div className="mx-auto max-w-6xl">
                          <div className="text-center">
                            <p className="text-sm font-medium text-slate-400">
                              Question {item.item_order}/{paper.total_items}
                            </p>
                            <div className="mx-auto mt-4 max-w-5xl text-slate-950 [&_p]:mb-0 [&_p]:text-2xl [&_p]:font-semibold [&_p]:leading-[1.5] [&_p]:tracking-[-0.03em] sm:[&_p]:text-3xl [&_.katex-display]:my-4 [&_.katex]:text-inherit">
                              <ExamMarkdown content={item.stem} />
                            </div>
                            <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-sm text-slate-500">
                              <span>{formatDifficultyLabel(item.difficulty)}</span>
                              <span>·</span>
                              <span>{item.question_type}</span>
                              <span>·</span>
                              <span>{buildKnowledgeLabel(item)}</span>
                            </div>
                          </div>

                          {isChoice ? (
                            <div className="mt-10 grid gap-4" role="radiogroup" aria-label={`第 ${item.item_order} 题选项`}>
                              {(item.options ?? []).map((option: string) => {
                                const isSelected = answerValue === option;
                                const isCorrectOption = (item.correct_answer ?? "") === option;
                                const isWrongSelectedOption = isGraded && isSelected && !isCorrectOption;
                                const isRightOption = isGraded && isSelected && isCorrectOption;
                                return (
                                  <button
                                    key={option}
                                    type="button"
                                    role="radio"
                                    aria-checked={isSelected}
                                    disabled={isGraded}
                                    onClick={() =>
                                      setAnswers((current) => ({
                                        ...current,
                                        [item.id]: isSelected ? "" : option,
                                      }))
                                    }
                                    className={`flex items-center gap-5 rounded-[28px] border px-7 py-6 text-left text-lg leading-8 transition ${
                                      isGraded
                                        ? isRightOption
                                          ? "border-emerald-300 bg-emerald-50 text-emerald-900 shadow-[0_12px_30px_rgba(16,185,129,0.12)]"
                                          : isWrongSelectedOption
                                            ? "border-rose-300 bg-rose-50 text-rose-900 shadow-[0_12px_30px_rgba(244,63,94,0.10)]"
                                            : "border-slate-200 bg-white text-slate-500"
                                        : isSelected
                                          ? "border-slate-900 bg-slate-900 text-white shadow-[0_18px_40px_rgba(15,23,42,0.16)]"
                                          : "border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50"
                                    } disabled:cursor-not-allowed`}
                                  >
                                    <span
                                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border-4 ${
                                        isGraded
                                          ? isRightOption
                                            ? "border-emerald-600 bg-white"
                                            : isWrongSelectedOption
                                              ? "border-rose-600 bg-white"
                                              : "border-slate-300 bg-white"
                                          : isSelected
                                            ? "border-white bg-white"
                                            : "border-slate-900 bg-white"
                                      }`}
                                    >
                                      <span
                                        className={`h-3.5 w-3.5 rounded-full ${
                                          isGraded
                                            ? isRightOption
                                              ? "bg-emerald-600"
                                              : isWrongSelectedOption
                                                ? "bg-rose-600"
                                                : "bg-transparent"
                                            : isSelected
                                              ? "bg-slate-900"
                                              : "bg-transparent"
                                        }`}
                                      />
                                    </span>
                                    <div className={`min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-lg [&_p]:leading-8 [&_.katex-display]:my-3 [&_.katex]:text-inherit ${
                                      isGraded
                                        ? isRightOption
                                          ? "[&_p]:text-emerald-900"
                                          : isWrongSelectedOption
                                            ? "[&_p]:text-rose-900"
                                            : "[&_p]:text-slate-500"
                                        : isSelected
                                          ? "[&_p]:text-white"
                                          : "[&_p]:text-slate-800"
                                    }`}>
                                      <ExamMarkdown content={option} />
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="mt-10">
                              <textarea
                                className={`min-h-36 w-full rounded-[28px] border px-6 py-5 text-lg leading-8 outline-none transition ${
                                  isGraded
                                    ? isCorrect
                                      ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                                      : "border-rose-300 bg-rose-50 text-rose-900"
                                    : "border-slate-200 bg-white text-slate-900 focus:border-slate-400"
                                }`}
                                placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                                value={answerValue}
                                onChange={(event) =>
                                  setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                                }
                                disabled={isGraded}
                              />
                            </div>
                          )}
                        </div>

                        {paper.status === "graded" && (
                          <div className="mx-auto mt-6 max-w-6xl rounded-[24px] bg-slate-50 px-5 py-5 text-sm leading-7 text-slate-600">
                            <div className="[&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">你的答案</p>
                              <ExamMarkdown content={item.user_answer || "未作答"} />
                            </div>
                            <div className="mt-3 [&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">正确答案</p>
                              <ExamMarkdown content={item.correct_answer || "无标准答案"} />
                            </div>
                            <div className="mt-3 [&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">解析</p>
                              <ExamMarkdown content={item.explanation || "暂无解析"} />
                            </div>
                            <div className="mt-4 flex items-center gap-2 border-t border-slate-200 pt-4">
                              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">结果</span>
                              <span className={item.is_correct ? "font-medium text-emerald-700" : "font-medium text-rose-700"}>
                                {item.is_correct ? "正确" : "需要继续巩固"}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </section>

                <section className="flex flex-col items-center justify-center border-t border-slate-100 pt-4 pb-12 text-center sm:pb-16">
                  <Button
                    className="h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)]"
                    onClick={() =>
                      submitExam.mutate({
                        subject: subjectId,
                        examPaperId: paperId,
                        data: {
                          answers: (paper.items ?? []).map((item: ExamPaperItemResponse) => ({
                            exam_paper_item_id: item.id,
                            item_order: item.item_order,
                            answer: answers[item.id] ?? "",
                          })),
                        },
                      })
                    }
                    disabled={paper.status === "graded" || submitExam.isPending}
                  >
                    {paper.status === "graded"
                      ? "已完成批改"
                      : submitExam.isPending
                        ? "提交中..."
                        : "提交这份考卷"}
                  </Button>
                  </section>
                </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function ExamsPage() {
  const { subjectId } = useParams();
  const navigate = useNavigate();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState({
    active: true,
    completed: true,
  });

  const historyQuery = useExamHistoryApiV1SubjectsSubjectExamsHistoryGet(subjectId ?? "", { page: 1, size: 24 });
  const history = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data),
    [historyQuery.data],
  );
  const historyItems = history?.items ?? [];

  const activeHistoryItems = useMemo(
    () => historyItems.filter((item) => item.status !== "graded"),
    [historyItems],
  );
  const completedHistoryItems = useMemo(
    () => historyItems.filter((item) => item.status === "graded"),
    [historyItems],
  );

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
          <section className="overflow-hidden px-2 py-4 sm:px-4 lg:px-6">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-sm font-medium text-slate-600">
                  <Sparkles className="h-4 w-4 text-sky-500" />
                  Exam Studio
                </div>

                <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-5xl">
                  所有考试卷都在这里
                </h1>

                <p className="mt-4 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">
                  一键创建新的练习卷，继续完成未做完的测试，也可以回看已经生成过的考卷与得分记录。
                </p>

                <div className="mt-8">
                  <Button
                    size="lg"
                    className="h-14 rounded-full bg-black px-7 text-base font-semibold text-white hover:bg-slate-900"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    <Plus className="h-5 w-5" />
                    创建新考卷
                  </Button>
                </div>
              </div>

              <HeroOrb />
            </div>
          </section>

          <section>
            <div className="space-y-6">
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
                <div className="px-1 py-6">
                  <div className="grid h-14 w-14 place-items-center rounded-2xl bg-slate-900 text-white">
                    <GraduationCap className="h-6 w-6" />
                  </div>
                  <h3 className="mt-5 text-xl font-semibold text-slate-950">还没有考卷</h3>
                  <p className="mt-3 max-w-xl text-sm leading-7 text-slate-500">
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

              {[
                { key: "active" as const, title: "待完成的考卷", items: activeHistoryItems },
                { key: "completed" as const, title: "已完成的考卷", items: completedHistoryItems },
              ].map((group) => (
                <div key={group.key} className="space-y-4">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedGroups((current) => ({
                        ...current,
                        [group.key]: !current[group.key],
                      }))
                    }
                    className="flex w-full items-center justify-between px-1 py-2 text-left"
                  >
                    <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-950">
                      {group.title}({group.items.length})
                    </h3>
                    <div className="grid h-10 w-10 place-items-center rounded-full text-slate-500">
                      <ChevronDown
                        className={`h-5 w-5 transition-transform ${
                          expandedGroups[group.key] ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </button>

                  {expandedGroups[group.key] && (
                    <div className="space-y-4">
                      {group.items.length === 0 ? (
                        <div className="px-1 py-1 text-sm text-slate-500">这个分组下暂时没有考卷。</div>
                      ) : (
                        group.items.map((item: ExamHistoryItem) => {
                          const statusMeta = getStatusMeta(item.status);
                          const scoreText =
                            item.score_obtained != null && item.total_score != null
                              ? `${item.score_obtained}/${item.total_score}`
                              : "未评分";

                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => navigate(`/subject/${subjectId}/exams/${item.id}`)}
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
                                        : "点击进入考试"}
                                  </div>
                                  <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-slate-100 text-slate-600 transition group-hover:bg-slate-900 group-hover:text-white">
                                    <ChevronRight className="h-5 w-5" />
                                  </div>
                                </div>
                              </div>
                            </button>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <CreateExamModal
        open={isCreateOpen}
        subjectId={subjectId}
        onClose={() => setIsCreateOpen(false)}
        onCreated={(paperId) => navigate(`/subject/${subjectId}/exams/${paperId}`)}
      />
    </>
  );
}

export function ExamPaperPage() {
  const { subjectId, examPaperId } = useParams();

  if (!subjectId || !examPaperId || Number.isNaN(Number(examPaperId))) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-[#f7f8fc] px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少考卷信息，暂时无法进入考试页面。
        </div>
      </div>
    );
  }

  return (
    <ExamPaperWorkspace
      subjectId={subjectId}
      paperId={Number(examPaperId)}
      backHref={`/subject/${subjectId}/exams`}
    />
  );
}
