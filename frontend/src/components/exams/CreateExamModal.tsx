import { useEffect, useState } from "react";
import {
  RotateCcw,
  Save,
} from "lucide-react";

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
const QUESTION_COUNT_PRESETS = [
  { label: "轻量", value: 10 },
  { label: "标准", value: 24 },
  { label: "冲刺", value: 40 },
] as const;
type QuestionCountMode = "preset" | "custom";

function getQuestionCountMode(numQuestions: number): QuestionCountMode {
  return QUESTION_COUNT_PRESETS.some((preset) => preset.value === numQuestions) ? "preset" : "custom";
}

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

export function applyExamModeToCreateConfig(
  config: CreateExamConfig,
  examMode: CreateExamConfig["examMode"],
): CreateExamConfig {
  return normalizeCreateExamConfig({
    ...config,
    examMode,
    numQuestions:
      examMode === "paper_exam" && config.examMode !== "paper_exam" && config.numQuestions <= 12
        ? 24
        : config.numQuestions,
  });
}

export function getDefaultCreateExamConfigForMode(examMode: CreateExamConfig["examMode"]): CreateExamConfig {
  return applyExamModeToCreateConfig(DEFAULT_CREATE_EXAM_CONFIG, examMode);
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
  initialExamMode?: CreateExamConfig["examMode"] | null;
  onClose: () => void;
}

export function CreateExamModal({ open, courseId, courseName, initialExamMode, onClose }: CreateExamModalProps) {
  const { toast } = useToast();
  const [config, setConfig] = useState<CreateExamConfig>(() => loadCreateExamConfig(courseId));
  const [questionCountMode, setQuestionCountMode] = useState<QuestionCountMode>(() =>
    getQuestionCountMode(loadCreateExamConfig(courseId).numQuestions),
  );
  const displayName = courseName?.trim() || "当前课程";
  const activeExamMode = PAPER_EXAM_MODES.find((item) => item.value === config.examMode);
  const isCustomQuestionCount = questionCountMode === "custom";

  useEffect(() => {
    if (!open) return;
    const stored = loadCreateExamConfig(courseId);
    const nextConfig = initialExamMode ? applyExamModeToCreateConfig(stored, initialExamMode) : stored;
    setConfig(nextConfig);
    setQuestionCountMode(getQuestionCountMode(nextConfig.numQuestions));
  }, [open, courseId, initialExamMode]);

  const handleReset = () => {
    const resetConfig = applyExamModeToCreateConfig(DEFAULT_CREATE_EXAM_CONFIG, config.examMode);
    setConfig(resetConfig);
    setQuestionCountMode(getQuestionCountMode(resetConfig.numQuestions));
    saveCreateExamConfig(courseId, resetConfig);
    toast({
      title: "配置已重置",
      description: "之后会使用当前模式的默认配置开始训练或测试。",
      variant: "success",
    });
  };

  const handleSave = () => {
    saveCreateExamConfig(courseId, config);
    toast({
      title: "配置已保存",
      description: "下次点击开始会直接使用这套配置。",
      variant: "success",
    });
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`${activeExamMode?.label ?? "出题"}配置`}
      className="max-w-2xl rounded-xl"
    >
      <div className="space-y-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">当前课程</p>
          <h3 className="mt-1 break-words text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">
            {displayName}
          </h3>
        </div>

        <section className="divide-y divide-slate-100 dark:divide-slate-800">
          <div className="grid gap-3 py-4 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center">
            <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">题目数量</p>
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 sm:grid-cols-4 dark:bg-slate-800/60">
                {QUESTION_COUNT_PRESETS.map((preset) => {
                  const selected = !isCustomQuestionCount && config.numQuestions === preset.value;
                  return (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() => {
                        setQuestionCountMode("preset");
                        setConfig((current) => ({
                          ...current,
                          numQuestions: preset.value,
                        }));
                      }}
                      className={`rounded-md px-3 py-2 text-center text-sm transition ${
                        selected
                          ? "bg-white font-semibold text-slate-950 shadow-sm dark:bg-slate-950 dark:text-slate-100"
                          : "text-slate-600 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900/70 dark:hover:text-slate-100"
                      }`}
                      aria-pressed={selected}
                    >
                      {preset.label} <span className="text-xs text-slate-400">{preset.value}题</span>
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setQuestionCountMode("custom")}
                  className={`rounded-md px-3 py-2 text-center text-sm transition ${
                    isCustomQuestionCount
                      ? "bg-white font-semibold text-slate-950 shadow-sm dark:bg-slate-950 dark:text-slate-100"
                      : "text-slate-600 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900/70 dark:hover:text-slate-100"
                  }`}
                  aria-pressed={isCustomQuestionCount}
                >
                  自定义
                </button>
              </div>
              {isCustomQuestionCount && (
                <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                  <span>题量</span>
                  <input
                    className="h-9 w-24 rounded-lg border border-transparent bg-slate-100 px-3 text-center font-semibold tabular-nums text-slate-950 outline-none transition focus:border-slate-300 focus:bg-white dark:bg-slate-800/60 dark:text-slate-100 dark:focus:border-slate-700"
                    type="number"
                    min={1}
                    max={80}
                    value={config.numQuestions}
                    aria-label="自定义题目数量"
                    onChange={(event) =>
                      setConfig((current) => ({
                        ...current,
                        numQuestions: Math.min(80, Math.max(1, Number(event.target.value) || 1)),
                      }))
                    }
                  />
                  <span>题</span>
                </label>
              )}
            </div>
          </div>

          {config.examMode === "paper_exam" && (
            <div className="grid gap-3 py-4 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center">
              <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">考卷格式</p>
              <select
                className="h-10 w-full rounded-lg border border-transparent bg-slate-100 px-3 text-sm font-medium text-slate-900 outline-none transition focus:border-slate-300 focus:bg-white dark:bg-slate-800/60 dark:text-slate-100 dark:focus:border-slate-700"
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
            </div>
          )}

          <label className="grid gap-3 py-4 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-start">
            <span className="text-sm font-semibold text-slate-950 dark:text-slate-100">出题要求</span>
            <textarea
              className="min-h-20 w-full resize-none rounded-lg border border-transparent bg-slate-50 px-3 py-2.5 text-sm leading-6 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-700"
              placeholder="题型、难度或重点范围"
              value={config.userPrompt}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  userPrompt: event.target.value,
                }))
              }
            />
          </label>
        </section>

        <div className="flex justify-end gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
          <Button variant="outline" className="rounded-full px-5" onClick={handleReset}>
            <RotateCcw className="h-4 w-4" />
            重置
          </Button>
          <Button className="rounded-full bg-black px-6 dark:bg-white dark:text-slate-950" onClick={handleSave}>
            <Save className="h-4 w-4" />
            保存配置
          </Button>
        </div>
      </div>
    </Modal>
  );
}
