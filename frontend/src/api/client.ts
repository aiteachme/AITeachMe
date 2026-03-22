import axios, { AxiosRequestConfig, AxiosResponse } from "axios";

const instance = axios.create({
    baseURL: import.meta.env.VITE_API_URL ?? "",
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


instance.interceptors.request.use((config) => {
    const token = localStorage.getItem("token");

    if (token && config.headers) {
        config.headers.set("Authorization", `Bearer ${token}`);
    }

    (config as any).metadata = { startTime: Date.now() };
    console.log("🚀 API Request");
    console.log("URL:", config.url);
    console.log("Method:", config.method);
    console.log("Params:", config.params);
    console.log("Data:", config.data);
    return config;
});

// 响应拦截器
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
    }
);

export const apiClient = async <T>(
    config: AxiosRequestConfig,
    options?: AxiosRequestConfig
): Promise<T> => {

    const res = await instance({
        ...config,
        ...options,
    });

    return res.data;
};

export function getApiErrorMessage(
    error: unknown,
    fallback = "请求失败，请稍后重试"
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

export function isApiErrorStatus(
    error: unknown,
    status: number,
    errorCode?: string
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
