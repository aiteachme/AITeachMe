import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, getApiErrorMessage } from "../api/client";
import type { CourseItem } from "../api/generated/model";
import type { ApiResponse } from "../api/types";
import { useToast } from "../components/ui/Toast";

export const courseBuildPreferencesQueryKey = (courseId: string) => ["course-build-preferences", courseId];

export async function saveCourseImageUnderstanding(courseId: string, enabled: boolean): Promise<CourseItem> {
  const response = await apiClient<ApiResponse<CourseItem>>({
    method: "POST",
    url: "/api/v1/courses/update",
    data: { course_id: courseId, image_understanding_enabled: enabled },
  });
  if (!response.data) throw new Error("未能保存图片理解设置。");
  return response.data;
}

export function useCourseBuildPreferences(courseId: string, initialImageUnderstanding = false) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const query = useQuery({
    queryKey: courseBuildPreferencesQueryKey(courseId),
    enabled: Boolean(courseId),
    staleTime: 0,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      const response = await apiClient<ApiResponse<CourseItem>>({
        method: "POST",
        url: "/api/v1/courses/detail",
        data: { course_id: courseId },
      });
      if (!response.data) throw new Error("未能读取课程设置。");
      return response.data;
    },
  });
  const mutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => saveCourseImageUnderstanding(id, enabled),
    onSuccess: (course) => {
      queryClient.setQueryData(courseBuildPreferencesQueryKey(course.course_id), course);
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
    onError: (error) => toast({
      title: "图片理解设置未保存",
      description: getApiErrorMessage(error, "请稍后再试。"),
      variant: "error",
    }),
  });
  return {
    imageUnderstandingEnabled: mutation.isPending && mutation.variables?.id === courseId
      ? mutation.variables.enabled
      : query.data?.image_understanding_enabled ?? initialImageUnderstanding,
    setImageUnderstandingEnabled: (enabled: boolean) => mutation.mutate({ id: courseId, enabled }),
    isPending: query.isPending || mutation.isPending,
    isError: query.isError,
  };
}
