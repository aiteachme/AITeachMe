import posthog from "posthog-js";
import type { CaptureResult, PostHog, PostHogConfig, Properties } from "posthog-js";
import { getDeviceKey } from "../api/client";
import { isElectronRuntime } from "./electronRuntime";

type RuntimeUserIdentity = {
  userId?: string | null;
  email?: string | null;
  isAuthenticated?: boolean | null;
};

type RouteSnapshot = {
  pathname: string;
  search?: string;
  hash?: string;
};

const DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com";
const SENSITIVE_PROPERTY_RE =
  /(^|[_\-$])(api[_-]?key|authorization|content|device[_-]?key|email|file(name)?|markdown|message|password|prompt|secret|text|token)([_\-$]|$)/i;
const URL_PROPERTY_RE = /(^|[_\-$])(current[_-]?url|href|pathname|referrer|url)([_\-$]|$)/i;
const MAX_PROPERTY_DEPTH = 4;
const POSTHOG_TRANSPORT_PROPERTY_KEYS = ["api_key", "token"] as const;
const BACKEND_OWNED_EVENTS = new Set([
  "auth_login_succeeded",
  "auth_logout_succeeded",
  "auth_register_succeeded",
  "course_created",
  "course_plan_requested",
  "course_plan_generated",
  "course_build_plan_confirmed",
  "exam_generation_requested",
  "exam_generated",
  "exam_graded",
  "exam_submitted",
  "knowledge_build_submitted",
  "knowledge_build_started",
  "knowledge_build_completed",
  "knowledge_build_failed",
  "knowledge_build_cancelled",
  "question_template_answer_graded",
]);

let initialized = false;
let enabled = false;
let identifiedUserId: string | null = null;
let currentIsAuthenticated = false;
let lastPageviewKey: string | null = null;
let lastPageviewAt = 0;
const capturedOnceKeys = new Set<string>();
let routeDurationListenersInstalled = false;
let lastRouteSnapshot: RouteSnapshot | null = null;
let activeRoute:
  | {
      durationMs: number;
      routePath: string;
      visibleStartedAt: number | null;
    }
  | null = null;

function envFlag(value: string | boolean | undefined, fallback = false): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value !== "string") {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return fallback;
  }
  return ["1", "true", "yes", "on"].includes(normalized);
}

function getRuntimeEnvValue(key: keyof ImportMetaEnv): string | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const value = window.__AITEACHME_RUNTIME_CONFIG__?.[key as string];
  return typeof value === "string" ? value.trim() : undefined;
}

function getEnvValue(key: keyof ImportMetaEnv): string {
  const runtimeValue = getRuntimeEnvValue(key);
  if (runtimeValue !== undefined) {
    return runtimeValue;
  }
  const value = import.meta.env[key];
  return typeof value === "string" ? value.trim() : "";
}

function getEnvFlag(key: keyof ImportMetaEnv, fallback = false): boolean {
  const runtimeValue = getRuntimeEnvValue(key);
  return envFlag(runtimeValue ?? import.meta.env[key], fallback);
}

function resolveRuntimeSurface(): "electron" | "tauri" | "web" {
  if (isElectronRuntime()) {
    return "electron";
  }
  if (typeof window !== "undefined" && window.location.hostname === "tauri.localhost") {
    return "tauri";
  }
  return "web";
}

function getDeviceKeySuffix(): string | undefined {
  try {
    const key = getDeviceKey();
    return key ? key.slice(-8) : undefined;
  } catch {
    return undefined;
  }
}

function getEmailDomain(email?: string | null): string | undefined {
  const value = email?.trim().toLowerCase() ?? "";
  if (!value.includes("@")) {
    return undefined;
  }
  return value.split("@").pop() ?? undefined;
}

function normalizeRoutePath(pathname: string): string {
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  return path
    .replace(/\/courses\/[^/]+/i, "/courses/:courseId")
    .replace(/\/course\/[^/]+/i, "/course/:courseId")
    .replace(/\/exams\/question-templates\/[^/]+\/answer-history/i, "/exams/question-templates/:templateId/answer-history")
    .replace(/\/exams\/[^/]+$/i, "/exams/:examPaperId");
}

function buildSafeRouteUrl(routePath: string): string {
  if (typeof window === "undefined") {
    return routePath;
  }
  if (window.location.protocol === "file:") {
    return `desktop://aiteachme${routePath}`;
  }
  const origin = window.location.origin || "app://aiteachme";
  return `${origin}${routePath}`;
}

function sanitizeUrl(value: string): string {
  if (!value) {
    return value;
  }

  try {
    const parsed = new URL(value, typeof window !== "undefined" ? window.location.origin : "https://aiteachme.local");
    const routePath = normalizeRoutePath(parsed.pathname);
    return parsed.origin === "null" ? routePath : `${parsed.origin}${routePath}`;
  } catch {
    return value.split(/[?#]/, 1)[0] ?? value;
  }
}

function sanitizeValue(key: string, value: unknown, depth = 0): unknown {
  if (SENSITIVE_PROPERTY_RE.test(key)) {
    return undefined;
  }
  if (typeof value === "string") {
    return URL_PROPERTY_RE.test(key) ? sanitizeUrl(value) : value;
  }
  if (value == null || typeof value !== "object" || depth >= MAX_PROPERTY_DEPTH) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((item) => sanitizeValue(key, item, depth + 1));
  }

  const sanitized: Record<string, unknown> = {};
  for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
    const nextValue = sanitizeValue(childKey, childValue, depth + 1);
    if (nextValue !== undefined) {
      sanitized[childKey] = nextValue;
    }
  }
  return sanitized;
}

function sanitizeProperties(properties: Properties): Properties {
  const sanitized = sanitizeValue("properties", properties);
  return sanitized && typeof sanitized === "object" && !Array.isArray(sanitized)
    ? (sanitized as Properties)
    : {};
}

function sanitizeCaptureProperties(properties: Properties): Properties {
  const sanitized = sanitizeProperties(properties);

  // PostHog's browser SDK carries the public project key in event properties.
  // Preserve those transport fields after sanitizing our own application data,
  // otherwise the ingestion API rejects events as missing an api_key.
  for (const key of POSTHOG_TRANSPORT_PROPERTY_KEYS) {
    if (typeof properties[key] === "string") {
      sanitized[key] = properties[key];
    }
  }

  return sanitized;
}

function beforeSend(capture: CaptureResult | null): CaptureResult | null {
  if (!capture) {
    return capture;
  }
  if (BACKEND_OWNED_EVENTS.has(capture.event)) {
    return null;
  }
  return {
    ...capture,
    properties: sanitizeCaptureProperties(capture.properties ?? {}),
    $set: capture.$set ? sanitizeProperties(capture.$set) : capture.$set,
    $set_once: capture.$set_once ? sanitizeProperties(capture.$set_once) : capture.$set_once,
  };
}

export function isAnalyticsEnabled(): boolean {
  return enabled;
}

export function initializeAnalytics(): PostHog | null {
  if (initialized) {
    return enabled ? posthog : null;
  }

  initialized = true;

  if (typeof window === "undefined") {
    return null;
  }

  const token = getEnvValue("VITE_POSTHOG_TOKEN");
  enabled = getEnvFlag("VITE_POSTHOG_ENABLED", false) && Boolean(token);
  if (!enabled) {
    return null;
  }

  const apiHost = getEnvValue("VITE_POSTHOG_HOST") || DEFAULT_POSTHOG_HOST;
  const sessionReplayEnabled = getEnvFlag("VITE_POSTHOG_SESSION_REPLAY", false);
  const debug = getEnvFlag("VITE_POSTHOG_DEBUG", false);

  const config: Partial<PostHogConfig> = {
    api_host: apiHost,
    autocapture: {
      dom_event_allowlist: ["click", "submit"],
      element_allowlist: ["a", "button", "form", "label"],
      element_attribute_ignorelist: ["aria-label", "title", "value"],
    },
    before_send: beforeSend,
    capture_pageleave: false,
    capture_pageview: false,
    debug,
    disable_session_recording: !sessionReplayEnabled,
    enable_recording_console_log: false,
    mask_all_element_attributes: false,
    mask_all_text: true,
    mask_personal_data_properties: true,
    person_profiles: "identified_only",
    property_denylist: [
      "$el_text",
      "$element_text",
      "authorization",
      "content",
      "email",
      "filename",
      "markdown",
      "message",
      "password",
      "prompt",
      "secret",
      "text",
    ],
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "*",
      blockSelector: ".ph-no-capture,[data-ph-no-capture]",
    },
  };

  posthog.init(token, config);
  posthog.register({
    app_surface: resolveRuntimeSurface(),
    app_version: getEnvValue("VITE_APP_VERSION") || undefined,
    device_key_suffix: getDeviceKeySuffix(),
  });

  return posthog;
}

export function getAnalyticsClient(): PostHog | null {
  return initializeAnalytics();
}

export function trackAnalyticsEvent(eventName: string, properties: Properties = {}): void {
  if (BACKEND_OWNED_EVENTS.has(eventName)) {
    return;
  }
  const client = getAnalyticsClient();
  if (!client) {
    return;
  }
  client.capture(eventName, sanitizeProperties(properties));
}

export function trackAnalyticsEventOnce(
  eventName: string,
  uniqueKey: string,
  properties: Properties = {},
): void {
  const dedupeKey = `${eventName}:${uniqueKey}`;
  if (capturedOnceKeys.has(dedupeKey)) {
    return;
  }
  capturedOnceKeys.add(dedupeKey);
  trackAnalyticsEvent(eventName, properties);
}

function buildCourseAnalyticsProperties(courseId: string): Properties {
  const normalized = courseId.trim();
  return {
    course_id_present: Boolean(normalized),
    course_id_suffix: normalized ? normalized.slice(-8) : undefined,
  };
}

export function trackCourseAnalyticsEvent(
  eventName: string,
  courseId: string,
  properties: Properties = {},
): void {
  trackAnalyticsEvent(eventName, {
    ...buildCourseAnalyticsProperties(courseId),
    ...properties,
  });
}

export function trackCourseAnalyticsEventOnce(
  eventName: string,
  courseId: string,
  uniqueKey: string,
  properties: Properties = {},
): void {
  trackAnalyticsEventOnce(eventName, `${courseId.trim()}:${uniqueKey}`, {
    ...buildCourseAnalyticsProperties(courseId),
    ...properties,
  });
}

function isRouteDurationTrackingSupported(): boolean {
  return typeof window !== "undefined" && typeof document !== "undefined" && resolveRuntimeSurface() === "web";
}

function isDocumentVisible(): boolean {
  return typeof document === "undefined" ? false : document.visibilityState !== "hidden";
}

function pauseActiveRouteDuration(now = Date.now()): void {
  if (!activeRoute?.visibleStartedAt) {
    return;
  }
  activeRoute.durationMs += Math.max(0, now - activeRoute.visibleStartedAt);
  activeRoute.visibleStartedAt = null;
}

function resumeActiveRouteDuration(now = Date.now()): void {
  if (!activeRoute || activeRoute.visibleStartedAt) {
    return;
  }
  activeRoute.visibleStartedAt = now;
}

function flushActiveRouteDuration(reason: string, now = Date.now()): void {
  if (!activeRoute) {
    return;
  }
  pauseActiveRouteDuration(now);
  const route = activeRoute;
  activeRoute = null;
  const durationMs = Math.round(route.durationMs);
  if (durationMs <= 0) {
    return;
  }

  const client = getAnalyticsClient();
  if (!client) {
    return;
  }
  const shouldUseBeacon = reason === "pagehide" || reason === "visibility_hidden";
  const captureOptions = shouldUseBeacon ? { send_instantly: true, transport: "sendBeacon" as const } : undefined;
  client.capture(
    "route_active_duration",
    sanitizeProperties({
      app_surface: "web",
      duration_ms: durationMs,
      is_authenticated: currentIsAuthenticated,
      reason,
      route_path: route.routePath,
    }),
    captureOptions,
  );
}

function ensureRouteDurationListeners(): void {
  if (routeDurationListenersInstalled || !isRouteDurationTrackingSupported()) {
    return;
  }
  routeDurationListenersInstalled = true;
  document.addEventListener("visibilitychange", () => {
    if (isDocumentVisible()) {
      if (activeRoute) {
        resumeActiveRouteDuration();
        return;
      }
      if (lastRouteSnapshot) {
        startAnalyticsRouteDuration(lastRouteSnapshot);
      }
      return;
    }
    flushActiveRouteDuration("visibility_hidden");
  });
  window.addEventListener("pagehide", () => flushActiveRouteDuration("pagehide"), { capture: true });
}

export function startAnalyticsRouteDuration(route: RouteSnapshot): void {
  if (!isRouteDurationTrackingSupported()) {
    return;
  }
  ensureRouteDurationListeners();
  lastRouteSnapshot = {
    pathname: route.pathname,
    search: route.search,
    hash: route.hash,
  };
  const routePath = normalizeRoutePath(route.pathname);
  if (activeRoute?.routePath === routePath) {
    return;
  }
  flushActiveRouteDuration("route_change");
  activeRoute = {
    durationMs: 0,
    routePath,
    visibleStartedAt: isDocumentVisible() ? Date.now() : null,
  };
}

export function captureAnalyticsPageview(route: RouteSnapshot): void {
  const client = getAnalyticsClient();
  if (!client) {
    return;
  }

  const routePath = normalizeRoutePath(route.pathname);
  const pageviewKey = `${routePath}|${Boolean(route.search)}|${Boolean(route.hash)}`;
  const now = Date.now();
  if (lastPageviewKey === pageviewKey && now - lastPageviewAt < 750) {
    return;
  }
  lastPageviewKey = pageviewKey;
  lastPageviewAt = now;

  client.capture("$pageview", {
    $current_url: buildSafeRouteUrl(routePath),
    $pathname: routePath,
    app_surface: resolveRuntimeSurface(),
    is_authenticated: currentIsAuthenticated,
    route_hash_present: Boolean(route.hash),
    route_path: routePath,
    route_search_present: Boolean(route.search),
  });
}

export function syncAnalyticsUserIdentity(user: RuntimeUserIdentity | null): void {
  const client = getAnalyticsClient();
  if (!client) {
    return;
  }

  if (!user?.userId) {
    currentIsAuthenticated = false;
    client.unregister("app_user_id");
    client.register({ is_authenticated: false });
    return;
  }

  currentIsAuthenticated = Boolean(user.isAuthenticated);
  const superProperties = {
    app_user_id: user.userId,
    account_domain: getEmailDomain(user.email),
    is_authenticated: currentIsAuthenticated,
  };
  client.register(superProperties);

  if (identifiedUserId !== user.userId) {
    identifiedUserId = user.userId;
    client.identify(user.userId, {
      account_domain: getEmailDomain(user.email),
      is_authenticated: currentIsAuthenticated,
    });
  }
}

export function resetAnalyticsIdentity(): void {
  const client = getAnalyticsClient();
  if (!client) {
    return;
  }
  identifiedUserId = null;
  currentIsAuthenticated = false;
  client.reset();
  client.register({
    app_surface: resolveRuntimeSurface(),
    app_version: getEnvValue("VITE_APP_VERSION") || undefined,
    device_key_suffix: getDeviceKeySuffix(),
    is_authenticated: false,
  });
}
