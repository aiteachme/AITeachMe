import type {
  ExamHistoryItem,
  ExamNodeLinkResponse,
  ExamPaperItemResponse,
  PaperPreview,
} from "../../api/generated/model";

type QueryEnvelope = Record<string, unknown>;

export interface ExamGenerationSnapshotPayload {
  exam_paper_id?: number;
  status?: string;
  num_questions?: number;
  paper_preview?: PaperPreview;
  selection_context?: Record<string, unknown>;
  generated_question?: Record<string, unknown>;
  generated_questions?: Record<string, unknown>[];
  generated_question_count?: number;
  failed_question?: Record<string, unknown>;
  failed_questions?: Record<string, unknown>[];
  failed_question_count?: number;
  error_message?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toPositiveInt(value: unknown): number | null {
  const parsed = toNumber(value);
  if (parsed == null || parsed <= 0) return null;
  return Math.trunc(parsed);
}

function toText(value: unknown): string {
  return typeof value === "string" ? value : String(value ?? "");
}

function toStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map((item) => toText(item).trim()).filter(Boolean);
  return items.length ? items : null;
}

export function parseExamGenerationSnapshot(rawData: string): ExamGenerationSnapshotPayload {
  try {
    const payload = JSON.parse(rawData || "{}");
    return isRecord(payload) ? (payload as ExamGenerationSnapshotPayload) : {};
  } catch {
    return {};
  }
}

function generatedQuestionsFromPayload(
  payload: ExamGenerationSnapshotPayload,
): Record<string, unknown>[] {
  const items: Record<string, unknown>[] = [];
  if (Array.isArray(payload.generated_questions)) {
    items.push(...payload.generated_questions.filter(isRecord));
  }
  if (isRecord(payload.generated_question)) {
    items.push(payload.generated_question);
  }

  const byOrder = new Map<number, Record<string, unknown>>();
  for (const item of items) {
    const order = toPositiveInt(item.item_order);
    if (order != null) {
      byOrder.set(order, item);
    }
  }
  return Array.from(byOrder.entries())
    .sort(([left], [right]) => left - right)
    .map(([, item]) => item);
}

function getEffectiveExamStatus(status: unknown, selectionContext: unknown): unknown {
  const rawStatus = toText(status);
  if (rawStatus !== "generating" || !isRecord(selectionContext)) {
    return status;
  }
  const generationStatus = toText(selectionContext.generation_status).trim();
  const errorMessage = toText(selectionContext.error_message).trim();
  if (generationStatus === "failed" || errorMessage) {
    return "failed";
  }
  return status;
}

function buildKnowledgeLinks(value: unknown): ExamNodeLinkResponse[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).flatMap((ref) => {
    const unitId = toPositiveInt(ref.knowledge_unit_id);
    if (unitId == null) return [];
    const weight = toNumber(ref.coverage_weight) ?? 1;
    const role = toText(ref.role || "secondary") || "secondary";
    return [{
      knowledge_unit_id: unitId,
      knowledge_unit_name: `#${unitId}`,
      coverage_weight: Math.max(0, Math.min(1, weight)),
      role,
      mastery_score: null,
    }];
  });
}

function draftItemFromGeneratedQuestion(question: Record<string, unknown>): ExamPaperItemResponse | null {
  const order = toPositiveInt(question.item_order);
  const stem = toText(question.stem).trim();
  if (order == null || !stem) return null;
  return {
    id: -1_000_000 - order,
    item_order: order,
    question_template_id: 0,
    question_type: toText(question.question_type || "text"),
    difficulty: toText(question.difficulty || "medium"),
    stem,
    options: toStringList(question.options),
    correct_answer: toText(question.correct_answer),
    explanation: toText(question.explanation),
    knowledge_unit_links: buildKnowledgeLinks(question.knowledge_unit_refs),
    user_answer: "",
    is_correct: null,
    score_obtained: null,
    score_max: 1,
    error_cause_label: null,
  };
}

function mergeGeneratedItems(
  existingItems: ExamPaperItemResponse[],
  generatedQuestions: Record<string, unknown>[],
): ExamPaperItemResponse[] {
  const byOrder = new Map<number, ExamPaperItemResponse>();
  for (const item of existingItems) {
    const order = toPositiveInt(item.item_order);
    if (order != null) {
      byOrder.set(order, item);
    }
  }

  for (const question of generatedQuestions) {
    const draft = draftItemFromGeneratedQuestion(question);
    if (!draft) continue;
    const existing = byOrder.get(draft.item_order);
    if (existing && existing.id > 0) continue;
    byOrder.set(draft.item_order, draft);
  }

  return Array.from(byOrder.values()).sort((left, right) => left.item_order - right.item_order);
}

export function patchExamDetailQueryData(
  current: unknown,
  payload: ExamGenerationSnapshotPayload,
): unknown {
  if (!isRecord(current) || !isRecord(current.data)) return current;
  const apiPayload = current.data;
  if (!isRecord(apiPayload.data)) return current;
  const paper = apiPayload.data as QueryEnvelope;

  const generatedQuestions = generatedQuestionsFromPayload(payload);
  const currentItems = Array.isArray(paper.items)
    ? paper.items.filter(isRecord) as unknown as ExamPaperItemResponse[]
    : [];
  const nextSelectionContext = payload.selection_context ?? paper.selection_context;
  const nextStatus = getEffectiveExamStatus(payload.status ?? paper.status, nextSelectionContext);
  const nextPaper: QueryEnvelope = {
    ...paper,
    status: nextStatus,
    total_items: payload.num_questions ?? paper.total_items,
    paper_preview: payload.paper_preview ?? paper.paper_preview,
    selection_context: nextSelectionContext,
    items: generatedQuestions.length
      ? mergeGeneratedItems(currentItems, generatedQuestions)
      : currentItems,
  };

  return {
    ...current,
    data: {
      ...apiPayload,
      data: nextPaper,
    },
  };
}

export function patchExamHistoryQueryData(
  current: unknown,
  payload: ExamGenerationSnapshotPayload,
): unknown {
  const paperId = toPositiveInt(payload.exam_paper_id);
  if (paperId == null || !isRecord(current) || !isRecord(current.data)) return current;
  const apiPayload = current.data;
  if (!isRecord(apiPayload.data) || !Array.isArray(apiPayload.data.items)) return current;

  const items = apiPayload.data.items as ExamHistoryItem[];
  const nextItems = items.map((item) => {
    if (item.id !== paperId) return item;
    const nextStatus = getEffectiveExamStatus(payload.status ?? item.status, payload.selection_context);
    return {
      ...item,
      status: nextStatus as string,
      total_items: payload.num_questions ?? item.total_items,
      paper_preview: payload.paper_preview ?? item.paper_preview,
    };
  });

  return {
    ...current,
    data: {
      ...apiPayload,
      data: {
        ...apiPayload.data,
        items: nextItems,
      },
    },
  };
}
