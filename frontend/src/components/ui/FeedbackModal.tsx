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
      setTimeout(() => {
        setContent("");
        setImagesDataUrls([]);
        setSuccessStatus(false);
        onClose();
      }, 1500);
    } catch (e) {
      setErrorStatus(getApiErrorMessage(e, "反馈发送失败，请稍后重试"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    Promise.all(
      files.map((file) => {
        return new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onload = (event) => resolve(event.target?.result as string);
          reader.readAsDataURL(file);
        });
      })
    ).then((newB64s) => {
      setImagesDataUrls((prev) => [...prev, ...newB64s]);
      setErrorStatus(null);
    });
    // reset input so same file can be selected again
    e.target.value = "";
  };

  return (
    <Modal open={open} onClose={isSubmitting ? () => {} : onClose} title="意见反馈" className="max-w-[36rem]">
      <div className="space-y-4">
        {successStatus && (
          <div className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            反馈发送成功！感谢你的宝贵意见。
          </div>
        )}
        
        {errorStatus && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {errorStatus}
          </div>
        )}

        <div className="relative">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={isSubmitting || successStatus}
            placeholder="请在此描述你的问题或建议..."
            className="w-full min-h-[160px] resize-none rounded-xl border border-slate-300 p-4 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:opacity-60"
            maxLength={2000}
          />
          <div className="absolute right-3 bottom-3 text-xs text-slate-400 pointer-events-none">
            已使用 {content.length} 个字符，共 2000 个
          </div>
        </div>


        <div className="flex">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isSubmitting || successStatus}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <ImagePlus className="w-3.5 h-3.5" />
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

        {imagesDataUrls.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {imagesDataUrls.map((url, i) => (
              <div key={i} className="relative inline-block rounded-lg border border-slate-200 overflow-hidden bg-slate-50 shadow-sm">
                <img src={url} alt={`Screenshot preview ${i}`} className="h-20 object-contain block" />
                <button 
                  onClick={() => {
                    // 移除选中的图片
                    setImagesDataUrls(prev => prev.filter((_, idx) => idx !== i));
                  }} 
                  disabled={isSubmitting || successStatus}
                  className="absolute top-1 right-1 flex h-5 w-5 items-center justify-center bg-black/60 hover:bg-black/80 rounded-full text-white transition-colors disabled:opacity-60"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end pt-3">
          <button
            onClick={handleSubmit}
            disabled={!content.trim() || isSubmitting || successStatus}
            className="rounded-full bg-slate-900 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                发送中
              </span>
            ) : "发送"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
