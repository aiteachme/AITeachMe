import { useRef, useState } from "react";
import { ImagePlus, Loader2, X } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import { Modal } from "./Modal";

interface FeedbackModalProps {
  open: boolean;
  onClose: () => void;
}

export function FeedbackModal({ open, onClose }: FeedbackModalProps) {
  const [content, setContent] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [imagesDataUrls, setImagesDataUrls] = useState<string[]>([]);
  const [errorStatus, setErrorStatus] = useState<string | null>(null);
  const [successStatus, setSuccessStatus] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async () => {
    if (!content.trim()) return;
    setIsSubmitting(true);
    setErrorStatus(null);
    setSuccessStatus(false);

    try {
      await apiClient({
        url: "/api/v1/system/feedback",
        method: "POST",
        data: {
          content,
          images: imagesDataUrls,
        },
      });
      setSuccessStatus(true);
      window.setTimeout(() => {
        setContent("");
        setImagesDataUrls([]);
        setSuccessStatus(false);
        onClose();
      }, 1500);
    } catch (error) {
      setErrorStatus(getApiErrorMessage(error, "反馈发送失败，请稍后重试"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;

    Promise.all(
      files.map(
        (file) =>
          new Promise<string>((resolve) => {
            const reader = new FileReader();
            reader.onload = (loadEvent) => resolve(loadEvent.target?.result as string);
            reader.readAsDataURL(file);
          }),
      ),
    ).then((newB64s) => {
      setImagesDataUrls((prev) => [...prev, ...newB64s]);
      setErrorStatus(null);
    });

    event.target.value = "";
  };

  return (
    <Modal
      open={open}
      onClose={isSubmitting ? () => {} : onClose}
      title="意见反馈"
      className="max-w-[36rem]"
    >
      <div className="space-y-4">
        {successStatus ? (
          <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
            反馈发送成功，感谢你的宝贵意见。
          </div>
        ) : null}

        {errorStatus ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {errorStatus}
          </div>
        ) : null}

        <div className="relative">
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={isSubmitting || successStatus}
            placeholder="请在这里描述你的问题或建议..."
            className="min-h-[160px] w-full resize-none rounded-xl border border-slate-300 bg-white p-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:ring-slate-800"
            maxLength={2000}
          />
          <div className="pointer-events-none absolute bottom-3 right-3 text-xs text-slate-400 dark:text-slate-500">
            已输入 {content.length} / 2000
          </div>
        </div>

        <div className="flex">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isSubmitting || successStatus}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          >
            <ImagePlus className="h-3.5 w-3.5" />
            添加图片
          </button>
          <input
            type="file"
            accept="image/*"
            multiple
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {imagesDataUrls.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {imagesDataUrls.map((url, index) => (
              <div
                key={`${url}-${index}`}
                className="relative inline-block overflow-hidden rounded-lg border border-slate-200 bg-slate-50 shadow-sm dark:border-slate-700 dark:bg-slate-900"
              >
                <img src={url} alt={`Screenshot preview ${index + 1}`} className="block h-20 object-contain" />
                <button
                  type="button"
                  onClick={() => {
                    setImagesDataUrls((prev) => prev.filter((_, idx) => idx !== index));
                  }}
                  disabled={isSubmitting || successStatus}
                  className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white transition-colors hover:bg-black/80 disabled:opacity-60"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex justify-end pt-3">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!content.trim() || isSubmitting || successStatus}
            className="rounded-full bg-slate-900 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            {isSubmitting ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                发送中
              </span>
            ) : (
              "发送"
            )}
          </button>
        </div>
      </div>
    </Modal>
  );
}
