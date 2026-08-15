import { useEffect, useMemo, useState } from "react";

import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import { PAPER_EXAM_MODES, PAPER_LAYOUT_MODES } from "./examDisplay";
import {
  CREATE_EXAM_DIFFICULTY_OPTIONS,
  CREATE_EXAM_QUESTION_COUNT_PRESETS,
  CREATE_EXAM_QUESTION_TYPE_OPTIONS,
  getDefaultCreateExamConfigForMode,
  loadCreateExamConfig,
  normalizeCreateExamConfig,
  saveCreateExamConfig,
  type CreateExamConfig,
} from "./examConfig";
import {
  getQuestionCountMode,
  OptionToggleGrid,
  QuestionCountSelector,
  TrainingConfigActions,
  TrainingConfigField,
  TrainingConfigIntro,
  type OptionSelectionMode,
  type QuestionCountMode,
} from "./TrainingConfigModal";

export {
  applyExamModeToCreateConfig,
  buildExamConfigUserPrompt,
  formatCreateExamDifficultySummary,
  formatCreateExamQuestionTypeSummary,
  getDefaultCreateExamConfigForMode,
  loadCreateExamConfig,
  saveCreateExamConfig,
  toExamGenerateRequest,
} from "./examConfig";
export type { CreateExamConfig } from "./examConfig";

interface CreateExamModalProps {
  open: boolean;
  courseId: string;
  initialExamMode?: CreateExamConfig["examMode"] | null;
  onClose: () => void;
  onSaved?: (config: CreateExamConfig) => void;
}

export function CreateExamModal({
  open,
  courseId,
  initialExamMode,
  onClose,
  onSaved,
}: CreateExamModalProps) {
  const { toast } = useToast();
  const requestedMode = initialExamMode ?? "paper_exam";
  const [config, setConfig] = useState<CreateExamConfig>(() => loadCreateExamConfig(courseId, requestedMode));
  const [questionCountMode, setQuestionCountMode] = useState<QuestionCountMode>(() =>
    getQuestionCountMode(
      loadCreateExamConfig(courseId, requestedMode).numQuestions,
      CREATE_EXAM_QUESTION_COUNT_PRESETS,
    ),
  );
  const [questionTypeMode, setQuestionTypeMode] = useState<OptionSelectionMode>(() =>
    loadCreateExamConfig(courseId, requestedMode).questionTypes.length ? "custom" : "primary",
  );
  const selectedQuestionTypeSet = useMemo(() => new Set(config.questionTypes), [config.questionTypes]);
  const activeExamMode = PAPER_EXAM_MODES.find((item) => item.value === config.examMode);
  const activeDifficulty = CREATE_EXAM_DIFFICULTY_OPTIONS.find((item) => item.value === config.difficulty);

  useEffect(() => {
    if (!open) return;
    const stored = loadCreateExamConfig(courseId, requestedMode);
    setConfig(stored);
    setQuestionCountMode(getQuestionCountMode(stored.numQuestions, CREATE_EXAM_QUESTION_COUNT_PRESETS));
    setQuestionTypeMode(stored.questionTypes.length ? "custom" : "primary");
  }, [courseId, open, requestedMode]);

  const toggleQuestionType = (questionType: string) => {
    const normalizedQuestionType = questionType as CreateExamConfig["questionTypes"][number];
    setConfig((current) => ({
      ...current,
      questionTypes: current.questionTypes.includes(normalizedQuestionType)
        ? current.questionTypes.filter((item) => item !== normalizedQuestionType)
        : [...current.questionTypes, normalizedQuestionType],
    }));
  };

  const handleReset = () => {
    const resetConfig = getDefaultCreateExamConfigForMode(config.examMode);
    setConfig(resetConfig);
    setQuestionCountMode(getQuestionCountMode(resetConfig.numQuestions, CREATE_EXAM_QUESTION_COUNT_PRESETS));
    setQuestionTypeMode("primary");
    toast({
      title: "已恢复默认配置",
      description: "点击保存后生效。",
      variant: "info",
    });
  };

  const handleSave = () => {
    if (questionTypeMode === "custom" && config.questionTypes.length === 0) {
      toast({
        title: "请选择题型",
        description: "指定题型模式至少选择一种题型。",
        variant: "error",
      });
      return;
    }
    const normalizedConfig = normalizeCreateExamConfig(
      questionTypeMode === "primary" ? { ...config, questionTypes: [] } : config,
      config.examMode,
    );
    saveCreateExamConfig(courseId, normalizedConfig);
    onSaved?.(normalizedConfig);
    toast({
      title: `${activeExamMode?.label ?? "出题"}配置已保存`,
      description: `下次点击开始将按 ${normalizedConfig.numQuestions} 题和当前题型、难度要求出题。`,
      variant: "success",
    });
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`${activeExamMode?.label ?? "出题"}出题配置`}
      className="max-w-2xl rounded-[24px]"
    >
      <div className="space-y-0">
        <TrainingConfigIntro
          description={config.examMode === "paper_exam"
            ? "用于阶段检验和考前模拟，保存后下次开始生效。"
            : "用于日常巩固和快速摸底，保存后下次开始生效。"}
        />

        <section className="divide-y divide-slate-100 dark:divide-slate-800">
          <TrainingConfigField label="题目数量" description="下次生成题量" align="center">
            <QuestionCountSelector
              value={config.numQuestions}
              mode={questionCountMode}
              presets={CREATE_EXAM_QUESTION_COUNT_PRESETS}
              customAriaLabel={`自定义${activeExamMode?.label ?? ""}题目数量`}
              onModeChange={setQuestionCountMode}
              onChange={(numQuestions) => setConfig((current) => ({ ...current, numQuestions }))}
            />
          </TrainingConfigField>

          <TrainingConfigField label="题型方式" description="自动搭配或手动限定">
            <OptionToggleGrid
              primaryLabel="智能搭配"
              secondaryLabel="指定题型"
              mode={questionTypeMode}
              options={CREATE_EXAM_QUESTION_TYPE_OPTIONS}
              selectedValues={selectedQuestionTypeSet}
              errorMessage={questionTypeMode === "custom" && config.questionTypes.length === 0
                ? "至少选择一种题型。"
                : null}
              onModeChange={setQuestionTypeMode}
              onToggle={toggleQuestionType}
            />
          </TrainingConfigField>

          <TrainingConfigField label="整体难度" description={activeDifficulty?.description} align="center">
            <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 sm:grid-cols-4 dark:bg-slate-900">
              {CREATE_EXAM_DIFFICULTY_OPTIONS.map((option) => {
                const selected = option.value === config.difficulty;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setConfig((current) => ({ ...current, difficulty: option.value }))}
                    className={`min-h-10 rounded-lg px-3 py-2 text-sm font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
                      selected
                        ? "bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                        : "text-slate-500 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
                    }`}
                    aria-pressed={selected}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </TrainingConfigField>

          {config.examMode === "paper_exam" ? (
            <TrainingConfigField label="考卷格式" description="选择卷面排版" align="center">
              <select
                className="h-10 w-full rounded-xl border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-500 dark:focus:ring-slate-800"
                value={config.paperLayoutMode}
                aria-label="考卷格式"
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
            </TrainingConfigField>
          ) : null}

          <TrainingConfigField label="补充要求" description="选填，补充重点或限制">
            <textarea
              className="min-h-20 w-full resize-y rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm leading-6 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-500 dark:focus:ring-slate-800"
              placeholder="例如：重点考查函数单调性，减少纯记忆题。"
              value={config.userPrompt}
              onChange={(event) => setConfig((current) => ({ ...current, userPrompt: event.target.value }))}
            />
          </TrainingConfigField>
        </section>

        <TrainingConfigActions
          onReset={handleReset}
          onCancel={onClose}
          onSave={handleSave}
          saveDisabled={questionTypeMode === "custom" && config.questionTypes.length === 0}
        />
      </div>
    </Modal>
  );
}
