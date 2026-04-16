import { useCallback, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  apiClient,
  getApiErrorCode,
  getApiErrorData,
  getApiErrorMessage,
} from "../api/client";
import type {
  DocGenBuildData,
  SubjectVectorStatusResponse,
} from "../api/generated/model";
import type { ApiResponse } from "../api/types";

export type KnowledgeBuildResolution = "rebuild" | "disable";

export interface KnowledgeBuildPrecheckConflictData {
  reason: string;
  subject_model?: string | null;
  subject_dim?: number | null;
  runtime_model?: string | null;
  runtime_dim?: number | null;
  requires_full_rebuild?: boolean;
  vector_enabled_after_continue?: boolean;
}

export interface KnowledgeBuildRequestInput {
  file_uids?: string[];
  prompt?: string;
  confirmed_plan_id?: string;
}

interface KnowledgeBuildRequestPayload extends KnowledgeBuildRequestInput {
  embedding_resolution?: KnowledgeBuildResolution;
  build_type?: "docs" | "graph";
}

interface UseKnowledgeBuildFlowOptions {
  subjectId: string;
  buildRequest: () => KnowledgeBuildRequestInput;
  buildType?: "docs" | "graph";
  fallbackErrorMessage?: string;
  onSuccess?: (data: DocGenBuildData) => void;
}

function isKnowledgeBuildPrecheckConflictData(
  value: unknown,
): value is KnowledgeBuildPrecheckConflictData {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Record<string, unknown>;
  return typeof record.reason === "string" && record.reason.trim().length > 0;
}

async function triggerKnowledgeBuild(
  subjectId: string,
  payload: KnowledgeBuildRequestPayload,
): Promise<DocGenBuildData> {
  const response = await apiClient<ApiResponse<DocGenBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subjectId}/knowledge/build`,
    data: payload,
  });

  return response.data ?? { requested_at: new Date().toISOString() };
}

export function useKnowledgeBuildFlow({
  subjectId,
  buildRequest,
  buildType = "docs",
  fallbackErrorMessage = "知识构建失败，请稍后重试。",
  onSuccess,
}: UseKnowledgeBuildFlowOptions) {
  const pendingRequestRef = useRef<KnowledgeBuildRequestPayload | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [precheckConflict, setPrecheckConflict] =
    useState<KnowledgeBuildPrecheckConflictData | null>(null);
  const [latestVectorStatus, setLatestVectorStatus] =
    useState<SubjectVectorStatusResponse | null>(null);

  const buildMutation = useMutation({
    mutationFn: (payload: KnowledgeBuildRequestPayload) =>
      triggerKnowledgeBuild(subjectId, payload),
    onSuccess: (data) => {
      pendingRequestRef.current = null;
      setPrecheckConflict(null);
      setErrorMessage("");
      setLatestVectorStatus(data.vector_status ?? null);
      onSuccess?.(data);
    },
    onError: (error) => {
      const errorCode = getApiErrorCode(error);
      const errorData = getApiErrorData<KnowledgeBuildPrecheckConflictData>(error);

      if (
        errorCode === "KNOWLEDGE_BUILD_PRECHECK_CONFLICT" &&
        isKnowledgeBuildPrecheckConflictData(errorData)
      ) {
        setErrorMessage("");
        setPrecheckConflict(errorData);
        return;
      }

      setPrecheckConflict(null);
      setErrorMessage(getApiErrorMessage(error, fallbackErrorMessage));
    },
  });

  const submitBuild = useCallback((overrides?: Partial<KnowledgeBuildRequestInput>) => {
    if (!subjectId) {
      setErrorMessage("缺少学科 ID，暂时无法发起知识构建。");
      return;
    }

    const requestPayload = {
      ...buildRequest(),
      ...overrides,
      build_type: buildType,
    } satisfies KnowledgeBuildRequestPayload;

    pendingRequestRef.current = requestPayload;
    setErrorMessage("");
    setPrecheckConflict(null);
    buildMutation.mutate(requestPayload);
  }, [buildMutation, buildRequest, buildType, subjectId]);

  const resolvePrecheckConflict = useCallback(
    (resolution: KnowledgeBuildResolution) => {
      if (!subjectId) {
        setErrorMessage("缺少学科 ID，暂时无法发起知识构建。");
        return;
      }

      const basePayload =
        pendingRequestRef.current ?? { ...buildRequest(), build_type: buildType };
      const nextPayload = {
        ...basePayload,
        embedding_resolution: resolution,
      } satisfies KnowledgeBuildRequestPayload;

      pendingRequestRef.current = basePayload;
      setErrorMessage("");
      buildMutation.mutate(nextPayload);
    },
    [buildMutation, buildRequest, buildType, subjectId],
  );

  const closePrecheckConflict = useCallback(() => {
    if (buildMutation.isPending) {
      return;
    }
    setPrecheckConflict(null);
  }, [buildMutation.isPending]);

  return {
    submitBuild,
    resolvePrecheckConflict,
    closePrecheckConflict,
    precheckConflict,
    errorMessage,
    isPending: buildMutation.isPending,
    latestVectorStatus,
  };
}
