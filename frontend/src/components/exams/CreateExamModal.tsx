import { useEffect, useState } from "react";
import { RotateCcw, Save } from "lucide-react";

import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import { PAPER_EXAM_MODES, PAPER_LAYOUT_MODES } from "./examDisplay";

export interface CreateExamConfig {
  examMode: (typeof PAPER_EXAM_MODES)[number]["value"];
  numQuestions: number;
  userPrompt: string;
  paperLayoutMode: (typeof PAPER_LAYOUT_MODES)[number]["value"];
}

export const DEFAULT_CREATE_EXAM_CONFIG: CreateExamConfig = {
  examMode: "paper_exam",
  numQuestions: 24,
  userPrompt: "",
  paperLayoutMode: "auto",
};

const CREATE_EXAM_CONFIG_STORAGE_PREFIX = "aiteachme.exam.createConfig.v1";

function getCreateExamConfigStorageKey(courseId: string) {
  return `${CREATE_EXAM_CONFIG_STORAGE_PREFIX}.${courseId}`;
}

function normalizeCreateExamConfig(
  value: (Partial<CreateExamConfig> & { focusPrompt?: string }) | null | undefined,
): CreateExamConfig {
  const examModeValues = new Set<string>(PAPER_EXAM_MODES.map((item) => item.value));
  const paperLayoutModeValues = new Set<string>(PAPER_LAYOUT_MODES.map((item) => item.value));
  const examMode = examModeValues.has(value?.examMode ?? "")
    ? (value?.examMode as CreateExamConfig["examMode"])
    : DEFAULT_CREATE_EXAM_CONFIG.examMode;
  const numQuestions = Number(value?.numQuestions);
  const defaultQuestionCount = examMode === "paper_exam" ? 24 : DEFAULT_CREATE_EXAM_CONFIG.numQuestions;

  return {
    examMode,
    numQuestions: Math.min(
      80,
      Math.max(1, Number.isFinite(numQuestions) ? numQuestions : defaultQuestionCount),
    ),
    userPrompt:
      typeof value?.userPrompt === "string"
        ? value.userPrompt
        : typeof value?.focusPrompt === "string"
          ? value.focusPrompt
          : DEFAULT_CREATE_EXAM_CONFIG.userPrompt,
    paperLayoutMode: paperLayoutModeValues.has(value?.paperLayoutMode ?? "")
      ? (value?.paperLayoutMode as CreateExamConfig["paperLayoutMode"])
      : DEFAULT_CREATE_EXAM_CONFIG.paperLayoutMode,
  };
}

export function loadCreateExamConfig(courseId: string): CreateExamConfig {
  if (typeof window === "undefined") {
    return DEFAULT_CREATE_EXAM_CONFIG;
  }

  try {
    const raw = window.localStorage.getItem(getCreateExamConfigStorageKey(courseId));
    return normalizeCreateExamConfig(raw ? JSON.parse(raw) : null);
  } catch {
    return DEFAULT_CREATE_EXAM_CONFIG;
  }
}

export function saveCreateExamConfig(courseId: string, config: CreateExamConfig) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    getCreateExamConfigStorageKey(courseId),
    JSON.stringify(normalizeCreateExamConfig(config)),
  );
}

export function toExamGenerateRequest(config: CreateExamConfig) {
  const normalized = normalizeCreateExamConfig(config);

  return {
    exam_mode: normalized.examMode,
    user_prompt: normalized.userPrompt.trim() || undefined,
    num_questions: normalized.numQuestions,
    paper_layout_mode: normalized.examMode === "paper_exam" ? normalized.paperLayoutMode : undefined,
  };
}

interface CreateExamModalProps {
  open: boolean;
  courseId: string;
  courseName?: string | null;
  onClose: () => void;
}

export function CreateExamModal({ open, courseId, courseName, onClose }: CreateExamModalProps) {
  const { toast } = useToast();
  const [config, setConfig] = useState<CreateExamConfig>(() => loadCreateExamConfig(courseId));
  const displayName = courseName?.trim() || "当前课程";

  useEffect(() => {
    if (!open) return;
    setConfig(loadCreateExamConfig(courseId));
  }, [open, courseId]);

  const handleReset = () => {
    setConfig(DEFAULT_CREATE_EXAM_CONFIG);
    saveCreateExamConfig(courseId, DEFAULT_CREATE_EXAM_CONFIG);
    toast({
      title: "配置已重置",
      description: "之后会使用默认配置开始训练或测试。",
      variant: "success",
    });
  };

  const handleSave = () => {
    saveCreateExamConfig(courseId, config);
    toast({
      title: "配置已保存",
      description: "下次点击测试会直接使用这套配置。",
      variant: "success",
    });
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title="训练与测试配置" className="max-w-2xl rounded-[28px]">
      <div className="space-y-6">
        <div className="rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,#fbfcff_0%,#f5f8ff_100%)] p-5 dark:border-slate-800 dark:bg-[linear-gradient(180deg,rgba(15,23,42,0.96)_0%,rgba(30,41,59,0.76)_100%)]">
          <p className="text-sm font-medium text-indigo-600 dark:text-indigo-300">面向当前课程</p>
          <h3 className="mt-2 text-2xl font-semibold text-slate-950 dark:text-slate-100">{displayName}</h3>
          <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-400">
            保存后，测试按钮会直接使用这套配置开始出题；需要调整时可再次进入这里。
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-sm text-slate-600 dark:text-slate-300">
            类型
            <select
              className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-500"
              value={config.examMode}
              onChange={(event) =>
                setConfig((current) => {
                  const examMode = event.target.value as CreateExamConfig["examMode"];
                  return {
                    ...current,
                    examMode,
                    numQuestions:
                      examMode === "paper_exam" && current.examMode !== "paper_exam" && current.numQuestions <= 10
                        ? 24
                        : current.numQuestions,
                  };
                })
              }
            >
              {PAPER_EXAM_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
            <span className="mt-2 block text-xs leading-6 text-slate-400 dark:text-slate-500">
              {PAPER_EXAM_MODES.find((item) => item.value === config.examMode)?.description}
            </span>
          </label>

          <label className="text-sm text-slate-600 dark:text-slate-300">
            题目数量
            <input
              className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-500"
              type="number"
              min={1}
              max={80}
              value={config.numQuestions}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  numQuestions: Math.min(80, Math.max(1, Number(event.target.value) || 1)),
                }))
              }
            />
          </label>

          {config.examMode === "paper_exam" && (
            <label className="text-sm text-slate-600 dark:text-slate-300">
              试卷版式
              <select
                className="mt-2 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-500"
                value={config.paperLayoutMode}
                onChange={(event) =>
                  setConfig((current) => ({
                    ...current,
                    paperLayoutMode: event.target.value as CreateExamConfig["paperLayoutMode"],
                  }))
                }
              >
                {PAPER_LAYOUT_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
              <span className="mt-2 block text-xs leading-6 text-slate-400 dark:text-slate-500">
                {PAPER_LAYOUT_MODES.find((item) => item.value === config.paperLayoutMode)?.description}
              </span>
            </label>
          )}

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/70">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">智能策略</p>
            <p className="mt-2 text-sm leading-7 text-slate-500 dark:text-slate-400">
              系统会结合知识点覆盖、练习状态和我的要求自动规划题型与难度。
            </p>
          </div>
        </div>

        <label className="block text-sm text-slate-600 dark:text-slate-300">
          我的要求
          <textarea
            className="mt-2 min-h-32 w-full rounded-[24px] border border-slate-200 bg-white px-4 py-4 text-sm leading-7 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-500"
            placeholder="例如：重点考递归和动态规划，题目接近期末考试，难度偏高，选项要有迷惑性"
            value={config.userPrompt}
            onChange={(event) =>
              setConfig((current) => ({
                ...current,
                userPrompt: event.target.value,
              }))
            }
          />
        </label>

        <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-500 dark:text-slate-400">配置保存在当前浏览器中，不会影响其他设备。</p>
          <div className="flex gap-3">
            <Button variant="outline" className="rounded-full px-5" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              重置
            </Button>
            <Button className="rounded-full bg-black px-6" onClick={handleSave}>
              <Save className="h-4 w-4" />
              保存
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
