// SectionId 保持为 string，便于通过配置文件直接新增/调整 tab，而不必同步修改类型枚举。
export type SectionId = string;

export type SettingSource =
  | "env"
  | "settings"
  | "system_settings"
  | "user_settings"
  | "runtime";

export type SettingStatus =
  | "configured"
  | "missing"
  | "default"
  | "disabled"
  | "enabled"
  | "runtime";

export type SettingPrimitive = string | number | boolean | null;

export interface SettingEntry {
  key: string;
  label: string;
  source: SettingSource;
  value?: unknown;
  default_value?: unknown;
  display_value?: string | null;
  reveal_value?: string | null;
  status: SettingStatus;
  secret?: boolean;
  secret_source?: string | null;
  editable?: boolean;
  restart_required?: boolean;
  ui_group?: string;
  ui_order?: number;
  description?: string;
}

export interface SettingSection {
  id: string;
  label: string;
  description: string;
  entries?: SettingEntry[];
}

export interface SettingsOverviewData {
  settings_source: string;
  mode: string;
  sections?: SettingSection[];
  notes?: string[];
}

export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

export type SaveState = "idle" | "saving" | "saved" | "error";

export type DraftRecord = Record<string, SettingPrimitive>;
