import axios, { AxiosHeaders } from "axios";
import type { AxiosRequestConfig, AxiosResponse } from "axios";

import { parseSseEventBlock } from "./sseParser.ts";

const DEFAULT_ELECTRON_LOCAL_API_BASE_URL = "http://127.0.0.1:19020";

function shouldUseMockApi(): boolean {
  return typeof window !== "undefined" && window.location.search.includes("mock=1");
}

function resolveDesktopApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return "";
  }

  if (shouldUseMockApi()) {
    return "";
  }

  const runtimeBase = (window.aiteachmeDesktop?.apiBaseUrl ?? "").trim();
  if (runtimeBase) {
    return runtimeBase;
  }

  const buildTimeBase = (import.meta.env?.VITE_API_URL ?? "").trim();
  if (window.location.protocol === "file:") {
    return buildTimeBase || DEFAULT_ELECTRON_LOCAL_API_BASE_URL;
  }
  if (!buildTimeBase && window.location.hostname === "tauri.localhost") {
    return "";
  }

  return "";
}

const API_BASE_URL = shouldUseMockApi()
  ? ""
  : resolveDesktopApiBaseUrl() || (import.meta.env?.VITE_API_URL ?? "").trim();
const DEVICE_KEY_STORAGE_KEY = "device_key";
const DEVICE_KEY_RE = /^[A-Za-z0-9._:-]{8,128}$/;
export const DEFAULT_API_TIMEOUT_MS = 60_000;
export const LONG_RUNNING_API_TIMEOUT_MS = 300_000;
const BACKEND_HEALTH_CHECK_TIMEOUT_MS = 1_200;
const BACKEND_RECOVERY_POLL_INTERVAL_MS = 1_500;
const BACKEND_RECOVERY_POLL_MAX_INTERVAL_MS = 10_000;
export const BACKEND_OFFLINE_EVENT = "aiteachme:backend-offline";
export const BACKEND_ONLINE_EVENT = "aiteachme:backend-online";
export const API_AUTH_CHANGED_EVENT = "aiteachme:api-auth-changed";

const instance = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_API_TIMEOUT_MS,
  withCredentials: true,
});

export interface ApiErrorPayload {
  code?: number | string;
  error_code?: string;
  message?: string;
  detail?: string;
  data?: unknown;
}

type ApiErrorShape = {
  code?: string;
  message?: string;
  response?: {
    status?: number;
    data?: ApiErrorPayload;
  };
};

type ApiRequestMetadata = {
  startTime: number;
  cleanupAbortSignal?: () => void;
};

type ApiRequestConfigWithMetadata = AxiosRequestConfig & {
  metadata?: ApiRequestMetadata;
};

type AbortSignalLike = {
  aborted: boolean;
  addEventListener?: AbortSignal["addEventListener"];
  removeEventListener?: AbortSignal["removeEventListener"];
};

const activeRequestControllers = new Set<AbortController>();
const activeSseSubscriptions = new Set<{ close: () => void }>();
let apiAuthGeneration = 0;
let backendOffline = false;
let recoveryProbeTimer: number | null = null;
let recoveryProbeAttempt = 0;
let connectionIssueProbe: Promise<boolean> | null = null;
let csrfToken: string | null = null;

// Cookie sessions replaced bearer tokens. Remove the legacy credential once so
// it cannot be recovered later by old application code or browser extensions.
try {
  window.localStorage.removeItem("token");
} catch {
  // Storage may be unavailable in SSR, privacy mode, or a restricted webview.
}

export function setApiCsrfToken(value: string | null | undefined): void {
  csrfToken = value?.trim() || null;
}

function generateDeviceKey(): string {
  let randomPart: string;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    randomPart = crypto.randomUUID();
  } else if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    randomPart = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  } else {
    randomPart = `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  }
  return `dk_${randomPart}`;
}

const IN_MEMORY_DEVICE_KEY = generateDeviceKey();

export function getDeviceKey(): string {
  try {
    const existing = localStorage.getItem(DEVICE_KEY_STORAGE_KEY);
    if (existing && DEVICE_KEY_RE.test(existing)) {
      return existing;
    }
    const generated = generateDeviceKey();
    localStorage.setItem(DEVICE_KEY_STORAGE_KEY, generated);
    return generated;
  } catch {
    return IN_MEMORY_DEVICE_KEY;
  }
}

function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function buildApiUrl(url: string): string {
  const base = getApiBaseUrl();
  if (/^https?:\/\//i.test(url) || !base) {
    return url;
  }
  const cleanBase = base.replace(/\/$/, "");
  const path = url.startsWith("/") ? url : `/${url}`;
  return `${cleanBase}${path}`;
}

function createBackendOfflineError(): Error & { code: string } {
  const error = new Error("后端服务已断开，正在尝试重连。") as Error & { code: string };
  error.name = "BackendOfflineError";
  error.code = "BACKEND_OFFLINE";
  return error;
}

export function isBackendOfflineError(error: unknown): boolean {
  const apiError = error as ApiErrorShape & { name?: string };
  return apiError?.code === "BACKEND_OFFLINE" || apiError?.name === "BackendOfflineError";
}

function dispatchBackendConnectionEvent(eventName: string, detail?: Record<string, unknown>) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(eventName, { detail }));
}

function createTrackedAbortSignal(externalSignal?: AbortSignalLike | null): {
  signal: AbortSignal;
  cleanup: () => void;
} {
  const controller = new AbortController();
  activeRequestControllers.add(controller);

  const abortFromExternal = () => {
    if (!controller.signal.aborted) {
      controller.abort();
    }
  };

  if (externalSignal?.aborted) {
    abortFromExternal();
  } else if (externalSignal?.addEventListener) {
    externalSignal.addEventListener("abort", abortFromExternal, { once: true });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      if (externalSignal?.removeEventListener) {
        externalSignal.removeEventListener("abort", abortFromExternal);
      }
      activeRequestControllers.delete(controller);
    },
  };
}

function createApiFetchHeaders(headers?: HeadersInit, requestMethod = "GET"): Headers {
  const nextHeaders = new Headers(headers);
  nextHeaders.set("X-Device-Key", getDeviceKey());

  nextHeaders.delete("Authorization");
  const method = requestMethod.toUpperCase();
  if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    nextHeaders.set("X-CSRF-Token", csrfToken);
  }

  return nextHeaders;
}

function closeActiveSseSubscriptions(): void {
  for (const subscription of Array.from(activeSseSubscriptions)) {
    subscription.close();
  }
}

export function abortActiveApiRequests(): void {
  closeActiveSseSubscriptions();
  abortTrackedApiRequests();
}

export function getApiAuthGeneration(): number {
  return apiAuthGeneration;
}

/** Rotate mounted SSE subscriptions after the authentication identity changes. */
export function notifyApiAuthChanged(): void {
  closeActiveSseSubscriptions();
  apiAuthGeneration += 1;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(API_AUTH_CHANGED_EVENT));
  }
}

function abortTrackedApiRequests(): void {
  for (const controller of Array.from(activeRequestControllers)) {
    if (!controller.signal.aborted) {
      controller.abort();
    }
  }
}

async function checkBackendHealthOnce(): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), BACKEND_HEALTH_CHECK_TIMEOUT_MS);
  try {
    const response = await fetch(buildApiUrl("/api/health"), {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function stopBackendRecoveryProbe() {
  if (typeof window === "undefined" || recoveryProbeTimer === null) {
    return;
  }
  window.clearTimeout(recoveryProbeTimer);
  recoveryProbeTimer = null;
  recoveryProbeAttempt = 0;
}

function startBackendRecoveryProbe() {
  if (typeof window === "undefined" || recoveryProbeTimer !== null) {
    return;
  }

  const schedule = () => {
    const delay = Math.min(
      BACKEND_RECOVERY_POLL_MAX_INTERVAL_MS,
      BACKEND_RECOVERY_POLL_INTERVAL_MS * 2 ** Math.min(recoveryProbeAttempt, 3),
    );
    recoveryProbeTimer = window.setTimeout(async () => {
      recoveryProbeTimer = null;
      if (await checkBackendHealthOnce()) {
        recoveryProbeAttempt = 0;
        markBackendOnline();
        return;
      }
      recoveryProbeAttempt += 1;
      if (backendOffline) {
        schedule();
      }
    }, delay);
  };

  schedule();
}

export function markBackendOnline(): void {
  if (!backendOffline) {
    return;
  }
  backendOffline = false;
  recoveryProbeAttempt = 0;
  stopBackendRecoveryProbe();
  dispatchBackendConnectionEvent(BACKEND_ONLINE_EVENT);
}

export function markBackendOffline(reason = "network_error"): void {
  if (backendOffline) {
    abortTrackedApiRequests();
    return;
  }

  backendOffline = true;
  recoveryProbeAttempt = 0;
  abortTrackedApiRequests();
  startBackendRecoveryProbe();
  dispatchBackendConnectionEvent(BACKEND_OFFLINE_EVENT, { reason });
}

export function isBackendOffline(): boolean {
  return backendOffline;
}

export function reportBackendConnectionIssue(reason = "stream_error"): Promise<boolean> {
  if (backendOffline) {
    return Promise.resolve(false);
  }
  if (connectionIssueProbe) {
    return connectionIssueProbe;
  }
  const probe = checkBackendHealthOnce()
    .then((isHealthy) => {
      if (isHealthy) {
        markBackendOnline();
        return true;
      }
      markBackendOffline(reason);
      return false;
    })
    .finally(() => {
      connectionIssueProbe = null;
    });
  connectionIssueProbe = probe;
  return probe;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function sanitizeErrorText(value: string, fallback = "请求失败，请重试。"): string {
  const text = value.trim();
  if (!text) {
    return fallback;
  }
  const lowered = text.toLowerCase();
  if (
    lowered.includes("<!doctype html") ||
    lowered.includes("<html") ||
    lowered.includes("<head") ||
    lowered.includes("<body") ||
    lowered.includes("text/html")
  ) {
    return "服务返回了网页内容而不是接口响应，请检查网关地址或反向代理配置。";
  }
  return text.length > 800 ? `${text.slice(0, 800).trim()}...` : text;
}

function isBackendDisconnectError(error: unknown): boolean {
  const apiError = error as ApiErrorShape & { response?: unknown; name?: string };
  if (apiError.response || apiError.code === "ERR_CANCELED" || apiError.name === "AbortError") {
    return false;
  }
  if (apiError.code === "ERR_NETWORK") {
    return true;
  }
  if (typeof apiError.message === "string") {
    return /network error|failed to fetch|load failed/i.test(apiError.message);
  }
  return error instanceof TypeError;
}

export async function runTrackedApiFetch<T>(
  url: string,
  init: RequestInit,
  consume: (response: Response) => Promise<T>,
  disconnectReason = "fetch_disconnect",
  markOfflineOnDisconnect = true,
): Promise<T> {
  if (backendOffline) {
    throw createBackendOfflineError();
  }

  const trackedSignal = createTrackedAbortSignal(init.signal ?? null);
  try {
    const response = await fetch(buildApiUrl(url), {
      ...init,
      credentials: init.credentials ?? "include",
      headers: createApiFetchHeaders(init.headers, init.method),
      signal: trackedSignal.signal,
    });
    return await consume(response);
  } catch (error) {
    if (isBackendDisconnectError(error)) {
      if (markOfflineOnDisconnect) {
        markBackendOffline(disconnectReason);
      }
    }
    throw error;
  } finally {
    trackedSignal.cleanup();
  }
}

export async function runAnonymousApiFetch<T>(
  url: string,
  init: RequestInit,
  consume: (response: Response) => Promise<T>,
  disconnectReason = "anonymous_fetch_disconnect",
): Promise<T> {
  if (backendOffline) {
    throw createBackendOfflineError();
  }

  const headers = new Headers(init.headers);
  headers.delete("Authorization");
  headers.delete("Cookie");
  headers.delete("X-Device-Key");
  const trackedSignal = createTrackedAbortSignal(init.signal ?? null);
  try {
    const response = await fetch(buildApiUrl(url), {
      ...init,
      credentials: "omit",
      headers,
      referrerPolicy: "no-referrer",
      signal: trackedSignal.signal,
    });
    return await consume(response);
  } catch (error) {
    if (isBackendDisconnectError(error)) {
      markBackendOffline(disconnectReason);
    }
    throw error;
  } finally {
    trackedSignal.cleanup();
  }
}

function extractErrorMessage(payload: unknown, fallback = "请求失败，请重试。"): string {
  if (typeof payload === "string" && payload.trim()) {
    return sanitizeErrorText(payload, fallback);
  }
  if (isRecord(payload)) {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) {
      return sanitizeErrorText(detail, fallback);
    }
    const message = payload.message;
    if (typeof message === "string" && message.trim()) {
      return sanitizeErrorText(message, fallback);
    }
    if (isRecord(payload.error)) {
      const nestedDetail = payload.error.detail;
      if (typeof nestedDetail === "string" && nestedDetail.trim()) {
        return sanitizeErrorText(nestedDetail, fallback);
      }
    }
  }
  return fallback;
}

async function parseErrorResponse(response: Response): Promise<string> {
  const rawText = await response.text();
  if (!rawText.trim()) {
    return `请求失败（${response.status}）`;
  }

  try {
    return extractErrorMessage(JSON.parse(rawText), `请求失败（${response.status}）`);
  } catch {
    return extractErrorMessage(rawText, `请求失败（${response.status}）`);
  }
}

export async function anonymousApiClient<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  return runAnonymousApiFetch(
    url,
    {
      ...init,
      headers,
    },
    async (response) => {
      if (!response.ok) {
        throw new Error(await parseErrorResponse(response));
      }
      return response.json() as Promise<T>;
    },
    "anonymous_api_disconnect",
  );
}

const SSE_CONNECTING = 0;
const SSE_OPEN = 1;
const SSE_CLOSED = 2;
const DEFAULT_SSE_MAX_RECONNECT_ATTEMPTS = 6;
const DEFAULT_SSE_RECONNECT_DELAY_MS = 750;
const MAX_SSE_RECONNECT_DELAY_MS = 10_000;

type SseConnectionError = Error & { status?: number; retryable?: boolean };

export interface AuthenticatedSseOptions {
  disconnectReason?: string;
  maxReconnectAttempts?: number;
  reconnectDelayMs?: number;
}

export interface AuthenticatedSseStream extends EventTarget {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  readonly readyState: number;
  close(): void;
}

class FetchAuthenticatedSseStream extends EventTarget implements AuthenticatedSseStream {
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readyState = SSE_CONNECTING;

  private readonly controller = new AbortController();
  private readonly disconnectReason: string;
  private readonly maxReconnectAttempts: number;
  private reconnectDelayMs: number;
  private reconnectAttempts = 0;
  private lastEventId = "";
  private closed = false;
  private readonly url: string;

  constructor(
    url: string,
    options: AuthenticatedSseOptions,
  ) {
    super();
    this.url = url;
    this.disconnectReason = options.disconnectReason ?? "get_sse_disconnect";
    this.maxReconnectAttempts = Math.max(
      0,
      Math.min(20, options.maxReconnectAttempts ?? DEFAULT_SSE_MAX_RECONNECT_ATTEMPTS),
    );
    this.reconnectDelayMs = Math.max(
      250,
      Math.min(MAX_SSE_RECONNECT_DELAY_MS, options.reconnectDelayMs ?? DEFAULT_SSE_RECONNECT_DELAY_MS),
    );
    activeSseSubscriptions.add(this);
    void this.connectLoop();
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = SSE_CLOSED;
    activeSseSubscriptions.delete(this);
    this.controller.abort();
  }

  private emitOpen(): void {
    const event = new Event("open");
    this.dispatchEvent(event);
    this.onopen?.(event);
  }

  private emitError(): void {
    const event = new Event("error");
    this.dispatchEvent(event);
    this.onerror?.(event);
  }

  private dispatchBlock(block: string): void {
    const parsed = parseSseEventBlock(block);
    if (parsed.retryMs !== null) {
      this.reconnectDelayMs = Math.max(
        250,
        Math.min(MAX_SSE_RECONNECT_DELAY_MS, parsed.retryMs),
      );
    }
    if (parsed.lastEventId !== null) this.lastEventId = parsed.lastEventId;
    if (!parsed.message) return;

    this.reconnectAttempts = 0;
    this.dispatchEvent(
      new MessageEvent(parsed.message.type, {
        data: parsed.message.data,
        lastEventId: this.lastEventId,
      }),
    );
  }

  private async consumeBody(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!this.closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r/g, "");

        let boundaryIndex = buffer.indexOf("\n\n");
        while (boundaryIndex !== -1) {
          this.dispatchBlock(buffer.slice(0, boundaryIndex));
          buffer = buffer.slice(boundaryIndex + 2);
          if (this.closed) return;
          boundaryIndex = buffer.indexOf("\n\n");
        }
      }

      buffer += decoder.decode().replace(/\r/g, "");
      if (!this.closed && buffer.trim()) this.dispatchBlock(buffer);
    } finally {
      reader.releaseLock();
    }
  }

  private async connectOnce(): Promise<void> {
    const headers = new Headers({
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    });
    if (this.lastEventId) headers.set("Last-Event-ID", this.lastEventId);

    await runTrackedApiFetch(
      this.url,
      {
        method: "GET",
        headers,
        cache: "no-store",
        signal: this.controller.signal,
      },
      async (response) => {
        if (!response.ok) {
          const error = new Error(await parseErrorResponse(response)) as SseConnectionError;
          error.status = response.status;
          throw error;
        }
        const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
        if (!contentType.includes("text/event-stream")) {
          const error = new Error("SSE 响应类型无效。");
          (error as SseConnectionError).retryable = false;
          throw error;
        }
        if (!response.body) throw new Error("SSE 响应流不可用。");

        this.readyState = SSE_OPEN;
        this.emitOpen();
        await this.consumeBody(response.body);
      },
      this.disconnectReason,
      false,
    );
  }

  private shouldReconnect(error: unknown): boolean {
    if (isBackendOfflineError(error)) return false;
    const connectionError = error as SseConnectionError | null;
    if (connectionError?.retryable === false) return false;
    const status = connectionError?.status;
    return !(typeof status === "number" && status >= 400 && status < 500);
  }

  private waitForBackendOnline(): Promise<void> {
    return new Promise((resolve) => {
      if (this.closed || !backendOffline) {
        resolve();
        return;
      }
      const onOnline = () => done();
      const onAbort = () => done();
      const signal = this.controller.signal;
      window.addEventListener(BACKEND_ONLINE_EVENT, onOnline, { once: true });
      signal.addEventListener("abort", onAbort, { once: true });

      function done() {
        window.removeEventListener(BACKEND_ONLINE_EVENT, onOnline);
        signal.removeEventListener("abort", onAbort);
        resolve();
      }
    });
  }

  private waitForReconnect(delayMs: number): Promise<"retry" | "offline" | "closed"> {
    return new Promise((resolve) => {
      if (this.closed) {
        resolve("closed");
        return;
      }
      if (backendOffline) {
        resolve("offline");
        return;
      }
      const timer = window.setTimeout(() => done("retry"), delayMs);
      const onOffline = () => done("offline");
      const onAbort = () => done("closed");
      const signal = this.controller.signal;
      window.addEventListener(BACKEND_OFFLINE_EVENT, onOffline, { once: true });
      signal.addEventListener("abort", onAbort, { once: true });

      function done(result: "retry" | "offline" | "closed") {
        window.clearTimeout(timer);
        window.removeEventListener(BACKEND_OFFLINE_EVENT, onOffline);
        signal.removeEventListener("abort", onAbort);
        resolve(result);
      }
    });
  }

  private async connectLoop(): Promise<void> {
    while (!this.closed) {
      if (backendOffline) {
        this.readyState = SSE_CONNECTING;
        await this.waitForBackendOnline();
        continue;
      }
      try {
        await this.connectOnce();
        if (this.closed) return;
        throw new Error("SSE connection closed before a terminal event.");
      } catch (error) {
        if (!this.closed) this.emitError();
        if (this.closed) return;
        if (isBackendDisconnectError(error)) {
          await reportBackendConnectionIssue(this.disconnectReason);
          if (this.closed) return;
        }
        if (backendOffline || isBackendOfflineError(error)) {
          this.readyState = SSE_CONNECTING;
          await this.waitForBackendOnline();
          continue;
        }
        if (!this.shouldReconnect(error) || this.reconnectAttempts >= this.maxReconnectAttempts) {
          this.close();
          return;
        }

        const delayMs = Math.min(
          MAX_SSE_RECONNECT_DELAY_MS,
          this.reconnectDelayMs * 2 ** this.reconnectAttempts,
        );
        this.reconnectAttempts += 1;
        this.readyState = SSE_CONNECTING;
        const waitResult = await this.waitForReconnect(delayMs);
        if (waitResult === "offline") {
          this.reconnectAttempts = Math.max(0, this.reconnectAttempts - 1);
          await this.waitForBackendOnline();
        }
      }
    }
  }
}

export function openAuthenticatedSse(
  url: string,
  options: AuthenticatedSseOptions = {},
): AuthenticatedSseStream {
  return new FetchAuthenticatedSseStream(url, options);
}

export interface SseTokenPayload {
  content: string;
}

export interface SseDonePayload {
  turn_id?: string;
  session_id?: string;
  session_title?: string;
  contexts?: unknown;
  elapsed_ms?: number;
  elapsed_s?: number;
  client_actions?: unknown;
}

export interface SseErrorPayload {
  detail?: string;
  error_code?: string;
}

export interface SseStatusPayload {
  stage?: string;
  detail?: string;
  step?: string;
  elapsed_ms?: number;
  elapsed_s?: number;
  session_id?: string;
  session_title?: string;
  tool_name?: string;
  tool_display_name?: string;
  tool_phase?: string;
  tool_call_id?: string;
  success?: boolean;
  argument_names?: string[];
}

export interface PostSseJsonOptions {
  signal?: AbortSignal;
  onToken?: (payload: SseTokenPayload) => void;
  onDone?: (payload: SseDonePayload | unknown) => void;
  onError?: (payload: SseErrorPayload | unknown) => void;
  onStatus?: (payload: SseStatusPayload | unknown) => void;
  onAbort?: () => void;
}

export interface PostSseJsonResult {
  aborted: boolean;
  receivedToken: boolean;
  sawDone: boolean;
  donePayload?: SseDonePayload | unknown;
  errorPayload?: SseErrorPayload | unknown;
}

function parseSseData(rawData: string): unknown {
  if (!rawData || rawData === "[DONE]") {
    return undefined;
  }
  try {
    return JSON.parse(rawData);
  } catch {
    return rawData;
  }
}

function normalizeSseEvent(
  eventName: string,
  payload: unknown,
): "token" | "done" | "error" | "status" | "ignore" {
  if (eventName === "token" || eventName === "done" || eventName === "error" || eventName === "status") {
    return eventName;
  }
  if (!isRecord(payload)) {
    return "ignore";
  }
  if (typeof payload.content === "string") {
    return "token";
  }
  if (typeof payload.detail === "string" || typeof payload.error_code === "string") {
    return "error";
  }
  if (
    typeof payload.stage === "string" ||
    typeof payload.step === "string" ||
    typeof payload.elapsed_ms === "number" ||
    typeof payload.detail === "string"
  ) {
    return "status";
  }
  if ("turn_id" in payload || "contexts" in payload) {
    return "done";
  }
  return "ignore";
}

export async function postSseJson<TBody>(
  url: string,
  body: TBody,
  options: PostSseJsonOptions = {},
): Promise<PostSseJsonResult> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "X-Device-Key": getDeviceKey(),
  };

  let receivedToken = false;
  let sawDone = false;
  let donePayload: SseDonePayload | unknown;
  let errorPayload: SseErrorPayload | unknown;

  try {
    return await runTrackedApiFetch(
      url,
      {
        method: "POST",
        headers,
        cache: "no-store",
        body: JSON.stringify(body),
        signal: options.signal,
      },
      async (response) => {
        if (!response.ok) {
          throw new Error(await parseErrorResponse(response));
        }
        if (!response.body) {
          throw new Error("响应流不可用，请重试。");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const dispatchEventBlock = (block: string) => {
          if (!block.trim()) {
            return;
          }

          let eventName = "message";
          const dataLines: string[] = [];
          for (const line of block.split("\n")) {
            if (!line || line.startsWith(":")) {
              continue;
            }
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim() || "message";
              continue;
            }
            if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trimStart());
            }
          }

          const rawData = dataLines.join("\n");
          const payload = parseSseData(rawData);
          if (payload === undefined) {
            if (rawData === "[DONE]") {
              sawDone = true;
              options.onDone?.({});
            }
            return;
          }

          switch (normalizeSseEvent(eventName, payload)) {
            case "token":
              if (isRecord(payload) && typeof payload.content === "string" && payload.content.length > 0) {
                receivedToken = true;
                options.onToken?.({ content: payload.content });
              }
              break;
            case "done":
              sawDone = true;
              donePayload = payload;
              options.onDone?.(payload);
              break;
            case "error":
              errorPayload = payload;
              options.onError?.(payload);
              break;
            case "status":
              options.onStatus?.(payload);
              break;
            default:
              break;
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true }).replace(/\r/g, "");

          let boundaryIndex = buffer.indexOf("\n\n");
          while (boundaryIndex !== -1) {
            const block = buffer.slice(0, boundaryIndex);
            buffer = buffer.slice(boundaryIndex + 2);
            dispatchEventBlock(block);
            boundaryIndex = buffer.indexOf("\n\n");
          }
        }

        buffer += decoder.decode().replace(/\r/g, "");
        if (buffer.trim()) {
          dispatchEventBlock(buffer);
        }

        return {
          aborted: false,
          receivedToken,
          sawDone,
          donePayload,
          errorPayload,
        };
      },
      "sse_fetch_disconnect",
    );
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      options.onAbort?.();
      return {
        aborted: true,
        receivedToken,
        sawDone,
        donePayload,
        errorPayload,
      };
    }
    throw error;
  }
}

instance.interceptors.request.use((config) => {
  if (backendOffline) {
    return Promise.reject(createBackendOfflineError());
  }

  const headers = AxiosHeaders.from(config.headers);
  headers.set("X-Device-Key", getDeviceKey());

  headers.delete("Authorization");
  const method = String(config.method ?? "GET").toUpperCase();
  if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  config.headers = headers;
  
  // Apply dynamic base URL from settings
  const dynamicBaseUrl = getApiBaseUrl();
  if (dynamicBaseUrl) {
    config.baseURL = dynamicBaseUrl;
  }

  const trackedSignal = createTrackedAbortSignal(config.signal ?? null);
  config.signal = trackedSignal.signal;

  (config as ApiRequestConfigWithMetadata).metadata = {
    startTime: Date.now(),
    cleanupAbortSignal: trackedSignal.cleanup,
  };
  return config;
});

function cleanupTrackedRequest(config?: AxiosRequestConfig | null) {
  (config as ApiRequestConfigWithMetadata | undefined)?.metadata?.cleanupAbortSignal?.();
}

instance.interceptors.response.use(
  (response: AxiosResponse) => {
    cleanupTrackedRequest(response.config);
    const nextCsrfToken = response.data?.data?.csrf_token;
    if (typeof nextCsrfToken === "string" || nextCsrfToken === null) {
      setApiCsrfToken(nextCsrfToken);
    }
    return response;
  },
  (error) => {
    cleanupTrackedRequest(error?.config);
    if (isBackendDisconnectError(error)) {
      markBackendOffline("axios_disconnect");
    }
    return Promise.reject(error);
  },
);

export const apiClient = async <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> => {
  const res = await instance({
    ...config,
    ...options,
  });

  return res.data;
};

export interface OrvalRequestInit extends RequestInit {
  params?: AxiosRequestConfig["params"];
  timeout?: AxiosRequestConfig["timeout"];
}

export interface OrvalResponse<T> {
  data: T;
  status: number;
  headers: Headers;
}

function toAxiosHeaders(headers?: HeadersInit): Record<string, string> | undefined {
  if (!headers) {
    return undefined;
  }

  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }

  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }

  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [key, String(value)]),
  );
}

function toFetchHeaders(headers: AxiosResponse["headers"]): Headers {
  const normalizedEntries: Array<[string, string]> = headers instanceof AxiosHeaders
    ? Object.entries(headers.toJSON()).map(([key, value]) => [key, String(value)] as [string, string])
    : Object.entries(headers ?? {}).map(([key, value]) => [key, String(value)] as [string, string]);

  return new Headers(normalizedEntries);
}

export async function orvalApiClient<T>(
  url: string,
  options: OrvalRequestInit = {},
): Promise<T> {
  const { body, headers, params, method, signal, timeout } = options;

  const response = await instance({
    url,
    params,
    method,
    signal: signal ?? undefined,
    timeout,
    headers: toAxiosHeaders(headers),
    data: body,
  });

  return {
    data: response.data,
    status: response.status,
    headers: toFetchHeaders(response.headers),
  } as T;
}

export function getApiErrorMessage(
  error: unknown,
  fallback = "请求失败，请稍后重试",
): string {
  if (!isRecord(error)) {
    return fallback;
  }
  const apiError = error as ApiErrorShape;
  if (apiError.code === "BACKEND_OFFLINE") {
    return "后端服务已断开，正在尝试重连。";
  }
  if (apiError.code === "ERR_CANCELED") {
    return backendOffline ? "后端服务已断开，当前请求已自动停止。" : "请求已取消。";
  }
  if ((apiError as { name?: string }).name === "AbortError") {
    return backendOffline ? "后端服务已断开，当前请求已自动停止。" : "请求已取消。";
  }
  if (apiError.code === "ERR_NETWORK") {
    return "后端服务连接已断开，已停止当前请求并开始重连。";
  }
  if (
    apiError.code === "ECONNABORTED" ||
    (typeof apiError.message === "string" && /timeout of \d+ms exceeded/i.test(apiError.message))
  ) {
    return "请求处理时间超过预期，后端可能仍在继续执行。请稍后查看进度或重试。";
  }

  const message =
    apiError.response?.data?.message ??
    apiError.response?.data?.detail ??
    apiError.message;

  if (typeof message === "string" && message.trim()) {
    return sanitizeErrorText(message, fallback);
  }

  return fallback;
}

export function getApiErrorCode(error: unknown): string | null {
  if (!isRecord(error)) {
    return null;
  }
  const apiError = error as ApiErrorShape;
  const errorCode = apiError.response?.data?.error_code;

  return typeof errorCode === "string" && errorCode.trim() ? errorCode : null;
}

export function getApiErrorData<T>(error: unknown): T | null {
  if (!isRecord(error)) {
    return null;
  }
  const apiError = error as ApiErrorShape;
  const data = apiError.response?.data?.data;

  if (data === undefined || data === null) {
    return null;
  }

  return data as T;
}

export function getCreditInsufficientMessage(error: unknown): string | null {
  if (getApiErrorCode(error) !== "CREDIT_INSUFFICIENT") {
    return null;
  }
  const data = getApiErrorData<{ required?: number; available?: number }>(error);
  const required = Number(data?.required);
  const available = Number(data?.available);
  if (Number.isFinite(required) && Number.isFinite(available)) {
    return `当前可用额度 ${available}，本次需要 ${required}。请前往“AI 额度”查看记录或联系管理员。`;
  }
  return "AI 额度不足，请前往“AI 额度”查看记录或联系管理员。";
}

export function isApiErrorStatus(
  error: unknown,
  status: number,
  errorCode?: string,
): boolean {
  const apiError = error as ApiErrorShape;
  const response = apiError.response;

  if (response?.status !== status) {
    return false;
  }

  if (!errorCode) {
    return true;
  }

  return response.data?.error_code === errorCode;
}
