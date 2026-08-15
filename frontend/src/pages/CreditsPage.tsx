import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient, getApiErrorMessage } from "../api/client";
import { useAuthSession } from "../hooks/useAuthSession";

type ApiResponse<T> = { data: T };
type Summary = { balance: number; reserved: number; available: number; lifetime_granted: number; lifetime_spent: number };
type LedgerItem = { id: string; delta: number; operation: string; reason: string; balance_after: number; created_at: string };
type LedgerPage = { items: LedgerItem[]; page: number; size: number; total: number };

export function CreditsPage() {
  const [page, setPage] = useState(1);
  const auth = useAuthSession();
  const isLoggedIn = Boolean(auth.data?.current_user?.is_authenticated);
  const creditsEnabled = auth.data?.credits_enabled === true;
  const summary = useQuery({
    queryKey: ["credits", "summary"],
    enabled: isLoggedIn && creditsEnabled,
    queryFn: async () => (await apiClient<ApiResponse<Summary>>({ url: "/api/v1/credits/summary", method: "GET" })).data,
  });
  const ledger = useQuery({
    queryKey: ["credits", "ledger", page],
    enabled: isLoggedIn && creditsEnabled,
    queryFn: async () => (await apiClient<ApiResponse<LedgerPage>>({ url: "/api/v1/credits/ledger", method: "GET", params: { page, size: 20 } })).data,
  });

  if (auth.isLoading) return <p className="p-8 text-sm text-slate-500">正在读取额度信息…</p>;
  if (!creditsEnabled) return <p className="p-8 text-sm text-slate-500">AI 额度功能暂未开放。</p>;
  if (!isLoggedIn) return <p className="p-8 text-sm text-amber-700">请先登录，再查看 AI 额度。</p>;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">AI 额度</h1>
        <p className="mt-1 text-sm text-slate-500">教材构建每次 30，人工生成新试卷每次 5。</p>
      </div>
      <section className="grid gap-3 sm:grid-cols-3">
        {[
          ["可用额度", summary.data?.available ?? "—"],
          ["冻结中", summary.data?.reserved ?? "—"],
          ["累计使用", summary.data?.lifetime_spent ?? "—"],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-2 text-3xl font-semibold text-slate-900 dark:text-white">{value}</p>
          </div>
        ))}
      </section>
      {summary.error || ledger.error ? (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {getApiErrorMessage(summary.error ?? ledger.error, "额度信息加载失败，请稍后重试。")}
        </p>
      ) : null}
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <h2 className="border-b border-slate-100 px-5 py-4 font-medium dark:border-slate-800">额度记录</h2>
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {(ledger.data?.items ?? []).map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-4 px-5 py-4 text-sm">
              <div><p className="text-slate-800 dark:text-slate-100">{item.reason}</p><p className="mt-1 text-xs text-slate-400">{new Date(item.created_at).toLocaleString()}</p></div>
              <span className={item.delta > 0 ? "text-emerald-600" : "text-slate-700 dark:text-slate-200"}>{item.delta > 0 ? "+" : ""}{item.delta}</span>
            </div>
          ))}
          {!ledger.isLoading && !ledger.data?.items.length ? <p className="px-5 py-8 text-center text-sm text-slate-400">暂无记录</p> : null}
        </div>
        {(ledger.data?.total ?? 0) > (ledger.data?.size ?? 20) ? (
          <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-sm dark:border-slate-800">
            <span className="text-slate-500">第 {page} 页，共 {Math.ceil((ledger.data?.total ?? 0) / (ledger.data?.size ?? 20))} 页</span>
            <div className="flex gap-2">
              <button type="button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border px-3 py-1.5 disabled:opacity-40">上一页</button>
              <button type="button" disabled={page * (ledger.data?.size ?? 20) >= (ledger.data?.total ?? 0)} onClick={() => setPage((value) => value + 1)} className="rounded-lg border px-3 py-1.5 disabled:opacity-40">下一页</button>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
