import axios, { AxiosHeaders, AxiosRequestConfig, AxiosResponse } from "axios";

function resolveDesktopApiBaseUrl(): string {
  if (typeof window === "undefined" || window.location.protocol !== "file:") {
    return "";
  }
  return window.aiteachmeDesktop?.apiBaseUrl ?? "http://127.0.0.1:9020";
}

const API_BASE_URL = resolveDesktopApiBaseUrl() || (import.meta.env.VITE_API_URL ?? "").trim();
const DEVICE_KEY_STORAGE_KEY = "device_key";
const DEVICE_KEY_RE = /^[A-Za-z0-9._:-]{8,128}$/;
export const DEFAULT_API_TIMEOUT_MS = 10_000;
export const LONG_RUNNING_API_TIMEOUT_MS = 120_000;
const BACKEND_HEALTH_CHECK_TIMEOUT_MS = 1_200;
const BACKEND_RECOVERY_POLL_INTERVAL_MS = 1_500;
export const BACKEND_OFFLINE_EVENT = "aiteachme:backend-offline";
export const BACKEND_ONLINE_EVENT = "aiteachme:backend-online";

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
const activeEventSources = new Set<EventSource>();
let backendOffline = false;
let recoveryProbeTimer: number | null = null;
let connectionIssueProbeInFlight = false;

function getAccessToken(): string | null {
  return localStorage.getItem("token");
}

function generateDeviceKey(): string {
  const randomPart =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  return `dk_${randomPart}`;
}

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
    return "dk_fallback_local";
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

function createApiFetchHeaders(headers?: HeadersInit): Headers {
  const nextHeaders = new Headers(headers);
  nextHeaders.set("X-Device-Key", getDeviceKey());

  const token = getAccessToken();
  if (token) {
    nextHeaders.set("Authorization", `Bearer ${token}`);
  } else {
    nextHeaders.delete("Authorization");
  }

  return nextHeaders;
}

export function abortActiveApiRequests(): void {
  for (const controller of Array.from(activeRequestControllers)) {
    if (!controller.signal.aborted) {
      controller.abort();
    }
  }
}

function closeActiveEventSources(): void {
  for (const source of Array.from(activeEventSources)) {
    source.close();
  }
  activeEventSources.clear();
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
}

function startBackendRecoveryProbe() {
  if (typeof window === "undefined" || recoveryProbeTimer !== null) {
    return;
  }

  const schedule = () => {
    recoveryProbeTimer = window.setTimeout(async () => {
      recoveryProbeTimer = null;
      if (await checkBackendHealthOnce()) {
        markBackendOnline();
        return;
      }
      if (backendOffline) {
        schedule();
      }
    }, BACKEND_RECOVERY_POLL_INTERVAL_MS);
  };

  schedule();
}

export function markBackendOnline(): void {
  if (!backendOffline) {
    return;
  }
  backendOffline = false;
  stopBackendRecoveryProbe();
  dispatchBackendConnectionEvent(BACKEND_ONLINE_EVENT);
}

export function markBackendOffline(reason = "network_error"): void {
  if (backendOffline) {
    abortActiveApiRequests();
    closeActiveEventSources();
    return;
  }

  backendOffline = true;
  abortActiveApiRequests();
  closeActiveEventSources();
  startBackendRecoveryProbe();
  dispatchBackendConnectionEvent(BACKEND_OFFLINE_EVENT, { reason });
}

export function reportBackendConnectionIssue(reason = "stream_error"): void {
  if (backendOffline || connectionIssueProbeInFlight) {
    return;
  }
  connectionIssueProbeInFlight = true;
  void checkBackendHealthOnce()
    .then((isHealthy) => {
      if (isHealthy) {
        markBackendOnline();
        return;
      }
      markBackendOffline(reason);
    })
    .finally(() => {
      connectionIssueProbeInFlight = false;
    });
}

export function registerBackendEventSource(source: EventSource): () => void {
  activeEventSources.add(source);
  if (backendOffline) {
    source.close();
  }
  return () => {
    activeEventSources.delete(source);
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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
): Promise<T> {
  if (backendOffline) {
    throw createBackendOfflineError();
  }

  const trackedSignal = createTrackedAbortSignal(init.signal ?? null);
  try {
    const response = await fetch(buildApiUrl(url), {
      ...init,
      credentials: init.credentials ?? "include",
      headers: createApiFetchHeaders(init.headers),
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
    return payload.trim();
  }
  if (isRecord(payload)) {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
    const message = payload.message;
    if (typeof message === "string" && message.trim()) {
      return message.trim();
    }
    if (isRecord(payload.error)) {
      const nestedDetail = payload.error.detail;
      if (typeof nestedDetail === "string" && nestedDetail.trim()) {
        return nestedDetail.trim();
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

export interface SseTokenPayload {
  content: string;
}

export interface SseDonePayload {
  turn_id?: string;
  session_id?: string;
  session_title?: string;
  contexts?: unknown;
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
  session_id?: string;
  session_title?: string;
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

  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    headers.delete("Authorization");
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
  const { body, headers, params, method, signal } = options;

  const response = await instance({
    url,
    params,
    method,
    signal: signal ?? undefined,
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
    return message;
  }

  return fallback;
}

export function getApiErrorCode(error: unknown): string | null {
  const apiError = error as ApiErrorShape;
  const errorCode = apiError.response?.data?.error_code;

  return typeof errorCode === "string" && errorCode.trim() ? errorCode : null;
}

export function getApiErrorData<T>(error: unknown): T | null {
  const apiError = error as ApiErrorShape;
  const data = apiError.response?.data?.data;

  if (data === undefined || data === null) {
    return null;
  }

  return data as T;
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
