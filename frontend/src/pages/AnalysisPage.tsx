import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Target, Award, Loader2, BookOpen } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import {
  getLearningReportApiV1ProfileSubjectReportPost,
  listProfilesApiV1ProfileSubjectPost,
} from "../api/generated/profile";

export function AnalysisPage() {
  const { subjectId = "" } = useParams();

  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ["report", subjectId],
    queryFn: () => getLearningReportApiV1ProfileSubjectReportPost(subjectId),
    enabled: !!subjectId,
  });

  const { data: profileData, isLoading: profileLoading } = useQuery({
    queryKey: ["profile", subjectId],
    queryFn: () => listProfilesApiV1ProfileSubjectPost(subjectId, { limit: 20, offset: 0 }),
    enabled: !!subjectId,
  });

  const isLoading = reportLoading || profileLoading;
  const profiles = profileData?.items ?? [];
  const overallPct = report?.overall_mastery != null
    ? Math.round(report.overall_mastery * 100)
    : null;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32 text-slate-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">学习分析</h1>
        <p className="text-slate-500 mt-2">追踪您的学习进度和表现</p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>总体掌握度</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">
                  {overallPct != null ? `${overallPct}%` : "—"}
                </p>
              </div>
              <TrendingUp className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>已覆盖知识点</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">{profiles.length}</p>
                <p className="text-xs text-slate-500 mt-1">个</p>
              </div>
              <Target className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>薄弱知识点</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-orange-500">
                  {report?.weak_points_top5.length ?? 0}
                </p>
                <p className="text-xs text-slate-500 mt-1">需加强</p>
              </div>
              <Award className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>知识点掌握度</CardTitle>
            <CardDescription>各知识点学习情况</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {profiles.length === 0 && (
              <p className="text-center py-4 text-slate-400 text-sm">暂无数据</p>
            )}
            {profiles.map((item) => {
              const pct = item.mastery != null ? Math.round(item.mastery * 100) : 0;
              return (
                <div key={item.knowledge_point}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-slate-700">{item.knowledge_point}</span>
                    <span className="text-sm text-slate-500">{pct}%</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2">
                    <div
                      className="bg-slate-900 h-2 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>薄弱知识点</CardTitle>
              <CardDescription>需要加强练习的内容</CardDescription>
            </CardHeader>
            <CardContent>
              {(report?.weak_points_top5 ?? []).length === 0 && (
                <p className="text-center py-4 text-slate-400 text-sm">暂无数据</p>
              )}
              <div className="space-y-3">
                {(report?.weak_points_top5 ?? []).map((item) => (
                  <div key={item.knowledge_point} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                    <span className="text-sm font-medium text-slate-700">{item.knowledge_point}</span>
                    <span className="text-sm text-orange-600 font-medium">
                      {item.mastery != null ? `${Math.round(item.mastery * 100)}%` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {report?.suggestions && report.suggestions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>复习建议</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {report.suggestions.map((s, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                      <BookOpen className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                      {s}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
