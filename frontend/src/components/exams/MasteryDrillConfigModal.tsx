import { filterAvailableCustomTypeSelections, toggleCustomTypeSelection } from "./questionTypeSelection";
import { useEffect, useMemo, useState } from "react";

import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import {
  DEFAULT_MASTERY_DRILL_CONFIG,
  MASTERY_DRILL_QUESTION_COUNT_PRESETS,
  loadMasteryDrillConfig,
  normalizeMasteryDrillConfig,
  saveMasteryDrillConfig,
  toggleMasteryDrillQuestionType,
  type MasteryDrillConfig,
} from "./masteryDrillConfig";
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

export interface MasteryDrillQuestionTypeOption {
  value: string;
  label: string;
  count: number;
  registryId?: number;
  typeKey?: string;
}

export function MasteryDrillConfigModal({
  open,
  courseId,
  typeOptions,
  onClose,
  onSaved,
}: {
  open: boolean;
  courseId: string;
  typeOptions: MasteryDrillQuestionTypeOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [config, setConfig] = useState<MasteryDrillConfig>(() => loadMasteryDrillConfig(courseId));
  const [questionCountMode, setQuestionCountMode] = useState<QuestionCountMode>(() =>
    getQuestionCountMode(config.numQuestions, MASTERY_DRILL_QUESTION_COUNT_PRESETS),
  );
  const [questionTypeMode, setQuestionTypeMode] = useState<OptionSelectionMode>(() =>
    config.questionTypes.length || config.customQuestionTypes.length ? "custom" : "primary",
  );
  const typeValues = useMemo(
    () => typeOptions.filter((item) => !item.registryId).map((item) => item.value),
    [typeOptions],
  );
  const selectedTypeValues = useMemo(
    () => config.questionTypes.filter((item) => typeValues.includes(item)),
    [config.questionTypes, typeValues],
  );
  const selectedTypeSet = useMemo(() => new Set([
    ...selectedTypeValues,
    ...config.customQuestionTypes.map((item) => `registry:${item.registryId}`),
  ]), [config.customQuestionTypes, selectedTypeValues]);
  const isSelectedCustomQuestionTypeAvailable = config.customQuestionTypes.every((selected) =>
    typeOptions.some((item) => item.registryId === selected.registryId));
  const selectedTypeCount = selectedTypeValues.length + config.customQuestionTypes.length;
  const isTypeSelectionValid = questionTypeMode === "primary" || (
    selectedTypeCount > 0 && isSelectedCustomQuestionTypeAvailable
  );

  useEffect(() => {
    if (!open) return;
    const stored = loadMasteryDrillConfig(courseId);
    setConfig(stored);
    setQuestionCountMode(getQuestionCountMode(stored.numQuestions, MASTERY_DRILL_QUESTION_COUNT_PRESETS));
    setQuestionTypeMode(
      stored.questionTypes.length || stored.customQuestionTypes.length ? "custom" : "primary",
    );
  }, [courseId, open]);

  const toggleQuestionType = (typeValue: string) => {
    if (typeValue.startsWith("registry:")) {
      const registryId = Number(typeValue.slice("registry:".length));
      const selected = typeOptions.find((item) => item.registryId === registryId);
      if (!selected?.typeKey) return;
      setConfig((current) => ({
        ...current,
        customQuestionTypes: toggleCustomTypeSelection(current.customQuestionTypes, {
          registryId, typeKey: selected.typeKey ?? "",
        }),
      }));
      return;
    }
    if (!typeValues.length) return;
    setConfig((current) => ({
      ...current,
      questionTypes: toggleMasteryDrillQuestionType(
        current.questionTypes,
        typeValue,
        typeValues,
      ),
    }));
  };

  const handleReset = () => {
    const resetConfig = normalizeMasteryDrillConfig(DEFAULT_MASTERY_DRILL_CONFIG);
    setConfig(resetConfig);
    setQuestionCountMode(getQuestionCountMode(resetConfig.numQuestions, MASTERY_DRILL_QUESTION_COUNT_PRESETS));
    setQuestionTypeMode("primary");
    toast({
      title: "已恢复默认配置",
      description: "点击保存后生效。",
      variant: "info",
    });
  };

  const handleSave = () => {
    if (questionTypeMode !== "primary" && selectedTypeCount > config.numQuestions) {
      toast({ title: "题量不足", description: "题目数量不能少于所选题型数量。", variant: "error" });
      return;
    }
    if (!isTypeSelectionValid) {
      toast({
        title: isSelectedCustomQuestionTypeAvailable ? "请选择题型" : "题型当前不可用",
        description: isSelectedCustomQuestionTypeAvailable
          ? "至少保留一种题型用于闯关。"
          : "该自定义题型已停用、归档或不支持闯关，请重新选择。",
        variant: "error",
      });
      return;
    }
    const normalizedConfig = normalizeMasteryDrillConfig({
      ...config,
      questionTypes: questionTypeMode === "primary" ? [] : selectedTypeValues,
      customQuestionTypes: questionTypeMode === "primary" ? [] : config.customQuestionTypes,
    });
    saveMasteryDrillConfig(courseId, normalizedConfig);
    onSaved();
    toast({
      title: "闯关配置已保存",
      description: `下次开始将优先从题库选择 ${normalizedConfig.numQuestions} 题。`,
      variant: "success",
    });
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title="闯关出题配置" className="max-w-2xl rounded-[24px]">
      <div className="space-y-0">
        <TrainingConfigIntro
          description="优先复用题库，不足时自动生成并入库。"
        />
        <section className="divide-y divide-slate-100 dark:divide-slate-800">
          <TrainingConfigField label="题目数量" description="题库不足时自动补齐" align="center">
            <QuestionCountSelector
              value={config.numQuestions}
              mode={questionCountMode}
              presets={MASTERY_DRILL_QUESTION_COUNT_PRESETS}
              customAriaLabel="自定义闯关题目数量"
              onModeChange={setQuestionCountMode}
              onChange={(numQuestions) => setConfig((current) => ({ ...current, numQuestions }))}
            />
          </TrainingConfigField>
          <TrainingConfigField label="题型方式" description="智能选择 2～全部种题型">
            <OptionToggleGrid
              primaryLabel="智能搭配"
              secondaryLabel="指定题型"
              mode={questionTypeMode}
              options={typeOptions.map((option) => ({
                value: option.registryId ? `registry:${option.registryId}` : option.value,
                label: option.label,
                meta: option.registryId
                  ? (option.count > 0 ? `自定义 · 题库 ${option.count} 题` : "自定义 · 可生成")
                  : (option.count > 0 ? `题库 ${option.count} 题` : "可生成"),
              }))}
              selectedValues={selectedTypeSet}
              emptyMessage="暂无可用题型。"
              errorMessage={isTypeSelectionValid
                ? null
                : (isSelectedCustomQuestionTypeAvailable
                    ? "至少选择一种题型。"
                    : "所选自定义题型当前不可用，请重新选择。")}
              onModeChange={setQuestionTypeMode}
              onToggle={toggleQuestionType}
            />
            {questionTypeMode === "custom" && !isSelectedCustomQuestionTypeAvailable ? (
              <button
                type="button"
                className="mt-2 text-sm font-semibold text-indigo-600 underline underline-offset-4 dark:text-indigo-300"
                onClick={() => setConfig((current) => ({
                  ...current,
                  customQuestionTypes: filterAvailableCustomTypeSelections(
                    current.customQuestionTypes,
                    typeOptions.flatMap((item) => item.registryId ? [item.registryId] : []),
                  ),
                }))}
              >
                移除不可用题型
              </button>
            ) : null}
          </TrainingConfigField>
        </section>
        <TrainingConfigActions
          onReset={handleReset}
          onCancel={onClose}
          onSave={handleSave}
          saveDisabled={!isTypeSelectionValid}
        />
      </div>
    </Modal>
  );
}
