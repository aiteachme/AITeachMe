import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Loader2, LogOut, ShieldCheck, Unlink } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { apiClient, getApiErrorMessage, notifyApiAuthChanged, setApiCsrfToken } from "../api/client";
import { useAuthSession } from "../hooks/useAuthSession";
import { AUTH_SESSION_QUERY_KEY } from "../lib/authSession";

type ProviderName = "google" | "qq" | "wechat";
type ApiResponse<T> = { data: T };
type Provider = { provider: ProviderName; label: string };
type Identity = {
  id: string;
  provider: ProviderName;
  provider_email?: string | null;
  created_at: string;
};

const PROVIDER_LABELS: Record<ProviderName, string> = {
  google: "Google",
  qq: "QQ",
  wechat: "微信",
};

export function AccountPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const auth = useAuthSession();
  const isLoggedIn = Boolean(auth.data?.current_user?.is_authenticated);
  const identities = useQuery({
    queryKey: ["auth", "identities"],
    enabled: isLoggedIn,
    queryFn: async () => (
      await apiClient<ApiResponse<Identity[]>>({ url: "/api/v1/auth/identities", method: "GET" })
    ).data ?? [],
  });
  const providers = useQuery({
    queryKey: ["auth", "oauth-providers"],
    enabled: isLoggedIn,
    staleTime: 5 * 60_000,
    queryFn: async () => (
      await apiClient<ApiResponse<Provider[]>>({ url: "/api/v1/auth/providers", method: "GET" })
    ).data ?? [],
  });

  const bindIdentity = useMutation({
    mutationFn: async (provider: ProviderName) => (
      await apiClient<ApiResponse<{ authorization_url: string }>>({
        url: `/api/v1/auth/oauth/${provider}/start`,
        method: "POST",
        data: { mode: "link", return_to: "/account" },
      })
    ).data,
    onSuccess: (data) => window.location.assign(data.authorization_url),
  });
  const unlinkIdentity = useMutation({
    mutationFn: async (identityId: string) => apiClient({
      url: `/api/v1/auth/identities/${identityId}`,
      method: "DELETE",
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "identities"] });
    },
  });
  const logoutAll = useMutation({
    mutationFn: async () => apiClient({ url: "/api/v1/auth/logout-all", method: "POST", data: {} }),
    onSuccess: async () => {
      notifyApiAuthChanged();
      setApiCsrfToken(null);
      queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, null);
      await queryClient.invalidateQueries();
      navigate("/?auth=login", { replace: true });
    },
  });

  if (auth.isLoading) {
    return <p className="p-8 text-sm text-slate-500">正在读取账号信息…</p>;
  }
  if (!isLoggedIn) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <p className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
          请先登录，再管理第三方登录方式。
        </p>
      </main>
    );
  }

  const linkedProviders = new Set((identities.data ?? []).map((item) => item.provider));
  const error = bindIdentity.error ?? unlinkIdentity.error ?? logoutAll.error;

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">账号与登录安全</h1>
        <p className="mt-1 text-sm text-slate-500">
          {auth.data?.current_user?.email ?? "第三方登录账号"} · 可绑定多种登录方式，解绑时会保留至少一种可用方式。
        </p>
      </div>

      {searchParams.get("oauth") === "linked" ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          新的第三方登录方式已绑定。
        </div>
      ) : null}
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {getApiErrorMessage(error, "登录方式操作失败，请稍后重试。")}
        </div>
      ) : null}

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <h2 className="font-medium text-slate-900 dark:text-white">已绑定的登录方式</h2>
        </div>
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {(identities.data ?? []).map((identity) => (
            <div key={identity.id} className="flex items-center justify-between gap-4 px-5 py-4">
              <div className="flex min-w-0 items-center gap-3">
                <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-500" />
                <div className="min-w-0">
                  <p className="font-medium text-slate-800 dark:text-slate-100">{PROVIDER_LABELS[identity.provider]}</p>
                  <p className="truncate text-xs text-slate-400">
                    {identity.provider_email || `绑定于 ${new Date(identity.created_at).toLocaleDateString()}`}
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={unlinkIdentity.isPending}
                onClick={() => unlinkIdentity.mutate(identity.id)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                <Unlink className="h-3.5 w-3.5" />解绑
              </button>
            </div>
          ))}
          {!identities.isLoading && !identities.data?.length ? (
            <p className="px-5 py-6 text-sm text-slate-500">当前使用邮箱密码登录，尚未绑定第三方账号。</p>
          ) : null}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="font-medium text-slate-900 dark:text-white">绑定新的登录方式</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {(providers.data ?? []).map((provider) => {
            const linked = linkedProviders.has(provider.provider);
            return (
              <button
                key={provider.provider}
                type="button"
                disabled={linked || bindIdentity.isPending}
                onClick={() => bindIdentity.mutate(provider.provider)}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                {bindIdentity.isPending && bindIdentity.variables === provider.provider
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Link2 className="h-4 w-4" />}
                {linked ? `${provider.label} 已绑定` : `绑定 ${provider.label}`}
              </button>
            );
          })}
          {!providers.isLoading && !providers.data?.length ? (
            <p className="text-sm text-slate-500 sm:col-span-3">当前部署尚未启用第三方登录。</p>
          ) : null}
        </div>
      </section>

      <section className="flex items-center justify-between gap-4 rounded-xl border border-red-200 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5">
        <div>
          <h2 className="font-medium text-red-800 dark:text-red-200">退出所有设备</h2>
          <p className="mt-1 text-sm text-red-600 dark:text-red-300">立即撤销此账号的全部浏览器会话。</p>
        </div>
        <button
          type="button"
          disabled={logoutAll.isPending}
          onClick={() => logoutAll.mutate()}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          <LogOut className="h-4 w-4" />全部退出
        </button>
      </section>
    </main>
  );
}
