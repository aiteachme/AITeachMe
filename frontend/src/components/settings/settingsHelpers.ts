import type {
  DraftRecord,
  SettingEntry,
  SettingPrimitive,
  SettingSection,
  SettingSource,
} from "./settingsTypes";

export const SECRET_PRESERVE_VALUE = "__AITM_SECRET_PRESERVE__";

export function isCredentialKey(key: string): boolean {
  const normalizedKey = key.toLowerCase();
  return (
    normalizedKey.includes("key") ||
    normalizedKey.includes("token") ||
    normalizedKey.includes("secret") ||
    normalizedKey.includes("password")
  );
}

export function isPrimitive(value: unknown): value is SettingPrimitive {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

export function displayValue(entry: SettingEntry): string {
  if (entry.secret || /key|token|secret|password|database\.url/i.test(entry.key)) {
    return entry.status === "configured" ? "已配置" : "未配置";
  }
  if (entry.display_value !== undefined && entry.display_value !== null) {
    return entry.display_value;
  }
  if (entry.value === null || entry.value === undefined || entry.value === "") {
    return "未配置";
  }
  if (typeof entry.value === "boolean") {
    return entry.value ? "开启" : "关闭";
  }
  return String(entry.value);
}

export function editableEntries(
  sections: SettingSection[],
  source?: SettingSource,
): SettingEntry[] {
  return sections
    .flatMap((section) => section.entries ?? [])
    .filter(
      (entry) =>
        entry.editable && isPrimitive(entry.value) && (!source || entry.source === source),
    );
}

export function draftFromEntries(
  entries: SettingEntry[],
  source: "value" | "default_value" = "value",
): DraftRecord {
  return Object.fromEntries(
    entries.map((entry) => {
      if (source === "value" && entry.secret && entry.status === "configured") {
        return [entry.key, SECRET_PRESERVE_VALUE];
      }
      return [entry.key, isPrimitive(entry[source]) ? entry[source] : null];
    }),
  ) as DraftRecord;
}

export function sameDraft(a: DraftRecord, b: DraftRecord): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function buildSettingsPayload(
  draft: DraftRecord,
  entries: SettingEntry[],
): Record<string, unknown> {
  const allowed = new Set(entries.map((entry) => entry.key));
  const root: Record<string, unknown> = {};

  Object.entries(draft).forEach(([key, value]) => {
    if (!allowed.has(key)) {
      return;
    }

    const parts = key.split(".");
    let cursor = root;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        cursor[part] = value;
        return;
      }
      if (
        typeof cursor[part] !== "object" ||
        cursor[part] === null ||
        Array.isArray(cursor[part])
      ) {
        cursor[part] = {};
      }
      cursor = cursor[part] as Record<string, unknown>;
    });
  });

  return root;
}

export function buildChangedSettingsPayload(
  draft: DraftRecord,
  defaults: DraftRecord,
  entries: SettingEntry[],
): Record<string, unknown> {
  const changedDraft = Object.fromEntries(
    Object.entries(draft).filter(([key, value]) => value !== defaults[key]),
  ) as DraftRecord;
  return buildSettingsPayload(changedDraft, entries);
}

export function buildChangedFlatPayload(
  draft: DraftRecord,
  saved: DraftRecord,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(draft)
      .filter(([key, value]) => value !== saved[key])
      .map(([key, value]) => [key, value === null ? "" : String(value)]),
  );
}

export function parseInputValue(
  raw: string,
  currentValue: SettingPrimitive,
): SettingPrimitive {
  if (typeof currentValue === "number") {
    const nextValue = Number(raw);
    return Number.isFinite(nextValue) ? nextValue : currentValue;
  }
  if (currentValue === null) {
    const normalized = raw.trim().toLowerCase();
    if (!normalized || normalized === "null") return null;
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return raw;
}

export function resolveEntryInputType(entry: SettingEntry, value: SettingPrimitive): string {
  if (entry.secret || isCredentialKey(entry.key)) {
    return "password";
  }
  if (typeof value === "number") {
    return "number";
  }
  return "text";
}
