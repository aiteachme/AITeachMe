import { type FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, getApiErrorMessage } from "../api/client";
import { useAuthSession } from "../hooks/useAuthSession";

type ApiResponse<T> = { data: T };
type AdminUser = { user_id: string; email?: string; display_name?: string; role: string; balance: number; reserved: number };

export function AdminPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [operation, setOperation] = useState<"grant" | "deduct" | "set">("grant");
  const [amount, setAmount] = useState("100");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const auth = useAuthSession();
  const isAdmin = auth.data?.current_user?.role === "admin";
  const users = useQuery({
    queryKey: ["admin", "users", query],
    enabled: isAdmin,
    queryFn: async () => (await apiClient<ApiResponse<{ items: AdminUser[] }>>({ url: "/api/v1/admin/users", method: "GET", params: { q: query } })).data,
  });

  if (auth.isLoading) return <p className="p-8 text-sm text-slate-500">正在校验管理员权限…</p>;
  if (!isAdmin) return <p className="p-8 text-sm text-red-600">此页面仅管理员可访问。</p>;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setError("");
    try {
      await apiClient({
        url: `/api/v1/admin/users/${selected.user_id}/credits/adjust`, method: "POST",
        data: { operation, amount: Number(amount), reason, idempotency_key: crypto.randomUUID() },
      });
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    } catch (cause) { setError(getApiErrorMessage(cause, "额度调整失败。")); }
  };

  return (
    <main className="mx-auto w-full max-w-6xl space-y-5 px-4 py-8">
      <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">用户与 AI 额度管理</h1>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索用户 ID、邮箱或名称" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900" />
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
          {(users.data?.items ?? []).map((user) => (
            <button key={user.user_id} onClick={() => setSelected(user)} className="flex w-full items-center justify-between border-b border-slate-100 px-4 py-3 text-left text-sm hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900">
              <span><strong className="block">{user.email || user.user_id}</strong><span className="text-xs text-slate-400">{user.user_id}</span></span>
              <span>可用 {user.balance - user.reserved}</span>
            </button>
          ))}
        </div>
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
          <h2 className="font-medium">调整额度</h2>
          <p className="text-xs text-slate-500">{selected ? selected.email || selected.user_id : "请先选择用户"}</p>
          <select value={operation} onChange={(event) => setOperation(event.target.value as typeof operation)} className="w-full rounded-lg border p-2 dark:bg-slate-900"><option value="grant">赠送</option><option value="deduct">扣减</option><option value="set">设定余额</option></select>
          <input type="number" min="0" value={amount} onChange={(event) => setAmount(event.target.value)} className="w-full rounded-lg border p-2 dark:bg-slate-900" />
          <textarea required minLength={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="请输入中文操作原因" className="min-h-24 w-full rounded-lg border p-2 dark:bg-slate-900" />
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button disabled={!selected} className="w-full rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-slate-900">确认调整</button>
        </form>
      </div>
    </main>
  );
}
