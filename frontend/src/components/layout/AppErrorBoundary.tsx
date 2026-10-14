import { Component, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

/** Keep failed lazy imports (including stale deployment chunks) recoverable. */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="flex min-h-screen items-center justify-center bg-zinc-50 px-6 text-zinc-900 dark:bg-slate-950 dark:text-slate-100">
        <section role="alert" className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h1 className="text-lg font-semibold">页面未能加载</h1>
          <p className="mt-3 text-sm leading-6 text-zinc-600 dark:text-slate-400">
            页面版本更新或网络中断可能导致加载失败，请重新加载页面后再试。
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            重新加载页面
          </button>
        </section>
      </main>
    );
  }
}
