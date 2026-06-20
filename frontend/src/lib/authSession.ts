import { apiClient } from "../api/client";
import type { AuthSessionData } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export const AUTH_SESSION_QUERY_KEY = ["auth-session", "current-user"] as const;
export const AUTH_SESSION_STALE_TIME_MS = 30_000;

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthSessionData | null> {
  const response = await apiClient<ApiResponse<AuthSessionData>>({
    url: "/api/v1/auth/user",
    method: "POST",
    data: {},
    signal,
  });
  return response.data ?? null;
}
