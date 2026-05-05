import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { captureAnalyticsPageview } from "../../lib/analytics";

export function RouteAnalyticsBridge() {
  const location = useLocation();
  const lastRouteRef = useRef<string | null>(null);

  useEffect(() => {
    const routeKey = `${location.pathname}${location.search}${location.hash}`;
    if (lastRouteRef.current === routeKey) {
      return;
    }
    lastRouteRef.current = routeKey;
    captureAnalyticsPageview({
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    });
  }, [location.hash, location.pathname, location.search]);

  return null;
}
