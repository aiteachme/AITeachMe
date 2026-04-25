export const DIGEST_MODE_OPTIONS = [
  { value: "sprint", label: "速成课模式" },
  { value: "systematic", label: "系统课模式" },
] as const;

export function formatDigestModeLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  return DIGEST_MODE_OPTIONS.find((option) => option.value === normalized)?.label ?? "知识文档模式";
}
