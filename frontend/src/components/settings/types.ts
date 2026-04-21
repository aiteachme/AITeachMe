import type { LucideIcon } from "lucide-react";

export type SectionId =
  | "connection"
  | "models"
  | "learning"
  | "search"
  | "ops"
  | "observability";

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
  status: SettingStatus;
  secret?: boolean;
  editable?: boolean;
  restart_required?: boolean;
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

export interface SectionNavEntry {
  id: SectionId;
  label: string;
  description: string;
  icon: LucideIcon;
}

export type DraftRecord = Record<string, SettingPrimitive>;
