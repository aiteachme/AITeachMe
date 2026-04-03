/**
 * 全局 Toast 通知组件。
 *
 * 使用方式:
 *   1. 在 App 根组件包裹 <ToastProvider />
 *   2. 任意子组件通过 useToast() 调用 toast()
 *
 * 示例:
 *   const { toast } = useToast();
 *   toast({ title: "成功", description: "操作完成", variant: "success" });
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Info, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

export type ToastVariant = "info" | "success" | "warning" | "error";

export interface ToastOptions {
  /** 标题（必填） */
  title: string;
  /** 描述 / 详情（可选） */
  description?: string;
  /** 类型，默认 info */
  variant?: ToastVariant;
  /** 自动关闭延时 ms，默认 5000，设为 0 则不自动关闭 */
  duration?: number;
}

interface ToastItem extends ToastOptions {
  id: string;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
}

/* ------------------------------------------------------------------ */
/* Context                                                             */
/* ------------------------------------------------------------------ */

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider />");
  return ctx;
}

/* ------------------------------------------------------------------ */
/* Variant styling — matches project's slate/white light theme         */
/* ------------------------------------------------------------------ */

const variantConfig: Record<
  ToastVariant,
  {
    icon: React.ReactNode;
    border: string;
    bg: string;
    iconColor: string;
    accent: string;
  }
> = {
  info: {
    icon: <Info size={18} />,
    border: "border-blue-200",
    bg: "bg-white",
    iconColor: "text-blue-500",
    accent: "bg-blue-500",
  },
  success: {
    icon: <CheckCircle2 size={18} />,
    border: "border-emerald-200",
    bg: "bg-white",
    iconColor: "text-emerald-500",
    accent: "bg-emerald-500",
  },
  warning: {
    icon: <AlertTriangle size={18} />,
    border: "border-amber-200",
    bg: "bg-white",
    iconColor: "text-amber-500",
    accent: "bg-amber-500",
  },
  error: {
    icon: <XCircle size={18} />,
    border: "border-red-200",
    bg: "bg-white",
    iconColor: "text-red-500",
    accent: "bg-red-500",
  },
};

/* ------------------------------------------------------------------ */
/* Single toast item                                                   */
/* ------------------------------------------------------------------ */

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: string) => void;
}) {
  const v = variantConfig[item.variant || "info"];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 80, scale: 0.96 }}
      transition={{ type: "spring", stiffness: 380, damping: 26 }}
      className={`
        pointer-events-auto relative flex items-start gap-3
        w-[380px] max-w-[90vw] overflow-hidden rounded-xl border
        px-4 py-3
        shadow-[0_8px_30px_-8px_rgba(15,23,42,0.12)]
        ${v.border} ${v.bg}
      `}
    >
      {/* Left accent bar */}
      <span
        className={`absolute inset-y-0 left-0 w-[3px] rounded-l-xl ${v.accent}`}
      />

      <span className={`mt-0.5 shrink-0 ${v.iconColor}`}>{v.icon}</span>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold leading-5 text-slate-800">
          {item.title}
        </p>
        {item.description && (
          <p className="mt-0.5 text-xs leading-4 text-slate-500">
            {item.description}
          </p>
        )}
      </div>

      <button
        onClick={() => onDismiss(item.id)}
        title="关闭"
        aria-label="关闭通知"
        className="mt-0.5 shrink-0 rounded p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
      >
        <X size={14} />
      </button>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* Provider                                                            */
/* ------------------------------------------------------------------ */

const MAX_TOASTS = 5;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counterRef = useRef(0);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (options: ToastOptions) => {
      const id = `toast-${++counterRef.current}`;
      const duration = options.duration ?? 5000;

      setItems((prev) => {
        const next = [...prev, { ...options, id }];
        return next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next;
      });

      if (duration > 0) {
        setTimeout(() => dismiss(id), duration);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Toast container — fixed top-right, matching common SaaS patterns */}
      <div className="pointer-events-none fixed top-5 right-5 z-[9999] flex flex-col items-end gap-2">
        <AnimatePresence mode="popLayout">
          {items.map((item) => (
            <ToastCard key={item.id} item={item} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
