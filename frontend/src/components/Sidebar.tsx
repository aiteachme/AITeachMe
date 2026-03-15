import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
  X
} from "lucide-react";
import { Button } from "./ui/Button";
import { cn } from "../lib/utils";

interface Module {
  id: string;
  name: string;
  icon: React.ReactNode;
  path: string;
}

interface Subject {
  id: string;
  name: string;
  modules: Module[];
}

const moduleIcons = {
  upload: <Upload className="w-4 h-4" />,
  summary: <BookOpen className="w-4 h-4" />,
  chat: <MessageSquare className="w-4 h-4" />,
  exam: <FileText className="w-4 h-4" />,
  analysis: <BarChart3 className="w-4 h-4" />,
};

export function Sidebar() {
  const [subjects, setSubjects] = useState<Subject[]>([
    {
      id: "1",
      name: "高数",
      modules: [
        { id: "chat", name: "对话", icon: moduleIcons.chat, path: "/subject/1/chat" },
        { id: "upload", name: "上传资料", icon: moduleIcons.upload, path: "/subject/1/upload" },
        { id: "summary", name: "知识总结", icon: moduleIcons.summary, path: "/subject/1/summary" },
        { id: "exam", name: "考题预测", icon: moduleIcons.exam, path: "/subject/1/exam" },
        { id: "analysis", name: "学习分析", icon: moduleIcons.analysis, path: "/subject/1/analysis" },
      ],
    },
  ]);

  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set(["1"]));
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const location = useLocation();

  const toggleSubject = (subjectId: string) => {
    setExpandedSubjects((prev) => {
      const next = new Set(prev);
      if (next.has(subjectId)) {
        next.delete(subjectId);
      } else {
        next.add(subjectId);
      }
      return next;
    });
  };

  const addNewSubject = () => {
    const newId = String(subjects.length + 1);
    const newSubject: Subject = {
      id: newId,
      name: `新学科 ${newId}`,
      modules: [
        { id: "chat", name: "对话", icon: moduleIcons.chat, path: `/subject/${newId}/chat` },
        { id: "upload", name: "上传资料", icon: moduleIcons.upload, path: `/subject/${newId}/upload` },
        { id: "summary", name: "知识总结", icon: moduleIcons.summary, path: `/subject/${newId}/summary` },
        { id: "exam", name: "考题预测", icon: moduleIcons.exam, path: `/subject/${newId}/exam` },
        { id: "analysis", name: "学习分析", icon: moduleIcons.analysis, path: `/subject/${newId}/analysis` },
      ],
    };
    setSubjects([...subjects, newSubject]);
    setExpandedSubjects((prev) => new Set([...prev, newId]));
  };

  const SidebarContent = () => (
    <>
      <div className="p-4 border-b border-slate-200">
        <h1 className="text-xl font-bold text-slate-900">AI TEACHE ME</h1>
      </div>

      <div className="p-4">
        <Button
          onClick={addNewSubject}
          className="w-full justify-start"
          variant="default"
        >
          <Plus className="w-4 h-4" />
          新建学科
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {subjects.map((subject) => (
          <div key={subject.id} className="mb-2">
            <button
              onClick={() => toggleSubject(subject.id)}
              className="flex items-center w-full px-3 py-2 text-sm font-medium text-slate-700 rounded-lg hover:bg-slate-100 transition-colors"
            >
              {expandedSubjects.has(subject.id) ? (
                <ChevronDown className="w-4 h-4 mr-2" />
              ) : (
                <ChevronRight className="w-4 h-4 mr-2" />
              )}
              {subject.name}
            </button>

            {expandedSubjects.has(subject.id) && (
              <div className="ml-6 mt-1 space-y-1">
                {subject.modules.map((module) => (
                  <Link
                    key={module.id}
                    to={module.path}
                    onClick={() => setIsMobileOpen(false)}
                    className={cn(
                      "flex items-center px-3 py-2 text-sm rounded-lg transition-colors",
                      location.pathname === module.path
                        ? "bg-slate-100 text-slate-900 font-medium"
                        : "text-slate-600 hover:bg-slate-50"
                    )}
                  >
                    {module.icon}
                    <span className="ml-2">{module.name}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={() => setIsMobileOpen(!isMobileOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 rounded-lg bg-white border border-slate-200 shadow-sm"
      >
        {isMobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>

      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/20 z-30"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed lg:static inset-y-0 left-0 z-40 w-64 bg-white border-r border-slate-200 flex flex-col transition-transform duration-200",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <SidebarContent />
      </aside>
    </>
  );
}
