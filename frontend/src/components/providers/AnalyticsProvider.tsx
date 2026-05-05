import type { PropsWithChildren } from "react";
import { PostHogProvider } from "@posthog/react";
import { getAnalyticsClient } from "../../lib/analytics";

export function AnalyticsProvider({ children }: PropsWithChildren) {
  const client = getAnalyticsClient();

  if (!client) {
    return <>{children}</>;
  }

  return <PostHogProvider client={client}>{children}</PostHogProvider>;
}
