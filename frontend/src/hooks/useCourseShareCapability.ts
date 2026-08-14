import { useQuery } from "@tanstack/react-query";

import {
  AUTH_SESSION_QUERY_KEY,
  AUTH_SESSION_STALE_TIME_MS,
  fetchAuthSession,
} from "../lib/authSession";
import { resolveCourseSharePublicBaseUrl } from "../lib/courseSharing";

export function useCanManageCourseShares(): boolean {
  const authSessionQuery = useQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: ({ signal }) => fetchAuthSession(signal),
    staleTime: AUTH_SESSION_STALE_TIME_MS,
    retry: 1,
  });

  return Boolean(
    resolveCourseSharePublicBaseUrl() &&
    authSessionQuery.data?.auth_enabled &&
    authSessionQuery.data.current_user?.is_authenticated,
  );
}
