import type { QuestionTypeCatalogItemResponse } from "../../api/generated/model/questionTypeCatalogItemResponse.ts";
import { isSupportedQuestionType } from "./questionTypes.ts";

type CatalogAvailability = Pick<QuestionTypeCatalogItemResponse,
  "type_key" | "scope" | "source" | "is_system" | "status" | "is_active" |
  "runtime_ready" | "runtime_message" | "current_version_id" | "modes"
>;

export type QuestionTypeStatusCategory = "available" | "inactive" | "pending" | "archived";

export function isCustomQuestionTypeReady(item: CatalogAvailability): boolean {
  return item.scope === "course" && item.source === "upload" &&
    item.runtime_ready === true && Boolean(item.current_version_id);
}

export function getQuestionTypeStatusCategory(item: CatalogAvailability): QuestionTypeStatusCategory {
  if (item.status === "archived") return "archived";
  if (item.is_system) return "available";
  const legacyBuiltinReady = item.runtime_ready === true && isSupportedQuestionType(item.type_key);
  if (!legacyBuiltinReady && !isCustomQuestionTypeReady(item)) return "pending";
  if (item.status !== "active" || !item.is_active) return "inactive";
  return "available";
}

export function isCustomQuestionTypeAvailable(item: CatalogAvailability): boolean {
  return isCustomQuestionTypeReady(item) && getQuestionTypeStatusCategory(item) === "available";
}

export function getQuestionTypeStatusLabel(item: CatalogAvailability): string {
  const labels: Record<QuestionTypeStatusCategory, string> = {
    available: "可用",
    inactive: "已停用",
    pending: "待接入",
    archived: "已归档",
  };
  return labels[getQuestionTypeStatusCategory(item)];
}

export function getQuestionTypeStatusDescription(item: CatalogAvailability): string {
  switch (getQuestionTypeStatusCategory(item)) {
    case "available":
      return "已启用，可在下方支持的场景中选择出题。";
    case "inactive":
      return "当前已停用，未进入出题配置。点击“启用题型”即可用于下方支持的场景。";
    case "archived":
      return "已归档，未进入出题配置。恢复到目录后可重新启用。";
    case "pending":
      return item.runtime_message || (item.current_version_id
        ? "当前版本暂不支持出题，请导入受支持的题型包版本。"
        : "尚未设置当前版本，请先选择可用的安装版本。");
  }
}

export function countQuestionTypesForMode(items: readonly CatalogAvailability[], mode: string): number {
  return items.filter((item) => item.is_system || (
    isCustomQuestionTypeAvailable(item) && (item.modes ?? []).includes(mode)
  )).length;
}
