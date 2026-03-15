import { TrendingUp, Clock, Target, Award } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/Card";

export function AnalysisPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">学习分析</h1>
        <p className="text-slate-500 mt-2">追踪您的学习进度和表现</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>学习时长</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">24.5</p>
                <p className="text-xs text-slate-500 mt-1">小时</p>
              </div>
              <Clock className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>完成章节</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">8/12</p>
                <p className="text-xs text-slate-500 mt-1">章节</p>
              </div>
              <Target className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>平均分数</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-slate-900">85</p>
                <p className="text-xs text-slate-500 mt-1">分</p>
              </div>
              <Award className="w-8 h-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>进步趋势</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-3xl font-bold text-green-600">+12%</p>
                <p className="text-xs text-slate-500 mt-1">本周</p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-500" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>学习进度</CardTitle>
            <CardDescription>各章节掌握情况</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {[
              { name: "函数与极限", progress: 100 },
              { name: "导数与微分", progress: 85 },
              { name: "积分", progress: 60 },
              { name: "微分方程", progress: 30 },
            ].map((item, i) => (
              <div key={i}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-slate-700">{item.name}</span>
                  <span className="text-sm text-slate-500">{item.progress}%</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2">
                  <div
                    className="bg-slate-900 h-2 rounded-full transition-all"
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>薄弱知识点</CardTitle>
            <CardDescription>需要加强练习的内容</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[
                { topic: "隐函数求导", accuracy: 65 },
                { topic: "定积分应用", accuracy: 70 },
                { topic: "微分方程解法", accuracy: 58 },
              ].map((item, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"
                >
                  <span className="text-sm font-medium text-slate-700">{item.topic}</span>
                  <span className="text-sm text-orange-600 font-medium">
                    {item.accuracy}% 正确率
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
