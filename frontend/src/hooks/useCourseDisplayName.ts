import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { listCoursesApiApiV1CoursesListPost } from "../api/generated/courses";
import type { CourseItem } from "../api/generated/model";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";

export function getCourseDisplayName(course: { name?: string | null } | null | undefined, fallback = "未命名课程") {
  return course?.name?.trim() || fallback;
}

export function useCourseDisplayName(courseId: string | null | undefined) {
  const coursesQuery = useQuery({
    queryKey: ["courses"],
    queryFn: async (): Promise<CourseItem[]> =>
      unwrapOrvalResponse(
        await listCoursesApiApiV1CoursesListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
    enabled: Boolean(courseId),
  });

  const course = useMemo<CourseItem | null>(
    () => coursesQuery.data?.find((item) => item.course_id === courseId) ?? null,
    [coursesQuery.data, courseId],
  );

  return {
    course,
    courseName: course ? getCourseDisplayName(course) : null,
    isLoading: coursesQuery.isLoading,
  };
}
