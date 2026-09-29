import type { QueryClient } from "@tanstack/react-query";
import type { QuestionTypeCatalogItemResponse } from "../../api/generated/model/questionTypeCatalogItemResponse.ts";

export async function refreshQuestionTypeCatalogAfterUpdate(
  queryClient: QueryClient,
  courseId: string,
  updated: QuestionTypeCatalogItemResponse,
): Promise<void> {
  const queryKey = ["question-type-catalog", courseId] as const;
  // A read started before PATCH may finish later with the old status/version.
  await queryClient.cancelQueries({ queryKey, exact: true });
  queryClient.setQueryData<QuestionTypeCatalogItemResponse[]>(queryKey, (current) => (
    current?.map((item) => item.id === updated.id ? updated : item)
  ));
  await queryClient.invalidateQueries({ queryKey, exact: true });
}
