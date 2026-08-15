import { useCallback, useRef, useState } from "react";

import type { ExamPaperDetailResponse } from "../../api/generated/model/examPaperDetailResponse";

interface MarkableQuestionTemplate {
  id: number;
  is_marked?: boolean;
}

export function addPendingQuestionTemplateId(
  pendingIds: ReadonlySet<number>,
  questionTemplateId: number,
): Set<number> | null {
  if (pendingIds.has(questionTemplateId)) {
    return null;
  }
  const next = new Set(pendingIds);
  next.add(questionTemplateId);
  return next;
}

export function removePendingQuestionTemplateId(
  pendingIds: ReadonlySet<number>,
  questionTemplateId: number,
): Set<number> {
  const next = new Set(pendingIds);
  next.delete(questionTemplateId);
  return next;
}

export function useQuestionTemplateMarkRequestGuard() {
  const pendingRef = useRef<Set<number>>(new Set());
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(() => new Set());

  const begin = useCallback((questionTemplateId: number) => {
    const next = addPendingQuestionTemplateId(pendingRef.current, questionTemplateId);
    if (next === null) {
      return false;
    }
    pendingRef.current = next;
    setPendingIds(next);
    return true;
  }, []);

  const finish = useCallback((questionTemplateId: number) => {
    if (!pendingRef.current.has(questionTemplateId)) {
      return;
    }
    const next = removePendingQuestionTemplateId(pendingRef.current, questionTemplateId);
    pendingRef.current = next;
    setPendingIds(next);
  }, []);

  return { pendingIds, begin, finish } as const;
}

export function patchQuestionTemplateMarkInTemplates<T extends MarkableQuestionTemplate>(
  templates: T[],
  questionTemplateId: number,
  isMarked: boolean,
): T[] {
  const needsPatch = templates.some(
    (template) =>
      template.id === questionTemplateId &&
      (template.is_marked === true) !== isMarked,
  );
  if (!needsPatch) {
    return templates;
  }

  return templates.map((template) =>
    template.id === questionTemplateId
      ? { ...template, is_marked: isMarked }
      : template,
  );
}

export function restoreQuestionTemplateMarkInTemplates<T extends MarkableQuestionTemplate>(
  templates: T[],
  questionTemplateId: number,
  optimisticIsMarked: boolean,
  previousIsMarked: boolean,
): T[] {
  const current = templates.find((template) => template.id === questionTemplateId);
  if (!current || (current.is_marked === true) !== optimisticIsMarked) {
    return templates;
  }
  return patchQuestionTemplateMarkInTemplates(
    templates,
    questionTemplateId,
    previousIsMarked,
  );
}

export function patchQuestionTemplateMarkInPrepareResult<
  TTemplate extends MarkableQuestionTemplate,
  TPrepare extends { templates: TTemplate[] },
>(
  prepareResult: TPrepare,
  questionTemplateId: number,
  isMarked: boolean,
): TPrepare {
  const templates = patchQuestionTemplateMarkInTemplates(
    prepareResult.templates,
    questionTemplateId,
    isMarked,
  );
  if (templates === prepareResult.templates) {
    return prepareResult;
  }

  return { ...prepareResult, templates };
}

export function restoreQuestionTemplateMarkInPrepareResult<
  TTemplate extends MarkableQuestionTemplate,
  TPrepare extends { templates: TTemplate[] },
>(
  prepareResult: TPrepare,
  questionTemplateId: number,
  optimisticIsMarked: boolean,
  previousIsMarked: boolean,
): TPrepare {
  const templates = restoreQuestionTemplateMarkInTemplates(
    prepareResult.templates,
    questionTemplateId,
    optimisticIsMarked,
    previousIsMarked,
  );
  if (templates === prepareResult.templates) {
    return prepareResult;
  }
  return { ...prepareResult, templates };
}

export function patchQuestionTemplateMarkInPaper(
  paper: ExamPaperDetailResponse,
  questionTemplateId: number,
  isMarked: boolean,
): ExamPaperDetailResponse {
  const items = paper.items;
  const needsPatch = items?.some(
    (item) =>
      item.question_template_id === questionTemplateId &&
      (item.is_marked === true) !== isMarked,
  );
  if (!items || !needsPatch) {
    return paper;
  }

  return {
    ...paper,
    items: items.map((item) =>
      item.question_template_id === questionTemplateId
        ? { ...item, is_marked: isMarked }
        : item,
    ),
  };
}

export function restoreQuestionTemplateMarkInPaper(
  paper: ExamPaperDetailResponse,
  questionTemplateId: number,
  optimisticIsMarked: boolean,
  previousIsMarked: boolean,
): ExamPaperDetailResponse {
  const current = paper.items?.find(
    (item) => item.question_template_id === questionTemplateId,
  );
  if (!current || (current.is_marked === true) !== optimisticIsMarked) {
    return paper;
  }
  return patchQuestionTemplateMarkInPaper(
    paper,
    questionTemplateId,
    previousIsMarked,
  );
}
