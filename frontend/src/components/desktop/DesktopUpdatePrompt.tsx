import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Loader2, RefreshCw } from "lucide-react";
import type { DownloadEvent, Update } from "@tauri-apps/plugin-updater";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";

const CHECK_DELAY_MS = 1800;
const CHECK_TIMEOUT_MS = 15_000;
const INSTALL_TIMEOUT_MS = 180_000;
const STARTUP_CHECK_SESSION_KEY = "aiteachme:tauri-local-update-startup-check";

type UpdateStatus = "available" | "downloading" | "installing" | "restarting" | "failed";

function isTauriLocalRuntime(): boolean {
  return window.location.hostname === "tauri.localhost" && window.aiteachmeDesktop?.desktopFlavor === "local";
}

function describeError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return "请稍后重试，或从 GitHub Release 手动下载安装包。";
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

export function DesktopUpdatePrompt() {
  const { toast } = useToast();
  const hasStartedRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [update, setUpdate] = useState<Update | null>(null);
  const [status, setStatus] = useState<UpdateStatus>("available");
  const [errorText, setErrorText] = useState("");
  const [downloadedBytes, setDownloadedBytes] = useState(0);
  const [contentLength, setContentLength] = useState<number | null>(null);

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
      void (async () => {
        try {
          const { check } = await import("@tauri-apps/plugin-updater");
          const availableUpdate = await check({ timeout: CHECK_TIMEOUT_MS });
          if (!availableUpdate) {
            return;
          }
          setUpdate(availableUpdate);
          setStatus("available");
          setErrorText("");
          setOpen(true);
        } catch (error) {
          logSkippedStartupCheck(error);
        }
      })();
    }, CHECK_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [toast]);

  const progressPercent = useMemo(() => {
    if (!contentLength || contentLength <= 0) {
      return null;
    }
    return Math.min(100, Math.round((downloadedBytes / contentLength) * 100));
  }, [contentLength, downloadedBytes]);

  const updateDate = formatUpdateDate(update?.date);
  const isBusy = status === "downloading" || status === "installing" || status === "restarting";

  const handleClose = useCallback(() => {
    if (!isBusy) {
      setOpen(false);
    }
  }, [isBusy]);

  const handleInstall = useCallback(async () => {
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
      const message = describeError(error);
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

  if (!update) {
    return null;
  }

  return (
    <Modal open={open} onClose={handleClose} title="发现新版本" className="max-w-lg rounded-xl">
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
          <Button variant="outline" onClick={handleClose} disabled={isBusy}>
            稍后再说
          </Button>
          <Button onClick={handleInstall} disabled={isBusy}>
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
