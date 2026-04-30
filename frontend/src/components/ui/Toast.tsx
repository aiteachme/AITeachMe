import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastVariant = "info" | "success" | "warning" | "error";

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
}

interface ToastItem extends ToastOptions {
  id: string;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within <ToastProvider />");
  }
  return ctx;
}

const variantConfig: Record<
  ToastVariant,
  {
    icon: React.ReactNode;
    border: string;
    bg: string;
    title: string;
    description: string;
    close: string;
    iconColor: string;
    accent: string;
  }
> = {
  info: {
    icon: <Info size={18} />,
    border: "border-indigo-200 dark:border-indigo-500/30",
    bg: "bg-white dark:bg-slate-950/95",
    title: "text-slate-800 dark:text-slate-100",
    description: "text-slate-500 dark:text-slate-400",
    close:
      "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200",
    iconColor: "text-indigo-500",
    accent: "bg-indigo-500",
  },
  success: {
    icon: <CheckCircle2 size={18} />,
    border: "border-emerald-200 dark:border-emerald-500/30",
    bg: "bg-white dark:bg-slate-950/95",
    title: "text-slate-800 dark:text-slate-100",
    description: "text-slate-500 dark:text-slate-400",
    close:
      "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200",
    iconColor: "text-emerald-500",
    accent: "bg-emerald-500",
  },
  warning: {
    icon: <AlertTriangle size={18} />,
    border: "border-amber-200 dark:border-amber-500/30",
    bg: "bg-white dark:bg-slate-950/95",
    title: "text-slate-800 dark:text-slate-100",
    description: "text-slate-500 dark:text-slate-400",
    close:
      "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200",
    iconColor: "text-amber-500",
    accent: "bg-amber-500",
  },
  error: {
    icon: <XCircle size={18} />,
    border: "border-red-200 dark:border-red-500/30",
    bg: "bg-white dark:bg-slate-950/95",
    title: "text-slate-800 dark:text-slate-100",
    description: "text-slate-500 dark:text-slate-400",
    close:
      "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200",
    iconColor: "text-red-500",
    accent: "bg-red-500",
  },
};

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: string) => void;
}) {
  const variant = variantConfig[item.variant || "info"];

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
        dark:shadow-[0_20px_40px_-24px_rgba(0,0,0,0.75)]
        ${variant.border} ${variant.bg}
      `}
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] rounded-l-xl ${variant.accent}`} />
      <span className={`mt-0.5 shrink-0 ${variant.iconColor}`}>{variant.icon}</span>

      <div className="min-w-0 flex-1">
        <p className={`text-sm font-semibold leading-5 ${variant.title}`}>{item.title}</p>
        {item.description ? (
          <p className={`mt-0.5 text-xs leading-4 ${variant.description}`}>{item.description}</p>
        ) : null}
      </div>

      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        title="关闭"
        aria-label="关闭通知"
        className={`mt-0.5 shrink-0 rounded p-0.5 transition ${variant.close}`}
      >
        <X size={14} />
      </button>
    </motion.div>
  );
}

const MAX_TOASTS = 5;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counterRef = useRef(0);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
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
        window.setTimeout(() => dismiss(id), duration);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}

      <div className="pointer-events-none fixed right-5 top-20 z-[9999] flex flex-col items-end gap-2 md:right-6">
        <AnimatePresence mode="popLayout">
          {items.map((item) => (
            <ToastCard key={item.id} item={item} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
