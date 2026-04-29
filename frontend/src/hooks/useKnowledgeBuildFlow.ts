import { useCallback, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  LONG_RUNNING_API_TIMEOUT_MS,
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
import { useToast, type ToastVariant } from "../components/ui/Toast";
import { buildKnowledgeBuildRuntimeQueryKey } from "../lib/knowledgeBuildRuntime";

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
  file_ids?: string[];
  prompt?: string;
  confirmed_plan_id?: string;
}

interface KnowledgeBuildRequestPayload extends KnowledgeBuildRequestInput {
  embedding_resolution?: KnowledgeBuildResolution;
  build_type?: "docs";
}

interface UseKnowledgeBuildFlowOptions {
  subjectId: string;
  buildRequest: () => KnowledgeBuildRequestInput;
  buildType?: "docs";
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

const AUTO_DISABLE_PRECHECK_REASONS = new Set([
  "embedding_not_configured",
  "embedding_api_key_missing",
  "vector_extension_unavailable",
  "llamaindex_postgres_unavailable",
]);

function buildVectorSkipNotice(reason?: string) {
  switch (reason) {
    case "embedding_api_key_missing":
      return "当前后端缺少 embedding 调用凭证，本轮不会写入 embedding，也不会使用向量检索和 RAG。";
    case "embedding_not_configured":
      return "当前后端未配置 embedding 模型，本轮不会写入 embedding，也不会使用向量检索和 RAG。";
    case "vector_extension_unavailable":
      return "当前环境暂时不可用向量索引，本轮不会写入 embedding，也不会使用向量检索和 RAG。";
    case "llamaindex_postgres_unavailable":
      return "当前云端环境缺少向量索引依赖，本轮不会写入 embedding，也不会使用向量检索和 RAG。";
    default:
      return "当前向量能力不可用，本轮会跳过 embedding 写入、向量检索和 RAG。";
  }
}

interface VectorNoticeToast {
  title: string;
  description: string;
  variant: ToastVariant;
  duration?: number;
}

function buildVectorNoticeToast(
  status?: SubjectVectorStatusResponse | null,
): VectorNoticeToast | null {
  const notice = status?.notice?.trim();
  if (!notice) {
    return null;
  }

  if (status?.mode === "disabled") {
    return {
      title: "已切换为非向量构建",
      description: notice,
      variant: "warning",
      duration: 7000,
    };
  }

  if (notice.includes("已自动绑定当前 embedding 模型并初始化向量索引")) {
    return {
      title: "知识检索索引已准备好",
      description: "系统已完成当前学科的检索索引初始化，后续构建和问答会使用资料检索增强。",
      variant: "success",
      duration: 4500,
    };
  }

  return {
    title: "知识检索状态已更新",
    description: notice,
    variant: "info",
    duration: 5000,
  };
}

async function triggerKnowledgeBuild(
  subjectId: string,
  payload: KnowledgeBuildRequestPayload,
): Promise<DocGenBuildData> {
  const response = await apiClient<ApiResponse<DocGenBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subjectId}/knowledge/build`,
    data: payload,
    timeout: LONG_RUNNING_API_TIMEOUT_MS,
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
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const pendingRequestRef = useRef<KnowledgeBuildRequestPayload | null>(null);
  const vectorNoticeShownRef = useRef("");
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
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(subjectId) });
      const vectorToast = buildVectorNoticeToast(data.vector_status);
      if (vectorToast && vectorToast.description !== vectorNoticeShownRef.current) {
        vectorNoticeShownRef.current = vectorToast.description;
        toast({
          ...vectorToast,
          duration: vectorToast.duration ?? 5000,
        });
      }
      onSuccess?.(data);
    },
    onError: (error) => {
      const errorCode = getApiErrorCode(error);
      const errorData = getApiErrorData<KnowledgeBuildPrecheckConflictData>(error);

      if (
        errorCode === "KNOWLEDGE_BUILD_PRECHECK_CONFLICT" &&
        isKnowledgeBuildPrecheckConflictData(errorData)
      ) {
        if (AUTO_DISABLE_PRECHECK_REASONS.has(errorData.reason)) {
          const basePayload =
            pendingRequestRef.current ?? { ...buildRequest(), build_type: buildType };
          const nextPayload = {
            ...basePayload,
            embedding_resolution: "disable",
          } satisfies KnowledgeBuildRequestPayload;
          const notice = buildVectorSkipNotice(errorData.reason);
          vectorNoticeShownRef.current = notice;
          toast({
            title: "本轮已跳过向量检索",
            description: `${notice} 知识文档和知识图谱会继续构建。`,
            variant: "warning",
            duration: 7000,
          });
          setErrorMessage("");
          setPrecheckConflict(null);
          pendingRequestRef.current = basePayload;
          buildMutation.mutate(nextPayload);
          return;
        }
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

    if (!requestPayload.confirmed_plan_id) {
      setErrorMessage("知识文档构建必须先在构建方案页确认计划。请先生成并确认方案，再开始构建。");
      setPrecheckConflict(null);
      return;
    }

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
