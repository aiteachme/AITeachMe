import { useEffect, useMemo, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  FileText,
  GraduationCap,
  Layers3,
  Plus,
  Sparkles,
  Tags,
  Target,
  Trash2,
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
import { getApiErrorMessage, orvalApiClient } from "../api/client";
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

interface ExamStudyGuideFocusUnit {
  knowledge_unit_id?: number | null;
  knowledge_unit_name: string;
  mastery_score?: number | null;
  reason: string;
}

interface ExamStudyGuideResponse {
  exam_paper_id: number;
  subject: string;
  generated_at: string;
  overall_summary: string;
  strengths: string[];
  priority_gaps: string[];
  action_steps: string[];
  review_tasks: string[];
  focus_units: ExamStudyGuideFocusUnit[];
}

interface ExamPaperDeleteResponse {
  deleted: boolean;
  exam_paper_id: number;
}

interface QuestionTemplateItem {
  id: number;
  subject: string;
  knowledge_unit_id?: number | null;
  question_type: string;
  difficulty: string;
  stem: string;
  options?: string[] | null;
  answer: string;
  explanation: string;
  knowledge_unit_refs: Array<Record<string, unknown>>;
  selection_hints: Record<string, unknown>;
  template_version: number;
  status: string;
  created_at: string;
  updated_at: string;
}

interface QuestionTypeRegistryItem {
  id: number;
  type_key: string;
  display_name: string;
  scope: string;
  subject: string;
  description: string;
  answer_format: string;
  grading_method: string;
  option_schema: Record<string, unknown>;
  rubric: Record<string, unknown>;
  source: string;
  confidence: number;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

async function getExamStudyGuide(subjectId: string, paperId: number, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamStudyGuideResponse } }>(
    `/api/v1/subjects/${subjectId}/exams/${paperId}/study-guide`,
    {
      method: "GET",
      signal,
    },
  );
}

async function deleteExamPaper(subjectId: string, paperId: number) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamPaperDeleteResponse } }>(
    `/api/v1/subjects/${subjectId}/exams/${paperId}`,
    {
      method: "DELETE",
    },
  );
}

async function getQuestionTemplates(subjectId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateItem[] } }>(
    `/api/v1/subjects/${subjectId}/exams/question-templates`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getQuestionTypes(subjectId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTypeRegistryItem[] } }>(
    `/api/v1/subjects/${subjectId}/exams/question-types`,
    {
      method: "GET",
      signal,
    },
  );
}

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

function getOptionKey(option: string) {
  const cleaned = option.trim();
  const match = cleaned.match(/^([A-Da-d])(?:[.)、．\s]|$)/);
  return (match?.[1] ?? cleaned.slice(0, 1)).toUpperCase();
}

function splitMultiChoiceAnswer(value?: string | null) {
  return new Set(
    String(value ?? "")
      .replace(/[，、；;\s]+/g, ",")
      .split(",")
      .map((item) => item.trim().replace(/[.)、．]$/g, "").toUpperCase())
      .filter(Boolean),
  );
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
  onStepSelect,
  isStepEnabled,
}: {
  currentStep: 1 | 2 | 3;
  onBack: () => void;
  onStepSelect?: (step: 1 | 2 | 3) => void;
  isStepEnabled?: (step: 1 | 2 | 3) => boolean;
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
            const isEnabled = isStepEnabled?.(step) ?? true;

            return (
              <div key={step} className="flex items-center gap-1.5 sm:gap-2.5">
                <button
                  type="button"
                  disabled={!isEnabled}
                  onClick={() => onStepSelect?.(step)}
                  className={`grid h-7 w-7 place-items-center rounded-lg text-xs font-semibold transition sm:h-8 sm:w-8 sm:text-sm ${
                    isActive
                      ? "bg-violet-500 text-white shadow-[0_10px_24px_rgba(139,92,246,0.28)]"
                      : isCompleted
                        ? "bg-slate-900 text-white"
                        : "bg-slate-200 text-slate-700"
                  } ${isEnabled ? "cursor-pointer" : "cursor-not-allowed opacity-45"}`}
                >
                  {step}
                </button>
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

function StudyGuideSection({
  icon,
  title,
  items,
}: {
  icon: ReactNode;
  title: string;
  items: string[];
}) {
  if (!items.length) return null;

  return (
    <section className="rounded-[28px] border border-slate-200/80 bg-white/92 p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-2xl bg-slate-100 text-slate-700">
          {icon}
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <p className="text-sm text-slate-500">根据本次考卷与当前掌握情况生成</p>
        </div>
      </div>
      <div className="mt-5 space-y-3">
        {items.map((item, index) => (
          <div key={`${title}-${index}`} className="flex gap-3 rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700">
            <span className="mt-1 text-xs font-semibold text-slate-400">{index + 1}</span>
            <span>{item}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExamStudyGuideView({
  guide,
  paper,
  onBackToReview,
}: {
  guide: ExamStudyGuideResponse;
  paper: ExamPaperDetailResponse;
  onBackToReview: () => void;
}) {
  return (
    <div className="space-y-8">
      <section className="rounded-[32px] border border-slate-200/80 bg-[linear-gradient(135deg,#ffffff_0%,#f8fbff_52%,#f2f7ff_100%)] px-6 py-7 shadow-sm sm:px-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-[0.16em] text-slate-500">
              <Sparkles className="h-3.5 w-3.5" />
              学习指南
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">
              {buildExamTitle(paper)}
            </h1>
            <p className="mt-4 text-base leading-8 text-slate-600">{guide.overall_summary}</p>
          </div>
          <Button variant="outline" className="rounded-full px-5" onClick={onBackToReview}>
            返回批改结果
          </Button>
        </div>
      </section>

      {guide.focus_units.length > 0 && (
        <section className="rounded-[28px] border border-slate-200/80 bg-white/92 p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-rose-50 text-rose-700">
              <Target className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-950">重点查漏知识点</h2>
              <p className="text-sm text-slate-500">优先处理这些最影响当前表现的知识点</p>
            </div>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {guide.focus_units.map((unit, index) => (
              <div key={`${unit.knowledge_unit_name}-${index}`} className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-semibold text-slate-900">{unit.knowledge_unit_name}</h3>
                  {typeof unit.mastery_score === "number" && (
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-500 ring-1 ring-inset ring-slate-200">
                      掌握度 {(unit.mastery_score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <p className="mt-3 text-sm leading-7 text-slate-600">{unit.reason}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <StudyGuideSection icon={<GraduationCap className="h-5 w-5" />} title="做得不错" items={guide.strengths} />
        <StudyGuideSection icon={<Layers3 className="h-5 w-5" />} title="优先补漏" items={guide.priority_gaps} />
        <StudyGuideSection icon={<ArrowRight className="h-5 w-5" />} title="下一步怎么学" items={guide.action_steps} />
        <StudyGuideSection icon={<FileText className="h-5 w-5" />} title="立刻可做的复习任务" items={guide.review_tasks} />
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
  const [activeStage, setActiveStage] = useState<1 | 2 | 3>(1);

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet(subjectId, paperId, {
    query: {
      enabled: Boolean(subjectId && paperId),
    },
  });

  const paper = useMemo<ExamPaperDetailResponse | null>(
    () => unwrapOrvalResponse<ExamPaperDetailResponse>(examDetailQuery.data),
    [examDetailQuery.data],
  );

  useEffect(() => {
    if (!paper) return;
    if (paper.status === "graded") {
      setActiveStage((current) => (current === 1 ? 2 : current));
      return;
    }
    setActiveStage(1);
  }, [paper?.id, paper?.status]);

  const studyGuideQuery = useQuery({
    queryKey: ["exam-study-guide", subjectId, paperId],
    enabled: Boolean(subjectId && paperId && paper?.status === "graded" && activeStage === 3),
    queryFn: async ({ signal }) => {
      const response = await getExamStudyGuide(subjectId, paperId, signal);
      return unwrapOrvalResponse<ExamStudyGuideResponse>(response);
    },
  });

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
        setActiveStage(2);
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
      <ExamStageHeader
        currentStep={paper?.status === "graded" ? activeStage : 1}
        onBack={() => navigate(backHref)}
        onStepSelect={(step) => {
          if (step === 1) {
            setActiveStage(1);
            return;
          }
          if (paper?.status === "graded") {
            setActiveStage(step);
          }
        }}
        isStepEnabled={(step) => {
          if (step === 1) return true;
          return paper?.status === "graded";
        }}
      />

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
              {activeStage !== 3 && (
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
                    const isSingleChoice = item.question_type === "single_choice";
                    const isMultipleChoice = item.question_type === "multiple_choice" || item.question_type === "multi_choice";
                    const isTrueFalse = item.question_type === "true_false";
                    const isChoice = isSingleChoice || isMultipleChoice || isTrueFalse;
                    const choiceOptions = isTrueFalse && !(item.options?.length)
                      ? ["True", "False"]
                      : (item.options ?? []);
                    const selectedMultiChoice = splitMultiChoiceAnswer(answerValue);
                    const correctMultiChoice = splitMultiChoiceAnswer(item.correct_answer);
                    const isGraded = paper.status === "graded";
                    const isReviewStage = isGraded && activeStage === 2;
                    const isReadonly = isGraded;
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
                            {isReviewStage && (
                              <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-sm text-slate-500">
                                <span>{formatDifficultyLabel(item.difficulty)}</span>
                                <span>·</span>
                                <span>{item.question_type}</span>
                                <span>·</span>
                                <span>{buildKnowledgeLabel(item)}</span>
                              </div>
                            )}
                          </div>

                          {isChoice ? (
                            <div
                              className="mt-10 grid gap-4"
                              role={isMultipleChoice ? "group" : "radiogroup"}
                              aria-label={`第 ${item.item_order} 题选项`}
                            >
                              {choiceOptions.map((option: string) => {
                                const optionValue = isMultipleChoice ? getOptionKey(option) : option;
                                const isSelected = isMultipleChoice
                                  ? selectedMultiChoice.has(optionValue)
                                  : answerValue === optionValue;
                                const isCorrectOption = isMultipleChoice
                                  ? correctMultiChoice.has(optionValue)
                                  : (item.correct_answer ?? "") === optionValue;
                                const isWrongSelectedOption = isReviewStage && isSelected && !isCorrectOption;
                                const isRightOption = isReviewStage && isSelected && isCorrectOption;
                                return (
                                  <button
                                    key={option}
                                    type="button"
                                    role={isMultipleChoice ? "checkbox" : "radio"}
                                    aria-checked={isSelected}
                                    disabled={isReadonly}
                                    onClick={() => {
                                      setAnswers((current) => {
                                        if (!isMultipleChoice) {
                                          return {
                                            ...current,
                                            [item.id]: isSelected ? "" : optionValue,
                                          };
                                        }
                                        const next = splitMultiChoiceAnswer(current[item.id]);
                                        if (next.has(optionValue)) {
                                          next.delete(optionValue);
                                        } else {
                                          next.add(optionValue);
                                        }
                                        return {
                                          ...current,
                                          [item.id]: Array.from(next).sort().join(","),
                                        };
                                      });
                                    }}
                                    className={`flex items-center gap-5 rounded-[28px] border px-7 py-6 text-left text-lg leading-8 transition ${
                                      isReviewStage
                                        ? isRightOption
                                          ? "border-emerald-300 bg-emerald-50 text-emerald-900 shadow-[0_12px_30px_rgba(16,185,129,0.12)]"
                                          : isWrongSelectedOption
                                            ? "border-rose-300 bg-rose-50 text-rose-900 shadow-[0_12px_30px_rgba(244,63,94,0.10)]"
                                            : "border-slate-200 bg-white text-slate-500"
                                        : isReadonly
                                          ? isSelected
                                            ? "border-slate-900 bg-slate-900 text-white shadow-[0_18px_40px_rgba(15,23,42,0.16)]"
                                            : "border-slate-200 bg-white text-slate-700"
                                        : isSelected
                                          ? "border-slate-900 bg-slate-900 text-white shadow-[0_18px_40px_rgba(15,23,42,0.16)]"
                                          : "border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50"
                                    } ${isReadonly ? "cursor-default" : ""} disabled:cursor-not-allowed`}
                                  >
                                    <span
                                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border-4 ${
                                        isReviewStage
                                          ? isRightOption
                                            ? "border-emerald-600 bg-white"
                                            : isWrongSelectedOption
                                              ? "border-rose-600 bg-white"
                                              : "border-slate-300 bg-white"
                                          : isReadonly
                                            ? isSelected
                                              ? "border-white bg-white"
                                              : "border-slate-400 bg-white"
                                          : isSelected
                                            ? "border-white bg-white"
                                            : "border-slate-900 bg-white"
                                      }`}
                                    >
                                      <span
                                        className={`${isMultipleChoice ? "h-3.5 w-3.5 rounded-[4px]" : "h-3.5 w-3.5 rounded-full"} ${
                                          isReviewStage
                                            ? isRightOption
                                              ? "bg-emerald-600"
                                              : isWrongSelectedOption
                                                ? "bg-rose-600"
                                                : "bg-transparent"
                                            : isReadonly
                                              ? isSelected
                                                ? "bg-slate-900"
                                                : "bg-transparent"
                                            : isSelected
                                              ? "bg-slate-900"
                                              : "bg-transparent"
                                        }`}
                                      />
                                    </span>
                                    <div className={`min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-lg [&_p]:leading-8 [&_.katex-display]:my-3 [&_.katex]:text-inherit ${
                                      isReviewStage
                                        ? isRightOption
                                          ? "[&_p]:text-emerald-900"
                                          : isWrongSelectedOption
                                            ? "[&_p]:text-rose-900"
                                            : "[&_p]:text-slate-500"
                                        : isReadonly
                                          ? isSelected
                                            ? "[&_p]:text-white"
                                            : "[&_p]:text-slate-700"
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
                                  isReviewStage
                                    ? isCorrect
                                      ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                                      : "border-rose-300 bg-rose-50 text-rose-900"
                                    : isReadonly
                                      ? "border-slate-200 bg-slate-50 text-slate-900"
                                    : "border-slate-200 bg-white text-slate-900 focus:border-slate-400"
                                }`}
                                placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                                value={answerValue}
                                onChange={(event) =>
                                  setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                                }
                                disabled={isReadonly}
                              />
                            </div>
                          )}
                        </div>

                        {isReviewStage && (
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

                <section className="flex flex-col items-center justify-center gap-3 border-t border-slate-100 pt-4 pb-12 text-center sm:pb-16">
                  <Button
                    className={`h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)] ${paper.status === "graded" ? "hidden" : ""}`}
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
                    disabled={submitExam.isPending}
                  >
                    {paper.status === "graded"
                      ? "已完成批改"
                      : submitExam.isPending
                        ? "提交中..."
                        : "提交这份考卷"}
                  </Button>
                  {paper.status === "graded" && (
                    <>
                      <Button
                        className="h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)]"
                        onClick={() => {
                          setActiveStage(3);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        查看学习指南
                      </Button>
                      <p className="text-sm text-slate-500">进入第 3 步，根据本次结果继续查漏补缺。</p>
                    </>
                  )}
                  </section>
                </div>
                </>
              )}

              {activeStage === 3 && (
                <div className="mx-auto max-w-6xl">
                  {studyGuideQuery.isLoading && (
                    <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
                      正在生成学习指南...
                    </div>
                  )}

                  {studyGuideQuery.error && (
                    <div className="rounded-[28px] border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
                      {getApiErrorMessage(studyGuideQuery.error, "学习指南生成失败")}
                    </div>
                  )}

                  {studyGuideQuery.data && (
                    <ExamStudyGuideView
                      guide={studyGuideQuery.data}
                      paper={paper}
                      onBackToReview={() => setActiveStage(2)}
                    />
                  )}
                </div>
              )}
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
  const queryClient = useQueryClient();
  const { toast } = useToast();
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

  const deleteExamMutation = useMutation({
    mutationFn: async (paperId: number) => {
      if (!subjectId) {
        throw new Error("缺少学科标识，无法删除考卷。");
      }
      return deleteExamPaper(subjectId, paperId);
    },
    onSuccess: async (_response, paperId) => {
      await queryClient.invalidateQueries({
        queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId ?? "", { page: 1, size: 24 }),
      });
      toast({
        title: "考卷已删除",
        description: `已删除考卷 #${paperId}。`,
        variant: "success",
      });
    },
    onError: (error) => {
      toast({
        title: "删除失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
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
      <div className="min-h-[calc(100vh-4rem)] bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_55%,#eef3f8_100%)] dark:bg-none dark:bg-slate-900 px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <section className="overflow-hidden px-2 py-4 sm:px-4 lg:px-6">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-800/80 px-3 py-1 text-sm font-medium text-slate-600 dark:text-slate-300">
                  <Sparkles className="h-4 w-4 text-sky-500" />
                  Exam Studio
                </div>

                <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-slate-950 dark:text-slate-100 sm:text-5xl">
                  所有考试卷都在这里
                </h1>

                <p className="mt-4 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-400 sm:text-lg">
                  一键创建新的练习卷，继续完成未做完的测试，也可以回看已经生成过的考卷与得分记录。
                </p>

                <div className="mt-8 flex flex-wrap gap-3">
                  <Button
                    size="lg"
                    className="h-14 rounded-full bg-black px-7 text-base font-semibold text-white hover:bg-slate-900"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    <Plus className="h-5 w-5" />
                    创建新考卷
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    className="h-14 rounded-full px-6 text-base font-semibold text-slate-800 dark:text-slate-200 dark:border-slate-700"
                    onClick={() => navigate(`/subject/${subjectId}/exams/question-templates`)}
                  >
                    <BookOpen className="h-5 w-5" />
                    题库查看
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    className="h-14 rounded-full px-6 text-base font-semibold text-slate-800 dark:text-slate-200 dark:border-slate-700"
                    onClick={() => navigate(`/subject/${subjectId}/exams/question-types`)}
                  >
                    <Tags className="h-5 w-5" />
                    题型查看
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
                    <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-950 dark:text-slate-100">
                      {group.title}({group.items.length})
                    </h3>
                    <div className="grid h-10 w-10 place-items-center rounded-full text-slate-500 dark:text-slate-400">
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
                          const isDeleting = deleteExamMutation.isPending && deleteExamMutation.variables === item.id;

                          const handleDeleteExam = (event: MouseEvent<HTMLButtonElement>) => {
                            event.stopPropagation();
                            if (isDeleting) return;
                            const confirmed = window.confirm(
                              `确认删除这份考卷吗？\n\n${buildExamTitle(item)}\n\n删除后无法恢复。`,
                            );
                            if (!confirmed) return;
                            deleteExamMutation.mutate(item.id);
                          };

                          const handleOpenExam = () => {
                            navigate(`/subject/${subjectId}/exams/${item.id}`);
                          };

                          const handleCardKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
                            if (event.key !== "Enter" && event.key !== " ") return;
                            event.preventDefault();
                            handleOpenExam();
                          };

                          return (
                            <div
                              key={item.id}
                              role="button"
                              tabIndex={0}
                              onClick={handleOpenExam}
                              onKeyDown={handleCardKeyDown}
                              className="group w-full rounded-[28px] border border-slate-200/80 bg-[linear-gradient(180deg,#ffffff_0%,#fbfcff_100%)] px-5 py-5 text-left transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_18px_45px_rgba(15,23,42,0.08)] sm:px-6"
                            >
                              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                                <div className="flex min-w-0 items-start gap-4">
                                  <div className={`mt-1 grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br ${statusMeta.accent} text-slate-950 shadow-lg`}>
                                    <Target className="h-6 w-6" />
                                  </div>

                                  <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-3">
                                      <h3 className="truncate text-xl font-semibold tracking-[-0.03em] text-slate-950 dark:text-slate-100">
                                        {buildExamTitle(item)}
                                      </h3>
                                      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusMeta.tone}`}>
                                        {statusMeta.label}
                                      </span>
                                    </div>

                                    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
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
                                      <div className="rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-sm font-medium text-slate-700 dark:text-slate-300">
                                        得分：{scoreText}
                                      </div>
                                      <div className="rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-sm font-medium text-slate-700 dark:text-slate-300">
                                        学科：{item.subject}
                                      </div>
                                    </div>
                                  </div>
                                </div>

                                <div className="flex items-center justify-between gap-4 lg:justify-end">
                                  <div className="flex items-center gap-3">
                                    <div className="text-sm text-slate-400">
                                      {item.graded_at
                                        ? `最近批改 ${formatDateTime(item.graded_at)}`
                                        : item.submitted_at
                                          ? `最近提交 ${formatDateTime(item.submitted_at)}`
                                          : "点击进入考试"}
                                    </div>
                                    <Button
                                      type="button"
                                      size="icon"
                                      variant="outline"
                                      className="h-12 w-12 rounded-full border-red-200 bg-white text-red-500 hover:bg-red-50 hover:text-red-600"
                                      aria-label={`删除考卷 ${buildExamTitle(item)}`}
                                      title="删除考卷"
                                      disabled={isDeleting}
                                      onClick={handleDeleteExam}
                                    >
                                      <Trash2 className="h-[18px] w-[18px]" />
                                    </Button>
                                  </div>
                                  <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 transition group-hover:bg-slate-900 dark:group-hover:bg-slate-700 group-hover:text-white">
                                    <ChevronRight className="h-5 w-5" />
                                  </div>
                                </div>
                              </div>
                            </div>
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

function JsonBadge({ value }: { value: unknown }) {
  const text = JSON.stringify(value ?? {}, null, 2);
  if (!text || text === "{}" || text === "[]") {
    return <span className="text-slate-400">无</span>;
  }
  return (
    <pre className="max-h-40 overflow-auto border-l-2 border-slate-200 pl-3 text-xs leading-5 text-slate-600">
      {text}
    </pre>
  );
}

function KnowledgeRefTags({ refs }: { refs: Array<Record<string, unknown>> }) {
  if (!refs.length) {
    return <span className="text-sm text-slate-400">无</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {refs.map((ref, index) => {
        const unitId = ref.knowledge_unit_id ?? ref.unit_id ?? "unknown";
        const role = String(ref.role ?? "related");
        const weight = Number(ref.coverage_weight ?? 1);
        const weightLabel = Number.isFinite(weight) ? weight.toFixed(2).replace(/\.?0+$/, "") : "1";

        return (
          <span
            key={`${String(unitId)}-${role}-${index}`}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm"
          >
            <span className="text-slate-950">知识点 #{String(unitId)}</span>
            <span className="text-slate-400">|</span>
            <span>{role}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
              {weightLabel}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function ExamCatalogShell({
  subjectId,
  eyebrow,
  title,
  description,
  children,
}: {
  subjectId: string;
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_55%,#eef3f8_100%)] dark:bg-none dark:bg-slate-900 px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="px-2 py-4 sm:px-4 lg:px-6">
          <button
            type="button"
            onClick={() => navigate(`/subject/${subjectId}/exams`)}
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            返回考试中心
          </button>
          <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-600">
                <Sparkles className="h-4 w-4 text-sky-500" />
                {eyebrow}
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">
                {title}
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600 sm:text-base">
                {description}
              </p>
            </div>
            <div className="text-sm font-semibold text-slate-500">
              当前学科：{subjectId}
            </div>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

export function QuestionTemplatesPage() {
  const { subjectId } = useParams();

  const templatesQuery = useQuery({
    queryKey: ["exam-question-templates", subjectId],
    enabled: Boolean(subjectId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplates(subjectId ?? "", signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
  });

  if (!subjectId) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-[#f7f8fc] px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少学科标识，暂时无法加载题库。
        </div>
      </div>
    );
  }

  return (
    <ExamCatalogShell
      subjectId={subjectId}
      eyebrow="Question Bank"
      title="题库模板"
      description="这里展示当前学科已经沉淀下来的所有 QuestionTemplate。它们是可复用的题目模板，生成试卷时会复制为本次考试的题目快照。"
    >
      {templatesQuery.isLoading && (
        <div className="px-6 py-12 text-center text-sm text-slate-500">
          正在加载题库模板...
        </div>
      )}

      {templatesQuery.error && (
        <div className="px-2 py-4 text-sm text-red-700">
          {getApiErrorMessage(templatesQuery.error, "题库模板加载失败")}
        </div>
      )}

      {!templatesQuery.isLoading && !templatesQuery.error && (templatesQuery.data ?? []).length === 0 && (
        <div className="px-6 py-12 text-center">
          <BookOpen className="mx-auto h-10 w-10 text-slate-300" />
          <h3 className="mt-4 text-lg font-semibold text-slate-900">还没有题库模板</h3>
          <p className="mt-2 text-sm text-slate-500">创建考试后，系统生成的题目会沉淀到这里。</p>
        </div>
      )}

      <div className="grid gap-4">
        {(templatesQuery.data ?? []).map((item) => (
          <article
            key={item.id}
            className="rounded-[28px] border border-slate-200 bg-white px-5 py-5 shadow-sm transition hover:border-slate-300 sm:px-6"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                    #{item.id}
                  </span>
                  <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
                    {item.question_type}
                  </span>
                  <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                    {item.difficulty}
                  </span>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                    {item.status}
                  </span>
                </div>
                <div className="mt-4 text-base leading-8 text-slate-900">
                  <ExamMarkdown content={item.stem} />
                </div>
              </div>
              <div className="shrink-0 text-sm text-slate-500">
                知识单元：{item.knowledge_unit_id ?? "未绑定"}
              </div>
            </div>

            {item.options?.length ? (
              <div className="mt-5 grid gap-2 border-t border-slate-100 pt-4 md:grid-cols-2">
                {item.options.map((option, index) => (
                  <div key={`${item.id}-${index}`} className="text-sm leading-7 text-slate-700">
                    {option}
                  </div>
                ))}
              </div>
            ) : null}

            <div className="mt-5 grid gap-4 border-t border-slate-100 pt-5 lg:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">标准答案</p>
                <div className="mt-2 text-sm leading-7 text-emerald-950">
                  <ExamMarkdown content={item.answer} />
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">解析</p>
                <div className="mt-2 text-sm leading-7 text-slate-700">
                  <ExamMarkdown content={item.explanation} />
                </div>
              </div>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">知识点应用</p>
                <KnowledgeRefTags refs={item.knowledge_unit_refs} />
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">选择提示</p>
                <JsonBadge value={item.selection_hints} />
              </div>
            </div>
          </article>
        ))}
      </div>
    </ExamCatalogShell>
  );
}

export function QuestionTypesPage() {
  const { subjectId } = useParams();

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", subjectId],
    enabled: Boolean(subjectId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(subjectId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });

  if (!subjectId) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-[#f7f8fc] px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少学科标识，暂时无法加载题型。
        </div>
      </div>
    );
  }

  const rows = typesQuery.data ?? [];
  const globalRows = rows.filter((item) => item.scope === "global");
  const subjectRows = rows.filter((item) => item.scope !== "global");

  return (
    <ExamCatalogShell
      subjectId={subjectId}
      eyebrow="Question Types"
      title="题型注册表"
      description="这里展示系统基础题型和当前学科题型。后续系统从样卷中学习出的特色题型，也可以进入这张注册表。"
    >
      {typesQuery.isLoading && (
        <div className="px-6 py-12 text-center text-sm text-slate-500">
          正在加载题型...
        </div>
      )}

      {typesQuery.error && (
        <div className="px-2 py-4 text-sm text-red-700">
          {getApiErrorMessage(typesQuery.error, "题型加载失败")}
        </div>
      )}

      {!typesQuery.isLoading && !typesQuery.error && (
        <div className="grid gap-6">
          {[
            { title: "基础题型", rows: globalRows, icon: <Tags className="h-5 w-5" /> },
            { title: "当前学科题型", rows: subjectRows, icon: <Layers3 className="h-5 w-5" /> },
          ].map((group) => (
            <section key={group.title} className="space-y-4 px-1">
              <div className="flex items-center justify-between gap-3">
                <h2 className="inline-flex items-center gap-2 text-xl font-semibold tracking-[-0.03em] text-slate-950">
                  {group.icon}
                  {group.title}
                </h2>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-600">
                  {group.rows.length} 类
                </span>
              </div>

              {group.rows.length === 0 ? (
                <div className="px-5 py-8 text-center text-sm text-slate-500">
                  暂无{group.title}
                </div>
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {group.rows.map((item) => (
                    <article key={item.id} className="rounded-[28px] border border-slate-200 bg-white px-5 py-5 shadow-sm transition hover:border-slate-300">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <h3 className="text-lg font-semibold text-slate-950">{item.display_name}</h3>
                          <p className="mt-1 font-mono text-xs text-slate-500">{item.type_key}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200">
                            {item.scope}
                          </span>
                          <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200">
                            {item.grading_method}
                          </span>
                          {item.is_system && (
                            <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700">
                              system
                            </span>
                          )}
                        </div>
                      </div>

                      <p className="mt-4 text-sm leading-7 text-slate-600">{item.description || "暂无描述"}</p>
                      <div className="mt-4 border-t border-slate-100 pt-4 text-sm leading-7 text-slate-600">
                        <span className="font-semibold text-slate-900">答案格式：</span>
                        {item.answer_format || "未配置"}
                      </div>

                      <div className="mt-4 grid gap-4 border-t border-slate-100 pt-4">
                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">选项结构</p>
                          <JsonBadge value={item.option_schema} />
                        </div>
                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">评分规则</p>
                          <JsonBadge value={item.rubric} />
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
    </ExamCatalogShell>
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
