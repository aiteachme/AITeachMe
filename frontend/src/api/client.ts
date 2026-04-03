import axios, { AxiosHeaders, AxiosRequestConfig, AxiosResponse } from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";

const instance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

export interface ApiErrorPayload {
  code?: number | string;
  error_code?: string;
  message?: string;
  detail?: string;
  data?: unknown;
}

type ApiErrorShape = {
  message?: string;
  response?: {
    status?: number;
    data?: ApiErrorPayload;
  };
};

function getAccessToken(): string | null {
  return localStorage.getItem("token");
}

function getApiBaseUrl(): string {
  let base = API_BASE_URL;
  try {
    const stored = localStorage.getItem("app-settings");
    if (stored) {
      const { apiUrl } = JSON.parse(stored);
      if (apiUrl) base = apiUrl;
    }
  } catch {}
  return base;
}

function buildApiUrl(url: string): string {
  const base = getApiBaseUrl();
  if (/^https?:\/\//i.test(url) || !base) {
    return url;
  }
  const cleanBase = base.replace(/\/$/, "");
  const path = url.startsWith("/") ? url : `/${url}`;
  return `${cleanBase}${path}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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
  contexts?: unknown;
}

export interface SseErrorPayload {
  detail?: string;
  error_code?: string;
}

export interface PostSseJsonOptions {
  signal?: AbortSignal;
  onToken?: (payload: SseTokenPayload) => void;
  onDone?: (payload: SseDonePayload | unknown) => void;
  onError?: (payload: SseErrorPayload | unknown) => void;
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
): "token" | "done" | "error" | "ignore" {
  if (eventName === "token" || eventName === "done" || eventName === "error") {
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
  };
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let receivedToken = false;
  let sawDone = false;
  let donePayload: SseDonePayload | unknown;
  let errorPayload: SseErrorPayload | unknown;

  try {
    const response = await fetch(buildApiUrl(url), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: options.signal,
    });

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
  const token = getAccessToken();

  if (token && config.headers) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  
  // Apply dynamic base URL from settings
  const dynamicBaseUrl = getApiBaseUrl();
  if (dynamicBaseUrl) {
    config.baseURL = dynamicBaseUrl;
  }

  (config as { metadata?: { startTime: number } }).metadata = { startTime: Date.now() };
  console.log("🚀 API Request");
  console.log("URL:", config.url);
  console.log("Method:", config.method);
  console.log("Params:", config.params);
  console.log("Data:", config.data);
  return config;
});

instance.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log("✅ API Response");
    console.log("URL:", response.config.url);
    console.log("Status:", response.status);
    console.log("Data:", response.data);

    return response;
  },
  (error) => {
    console.error("❌ API Error");

    if (error.response) {
      console.error("URL:", error.config?.url);
      console.error("Status:", error.response.status);
      console.error("Data:", error.response.data);
    } else {
      console.error(error.message);
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
