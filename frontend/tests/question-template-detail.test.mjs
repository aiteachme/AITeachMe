import assert from "node:assert/strict";
import test from "node:test";

import {
  buildQuestionTemplateKnowledgeRefs,
  formatQuestionTemplateKnowledgeNameMarkdown,
  formatQuestionTemplateKnowledgeSummaryMarkdown,
  formatQuestionTemplateErrorCause,
  formatQuestionTemplateHistoryMode,
  formatQuestionTemplateStatus,
  formatQuestionTemplateVersion,
  shouldShowQuestionTemplateFeedback,
  summarizeQuestionTemplateHistory,
} from "../src/components/exams/questionTemplateDetail.ts";

test("题目状态、训练模式、版本和错因不暴露英文内部代码", () => {
  assert.equal(formatQuestionTemplateStatus("active"), "可用");
  assert.equal(formatQuestionTemplateVersion(3), "第 3 版");
  assert.equal(formatQuestionTemplateHistoryMode("paper_exam"), "考卷");
  assert.equal(formatQuestionTemplateHistoryMode("internal_mode"), "其他训练");
  assert.equal(formatQuestionTemplateErrorCause("knowledge_gap"), "知识点掌握不足");
  assert.equal(formatQuestionTemplateErrorCause("answer_not_precise"), "答案不够准确");
  assert.equal(formatQuestionTemplateErrorCause("new_internal_code"), "需要进一步分析");
});

test("知识点完整显示名称、类型和本题覆盖权重，不推断考查角色", () => {
  const refs = buildQuestionTemplateKnowledgeRefs([
    {
      knowledge_unit_id: 136,
      knowledge_unit_name: "折线图中的分段函数建模",
      knowledge_unit_type: "skill",
      coverage_weight: 0.45,
    },
    {
      knowledge_unit_id: 137,
      knowledge_unit_name: "一次函数解析式",
      knowledge_unit_type_label: "公式模型",
      coverage_weight: 0.3,
    },
  ]);

  assert.deepEqual(
    refs.map(({ name, typeLabel, isTopic, weightLabel }) => ({ name, typeLabel, isTopic, weightLabel })),
    [
      {
        name: "折线图中的分段函数建模",
        typeLabel: "解题技能",
        isTopic: false,
        weightLabel: "本题覆盖 45%",
      },
      {
        name: "一次函数解析式",
        typeLabel: "公式模型",
        isTopic: false,
        weightLabel: "本题覆盖 30%",
      },
    ],
  );
});

test("知识点规范名称中的裸 LaTeX 只在显示层补充数学定界符", () => {
  assert.equal(
    formatQuestionTemplateKnowledgeNameMarkdown("反比例函数 y=\\frac{k}{x}"),
    "反比例函数 $y=\\frac{k}{x}$",
  );
  assert.equal(
    formatQuestionTemplateKnowledgeNameMarkdown("反比例函数定义域 x\\neq 0"),
    "反比例函数定义域 $x\\neq 0$",
  );
  assert.equal(formatQuestionTemplateKnowledgeNameMarkdown("k=0不是反比例函数"), "k=0不是反比例函数");
  assert.equal(formatQuestionTemplateKnowledgeNameMarkdown("已有 $x\\neq0$"), "已有 $x\\neq0$");
});

test("主题节点的章节 Markdown 被压缩为安全的行内摘要", () => {
  const summary = formatQuestionTemplateKnowledgeSummaryMarkdown(
    "# 二次函数图像性质、解析式互化与最值应用 | 学习主线 | 本章要解决的问题 | |---|---| | 解析式结构 | 从 $y=ax^2+bx+c$ 中读取参数 | | 图像性质 | 判断开口方向与顶点 | ## 二次函数一般式结构",
  );

  assert.equal(summary.includes("#"), false);
  assert.equal(summary.includes("|"), false);
  assert.equal(summary.includes("---"), false);
  assert.equal(summary.includes("二次函数一般式结构"), false);
  assert.match(summary, /二次函数图像性质、解析式互化与最值应用/);
  assert.match(summary, /\$y=ax\^2\+bx\+c\$/);
});

test("仅有编号或占位名称时给出明确的未同步提示状态", () => {
  const [ref] = buildQuestionTemplateKnowledgeRefs([
    { knowledge_unit_id: 105, knowledge_unit_name: "KU-105", coverage_weight: 1 },
  ]);

  assert.equal(ref.name, "知识点 #105");
  assert.equal(ref.hasResolvedName, false);
});

test("作答历史汇总只用已批改记录计算正确率", () => {
  assert.deepEqual(
    summarizeQuestionTemplateHistory([
      { is_correct: true },
      { is_correct: false },
      { is_correct: null },
    ]),
    {
      attemptCount: 3,
      gradedCount: 2,
      correctCount: 1,
      wrongCount: 1,
      pendingCount: 1,
      accuracy: 50,
    },
  );
});

test("与上方解析完全重复的批改反馈不会再次展示", () => {
  assert.equal(shouldShowQuestionTemplateFeedback("**先求导**，再判断极值。", "先求导，再判断极值。"), false);
  assert.equal(shouldShowQuestionTemplateFeedback("需要补充定义域。", "先求导，再判断极值。"), true);
});
