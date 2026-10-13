export interface PlannerDiagnosticAnswerState {
  choice?: string;
  note?: string;
}

function parsePlannerDiagnosticAnswerText(value: string): PlannerDiagnosticAnswerState {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return {};
  }
  const choiceMatch = normalized.match(/(?:^|[；;]\s*)选择[:：]\s*([\s\S]+?)(?=[；;]\s*补充[:：]|$)/u);
  const noteMatch = normalized.match(/(?:^|[；;]\s*)补充[:：]\s*([\s\S]+)$/u);
  const choice = String(choiceMatch?.[1] ?? "").trim();
  const note = String(noteMatch?.[1] ?? "").trim();
  if (choice || note) {
    return { choice, note };
  }
  return { choice: normalized };
}

export function normalizePlannerDiagnosticAnswer(value: unknown): PlannerDiagnosticAnswerState {
  if (!value) {
    return {};
  }
  if (typeof value === "string") {
    return parsePlannerDiagnosticAnswerText(value);
  }
  if (typeof value === "object") {
    const raw = value as { choice?: unknown; note?: unknown; answer?: unknown };
    const choice = String(raw.choice ?? raw.answer ?? "").trim();
    // The controlled textarea must retain spaces/newlines while the user types.
    // Submission trims field boundaries in formatPlannerDiagnosticAnswer.
    const note = String(raw.note ?? "");
    return { choice, note };
  }
  return {};
}

export function normalizePlannerDiagnosticAnswers(value: unknown): Record<string, PlannerDiagnosticAnswerState> {
  if (!value || typeof value !== "object") {
    return {};
  }
  const answers: Record<string, PlannerDiagnosticAnswerState> = {};
  for (const [question, raw] of Object.entries(value as Record<string, unknown>)) {
    const normalizedQuestion = String(question ?? "").trim();
    if (!normalizedQuestion) {
      continue;
    }
    const answer = normalizePlannerDiagnosticAnswer(raw);
    if (answer.choice || answer.note?.trim()) {
      answers[normalizedQuestion] = answer;
    }
  }
  return answers;
}

export function formatPlannerDiagnosticAnswer(value: unknown): string {
  const answer = normalizePlannerDiagnosticAnswer(value);
  const parts: string[] = [];
  if (answer.choice) {
    parts.push(`选择：${answer.choice}`);
  }
  const note = answer.note?.trim();
  if (note) {
    parts.push(`补充：${note}`);
  }
  return parts.join("；").trim();
}
