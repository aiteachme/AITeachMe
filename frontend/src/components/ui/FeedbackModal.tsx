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
  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [includeScreenshot, setIncludeScreenshot] = useState(true);
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
          screenshot: includeScreenshot ? screenshotDataUrl : null,
        },
      });
      setSuccessStatus(true);
      setTimeout(() => {
        setContent("");
        setScreenshotDataUrl(null);
        setIncludeScreenshot(true);
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
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setScreenshotDataUrl(event.target?.result as string);
        setIncludeScreenshot(true);
      };
      reader.readAsDataURL(file);
    }
    // reset input so same file can be selected again
    e.target.value = "";
  };

  return (
    <Modal open={open} onClose={isSubmitting ? () => {} : onClose} title="发生了什么？" className="max-w-[36rem]">
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


        <div className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <label className="relative inline-flex cursor-pointer items-center">
              <input 
                type="checkbox" 
                checked={includeScreenshot} 
                onChange={(e) => setIncludeScreenshot(e.target.checked)} 
                disabled={isSubmitting || successStatus || !screenshotDataUrl}
                className="peer sr-only" 
              />
              <div className="h-5 w-9 rounded-full bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 peer-checked:bg-blue-600 peer-checked:after:translate-x-full peer-checked:after:border-white after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:border after:border-gray-300 after:bg-white after:transition-all peer-disabled:opacity-60"></div>
            </label>
            <span className="text-sm font-medium text-slate-700">在报告中包含屏幕截图附件</span>
          </div>

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isSubmitting || successStatus}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <ImagePlus className="w-3.5 h-3.5" />
            上传截图
          </button>
          <input
            type="file"
            accept="image/*"
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {includeScreenshot && screenshotDataUrl && (
          <div className="relative mt-2 inline-block rounded-lg border border-slate-200 overflow-hidden bg-slate-50 shadow-sm">
            <img src={screenshotDataUrl} alt="Screenshot preview" className="max-h-40 object-contain block" />
            <button 
              onClick={() => {
                setScreenshotDataUrl(null);
                setIncludeScreenshot(false);
              }} 
              disabled={isSubmitting || successStatus}
              className="absolute top-1.5 right-1.5 flex h-6 w-6 items-center justify-center bg-black/60 hover:bg-black/80 rounded-full text-white transition-colors disabled:opacity-60"
            >
              <X className="w-3.5 h-3.5" />
            </button>
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
