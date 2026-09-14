/** Only temporary read failures may be retried or replaced by build progress. */
export function isTransientDocumentReadError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const value = error as {
    code?: string;
    response?: { status?: number; data?: { error_code?: string } };
  };
  if (value.response?.data?.error_code === "PUBLISHED_DOCUMENT_STRUCTURE_INVALID") return false;
  const status = value.response?.status;
  if (typeof status === "number") return [408, 429, 500, 502, 503, 504].includes(status);
  return ["ERR_NETWORK", "ECONNABORTED", "ETIMEDOUT", "BACKEND_OFFLINE"].includes(value.code ?? "");
}

export function retryDocumentRead(failureCount: number, error: unknown): boolean {
  return isTransientDocumentReadError(error) && failureCount < 2;
}

/** Five recovery rounds per continuous failure, then require a manual retry. */
export function documentReadRecoveryDelay(attempt: number): number | null {
  return attempt < 5 ? Math.min(2000 * 2 ** attempt, 30_000) : null;
}

export function blockingDocumentReadError(errors: unknown[], keepBuildProgress: boolean): unknown {
  const failures = errors.filter(Boolean);
  // A transient metadata failure must never hide a permanent publication error.
  const permanent = failures.find((error) => !isTransientDocumentReadError(error));
  return permanent ?? (keepBuildProgress ? null : failures[0] ?? null);
}
