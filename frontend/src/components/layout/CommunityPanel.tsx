import { memo, useEffect } from "react";
import { X } from "lucide-react";

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

const WECHAT_QR_SRC = "/wechat-qr-1.jpg";
let communityQrPreloadStarted = false;

export function ensureCommunityQrPreloaded() {
  if (typeof window === "undefined" || communityQrPreloadStarted) {
    return;
  }

  communityQrPreloadStarted = true;
  const image = new Image();
  image.decoding = "async";
  image.src = WECHAT_QR_SRC;
}

export const CommunityModal = memo(function CommunityModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    ensureCommunityQrPreloaded();
  }, []);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 modal-backdrop"
        onClick={onClose}
      />

      <div className="relative z-10 w-full max-w-[400px] overflow-hidden rounded-[28px] bg-white dark:bg-slate-900 shadow-[0_16px_40px_rgba(15,23,42,0.12)] dark:shadow-[0_16px_40px_rgba(0,0,0,0.5)] ring-1 ring-zinc-200/70 dark:ring-slate-800">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 z-20 flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:text-slate-500 dark:hover:text-slate-300"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex flex-col items-center px-8 pb-10 pt-12">
          <div className="mb-6 flex flex-col items-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#07C160]/10 dark:bg-[#07C160]/20 text-[#07C160]">
              <WeChatIcon className="h-8 w-8" />
            </div>
            <h2 className="text-xl font-bold tracking-tight text-slate-800 dark:text-slate-100">微信交流群</h2>
            <p className="mt-2 text-[15px] text-slate-500 dark:text-slate-400">扫码加入交流群</p>
          </div>

          <div className="rounded-2xl border border-slate-100 dark:border-slate-800 dark:bg-slate-800/50 p-2">
            <img
              src={WECHAT_QR_SRC}
              alt="微信群二维码"
              loading="eager"
              decoding="async"
              className="block rounded-xl"
              style={{ width: 280, height: 280, objectFit: "contain" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
});
