import type { QuestionTypeSelection } from "../../api/generated/model/questionTypeSelection.ts";
import { isSupportedQuestionType } from "./questionTypes.ts";

export type CustomTypeSelection = { registryId: number; typeKey: string };
export type LegacyCustomSelection = { customQuestionTypeRegistryId?: number | null; customQuestionTypeKey?: string };

export function normalizeCustomTypeSelections(value: LegacyCustomSelection & { customQuestionTypes?: CustomTypeSelection[] }): CustomTypeSelection[] {
  const source = value.customQuestionTypes ?? (value.customQuestionTypeRegistryId
    ? [{ registryId: value.customQuestionTypeRegistryId, typeKey: value.customQuestionTypeKey ?? "" }]
    : []);
  const seen = new Set<number>();
  return source.flatMap((item) => {
    const registryId = Number(item?.registryId);
    const typeKey = String(item?.typeKey ?? "").trim().toLowerCase();
    if (!Number.isInteger(registryId) || registryId < 1 || !typeKey || seen.has(registryId)) return [];
    seen.add(registryId);
    return [{ registryId, typeKey }];
  });
}

export function buildQuestionTypeSelections(builtins: readonly string[], customs: readonly CustomTypeSelection[]): QuestionTypeSelection[] {
  return [
    ...builtins.filter(isSupportedQuestionType).map((question_type) => ({ question_type: question_type as QuestionTypeSelection["question_type"] })),
    ...customs.map(({ registryId }) => ({ registry_id: registryId })),
  ];
}

export function toggleCustomTypeSelection(selected: readonly CustomTypeSelection[], next: CustomTypeSelection) {
  return selected.some((item) => item.registryId === next.registryId)
    ? selected.filter((item) => item.registryId !== next.registryId)
    : [...selected, next];
}

export function filterAvailableCustomTypeSelections(
  selected: readonly CustomTypeSelection[],
  availableRegistryIds: readonly number[],
): CustomTypeSelection[] {
  const available = new Set(availableRegistryIds);
  return selected.filter((item) => available.has(item.registryId));
}
