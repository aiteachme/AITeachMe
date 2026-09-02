export function parseBackendDateTime(value: string) {
  const normalized = value.trim();
  const hasExplicitTimeZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  return new Date(hasExplicitTimeZone ? normalized : `${normalized}Z`);
}
