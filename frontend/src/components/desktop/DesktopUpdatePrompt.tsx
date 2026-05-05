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

export function isTauriLocalRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.location.hostname === "tauri.localhost" && window.aiteachmeDesktop?.desktopFlavor === "local";
}

function describeUpdateError(error: unknown): string {
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

async function checkDesktopUpdate(): Promise<Update | null> {
  const { check } = await import("@tauri-apps/plugin-updater");
  return check({ timeout: CHECK_TIMEOUT_MS });
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

      setUpdate(availableUpdate);
      setStatus("available");
      setErrorText("");
      setDownloadedBytes(0);
      setContentLength(null);
      setOpen(true);

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
  }, [toast]);

  const closeUpdateDialog = useCallback(() => {
    if (!isBusy) {
      setOpen(false);
    }
  }, [isBusy]);

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
  );
}
