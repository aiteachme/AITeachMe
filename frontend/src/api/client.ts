import axios, { AxiosRequestConfig, AxiosResponse } from "axios";

const instance = axios.create({
    baseURL: "",
    timeout: 10000,
});


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