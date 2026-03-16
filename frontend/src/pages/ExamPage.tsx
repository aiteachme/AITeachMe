import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FileQuestion, Clock, Loader2, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import {
  generateExamApiV1SubjectsSubjectExamGeneratePost,
  getExamHistoryApiV1SubjectsSubjectExamHistoryPost,
  submitAnswersApiV1ExamExamIdSubmitPost,
} from "../api/generated/exam";
import type { ExamResponse, SubmitResponse } from "../api/generated/model";

export function ExamPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();
  const [activeExam, setActiveExam] = useState<ExamResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<SubmitResponse | null>(null);

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["exam-history", subjectId],
    queryFn: () => getExamHistoryApiV1SubjectsSubjectExamHistoryPost(subjectId, { limit: 10, offset: 0 }),
    enabled: !!subjectId,
  });

  const generateMutation = useMutation({
    mutationFn: () => generateExamApiV1SubjectsSubjectExamGeneratePost(subjectId, {
      knowledge_points: [],
      num_questions: 5,
    }),
    onSuccess: (data) => {
      setActiveExam(data);
      setAnswers({});
      setResult(null);
    },
  });

  const submitMutation = useMutation({
    mutationFn: (examId: number) => submitAnswersApiV1ExamExamIdSubmitPost(examId, {
      answers: Object.entries(answers).map(([question_key, answer]) => ({ question_key, answer })),
    }),
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
    },
  });

  const history = historyData?.items ?? [];

  if (activeExam && !result) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-slate-900">答题中</h1>
          <Button variant="ghost" onClick={() => setActiveExam(null)}>退出</Button>
        </div>
        <div className="space-y-4">
          {activeExam.questions.map((q, i) => (
            <Card key={q.question_key}>
              <CardHeader>
                <CardTitle className="text-base">
                  {i + 1}. {q.stem}
                </CardTitle>
                <CardDescription>{q.knowledge_point} · {q.difficulty}</CardDescription>
              </CardHeader>
              <CardContent>
                {q.options ? (
                  <div className="space-y-2">
                    {q.options.map((opt, j) => (
                      <label key={j} className="flex items-center gap-3 p-3 border border-slate-200 rounded-lg cursor-pointer hover:bg-slate-50 transition-colors">
                        <input
                          type="radio"
                          name={q.question_key}
                          value={opt}
                          checked={answers[q.question_key] === opt}
                          onChange={() => setAnswers({ ...answers, [q.question_key]: opt })}
                        />
                        <span className="text-sm text-slate-700">{opt}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    className="w-full p-3 border border-slate-200 rounded-lg text-sm resize-none focus:outline-none focus:border-slate-400"
                    rows={3}
                    placeholder="请输入答案..."
                    value={answers[q.question_key] ?? ""}
                    onChange={(e) => setAnswers({ ...answers, [q.question_key]: e.target.value })}
                  />
                )}
              </CardContent>
            </Card>
          ))}
        </div>
        <Button
          className="w-full"
          onClick={() => submitMutation.mutate(activeExam.exam_id)}
          disabled={submitMutation.isPending}
        >
          {submitMutation.isPending ? <><Loader2 className="w-4 h-4 animate-spin mr-2" />提交中...</> : "提交答卷"}
        </Button>
      </div>
    );
  }

  if (result) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-slate-900">答题结果</h1>
          <Button onClick={() => { setActiveExam(null); setResult(null); }}>返回</Button>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>得分：{result.score} 分</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {result.results.map((r) => (
              <div key={r.question_key} className="flex items-start gap-3 p-3 border border-slate-200 rounded-lg">
                {r.is_correct
                  ? <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" />
                  : <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />}
                <div>
                  <p className="text-sm font-medium text-slate-800">正确答案：{r.correct_answer}</p>
                  <p className="text-xs text-slate-500 mt-1">{r.explanation}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">考题预测</h1>
        <p className="text-slate-500 mt-2">基于学习内容生成的模拟试题</p>
      </div>

      <Button
        onClick={() => generateMutation.mutate()}
        disabled={generateMutation.isPending}
        className="w-full sm:w-auto"
      >
        {generateMutation.isPending
          ? <><Loader2 className="w-4 h-4 animate-spin mr-2" />生成中...</>
          : "生成新试卷"}
      </Button>

      <Card>
        <CardHeader>
          <CardTitle>历史记录</CardTitle>
          <CardDescription>查看您的练习历史</CardDescription>
        </CardHeader>
        <CardContent>
          {historyLoading && (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
            </div>
          )}
          {!historyLoading && history.length === 0 && (
            <p className="text-center py-8 text-slate-400 text-sm">暂无考试记录</p>
          )}
          <div className="space-y-3">
            {history.map((item) => (
              <div key={item.exam_id} className="flex items-center justify-between p-4 border border-slate-200 rounded-lg">
                <div className="flex items-center gap-3">
                  <FileQuestion className="w-5 h-5 text-slate-400" />
                  <div>
                    <p className="text-sm font-medium text-slate-900">考卷 #{item.exam_id}</p>
                    <p className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                      <Clock className="w-3 h-3" />
                      {new Date(item.created_at).toLocaleDateString("zh-CN")}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  {item.score != null
                    ? <p className="text-lg font-bold text-slate-900">{item.score} 分</p>
                    : <p className="text-sm text-slate-400">未提交</p>}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
