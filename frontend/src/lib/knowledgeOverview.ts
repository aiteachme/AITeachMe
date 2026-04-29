import { knowledgeOverviewApiV1SubjectsSubjectIdKnowledgeOverviewPost } from "../api/generated/knowledge";
import type { KnowledgeOverviewRequest, KnowledgeOverviewResponse } from "../api/generated/model";
import { unwrapOrvalResponse } from "./unwrapOrvalResponse";

export type KnowledgeOverviewSection = NonNullable<KnowledgeOverviewRequest["include"]>[number];

export const OVERVIEW_INCLUDE_PRESETS = {
  wordCloud: ["graph", "stats"],
  knowledgeGraph: ["stats"],
  profileMappings: ["graph", "stats"],
} as const satisfies Record<string, readonly KnowledgeOverviewSection[]>;

export function buildKnowledgeOverviewQueryKey(
  subjectId: string,
  include: readonly KnowledgeOverviewSection[],
) {
  return ["knowledge-overview", subjectId, [...include].sort().join(",")] as const;
}

export async function fetchKnowledgeOverview(
  subjectId: string,
  include: readonly KnowledgeOverviewSection[],
): Promise<KnowledgeOverviewResponse> {
  const raw = await knowledgeOverviewApiV1SubjectsSubjectIdKnowledgeOverviewPost(subjectId, {
    full: false,
    include: [...include],
  });

  return (
    unwrapOrvalResponse<KnowledgeOverviewResponse>(raw) ?? {
      subject_id: subjectId,
      generated_at: new Date().toISOString(),
      graph: null,
      stats: {
        node_count: 0,
        edge_count: 0,
      },
      vector_status: {
        mode: "enabled",
        notice: null,
        embedding_model: null,
        vector_table: null,
      },
      planner_session_id: null,
      confirmed_plan_id: null,
      digest_mode: null,
    }
  );
}
