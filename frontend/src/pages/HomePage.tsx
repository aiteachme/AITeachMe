import { useState, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  Clock,
  Loader2,
  MessageSquare,
  FileText,
  Paperclip,
  X,
  FileUp
} from "lucide-react";

import { listSubjectsApiApiV1SubjectsListPost, createSubjectApiApiV1SubjectsAddPost } from "../api/generated/subjects";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { getApiErrorMessage } from "../api/client";
import { cn } from "../lib/utils";

// --- Form State ---
interface FormState {
  requirement: string;
}

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>({ requirement: "" });
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listSubjectsApiApiV1SubjectsListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
  });

  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      const created = unwrapOrvalResponse(
        await createSubjectApiApiV1SubjectsAddPost({
          name,
          description: "", // Send empty description
        })
      );
      if (!created) throw new Error("创建学科失败");
      return created;
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setError(null);
      // Pass the uploaded files to the files workspace for parsing and review.
      navigate(`/subject/${created.subject_id}/files`, {
        state: { 
          initialFiles: selectedFiles,
          initialPrompt: form.requirement 
        }
      });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "创建失败，请重试"));
    },
  });

  const canGenerate = !!form.requirement.trim() || selectedFiles.length > 0;

  const handleGenerate = () => {
    if (!canGenerate) return;
    setError(null);
    let name = form.requirement.trim();
    if (!name && selectedFiles.length > 0) {
      name = selectedFiles[0].name.replace(/\.[^/.]+$/, "") || "新建学科";
    }
    createMutation.mutate(name);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  const updateForm = (val: string) => {
    setForm({ requirement: val });
  };


  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFiles(prev => [...prev, ...Array.from(e.target.files as FileList)]);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };


  return (
    <div className="min-h-[100dvh] w-full flex flex-col items-center p-4 pt-16 md:p-8 md:pt-24 overflow-x-hidden relative">
      
      {/* ═══ Background Decor ═══ */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[10%] -left-[10%] h-[500px] w-[500px] animate-pulse rounded-full bg-blue-500/10 blur-3xl" style={{ animationDuration: "7s" }} />
        <div className="absolute bottom-0 -right-[5%] h-[600px] w-[600px] animate-pulse rounded-full bg-slate-800/5 blur-3xl" style={{ animationDuration: "11s" }} />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className={cn(
          "relative z-20 w-full max-w-[800px] flex flex-col items-center",
          subjects.length === 0 ? "justify-center min-h-[calc(100dvh-12rem)]" : "mt-[5vh]"
        )}
      >
        {/* ── Logo & Title ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, type: "spring", stiffness: 200, damping: 20 }}
          className="flex items-center justify-center gap-3 mb-4"
        >
          <div className="bg-slate-900 text-white p-2 rounded-xl shadow-lg">
            <BookOpen className="w-8 h-8" />
          </div>
          <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">AI 赛博私教</h1>
        </motion.div>

        {/* ── Slogan ── */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25 }}
          className="text-base md:text-lg text-slate-500 mb-8 font-medium tracking-wide text-center px-4"
        >
          把任何令人头疼的学习资料，变成你的 24 小时专属“赛博私教”。
        </motion.p>

        {/* ── Unified Input Area ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.35 }}
          className="w-full"
        >
          <div className="w-full rounded-2xl border border-slate-200 bg-white shadow-sm transition-all focus-within:ring-4 focus-within:ring-slate-900/5 focus-within:border-slate-300 focus-within:shadow-md">
            {/* Greeting Bar equivalent (optional) */}
            <div className="relative z-20 flex items-start justify-between px-4 pt-4">
              <span className="text-sm font-semibold text-slate-700">你好，学习者 👋</span>
            </div>

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              placeholder="你想学什么？输入学科名称，例如：高等数学、Python 核心编程..."
              className="w-full resize-none border-0 bg-transparent px-4 pt-3 pb-2 text-[15px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none min-h-[120px] max-h-[250px]"
              value={form.requirement}
              onChange={(e) => updateForm(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={3}
              disabled={createMutation.isPending}
            />

            <div className="px-3 pb-3 flex flex-col gap-2">
              {/* File Attachment Area */}
              {selectedFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 px-1 py-2 border-t border-slate-100">
                  {selectedFiles.map((file, idx) => (
                    <div key={idx} className="flex items-center gap-1 bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700 text-xs px-2.5 py-1.5 rounded-lg transition-colors group">
                      <FileUp className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-700" />
                      <span className="max-w-[140px] truncate font-medium">{file.name}</span>
                      <button 
                        onClick={() => removeFile(idx)}
                        title="移除文件"
                        className="ml-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-full p-0.5"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-end justify-between px-1">
                <div className="flex items-center gap-2 flex-1">
                  <input 
                    type="file" 
                    title="选择要上传的文件资料"
                    multiple 
                    className="hidden" 
                    ref={fileInputRef} 
                    onChange={handleFileChange}
                    accept=".pdf,.docx,.doc,.md,.markdown,.txt,.png,.jpg,.jpeg"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition-colors"
                  >
                    <Paperclip className="w-4 h-4" />
                    上传文件资料
                  </button>
                  {createMutation.isPending && (
                    <span className="text-xs text-slate-500 font-medium flex items-center ml-2">
                      <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> 正在准备学习空间...
                    </span>
                  )}
                </div>

                {/* Send button */}
                <button
                  onClick={handleGenerate}
                  disabled={!canGenerate || createMutation.isPending}
                  className={cn(
                    "shrink-0 h-10 rounded-xl flex items-center justify-center gap-1.5 transition-all px-5",
                    canGenerate && !createMutation.isPending
                      ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md cursor-pointer transform hover:-translate-y-0.5 active:translate-y-0"
                      : "bg-slate-100 text-slate-400 cursor-not-allowed"
                  )}
                >
                  <span className="text-sm font-bold">开始学习</span>
                  <ArrowUp className="w-4 h-4 ml-0.5" />
                </button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* ── Error ── */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 w-full p-4 bg-red-50 border border-red-100 rounded-xl"
            >
              <p className="text-sm text-red-600 font-medium text-center">{error}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ═══ Recent Classrooms ═══ */}
      {subjects.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="relative z-10 mt-12 w-full max-w-5xl flex flex-col items-center"
        >
          {/* Trigger */}
          <button
            onClick={() => setRecentOpen(!recentOpen)}
            className="group w-full flex items-center gap-4 py-3 cursor-pointer"
          >
            <div className="flex-1 h-[1px] bg-slate-200 group-hover:bg-slate-300 transition-colors" />
            <span className="shrink-0 flex items-center gap-2 text-sm font-medium text-slate-500 group-hover:text-slate-800 transition-colors select-none">
              <Clock className="w-4 h-4" />
              最近的学习空间
              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">{subjects.length}</span>
              <motion.div
                animate={{ rotate: recentOpen ? 180 : 0 }}
                transition={{ duration: 0.3, ease: "easeInOut" }}
              >
                <ChevronDown className="w-4 h-4" />
              </motion.div>
            </span>
            <div className="flex-1 h-[1px] bg-slate-200 group-hover:bg-slate-300 transition-colors" />
          </button>

          {/* Expandable Content */}
          <AnimatePresence>
            {recentOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
                className="w-full overflow-hidden"
              >
                <div className="pt-6 pb-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                  {isLoading && (
                    <div className="col-span-full py-8 flex justify-center w-full">
                      <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                    </div>
                  )}
                  {subjects.map((subject: any, i: number) => (
                    <motion.div
                      key={subject.subject_id}
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05, duration: 0.35, ease: "easeOut" }}
                    >
                      <Link to={`/subject/${subject.subject_id}/files`} className="block group">
                        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md hover:border-slate-300 transition-all duration-300 h-full flex flex-col group/card hover:-translate-y-1">
                          <div className="flex items-start justify-between mb-4">
                            <h3 className="text-lg font-bold text-slate-900 line-clamp-1 group-hover/card:text-slate-700 transition-colors">
                              {subject.name}
                            </h3>
                            <div className="p-2 bg-slate-50 rounded-lg group-hover/card:bg-slate-100 transition-colors border border-transparent group-hover/card:border-slate-200">
                              <BookOpen className="w-5 h-5 text-slate-400 group-hover/card:text-slate-700" />
                            </div>
                          </div>
                          <div className="mt-auto pt-4 flex items-center gap-3 border-t border-slate-50">
                            <span className="flex items-center text-xs font-medium text-slate-500 bg-slate-100 px-2.5 py-1 rounded-md">
                              <MessageSquare className="w-3.5 h-3.5 mr-1" /> 会话
                            </span>
                            <span className="flex items-center text-xs font-medium text-slate-500 bg-slate-100 px-2.5 py-1 rounded-md">
                              <FileText className="w-3.5 h-3.5 mr-1" /> 资料
                            </span>
                            <span className="text-xs text-slate-400 ml-auto flex items-center">
                               {/* subject._created_at if available, else standard fallback */}
                               进入学习 <ChevronDown className="w-3 h-3 ml-0.5 -rotate-90" />
                            </span>
                          </div>
                        </div>
                      </Link>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* Footer */}
      <div className="mt-auto pt-12 pb-6 text-center text-sm text-slate-400 font-medium">
        AITeachMe Open Source Project
      </div>
    </div>
  );
}

