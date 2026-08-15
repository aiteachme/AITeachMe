import { useQuery } from "@tanstack/react-query";

import {
  AUTH_SESSION_QUERY_KEY,
  AUTH_SESSION_STALE_TIME_MS,
  fetchAuthSession,
} from "../lib/authSession";

export function useAuthSession() {
  return useQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: ({ signal }) => fetchAuthSession(signal),
    staleTime: AUTH_SESSION_STALE_TIME_MS,
    retry: 1,
  });
}
