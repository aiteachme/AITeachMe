import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Loader2, RefreshCw } from "lucide-react";
import type { DownloadEvent, Update } from "@tauri-apps/plugin-updater";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";

const CHECK_DELAY_MS = 1800;
const CHECK_TIMEOUT_MS = 30_000;
const CHECK_WATCHDOG_MS = 45_000;
const INSTALL_TIMEOUT_MS = 900_000;
const STARTUP_CHECK_SESSION_KEY = "aiteachme:tauri-local-update-startup-check";
const DESKTOP_UPDATE_AVAILABLE_EVENT = "aiteachme:desktop-update-available";

type UpdateStatus = "available" | "downloading" | "installing" | "restarting" | "failed";

let pendingDesktopUpdateCheck: Promise<Update | null> | null = null;

export function isTauriLocalRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.location.hostname === "tauri.localhost" && window.aiteachmeDesktop?.desktopFlavor === "local";
}

function describeUpdateError(error: unknown): string {
  const fallbackMessage = "请稍后重试，或从 GitHub Release 手动下载安装包。";
  let message = "";

  if (error instanceof Error && error.message.trim()) {
    message = error.message.trim();
  } else if (typeof error === "string" && error.trim()) {
    message = error.trim();
  }

  if (/error sending request|failed to fetch|network|timed?\s*out|connection/i.test(message)) {
    return [
      "无法连接更新源。",
      "当前安装包内置的 GitHub Release 更新源无法访问，桌面端请求可能没有走浏览器代理或被网络拦截。",
      "请先从浏览器手动下载安装包；后续发布应改用 CDN/OSS 更新源。",
    ].join("\n");
  }

  return message || fallbackMessage;
}

function logSkippedStartupCheck(error: unknown) {
  if (import.meta.env.DEV) {
    console.info("Tauri updater startup check skipped.", error);
  }
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) {
    return "0 MB";
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatUpdateDate(value: string | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function checkDesktopUpdate(): Promise<Update | null> {
  if (pendingDesktopUpdateCheck) {
    return pendingDesktopUpdateCheck;
  }

  pendingDesktopUpdateCheck = (async () => {
    const { check } = await import("@tauri-apps/plugin-updater");
    let watchdog: number | null = null;
    try {
      const checkPromise = check({ timeout: CHECK_TIMEOUT_MS });
      const watchdogPromise = new Promise<never>((_, reject) => {
        watchdog = window.setTimeout(() => {
          reject(new Error("desktop update check timed out"));
        }, CHECK_WATCHDOG_MS);
      });
      return await Promise.race([checkPromise, watchdogPromise]);
    } finally {
      if (watchdog !== null) {
        window.clearTimeout(watchdog);
      }
      pendingDesktopUpdateCheck = null;
    }
  })();

  return pendingDesktopUpdateCheck;
}

function isDesktopUpdateAvailableEvent(event: Event): event is CustomEvent<Update> {
  return event instanceof CustomEvent && Boolean(event.detail);
}

function broadcastDesktopUpdateAvailable(update: Update) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<Update>(DESKTOP_UPDATE_AVAILABLE_EVENT, { detail: update }));
}

interface CheckForUpdateOptions {
  silent?: boolean;
}

interface DesktopUpdateModalProps {
  open: boolean;
  update: Update | null;
  status: UpdateStatus;
  errorText: string;
  downloadedBytes: number;
  contentLength: number | null;
  onClose: () => void;
  onInstall: () => void;
}

export function useDesktopUpdateDialog() {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [update, setUpdate] = useState<Update | null>(null);
  const [status, setStatus] = useState<UpdateStatus>("available");
  const [errorText, setErrorText] = useState("");
  const [downloadedBytes, setDownloadedBytes] = useState(0);
  const [contentLength, setContentLength] = useState<number | null>(null);

  const isBusy = status === "downloading" || status === "installing" || status === "restarting";

  const applyAvailableUpdate = useCallback((availableUpdate: Update, openDialog: boolean) => {
    setUpdate(availableUpdate);
    setStatus("available");
    setErrorText("");
    setDownloadedBytes(0);
    setContentLength(null);
    if (openDialog) {
      setOpen(true);
    }
  }, []);

  useEffect(() => {
    if (!isTauriLocalRuntime()) {
      return;
    }

    const handleUpdateAvailable = (event: Event) => {
      if (!isDesktopUpdateAvailableEvent(event)) {
        return;
      }
      applyAvailableUpdate(event.detail, false);
    };

    window.addEventListener(DESKTOP_UPDATE_AVAILABLE_EVENT, handleUpdateAvailable);
    return () => window.removeEventListener(DESKTOP_UPDATE_AVAILABLE_EVENT, handleUpdateAvailable);
  }, [applyAvailableUpdate]);

  const checkForUpdate = useCallback(async ({ silent = false }: CheckForUpdateOptions = {}) => {
    if (!isTauriLocalRuntime()) {
      if (!silent) {
        toast({
          title: "当前环境不支持在线更新",
          description: "只有本地桌面版可以直接检查并安装更新。",
          variant: "warning",
        });
      }
      return null;
    }

    try {
      const availableUpdate = await checkDesktopUpdate();
      if (!availableUpdate) {
        if (!silent) {
          toast({
            title: "已是最新版本",
            description: "当前没有可用更新。",
            variant: "success",
          });
        }
        return null;
      }

      applyAvailableUpdate(availableUpdate, true);
      broadcastDesktopUpdateAvailable(availableUpdate);

      if (!silent) {
        toast({
          title: "发现新版本",
          description: `AiTeachMe ${availableUpdate.version}`,
          variant: "info",
        });
      }

      return availableUpdate;
    } catch (error) {
      if (silent) {
        logSkippedStartupCheck(error);
        return null;
      }

      const message = describeUpdateError(error);
      toast({
        title: "检查更新失败",
        description: message,
        variant: "error",
        duration: 9000,
      });
      return null;
    }
  }, [applyAvailableUpdate, toast]);

  const closeUpdateDialog = useCallback(() => {
    if (!isBusy) {
      setOpen(false);
    }
  }, [isBusy]);

  const showUpdateDialog = useCallback(() => {
    if (update) {
      setOpen(true);
    }
  }, [update]);

  const installUpdate = useCallback(async () => {
    if (!update || isBusy) {
      return;
    }

    setStatus("downloading");
    setErrorText("");
    setDownloadedBytes(0);
    setContentLength(null);

    try {
      await update.downloadAndInstall((event: DownloadEvent) => {
        if (event.event === "Started") {
          setContentLength(event.data.contentLength ?? null);
          setDownloadedBytes(0);
          return;
        }
        if (event.event === "Progress") {
          setDownloadedBytes((current) => current + event.data.chunkLength);
          return;
        }
        if (event.event === "Finished") {
          setStatus("installing");
        }
      }, { timeout: INSTALL_TIMEOUT_MS });

      setStatus("restarting");
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (error) {
      const message = describeUpdateError(error);
      setStatus("failed");
      setErrorText(message);
      toast({
        title: "更新安装失败",
        description: message,
        variant: "error",
        duration: 9000,
      });
    }
  }, [isBusy, toast, update]);

  return {
    open,
    update,
    status,
    errorText,
    downloadedBytes,
    contentLength,
    isBusy,
    isSupported: isTauriLocalRuntime(),
    checkForUpdate,
    closeUpdateDialog,
    showUpdateDialog,
    installUpdate,
  };
}

export function DesktopUpdateModal({
  open,
  update,
  status,
  errorText,
  downloadedBytes,
  contentLength,
  onClose,
  onInstall,
}: DesktopUpdateModalProps) {
  const progressPercent = useMemo(() => {
    if (!contentLength || contentLength <= 0) {
      return null;
    }
    return Math.min(100, Math.round((downloadedBytes / contentLength) * 100));
  }, [contentLength, downloadedBytes]);

  const updateDate = formatUpdateDate(update?.date);
  const isBusy = status === "downloading" || status === "installing" || status === "restarting";

  if (!update) {
    return null;
  }

  return (
    <Modal open={open} onClose={onClose} title="发现新版本" className="max-w-lg rounded-xl">
      <div className="space-y-5">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                AiTeachMe {update.version}
              </p>
              {updateDate ? (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">发布于 {updateDate}</p>
              ) : null}
            </div>
            <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200">
              可更新
            </span>
          </div>
          {update.body ? (
            <p className="mt-3 max-h-28 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-slate-600 dark:text-slate-300">
              {update.body}
            </p>
          ) : null}
        </div>

        {status === "downloading" || status === "installing" || status === "restarting" ? (
          <div className="space-y-2">
            <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-slate-900 transition-all dark:bg-slate-100"
                style={{ width: `${progressPercent ?? 35}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {status === "downloading"
                ? progressPercent === null
                  ? `正在下载更新包，已下载 ${formatBytes(downloadedBytes)}`
                  : `正在下载更新包，${progressPercent}%（${formatBytes(downloadedBytes)} / ${formatBytes(contentLength ?? 0)}）`
                : status === "installing"
                  ? "正在安装更新，应用会自动关闭并完成覆盖安装..."
                  : "更新已安装，正在重启应用..."}
            </p>
          </div>
        ) : null}

        {status === "failed" && errorText ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
            {errorText}
          </div>
        ) : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onClose} disabled={isBusy}>
            稍后再说
          </Button>
          <Button onClick={onInstall} disabled={isBusy}>
            {status === "downloading" || status === "installing" || status === "restarting" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : status === "failed" ? (
              <RefreshCw className="h-4 w-4" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {status === "failed" ? "重试更新" : isBusy ? "更新中" : "立即更新"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

interface DesktopUpdateIndicatorProps {
  update: Update;
  isBusy: boolean;
  onOpen: () => void;
}

function DesktopUpdateIndicator({ update, isBusy, onOpen }: DesktopUpdateIndicatorProps) {
  const updateDate = formatUpdateDate(update.date);
  const tooltip = [
    `最新版本：AiTeachMe ${update.version}`,
    updateDate ? `发布于：${updateDate}` : "",
    "点击查看更新",
  ].filter(Boolean).join("\n");

  return (
    <div className="fixed right-5 top-5 z-[95] md:right-6">
      <button
        type="button"
        onClick={onOpen}
        disabled={isBusy}
        title={tooltip}
        aria-label={`发现新版本 AiTeachMe ${update.version}`}
        className="group relative inline-flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-200/80 bg-white/92 text-emerald-700 shadow-[0_12px_32px_-20px_rgba(15,23,42,0.65)] backdrop-blur-md transition hover:-translate-y-0.5 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/35 active:translate-y-0 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-60 dark:border-emerald-500/30 dark:bg-slate-950/88 dark:text-emerald-300 dark:hover:border-emerald-400/50 dark:hover:bg-emerald-500/10"
      >
        <Download className="h-4.5 w-4.5" />
        <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-white dark:ring-slate-950" />
        <span className="pointer-events-none absolute right-0 top-full mt-2 hidden w-max max-w-[min(20rem,calc(100vw-2rem))] whitespace-pre-line rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs leading-5 text-slate-700 shadow-lg dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 group-hover:block group-focus-visible:block">
          {tooltip}
        </span>
      </button>
    </div>
  );
}

export function DesktopUpdatePrompt() {
  const hasStartedRef = useRef(false);
  const updater = useDesktopUpdateDialog();
  const { checkForUpdate } = updater;

  useEffect(() => {
    if (hasStartedRef.current || !isTauriLocalRuntime()) {
      return;
    }
    hasStartedRef.current = true;

    try {
      if (window.sessionStorage.getItem(STARTUP_CHECK_SESSION_KEY) === "1") {
        return;
      }
      window.sessionStorage.setItem(STARTUP_CHECK_SESSION_KEY, "1");
    } catch {
      // Session storage is only used to avoid duplicate startup prompts.
    }

    const timer = window.setTimeout(() => {
      void checkForUpdate({ silent: true });
    }, CHECK_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [checkForUpdate]);

  return (
    <>
      {updater.update && !updater.open ? (
        <DesktopUpdateIndicator
          update={updater.update}
          isBusy={updater.isBusy}
          onOpen={updater.showUpdateDialog}
        />
      ) : null}
      <DesktopUpdateModal
        open={updater.open}
        update={updater.update}
        status={updater.status}
        errorText={updater.errorText}
        downloadedBytes={updater.downloadedBytes}
        contentLength={updater.contentLength}
        onClose={updater.closeUpdateDialog}
        onInstall={updater.installUpdate}
      />
    </>
  );
}
