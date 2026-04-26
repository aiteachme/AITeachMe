import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey, useGenerateExamApiV1SubjectsSubjectExamsGeneratePost } from "../../api/generated/exams";
import { getApiErrorMessage } from "../../api/client";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { DIFFICULTIES, EXAM_MODES, formatDifficultyLabel } from "./examDisplay";

interface CreateExamModalProps {
  open: boolean;
  subjectId: string;
  onClose: () => void;
  onCreated: (paperId: number) => void;
}

export function CreateExamModal({ open, subjectId, onClose, onCreated }: CreateExamModalProps) {
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
