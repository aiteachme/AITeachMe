import { useQuery } from "@tanstack/react-query";

import { apiClient, getApiErrorMessage } from "../../api/client";

type Provider = { provider: "google" | "qq" | "wechat"; label: string };
type ApiResponse<T> = { code: number; message: string; data: T };

export function OAuthButtons({ onError }: { onError: (message: string) => void }) {
  const providers = useQuery({
    queryKey: ["auth", "oauth-providers"],
    queryFn: async () => {
      const response = await apiClient<ApiResponse<Provider[]>>({
        url: "/api/v1/auth/providers",
        method: "GET",
      });
      return response.data ?? [];
    },
    staleTime: 5 * 60_000,
  });

  if (!providers.data?.length) return null;

  const start = async (provider: Provider["provider"]) => {
    onError("");
    try {
      const response = await apiClient<ApiResponse<{ authorization_url: string }>>({
        url: `/api/v1/auth/oauth/${provider}/start`,
        method: "POST",
        data: { mode: "login", return_to: `${window.location.pathname}${window.location.search}` },
      });
      window.location.assign(response.data.authorization_url);
    } catch (error) {
      onError(getApiErrorMessage(error, "第三方登录发起失败，请稍后重试。"));
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-xs text-slate-400">
        <span className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
        其他登录方式
        <span className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
      </div>
      <div className="grid grid-cols-3 gap-2">
        {providers.data.map((item) => (
          <button
            key={item.provider}
            type="button"
            onClick={() => void start(item.provider)}
            className="rounded-lg border border-slate-200 px-2 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
