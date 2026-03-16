import { useState, useRef, useEffect, memo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  Plus,
  Upload,
  BookOpen,
  MessageSquare,
  FileText,
  BarChart3,
  Menu,
  X,
  Loader2,
  Trash2,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "../ui/Button";
import { cn } from "../../lib/utils";
import { apiClient } from "../../api/client";

interface SubjectItem {
  id: number;
  subject: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
}

const MODULES = [
  { id: "chat", name: "对话", icon: <MessageSquare className="w-4 h-4" /> },
  { id: "upload", name: "上传资料", icon: <Upload className="w-4 h-4" /> },
  { id: "summary", name: "知识总结", icon: <BookOpen className="w-4 h-4" /> },
  { id: "exam", name: "考题预测", icon: <FileText className="w-4 h-4" /> },
  { id: "analysis", name: "学习分析", icon: <BarChart3 className="w-4 h-4" /> },
];

async function fetchSubjects(): Promise<SubjectItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<SubjectItem>>>({
    method: "POST",
    url: "/api/v1/subjects/list",
    data: { page: 1, size: 100 },
  });
  return res.data.items;
}

async function createSubject(payload: {
  subject: string;
  name: string;
  description: string;
}): Promise<SubjectItem> {
  const res = await apiClient<ApiResponse<SubjectItem>>({
    method: "POST",
    url: "/api/v1/subjects/add",
    data: payload,
  });
  return res.data;
}

async function deleteSubject(subject: string): Promise<void> {
  await apiClient({ method: "POST", url: "/api/v1/subjects/delete", data: { subject } });
}

// Extracted as a stable component to prevent unmount/remount on parent re-render
const NewSubjectForm = memo(function NewSubjectForm({
  onSubmit,
  onCancel,
  isPending,
  error,
}: {
  onSubmit: (name: string, slug: string) => void;
  onCancel: () => void;
  isPending: boolean;
  error?: string;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameInputRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    if (!name.trim() || !slug.trim()) return;
    onSubmit(name.trim(), slug.trim());
  };

  return (
    <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 space-y-2">
      <input
        ref={nameInputRef}
        className="w-full border border-slate-200 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
        placeholder="学科名称，如：高等数学"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        className="w-full border border-slate-200 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300 bg-white"
        placeholder="标识（英文），如：gaoshu"
        value={slug}
        onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
      />
      {error && (
        <p className="text-xs text-red-500 px-0.5">{error}</p>
      )}
      <div className="flex gap-2">
        <Button
          className="flex-1"
          onClick={handleSubmit}
          disabled={!name.trim() || !slug.trim() || isPending}
        >
          {isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "创建"}
        </Button>
        <Button variant="outline" className="flex-1" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
});

export function Sidebar() {
  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set());
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [createError, setCreateError] = useState<string | undefined>();

  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: fetchSubjects,
  });

  const createMutation = useMutation({
    mutationFn: createSubject,
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setExpandedSubjects((prev) => new Set([...prev, created.subject]));
      setShowNewForm(false);
      setCreateError(undefined);
      navigate(`/subject/${created.subject}/chat`);
    },
    onError: (err: unknown) => {
      const detail =
        (err as any)?.response?.data?.detail ??
        (err as any)?.message ??
        "创建失败，请重试";
      setCreateError(String(detail));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSubject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      navigate("/");
    },
  });

  const toggleSubject = (slug: string) => {
    setExpandedSubjects((prev) => {
      const next = new Set(prev);
      next.has(slug) ? next.delete(slug) : next.add(slug);
      return next;
    });
  };

  const handleCreate = (name: string, slug: string) => {
    setCreateError(undefined);
    createMutation.mutate({ subject: slug, name, description: "" });
  };

  return (
    <>
      <button
        onClick={() => setIsMobileOpen(!isMobileOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 rounded-lg bg-white border border-slate-200 shadow-sm"
      >
        {isMobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>

      {isMobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/20 z-30"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed lg:static inset-y-0 left-0 z-40 w-64 bg-white border-r border-slate-200 flex flex-col transition-transform duration-200",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="p-4 border-b border-slate-200">
          <h1 className="text-xl font-bold text-slate-900">AI TEACH ME</h1>
        </div>

        <div className="p-4 space-y-2">
          <Button
            onClick={() => setShowNewForm((v) => !v)}
            className="w-full justify-start"
            variant="default"
          >
            <Plus className="w-4 h-4" />
            新建学科
          </Button>

          {showNewForm && (
            <NewSubjectForm
              onSubmit={handleCreate}
              onCancel={() => { setShowNewForm(false); setCreateError(undefined); }}
              isPending={createMutation.isPending}
              error={createError}
            />
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4">
          {isLoading && (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
              加载中...
            </div>
          )}

          {subjects.map((subject) => (
            <div key={subject.subject} className="mb-2">
              <div className="flex items-center group">
                <button
                  onClick={() => toggleSubject(subject.subject)}
                  className="flex items-center flex-1 px-3 py-2 text-sm font-medium text-slate-700 rounded-lg hover:bg-slate-100 transition-colors"
                >
                  {expandedSubjects.has(subject.subject) ? (
                    <ChevronDown className="w-4 h-4 mr-2 shrink-0" />
                  ) : (
                    <ChevronRight className="w-4 h-4 mr-2 shrink-0" />
                  )}
                  <span className="truncate">{subject.name}</span>
                </button>
                <button
                  onClick={() => deleteMutation.mutate(subject.subject)}
                  className="opacity-0 group-hover:opacity-100 p-1 mr-1 text-slate-400 hover:text-red-500 transition-all rounded"
                  title="删除学科"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>

              {expandedSubjects.has(subject.subject) && (
                <div className="ml-6 mt-1 space-y-1">
                  {MODULES.map((mod) => {
                    const path = `/subject/${subject.subject}/${mod.id}`;
                    return (
                      <Link
                        key={mod.id}
                        to={path}
                        onClick={() => setIsMobileOpen(false)}
                        className={cn(
                          "flex items-center px-3 py-2 text-sm rounded-lg transition-colors",
                          location.pathname === path
                            ? "bg-slate-100 text-slate-900 font-medium"
                            : "text-slate-600 hover:bg-slate-50"
                        )}
                      >
                        {mod.icon}
                        <span className="ml-2">{mod.name}</span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
