import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, GraduationCap, History, Sparkles } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey,
  getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey,
  useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet,
  useExamHistoryApiV1SubjectsSubjectExamsHistoryGet,
  useGenerateExamApiV1SubjectsSubjectExamsGeneratePost,
  useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost,
} from "../api/generated/exams";
import type { ExamHistoryItem, ExamNodeLinkResponse, ExamPaperDetailResponse, ExamPaperItemResponse } from "../api/generated/model";
import { getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey } from "../api/generated/profile";
import { getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

const EXAM_MODES = [
  { value: "web_practice", label: "专项练习" },
  { value: "paper_exam", label: "整卷测试" },
] as const;

const DIFFICULTIES = [
  { value: "easy", label: "基础" },
  { value: "medium", label: "标准" },
  { value: "hard", label: "强化" },
] as const;

export function ExamsPage() {
  const { subjectId } = useParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [examMode, setExamMode] = useState<(typeof EXAM_MODES)[number]["value"]>("web_practice");
  const [difficulty, setDifficulty] = useState<(typeof DIFFICULTIES)[number]["value"]>("medium");
  const [numQuestions, setNumQuestions] = useState(8);
  const [focusPrompt, setFocusPrompt] = useState("");
  const [activePaperId, setActivePaperId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const historyQuery = useExamHistoryApiV1SubjectsSubjectExamsHistoryGet(subjectId ?? "", { page: 1, size: 10 });
  const history = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data),
    [historyQuery.data],
  );
  const historyItems = history?.items ?? [];

  useEffect(() => {
    if (!activePaperId && historyItems.length > 0) {
      setActivePaperId(historyItems[0].id);
    }
  }, [activePaperId, historyItems]);

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet(
    subjectId ?? "",
    activePaperId ?? 0,
    {
      query: {
        enabled: Boolean(subjectId && activePaperId),
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

  const generateExam = useGenerateExamApiV1SubjectsSubjectExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id || !subjectId) return;
        setActivePaperId(created.exam_paper_id);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 10 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, created.exam_paper_id),
          }),
        ]);
        toast({
          title: "试卷已生成",
          description: `已生成 ${created.num_questions} 题，开始作答吧。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "生成失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const submitExam = useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost({
    mutation: {
      onSuccess: async (response) => {
        if (!subjectId || !activePaperId) return;
        const graded = unwrapOrvalResponse(response);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 10 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, activePaperId),
          }),
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey(subjectId),
          }),
        ]);
        toast({
          title: "提交完成",
          description: `得分 ${graded?.score ?? 0}，已同步更新掌握状态。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "提交失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  if (!subjectId) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8">
        <div className="mx-auto max-w-5xl rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-amber-900">
          缺少学科标识，暂时无法生成试卷。
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-500">Examine</p>
              <h1 className="mt-1 text-3xl font-semibold text-slate-950">{subjectId}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                当前出题完全基于 KnowledgeUnit。专项练习会优先覆盖薄弱和到期复习知识点，整卷测试会混合基础与综合题。
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
              <Sparkles className="h-4 w-4" />
              支持 single_choice / fill_blank / short_answer 混合出题
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.92fr_1.08fr]">
          <div className="flex flex-col gap-6">
            <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2 text-slate-950">
                <GraduationCap className="h-5 w-5" />
                <h2 className="text-lg font-semibold">生成试卷</h2>
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <label className="text-sm text-slate-600">
                  模式
                  <select
                    className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900"
                    value={examMode}
                    onChange={(event) => setExamMode(event.target.value as typeof examMode)}
                  >
                    {EXAM_MODES.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="text-sm text-slate-600">
                  难度
                  <select
                    className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900"
                    value={difficulty}
                    onChange={(event) => setDifficulty(event.target.value as typeof difficulty)}
                  >
                    {DIFFICULTIES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="text-sm text-slate-600">
                  题量
                  <input
                    className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900"
                    type="number"
                    min={1}
                    max={40}
                    value={numQuestions}
                    onChange={(event) => setNumQuestions(Number(event.target.value) || 1)}
                  />
                </label>

                <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  当前会自动带入你的掌握状态和复习优先级。
                </div>
              </div>

              <label className="mt-4 block text-sm text-slate-600">
                聚焦范围
                <textarea
                  className="mt-2 min-h-28 w-full rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900"
                  placeholder="例如：递归、动态规划、SQL 聚合、微积分中的极限"
                  value={focusPrompt}
                  onChange={(event) => setFocusPrompt(event.target.value)}
                />
              </label>

              <div className="mt-5 flex items-center justify-between gap-4">
                <p className="text-sm text-slate-500">
                  生成后会自动创建试卷并写入历史记录。
                </p>
                <Button
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
                  {generateExam.isPending ? "生成中..." : "开始出题"}
                </Button>
              </div>

              {generateExam.error && (
                <p className="mt-4 text-sm text-red-600">
                  {getApiErrorMessage(generateExam.error, "生成失败")}
                </p>
              )}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2 text-slate-950">
                <History className="h-5 w-5" />
                <h2 className="text-lg font-semibold">最近试卷</h2>
              </div>

              <div className="mt-5 space-y-3">
                {historyQuery.isLoading && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    正在加载历史试卷...
                  </div>
                )}

                {!historyQuery.isLoading && historyItems.length === 0 && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    还没有试卷，先生成一份吧。
                  </div>
                )}

                {historyItems.map((item: ExamHistoryItem) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActivePaperId(item.id)}
                    className={`w-full rounded-lg border px-4 py-4 text-left transition ${
                      activePaperId === item.id
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-900 hover:border-slate-300"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium">{item.exam_mode}</p>
                        <p className={`mt-1 text-xs ${activePaperId === item.id ? "text-slate-200" : "text-slate-500"}`}>
                          {item.total_items} 题 · {item.status}
                        </p>
                      </div>
                      <div className={`text-sm ${activePaperId === item.id ? "text-slate-100" : "text-slate-600"}`}>
                        {item.score_obtained != null && item.total_score != null
                          ? `${item.score_obtained}/${item.total_score}`
                          : "--"}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-slate-950">
                <FileText className="h-5 w-5" />
                <h2 className="text-lg font-semibold">当前试卷</h2>
              </div>
              {paper && (
                <div className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {paper.exam_mode} · {paper.status}
                </div>
              )}
            </div>

            {examDetailQuery.error && (
              <p className="mt-4 text-sm text-red-600">
                {getApiErrorMessage(examDetailQuery.error, "加载试卷失败")}
              </p>
            )}

            {examDetailQuery.isLoading && (
              <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                正在加载试卷...
              </div>
            )}

            {!examDetailQuery.isLoading && !paper && (
              <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
                选择左侧试卷，或先生成一份新试卷。
              </div>
            )}

            {paper && (
              <>
                <div className="mt-5 flex flex-wrap gap-3 text-sm text-slate-600">
                  <div className="rounded-lg bg-slate-50 px-4 py-2">{paper.total_items} 题</div>
                  <div className="rounded-lg bg-slate-50 px-4 py-2">
                    得分 {paper.score_obtained ?? "--"} / {paper.total_score ?? "--"}
                  </div>
                </div>

                <div className="mt-6 space-y-5">
                  {(paper.items ?? []).map((item: ExamPaperItemResponse) => {
                    const linkLabel =
                      item.knowledge_unit_links
                        ?.map((link: ExamNodeLinkResponse) => link.knowledge_unit_name)
                        .filter(Boolean)
                        .join(", ") ||
                      "未命名知识点";
                    const answerValue = answers[item.id] ?? "";
                    const isChoice = item.question_type === "single_choice";

                    return (
                      <div key={item.id} className="rounded-lg border border-slate-200 px-4 py-5">
                        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                          <div>
                            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                              Q{item.item_order} · {item.question_type} · {item.difficulty}
                            </p>
                            <h3 className="mt-2 text-base font-medium leading-7 text-slate-950">{item.stem}</h3>
                          </div>
                          <div className="rounded-md bg-slate-100 px-3 py-1 text-xs text-slate-600">
                            {linkLabel}
                          </div>
                        </div>

                        {isChoice ? (
                          <div className="mt-4 grid gap-2">
                            {(item.options ?? []).map((option: string) => (
                              <label
                                key={option}
                                className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 px-3 py-3 text-sm text-slate-700"
                              >
                                <input
                                  type="radio"
                                  name={`exam-item-${item.id}`}
                                  checked={answerValue === option}
                                  onChange={() =>
                                    setAnswers((current) => ({ ...current, [item.id]: option }))
                                  }
                                  disabled={paper.status === "graded"}
                                />
                                <span>{option}</span>
                              </label>
                            ))}
                          </div>
                        ) : (
                          <textarea
                            className="mt-4 min-h-28 w-full rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900"
                            placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                            value={answerValue}
                            onChange={(event) =>
                              setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                            }
                            disabled={paper.status === "graded"}
                          />
                        )}

                        {paper.status === "graded" && (
                          <div className="mt-4 space-y-2 rounded-lg bg-slate-50 px-4 py-4 text-sm text-slate-600">
                            <p>你的答案：{item.user_answer || "未作答"}</p>
                            <p>正确答案：{item.correct_answer || "无标准答案"}</p>
                            <p>解析：{item.explanation}</p>
                            <p>结果：{item.is_correct ? "正确" : "待加强"}</p>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="mt-6 flex items-center justify-between gap-4 border-t border-slate-200 pt-5">
                  <p className="text-sm text-slate-500">
                    提交后会更新掌握度并生成新的复习任务。
                  </p>
                  <Button
                    onClick={() =>
                      activePaperId &&
                      submitExam.mutate({
                        subject: subjectId,
                        examPaperId: activePaperId,
                        data: {
                          answers: (paper.items ?? []).map((item: ExamPaperItemResponse) => ({
                            exam_paper_item_id: item.id,
                            item_order: item.item_order,
                            answer: answers[item.id] ?? "",
                          })),
                        },
                      })
                    }
                    disabled={!activePaperId || paper.status === "graded" || submitExam.isPending}
                  >
                    {paper.status === "graded"
                      ? "已批改"
                      : submitExam.isPending
                        ? "提交中..."
                        : "提交试卷"}
                  </Button>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
