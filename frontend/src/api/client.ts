import axios, { AxiosRequestConfig } from "axios"

const axiosInstance = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
    withCredentials: true,
})

export const apiClient = <T>(config: AxiosRequestConfig): Promise<T> => {
    return axiosInstance(config).then((res) => res.data)
}