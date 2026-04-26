import { useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, ChevronDown, Layers3, Loader2, MoreVertical, Plus, Sparkles, Tags } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey,
  useExamHistoryApiV1SubjectsSubjectExamsHistoryGet,
  useGenerateExamApiV1SubjectsSubjectExamsGeneratePost,
} from "../api/generated/exams";
import type { ExamHistoryItem } from "../api/generated/model";
import { getApiErrorMessage, orvalApiClient } from "../api/client";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import {
  CreateExamModal,
  ExamMarkdown,
  ExamPaperCard,
  ExamPaperWorkspace,
  buildExamTitle,
  loadCreateExamConfig,
  toExamGenerateRequest,
} from "../components/exams";
import { useExamResultDisplayPreference } from "../lib/examResultDisplayPreference";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";


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


export function ExamsPage() {
  const { subjectId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { mode: examResultDisplayMode } = useExamResultDisplayPreference();
  const [isCreateConfigOpen, setIsCreateConfigOpen] = useState(false);
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

  const generateExam = useGenerateExamApiV1SubjectsSubjectExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id) return;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId ?? "", { page: 1, size: 24 }),
        });
        navigate(`/subject/${subjectId}/exams/${created.exam_paper_id}`);
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

  const handleCreateExam = () => {
    if (!subjectId || generateExam.isPending) return;
    generateExam.mutate({
      subject: subjectId,
      data: toExamGenerateRequest(loadCreateExamConfig(subjectId)),
    });
  };

  if (!subjectId) {
    return (
      <div className="min-h-full bg-[#f7f8fc] px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900 shadow-sm">
          缺少学科标识，暂时无法加载考试中心。
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="min-h-full bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_55%,#eef3f8_100%)] dark:bg-none dark:bg-slate-900 px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          <section className="overflow-hidden px-2 py-4 sm:px-4 lg:px-6">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-800/80 px-3 py-1 text-sm font-medium text-slate-600 dark:text-slate-300">
                  <Sparkles className="h-4 w-4 text-sky-500" />
                  Exam Studio
                </div>

                <h1 className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-slate-950 dark:text-slate-100 sm:text-5xl">
                  所有考试卷都在这里
                </h1>

                <p className="mt-4 max-w-2xl text-base leading-8 text-slate-600 dark:text-slate-400 sm:text-lg">
                  一键创建新的练习卷，继续完成未做完的测试，也可以回看已经生成过的考卷与得分记录。
                </p>

                <div className="mt-8 flex flex-wrap gap-7">
                  <div className="inline-flex h-12 w-full overflow-hidden rounded-[10px] bg-black text-white shadow-sm transition-colors hover:bg-slate-900 sm:w-auto">
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center justify-center gap-2 px-6 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white active:scale-[0.99] sm:flex-none"
                      onClick={handleCreateExam}
                      disabled={generateExam.isPending}
                    >
                      {generateExam.isPending ? (
                        <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                      ) : (
                        <Plus className="h-4 w-4 shrink-0" />
                      )}
                      <span className="whitespace-nowrap">{generateExam.isPending ? "创建中..." : "创建新考卷"}</span>
                    </button>
                    <button
                      type="button"
                      className="grid h-full w-10 shrink-0 place-items-center border-l border-white/20 text-white/85 transition-colors hover:bg-white/10 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                      onClick={() => setIsCreateConfigOpen(true)}
                      aria-label="更多考卷设置"
                      title="更多设置"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </button>
                  </div>
                  <Button
                    size="lg"
                    variant="outline"
                    className="!h-12 w-full rounded-[10px] px-6 text-sm font-semibold text-slate-800 dark:border-slate-700 dark:text-slate-200 sm:w-auto"
                    onClick={() => navigate(`/subject/${subjectId}/exams/question-templates`)}
                  >
                    <BookOpen className="h-4 w-4" />
                    题库查看
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    className="!h-12 w-full rounded-[10px] px-6 text-sm font-semibold text-slate-800 dark:border-slate-700 dark:text-slate-200 sm:w-auto"
                    onClick={() => navigate(`/subject/${subjectId}/exams/question-types`)}
                  >
                    <Tags className="h-4 w-4" />
                    题型查看
                  </Button>
                </div>
              </div>
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
                    className="flex w-full items-center gap-5 px-1 py-2 text-left"
                  >
                    <h3 className="shrink-0 text-lg font-semibold tracking-[-0.02em] text-slate-950 dark:text-slate-100">
                      {group.title}({group.items.length})
                    </h3>
                    <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-slate-500 dark:text-slate-400">
                      <ChevronDown
                        className={`h-5 w-5 transition-transform ${
                          expandedGroups[group.key] ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </button>

                  {expandedGroups[group.key] && (
                    <div>
                      {group.items.length === 0 ? (
                        <div className="px-1 py-1 text-sm text-slate-500">这个分组下暂时没有考卷。</div>
                      ) : (
                        <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,250px))] justify-start gap-5">
                          {group.items.map((item: ExamHistoryItem) => {
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

                            return (
                              <ExamPaperCard
                                key={item.id}
                                item={item}
                                resultDisplayMode={examResultDisplayMode}
                                isDeleting={isDeleting}
                                onOpen={() => navigate(`/subject/${subjectId}/exams/${item.id}`)}
                                onDelete={handleDeleteExam}
                              />
                            );
                          })}
                        </div>
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
        open={isCreateConfigOpen}
        subjectId={subjectId}
        onClose={() => setIsCreateConfigOpen(false)}
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
    <div className="min-h-full bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_55%,#eef3f8_100%)] dark:bg-none dark:bg-slate-900 px-4 py-6 sm:px-6 lg:px-8">
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
      <div className="min-h-full bg-[#f7f8fc] px-6 py-8">
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
      <div className="min-h-full bg-[#f7f8fc] px-6 py-8">
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
      <div className="min-h-full bg-[#f7f8fc] px-6 py-8">
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
