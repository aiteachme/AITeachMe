import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { captureAnalyticsPageview, startAnalyticsRouteDuration } from "../../lib/analytics";

type RouteAnalyticsBridgeProps = {
  analyticsIdentityReady: boolean;
};

export function RouteAnalyticsBridge({ analyticsIdentityReady }: RouteAnalyticsBridgeProps) {
  const location = useLocation();
  const lastRouteRef = useRef<string | null>(null);

  useEffect(() => {
    if (!analyticsIdentityReady) {
      return;
    }
    const routeKey = `${location.pathname}${location.search}${location.hash}`;
    if (lastRouteRef.current === routeKey) {
      return;
    }
    lastRouteRef.current = routeKey;
    const route = {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    };
    captureAnalyticsPageview(route);
    startAnalyticsRouteDuration(route);
  }, [analyticsIdentityReady, location.hash, location.pathname, location.search]);

  return null;
}
