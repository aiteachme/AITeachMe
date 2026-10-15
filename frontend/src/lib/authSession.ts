import type { QueryClient } from "@tanstack/react-query";
import { abortActiveApiRequests, apiClient, notifyApiAuthChanged, setApiCsrfToken } from "../api/client.ts";
import type { AuthSessionData } from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export const AUTH_SESSION_QUERY_KEY = ["auth-session", "current-user"] as const;
export const AUTH_SESSION_STALE_TIME_MS = 30_000;

export function applyAuthSessionChange(queryClient: QueryClient, session: AuthSessionData | null): void {
  const previousSession = queryClient.getQueryData<AuthSessionData | null>(AUTH_SESSION_QUERY_KEY);
  const identityChanged = previousSession?.current_user?.user_id !== session?.current_user?.user_id;

  if (identityChanged) {
    abortActiveApiRequests();
    void queryClient.cancelQueries();
  } else {
    void queryClient.cancelQueries({ queryKey: AUTH_SESSION_QUERY_KEY, exact: true });
  }

  setApiCsrfToken(session?.csrf_token);
  queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, session);

  if (identityChanged) {
    // Reset immediately so failed refreshes cannot keep the previous user's data.
    // Browser UI preferences live outside the query cache and remain intact.
    void queryClient.resetQueries({
      predicate: (query) => !(
        query.queryKey.length === AUTH_SESSION_QUERY_KEY.length
        && query.queryKey.every((part, index) => part === AUTH_SESSION_QUERY_KEY[index])
      ),
    });
    // Do not wait for refetches before clearing local conversation/page state.
    notifyApiAuthChanged();
  }
}

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthSessionData | null> {
  const response = await apiClient<ApiResponse<AuthSessionData>>({
    url: "/api/v1/auth/user",
    method: "GET",
    signal,
  });
  setApiCsrfToken(response.data?.csrf_token);
  return response.data ?? null;
}
