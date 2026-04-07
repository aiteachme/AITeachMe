import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileCode,
  FileImage,
  FileText,
  FileType,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";

import { apiClient } from "../api/client";
import type { ApiResponse } from "../api/types";
import { KnowledgeBuildResolutionModal } from "../components/pages/KnowledgeBuildResolutionModal";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { useKnowledgeBuildFlow } from "../hooks/useKnowledgeBuildFlow";
import { useSettings } from "../hooks/useSettings";
import { fetchKnowledgeDocState, buildKnowledgeDocStateQueryKey } from "../lib/knowledgeDocs";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";
import { useToast } from "../components/ui/Toast";

/* ═══ Types ═══ */

interface OutlineChapter {
  title: string;
  sections: string[];
  source?: "file" | "ai";
}

interface OutlineData {
  title: string;
  description: string;
  chapters: OutlineChapter[];
  estimatedMinutes?: number;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  outline?: OutlineData;
  isThinking?: boolean;
}

type PagePhase = "idle" | "planning" | "reviewing" | "building" | "done";

/* ═══ Constants ═══ */

const ACCEPT = ".pdf,.docx,.doc,.ppt,.pptx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp";
const ACTIVE_STATUSES = new Set(["pending", "processing", "running"]);
let _msgId = 0;
const msgId = () => `m_${Date.now()}_${++_msgId}`;

/* ═══ API Helpers ═══ */

async function fetchFiles(subject: string): Promise<FilesData> {
  const r = await apiClient<ApiResponse<FilesData>>({ method: "GET", url: `/api/v1/subjects/${subject}/files` });
  return r.data ?? { subject, total: 0, ready_count: 0, processing_count: 0, failed_count: 0, items: [] };
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await apiClient<ApiResponse<FilesUploadData>>({ method: "POST", url: `/api/v1/subjects/${subject}/files/upload`, data: fd });
  return r.data ?? { subject, filenames: [], uploaded_items: [], started_parse_count: 0 };
}

async function deleteFile(subject: string, uid: string): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_uids: string[] }>>({ method: "POST", url: `/api/v1/subjects/${subject}/files/delete`, data: { file_uid: uid } });
}

/* ═══ Utilities ═══ */

function fileMeta(f: FileRecord) {
  if (f.markdown_ready) return { label: "就绪", dot: "bg-emerald-500", text: "text-emerald-600" };
  if (f.status === "failed") return { label: "失败", dot: "bg-red-500", text: "text-red-500" };
  if (ACTIVE_STATUSES.has(f.status) || f.ingest_status !== "pending") {
    const m: Record<string, string> = { classifying: "分类中", fast_parsing: "解析中", fast_parsed: "已解析", enhancing: "优化中", ready_for_digest: "就绪" };
    return { label: m[f.ingest_status] ?? "处理中", dot: "bg-sky-500 animate-pulse", text: "text-sky-600" };
  }
  return { label: "等待中", dot: "bg-amber-500 animate-pulse", text: "text-amber-600" };
}

function fileIcon(f: FileRecord) {
  const e = f.filetype?.toLowerCase();
  if (e === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(e ?? "")) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(e ?? "")) return <FileCode className="h-3.5 w-3.5 text-violet-400" />;
  if (["docx", "doc"].includes(e ?? "")) return <FileText className="h-3.5 w-3.5 text-blue-400" />;
  if (["ppt", "pptx"].includes(e ?? "")) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileText className="h-3.5 w-3.5 text-zinc-400" />;
}

function mockOutline(prompt: string, fc: number): OutlineData {
  const p = prompt.toLowerCase();
  if (p.includes("高等数学") || p.includes("高数") || p.includes("微积分")) {
    return {
      title: "高等数学 · 完整学习文档", description: `基于 ${fc} 份上传资料与 AI 知识框架定制`,
      chapters: [
        { title: "第一章 · 函数与极限", sections: ["函数概念", "数列极限", "函数极限", "极限运算", "连续性"], source: "file" },
        { title: "第二章 · 导数与微分", sections: ["导数定义", "求导公式", "链式法则", "高阶导数", "微分"], source: "file" },
        { title: "第三章 · 中值定理与导数应用", sections: ["罗尔定理", "拉格朗日", "洛必达", "极值"], source: "file" },
        { title: "第四章 · 不定积分", sections: ["原函数", "换元法", "分部积分"], source: "ai" },
        { title: "第五章 · 定积分及其应用", sections: ["定义与性质", "微积分基本定理", "应用"], source: "ai" },
      ],
      estimatedMinutes: 4,
    };
  }
  return {
    title: "学习文档方案", description: `基于 ${fc} 份资料与 AI 知识补充定制`,
    chapters: [
      { title: "第一章 · 基础概念", sections: ["核心定义", "基本原理", "关键术语"], source: "file" },
      { title: "第二章 · 核心理论", sections: ["理论框架", "重要公式", "理论应用"], source: "file" },
      { title: "第三章 · 方法与技巧", sections: ["解题方法", "常见题型", "易错点"], source: "ai" },
      { title: "第四章 · 综合应用", sections: ["跨章节综合", "典型例题", "拓展内容"], source: "ai" },
    ],
    estimatedMinutes: 3,
  };
}

/* ═══ Sub-Components ═══ */

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-2">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-2 w-2 rounded-full bg-zinc-400"
          animate={{ opacity: [0.3, 1, 0.3], scale: [0.85, 1, 0.85] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }} />
      ))}
    </div>
  );
}

/* ── File Chip (compact, for grid below input) ── */

function FileChip({ file, onDelete, isDeleting }: { file: FileRecord; onDelete: () => void; isDeleting: boolean }) {
  const meta = fileMeta(file);
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9, width: 0 }}
      className="group relative flex items-center gap-1.5 rounded-lg border border-zinc-200/80 bg-white px-2.5 py-2 transition-all hover:border-zinc-300 hover:shadow-sm min-w-0"
    >
      <div className="shrink-0">{fileIcon(file)}</div>
      <span className="truncate text-[12px] font-medium text-zinc-700 max-w-[100px]">{file.filename}</span>
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", meta.dot)} title={meta.label} />
      <button type="button" onClick={onDelete} disabled={isDeleting}
        className="absolute -right-1.5 -top-1.5 hidden h-4 w-4 items-center justify-center rounded-full bg-zinc-600 text-white shadow-sm group-hover:flex hover:bg-red-500 transition-colors">
        <X className="h-2.5 w-2.5" />
      </button>
    </motion.div>
  );
}

/* ── Files Tray (collapsible, below input) ── */

function FilesTray({
  files, isOpen, onToggle, onUpload, onDelete, isUploading, isDeletingFile,
}: {
  files: FileRecord[]; isOpen: boolean; onToggle: () => void;
  onUpload: (f: File[]) => void; onDelete: (uid: string) => void;
  isUploading: boolean; isDeletingFile: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const readyCount = files.filter((f) => f.markdown_ready).length;

  return (
    <div className="mx-auto w-full max-w-3xl">
      {/* Toggle bar */}
      <button type="button" onClick={onToggle}
        className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left transition-colors hover:bg-zinc-100/60">
        <Paperclip className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-[12px] font-medium text-zinc-500">
          {files.length > 0 ? `${files.length} 份文件` : "学习资料"}
          {readyCount > 0 && ` · ${readyCount} 已就绪`}
        </span>
        <ChevronDown className={cn("ml-auto h-3.5 w-3.5 text-zinc-400 transition-transform", isOpen && "rotate-180")} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 pt-1">
              {/* Upload button + file grid */}
              <div className="flex flex-wrap gap-2">
                {/* Add file button */}
                <input type="file" ref={inputRef} multiple accept={ACCEPT} className="hidden"
                  onChange={(e: ChangeEvent<HTMLInputElement>) => {
                    const f = Array.from(e.target.files ?? []); e.target.value = "";
                    if (f.length > 0) onUpload(f);
                  }} />
                <button type="button" onClick={() => inputRef.current?.click()} disabled={isUploading}
                  className="flex items-center gap-1.5 rounded-lg border border-dashed border-zinc-300 bg-zinc-50/50 px-3 py-2 text-[12px] font-medium text-zinc-500 transition-all hover:border-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-50">
                  {isUploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                  {isUploading ? "上传中…" : "添加文件"}
                </button>

                {/* File chips — 5 per row via grid */}
                <AnimatePresence>
                  {files.map((f) => (
                    <FileChip key={f.uid} file={f} onDelete={() => onDelete(f.uid)} isDeleting={isDeletingFile} />
                  ))}
                </AnimatePresence>
              </div>

              {files.length === 0 && (
                <p className="mt-2 text-center text-[11px] text-zinc-400">
                  支持 PDF · DOCX · PPT · Markdown · 图片 — 也可直接拖拽到页面任意位置上传
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Outline Card ── */

function OutlineCard({ outline, onConfirm, onModify, isBuilding }: {
  outline: OutlineData; onConfirm: () => void; onModify: () => void; isBuilding: boolean;
}) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const toggle = (i: number) => setExpanded((p) => ({ ...p, [i]: !p[i] }));

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="mt-3 overflow-hidden rounded-2xl border border-zinc-200 bg-gradient-to-b from-white to-zinc-50/50 shadow-sm">
      <div className="border-b border-zinc-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-sm">
            <BookOpen className="h-4 w-4 text-white" />
          </div>
          <div>
            <h3 className="text-[15px] font-semibold text-zinc-900">{outline.title}</h3>
            <p className="text-xs text-zinc-500">{outline.description}</p>
          </div>
        </div>
      </div>
      <div className="divide-y divide-zinc-100">
        {outline.chapters.map((ch, i) => (
          <div key={i} className="px-5 py-3">
            <button type="button" onClick={() => toggle(i)} className="flex w-full items-center gap-2 text-left">
              <ChevronRight className={cn("h-3.5 w-3.5 text-zinc-400 transition-transform", expanded[i] && "rotate-90")} />
              <span className="flex-1 text-[13px] font-medium text-zinc-800">{ch.title}</span>
              {ch.source === "ai" && <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-600">AI 补充</span>}
            </button>
            <AnimatePresence>
              {expanded[i] && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                  <div className="mt-2 ml-5 flex flex-wrap gap-1.5">
                    {ch.sections.map((s, j) => <span key={j} className="rounded-md bg-zinc-100 px-2 py-1 text-[11px] text-zinc-600">{s}</span>)}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ))}
      </div>
      <div className="border-t border-zinc-100 px-5 py-3">
        <div className="flex items-center gap-3 text-xs text-zinc-400">
          <span>{outline.chapters.length} 章</span><span>·</span>
          <span>约 {outline.chapters.reduce((a, c) => a + c.sections.length, 0)} 个知识点</span>
          {outline.estimatedMinutes && <><span>·</span><span>预计 {outline.estimatedMinutes} 分钟</span></>}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={onConfirm} disabled={isBuilding}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-zinc-800 disabled:opacity-50">
            {isBuilding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {isBuilding ? "构建中…" : "开始构建"}
          </button>
          <button type="button" onClick={onModify} disabled={isBuilding}
            className="flex items-center gap-1.5 rounded-xl border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-600 transition-all hover:bg-zinc-50 disabled:opacity-50">
            <RefreshCw className="h-3.5 w-3.5" /> 修改方案
          </button>
        </div>
      </div>
    </motion.div>
  );
}

/* ── Message Bubble ── */

function MessageBubble({ message, onConfirm, onModify, isBuilding }: {
  message: ChatMessage; onConfirm: () => void; onModify: () => void; isBuilding: boolean;
}) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-center py-2">
        <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-500">{message.content}</span>
      </motion.div>
    );
  }

  if (message.isThinking) {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 py-2">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 shadow-sm">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
        <div className="rounded-2xl rounded-tl-md bg-white border border-zinc-100 px-4 py-3 shadow-sm">
          <p className="text-xs text-zinc-500 mb-1">正在分析资料，制定学习方案…</p>
          <ThinkingDots />
        </div>
      </motion.div>
    );
  }

  if (isUser) {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end py-2">
        <div className="max-w-[80%] rounded-2xl rounded-tr-md bg-zinc-900 px-4 py-3 text-[14px] leading-relaxed text-white shadow-sm">
          {message.content}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 py-2">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 shadow-sm">
        <Sparkles className="h-4 w-4 text-white" />
      </div>
      <div className="max-w-[85%] space-y-1">
        <div className="rounded-2xl rounded-tl-md bg-white border border-zinc-100 px-4 py-3 text-[14px] leading-relaxed text-zinc-700 shadow-sm whitespace-pre-line">
          {message.content}
        </div>
        {message.outline && (
          <OutlineCard outline={message.outline} onConfirm={onConfirm} onModify={onModify} isBuilding={isBuilding} />
        )}
      </div>
    </motion.div>
  );
}

/* ═══ Main Component ═══ */

export function FilesPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  useSettings();
  const { toast } = useToast();
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const navState = location.state as { initialFiles?: File[]; initialPrompt?: string } | null;

  // ── State ──
  const [filesTrayOpen, setFilesTrayOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([{
    id: "welcome", role: "assistant", timestamp: new Date(),
    content: "👋 你好！我是你的学习助手。\n\n上传你的学习资料，然后告诉我你的学习目标。我会为你分析资料内容，制定一份专属的学习文档方案。\n\n你可以这样描述：\n• \"我要准备高等数学期末考试\"\n• \"帮我整理线性代数的核心知识点\"\n• \"我需要一份完整的概率论复习文档\"",
  }]);
  const [inputValue, setInputValue] = useState(navState?.initialPrompt ?? "");
  const [phase, setPhase] = useState<PagePhase>("idle");
  const [currentOutline, setCurrentOutline] = useState<OutlineData | null>(null);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);

  // ── Queries ──
  const { data: filesData, isLoading: _filesLoading } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((f) => !f.markdown_ready && f.status !== "failed") ? 1500 : false;
    },
  });

  const { data: knowledgeDocState } = useQuery({
    queryKey: buildKnowledgeDocStateQueryKey(subjectId),
    queryFn: () => fetchKnowledgeDocState(subjectId),
    enabled: Boolean(subjectId),
    retry: false,
  });

  const files = filesData?.items ?? [];
  const readyFiles = useMemo(() => files.filter((f) => f.markdown_ready), [files]);

  // ── Mutations ──
  const uploadMut = useMutation({
    mutationFn: (selected: File[]) => uploadFiles(subjectId, selected),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
      if (data.filenames.length > 0) {
        const names = data.filenames.length <= 2 ? data.filenames.join("、") : `${data.filenames[0]} 等 ${data.filenames.length} 个文件`;
        setMessages((prev) => [...prev, { id: msgId(), role: "system", content: `📎 已上传 ${names}`, timestamp: new Date() }]);
        setFilesTrayOpen(true);
      }
    },
  });

  const deleteMut = useMutation({
    mutationFn: (uid: string) => deleteFile(subjectId, uid),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  // ── Build Flow ──
  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId,
    buildType: "docs",
    buildRequest: () => ({
      prompt: messages.filter((m) => m.role === "user").map((m) => m.content).join("\n") || undefined,
    }),
    fallbackErrorMessage: "知识文档构建失败",
    onSuccess: (data) => {
      const rawData = data as unknown as Record<string, unknown>;
      const vectorStatus = rawData?.vector_status as { notice?: string } | undefined;
      if (vectorStatus?.notice)
        toast({ title: "向量索引已更新", description: vectorStatus.notice, variant: "info", duration: 6000 });
      setPhase("done");
      setMessages((prev) => [...prev, { id: msgId(), role: "assistant", timestamp: new Date(), content: "✅ 知识文档构建完成！正在跳转到文档页面…" }]);
      setTimeout(() => navigate(`/subject/${subjectId}/knowledge-docs?requested_at=${encodeURIComponent(data.requested_at)}`), 1500);
    },
  });

  // ── Auto-upload from HomePage ──
  useEffect(() => {
    if (navState?.initialFiles?.length && !hasAutoUploaded && subjectId) {
      setHasAutoUploaded(true);
      void uploadMut.mutateAsync(navState.initialFiles);
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [hasAutoUploaded, location.pathname, navigate, navState, subjectId, uploadMut]);

  // ── Notify when all files ready ──
  const prevReadyRef = useRef(0);
  useEffect(() => {
    if (readyFiles.length > 0 && readyFiles.length > prevReadyRef.current && readyFiles.length === files.length && files.length > 0) {
      setMessages((prev) => {
        if (prev.some((m) => m.id === "all_ready")) return prev;
        return [...prev, { id: "all_ready", role: "system", timestamp: new Date(), content: `✅ 所有 ${files.length} 份文件已解析完毕，可以开始规划学习方案` }];
      });
    }
    prevReadyRef.current = readyFiles.length;
  }, [readyFiles.length, files.length]);

  // ── Auto-open tray when files exist ──
  useEffect(() => {
    if (files.length > 0 && !filesTrayOpen) setFilesTrayOpen(true);
  }, [files.length, filesTrayOpen]);

  // ── Auto scroll ──
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, phase]);

  // ── Send ──
  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text || phase === "planning" || phase === "building") return;

    setMessages((prev) => [...prev, { id: msgId(), role: "user", content: text, timestamp: new Date() }]);
    setInputValue("");

    if (phase === "reviewing") {
      setPhase("planning");
      setMessages((prev) => [...prev, { id: msgId(), role: "assistant", content: "", timestamp: new Date(), isThinking: true }]);
      setTimeout(() => {
        const outline = mockOutline(text, files.length);
        setCurrentOutline(outline);
        setMessages((prev) => [
          ...prev.filter((m) => !m.isThinking),
          { id: msgId(), role: "assistant", content: "好的，我已根据你的修改意见重新调整了方案：", timestamp: new Date(), outline },
        ]);
        setPhase("reviewing");
      }, 2000);
      return;
    }

    setPhase("planning");
    setMessages((prev) => [...prev, { id: msgId(), role: "assistant", content: "", timestamp: new Date(), isThinking: true }]);
    setTimeout(() => {
      const outline = mockOutline(text, files.length);
      setCurrentOutline(outline);
      setMessages((prev) => [
        ...prev.filter((m) => !m.isThinking),
        { id: msgId(), role: "assistant", timestamp: new Date(),
          content: `好的！我已经分析了你上传的 ${files.length} 份资料。根据内容和你的学习目标，我为你制定了以下学习文档方案：`,
          outline },
      ]);
      setPhase("reviewing");
    }, 2500);
  }, [inputValue, phase, files.length]);

  const handleConfirmBuild = useCallback(() => {
    if (!currentOutline) return;
    setPhase("building");
    setMessages((prev) => [...prev, { id: msgId(), role: "system", timestamp: new Date(), content: "🚀 学习方案已确认，正在开始构建知识文档…" }]);
    knowledgeBuild.submitBuild();
  }, [currentOutline, knowledgeBuild]);

  const handleModifyPlan = useCallback(() => {
    setMessages((prev) => [...prev, {
      id: msgId(), role: "assistant", timestamp: new Date(),
      content: "好的，请告诉我你想怎么调整方案。例如：\n• 增加或删除某个章节\n• 调整章节顺序\n• 更偏向考前速成 / 系统梳理\n• 增加更多关于某个主题的内容",
    }]);
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  /* ═══ Render ═══ */

  return (
    <>
      <FullPageDropOverlay onDrop={(f) => void uploadMut.mutateAsync(f)} disabled={uploadMut.isPending} />

      <div className="flex h-full w-full flex-col bg-zinc-50 relative">
        {/* Grid bg */}
        <div className="pointer-events-none absolute inset-0 z-0">
          <div className="h-full w-full bg-[linear-gradient(to_right,#e4e4e7_1px,transparent_1px),linear-gradient(to_bottom,#e4e4e7_1px,transparent_1px)] bg-[size:28px_28px] [mask-image:radial-gradient(ellipse_100%_80%_at_50%_0%,#000_40%,transparent_100%)] opacity-40" />
        </div>

        {/* Header badge */}
        <div className="relative z-10 flex items-center justify-center pt-6 pb-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/80 bg-white/80 backdrop-blur-sm px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-zinc-500 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Sparkles className="h-3 w-3" /> Deep Research
          </div>
        </div>

        {/* Messages */}
        <div className="relative z-10 flex-1 overflow-y-auto px-4 md:px-8 lg:px-16 pb-4 toc-scroll">
          <div className="mx-auto max-w-3xl space-y-1">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} onConfirm={handleConfirmBuild} onModify={handleModifyPlan}
                isBuilding={phase === "building" || knowledgeBuild.isPending} />
            ))}

            {/* Build progress */}
            {phase === "building" && (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 py-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 shadow-sm">
                  <Sparkles className="h-4 w-4 text-white" />
                </div>
                <div className="rounded-2xl rounded-tl-md bg-white border border-zinc-100 px-5 py-4 shadow-sm space-y-2.5">
                  <p className="text-sm font-medium text-zinc-800">正在构建知识文档…</p>
                  {[
                    { label: "加载文件资料", done: true },
                    { label: "教研大纲规划", done: true },
                    { label: "靶向素材搜刮", active: true },
                    { label: "教学化内容写作", pending: true },
                    { label: "富媒体增强", pending: true },
                    { label: "发布知识文档", pending: true },
                  ].map((step, i) => (
                    <div key={i} className="flex items-center gap-2 text-[13px]">
                      {step.done ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                        : step.active ? <Loader2 className="h-4 w-4 animate-spin text-sky-500" />
                        : <div className="h-4 w-4 rounded-full border-2 border-zinc-200" />}
                      <span className={cn(step.done ? "text-zinc-600" : step.active ? "text-sky-700 font-medium" : "text-zinc-400")}>
                        {step.label}
                      </span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {knowledgeBuild.errorMessage && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3 py-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-100">
                  <AlertCircle className="h-4 w-4 text-red-500" />
                </div>
                <div className="rounded-2xl rounded-tl-md bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-700">
                  {knowledgeBuild.errorMessage}
                </div>
              </motion.div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Vector notice */}
        <div className="relative z-10 px-4 md:px-8 lg:px-16">
          <div className="mx-auto max-w-3xl">
            <SubjectVectorNotice status={knowledgeBuild.latestVectorStatus ?? knowledgeDocState?.vector_status} />
          </div>
        </div>

        {/* Bottom area: Input + Files Tray */}
        <div className="relative z-10 border-t border-zinc-200/60 bg-white/70 backdrop-blur-sm px-4 md:px-8 lg:px-16 pt-3 pb-4">
          {/* Input */}
          <div className="mx-auto max-w-3xl">
            <div className="flex items-end gap-2 rounded-2xl border border-zinc-200 bg-white px-4 py-3 shadow-sm transition-all focus-within:border-zinc-300 focus-within:shadow-md">
              <textarea ref={inputRef} value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={phase === "building"}
                placeholder={phase === "reviewing" ? "描述你想如何修改方案…"
                  : files.length === 0 ? "上传学习资料后，描述你的学习目标…"
                  : "描述你的学习目标，例如：我要准备高数期末考试…"}
                rows={1}
                className="flex-1 resize-none border-0 bg-transparent text-[14px] leading-relaxed text-zinc-800 placeholder:text-zinc-400 focus:outline-none disabled:opacity-50"
                style={{ minHeight: "24px", maxHeight: "120px" }}
                onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, 120)}px`; }}
              />
              <button type="button" onClick={handleSend}
                disabled={!inputValue.trim() || phase === "planning" || phase === "building"}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-zinc-900 text-white transition-all hover:bg-zinc-800 disabled:bg-zinc-200 disabled:text-zinc-400">
                <ArrowUp className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Files Tray (collapsible below input) */}
          <div className="mt-2">
            <FilesTray
              files={files} isOpen={filesTrayOpen}
              onToggle={() => setFilesTrayOpen((v) => !v)}
              onUpload={(f) => void uploadMut.mutateAsync(f)}
              onDelete={(uid) => deleteMut.mutate(uid)}
              isUploading={uploadMut.isPending}
              isDeletingFile={deleteMut.isPending}
            />
          </div>

          <p className="mt-1 text-center text-[11px] text-zinc-400">
            AI 会基于你的资料和目标制定学习方案 · 方案确认后开始构建知识文档
          </p>
        </div>
      </div>

      <KnowledgeBuildResolutionModal
        open={knowledgeBuild.precheckConflict !== null}
        conflict={knowledgeBuild.precheckConflict}
        isSubmitting={knowledgeBuild.isPending}
        onClose={knowledgeBuild.closePrecheckConflict}
        onResolve={knowledgeBuild.resolvePrecheckConflict}
      />
    </>
  );
}
