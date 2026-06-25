import { memo, useEffect, useState, type ComponentType } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, X } from "lucide-react";
import { buildApiUrl } from "../../api/client";

/* ------------------------------------------------------------------ */
/*  Inline brand icons                                                 */
/* ------------------------------------------------------------------ */

function WeChatIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" fill="none" className={className}>
      <path
        d="M690.1 377.4c5.9 0 11.8.2 17.6.5-24.4-128.7-158.3-227.1-313.4-227.1C209 150.8 57.7 284.2 57.7 444.1c0 85.5 46.5 159.5 122.8 217.4L152.1 756l112.4-58c38.3 11.5 73.1 20.5 112.4 20.5 11.6 0 23.1-.5 34.4-1.5-7.2-24.5-11.4-50.1-11.4-76.8 0-143.9 124.1-263.8 290.2-263.8zM485.4 307.6c23.5 0 38.3 15.3 38.3 38.6 0 23.3-14.8 38.6-38.3 38.6-23.5 0-46.2-15.3-46.2-38.6 0-23.3 22.7-38.6 46.2-38.6zM281.6 384.8c-23.5 0-46.2-15.3-46.2-38.6 0-23.3 22.7-38.6 46.2-38.6 23.5 0 38.3 15.3 38.3 38.6 0 23.3-14.8 38.6-38.3 38.6z"
        fill="#07C160"
      />
      <path
        d="M946.2 641.8c0-134.7-131.1-244.5-278-244.5-155.5 0-278.1 109.8-278.1 244.5S512.7 886 668.2 886c38.3 0 76.5-11.5 114.8-23l84.9 46.2-23-69.2c61.5-49.7 101.3-114.8 101.3-198.2zM590.7 603.2c-15.4 0-30.7-15.3-30.7-30.7 0-15.3 15.3-30.7 30.7-30.7 23.5 0 38.3 15.3 38.3 30.7 0 15.4-14.8 30.7-38.3 30.7zm153.5 0c-15.3 0-30.7-15.3-30.7-30.7 0-15.3 15.3-30.7 30.7-30.7 23.5 0 38.3 15.3 38.3 30.7 0 15.4-14.8 30.7-38.3 30.7z"
        fill="#07C160"
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Community Modal                                                    */
/* ------------------------------------------------------------------ */

type QrStatus = "loading" | "ready" | "error";
type CommunityChannel = {
  id: string;
  title: string;
  qrPath: string;
  qrAlt: string;
  Icon: ComponentType<{ className?: string }>;
  iconShellClassName: string;
  loaderClassName: string;
};

// Community QR channels stay config-driven so the sidebar can keep preloading
// every active channel. When the Feishu QR is ready, add another entry here
// with its icon, title such as "飞书交流群", and QR endpoint/link.
const COMMUNITY_CHANNELS: CommunityChannel[] = [
  {
    id: "wechat",
    title: "微信交流群",
    qrPath: "/api/v1/system/community/wechat-qr",
    qrAlt: "微信群二维码",
    Icon: WeChatIcon,
    iconShellClassName: "bg-[#07C160]/10 text-[#07C160] dark:bg-[#07C160]/20",
    loaderClassName: "text-[#07C160]",
  },
];
const DEFAULT_COMMUNITY_CHANNEL = COMMUNITY_CHANNELS[0];

const QR_CACHE_BUSTER_TTL_MS = 60_000;
type CommunityQrPreloadEntry = {
  image: HTMLImageElement | null;
  src: string;
  status: QrStatus;
  cacheToken: number;
};

const communityQrPreloadCache = new Map<string, CommunityQrPreloadEntry>();

function withCacheBuster(channel: CommunityChannel, entry: CommunityQrPreloadEntry, forceRefresh = false): string {
  const now = Date.now();
  if (forceRefresh || !entry.cacheToken || now - entry.cacheToken > QR_CACHE_BUSTER_TTL_MS) {
    entry.cacheToken = now;
  }

  const src = buildApiUrl(channel.qrPath);
  return `${src}${src.includes("?") ? "&" : "?"}t=${entry.cacheToken}`;
}

function getPreloadEntry(channel: CommunityChannel): CommunityQrPreloadEntry {
  const existing = communityQrPreloadCache.get(channel.id);
  if (existing) {
    return existing;
  }
  const entry: CommunityQrPreloadEntry = {
    image: null,
    src: "",
    status: "loading",
    cacheToken: 0,
  };
  communityQrPreloadCache.set(channel.id, entry);
  return entry;
}

export function ensureCommunityQrPreloaded(): { src: string; status: QrStatus } {
  if (typeof window === "undefined") {
    return { src: "", status: "loading" };
  }

  let defaultResult: { src: string; status: QrStatus } = { src: "", status: "loading" };
  for (const channel of COMMUNITY_CHANNELS) {
    const result = ensureCommunityChannelPreloaded(channel);
    if (channel.id === DEFAULT_COMMUNITY_CHANNEL.id) {
      defaultResult = result;
    }
  }
  return defaultResult;
}

function ensureCommunityChannelPreloaded(channel: CommunityChannel): { src: string; status: QrStatus } {
  const entry = getPreloadEntry(channel);
  if (
    entry.image &&
    entry.src &&
    entry.status !== "error"
  ) {
    if (entry.image.complete && entry.image.naturalWidth > 0) {
      entry.status = "ready";
    }
    return { src: entry.src, status: entry.status };
  }

  entry.src = withCacheBuster(channel, entry, entry.status === "error");
  entry.status = "loading";
  const image = new Image();
  image.decoding = "async";
  image.loading = "eager";
  image.onload = () => {
    entry.status = "ready";
  };
  image.onerror = () => {
    entry.status = "error";
    entry.image = null;
  };
  image.src = entry.src;
  entry.image = image;
  return { src: entry.src, status: entry.status };
}

export const CommunityModal = memo(function CommunityModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [qrSrc, setQrSrc] = useState("");
  const [qrStatus, setQrStatus] = useState<QrStatus>("loading");
  const ActiveIcon = DEFAULT_COMMUNITY_CHANNEL.Icon;

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) {
      setQrStatus("loading");
      return;
    }

    let ignore = false;
    const preloaded = ensureCommunityQrPreloaded();
    setQrStatus(preloaded.status === "ready" ? "ready" : "loading");
    if (!ignore) {
      setQrSrc(preloaded.src);
    }

    return () => {
      ignore = true;
    };
  }, [isOpen]);

  return (
    <AnimatePresence>
      {isOpen ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
          <motion.div
            className="absolute inset-0 modal-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          <motion.div
            className="relative z-10 w-full max-w-[400px] overflow-hidden rounded-[28px] bg-white shadow-[0_16px_40px_rgba(15,23,42,0.12)] ring-1 ring-zinc-200/70 dark:bg-slate-900 dark:shadow-[0_16px_40px_rgba(0,0,0,0.5)] dark:ring-slate-800"
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
          >
            <button
              type="button"
              onClick={onClose}
              className="absolute right-4 top-4 z-20 flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex flex-col items-center px-8 pb-10 pt-12">
              <div className="mb-6 flex flex-col items-center">
                <div className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl ${DEFAULT_COMMUNITY_CHANNEL.iconShellClassName}`}>
                  <ActiveIcon className="h-8 w-8" />
                </div>
                <h2 className="text-xl font-bold tracking-tight text-slate-800 dark:text-slate-100">{DEFAULT_COMMUNITY_CHANNEL.title}</h2>
              </div>

              <div className="rounded-2xl border border-slate-100 p-2 dark:border-slate-800 dark:bg-slate-800/50">
                {qrStatus === "error" ? (
                  <div
                    className="flex flex-col items-center justify-center rounded-xl bg-slate-50 px-6 text-center text-sm leading-6 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                    style={{ width: 280, height: 280 }}
                  >
                    <span className="font-medium text-slate-700 dark:text-slate-200">图片加载失败</span>
                    <span className="mt-2">可通过意见反馈告知我们。</span>
                  </div>
                ) : (
                  <div
                    className="relative rounded-xl bg-slate-50 dark:bg-slate-800"
                    style={{ width: 280, height: 280 }}
                  >
                    {qrStatus === "loading" ? (
                      <div className="absolute inset-0 flex flex-col items-center justify-center px-6 text-center text-sm leading-6 text-slate-500 dark:text-slate-400">
                        <Loader2 className={`mb-3 h-6 w-6 animate-spin ${DEFAULT_COMMUNITY_CHANNEL.loaderClassName}`} />
                        <span>二维码加载中</span>
                      </div>
                    ) : null}
                    {qrSrc ? (
                      <img
                        src={qrSrc}
                        alt={DEFAULT_COMMUNITY_CHANNEL.qrAlt}
                        loading="eager"
                        decoding="async"
                        onLoad={() => setQrStatus("ready")}
                        onError={() => setQrStatus("error")}
                        className={`block rounded-xl transition-opacity ${
                          qrStatus === "loading" ? "opacity-0" : "opacity-100"
                        }`}
                        style={{ width: 280, height: 280, objectFit: "contain" }}
                      />
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
});
