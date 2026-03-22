function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function unwrapOrvalResponse<T = any>(response: unknown): T | null {
  if (!isRecord(response) || !("data" in response)) {
    return null;
  }

  const payload = response.data;
  if (isRecord(payload) && "data" in payload) {
    return (payload.data as T | null | undefined) ?? null;
  }

  return (payload as T | null | undefined) ?? null;
}
