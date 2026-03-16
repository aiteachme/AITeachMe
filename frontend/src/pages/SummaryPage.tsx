import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { getKnowledgeOutlineApiV1KnowledgeSubjectOutlinePost } from "../api/generated/knowledge";
import type { OutlineNode } from "../api/generated/model";

function OutlineTree({ nodes }: { nodes: OutlineNode[] }) {
  return (
    <ul className="space-y-1">
      {nodes.map((node) => (
        <li key={node.id}>
          <div className={`flex items-center gap-2 py-1 ${node.level === 1 ? "font-medium text-slate-800" : "text-slate-600 pl-4 text-sm"}`}>
            <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
            {node.title}
          </div>
          {node.children && node.children.length > 0 && (
            <OutlineTree nodes={node.children} />
          )}
        </li>
      ))}
    </ul>
  );
}

export function SummaryPage() {
  const { subjectId = "" } = useParams();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["outline", subjectId],
    queryFn: () => getKnowledgeOutlineApiV1KnowledgeSubjectOutlinePost(subjectId),
    enabled: !!subjectId,
  });

  const outlines = data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">知识总结</h1>
        <p className="text-slate-500 mt-2">AI 生成的知识点总结和思维导图</p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" />
          加载中...
        </div>
      )}

      {isError && (
        <p className="text-center py-16 text-red-500 text-sm">加载失败，请刷新重试</p>
      )}

      {!isLoading && !isError && outlines.length === 0 && (
        <p className="text-center py-16 text-slate-400 text-sm">暂无知识大纲，请先上传学习资料</p>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {outlines.map((outline) => (
          <Card key={outline.knowledge_id} className="hover:shadow-md transition-shadow">
            <CardHeader>
              <div className="flex items-start justify-between">
                <BookOpen className="w-8 h-8 text-slate-400" />
              </div>
              <CardTitle className="text-lg mt-4">{outline.title}</CardTitle>
              <CardDescription>{outline.nodes.length} 个顶层知识点</CardDescription>
            </CardHeader>
            <CardContent>
              <OutlineTree nodes={outline.nodes} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
