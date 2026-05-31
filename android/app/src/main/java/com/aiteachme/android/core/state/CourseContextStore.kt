package com.aiteachme.android.core.state

import com.aiteachme.android.core.network.dto.CourseItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class CourseContextState(
    val courses: List<CourseItem> = emptyList(),
    val selectedCourseId: String? = null,
) {
    val selectedCourse: CourseItem?
        get() = courses.firstOrNull { it.courseId == selectedCourseId }
}

class CourseContextStore {
    private val _state = MutableStateFlow(CourseContextState())
    val state: StateFlow<CourseContextState> = _state.asStateFlow()

    fun setCourses(courses: List<CourseItem>) {
        _state.update { current ->
            val nextSelectedId = current.selectedCourseId
                ?.takeIf { selectedId -> courses.any { it.courseId == selectedId } }
                ?: courses.firstOrNull()?.courseId
            current.copy(
                courses = courses,
                selectedCourseId = nextSelectedId,
            )
        }
    }

    fun selectCourse(courseId: String) {
        _state.update { current ->
            current.copy(
                selectedCourseId = courseId.takeIf { selectedId ->
                    current.courses.any { it.courseId == selectedId }
                } ?: current.selectedCourseId,
            )
        }
    }

    fun upsertCourse(course: CourseItem) {
        _state.update { current ->
            val exists = current.courses.any { it.courseId == course.courseId }
            val nextCourses = if (exists) {
                current.courses.map { if (it.courseId == course.courseId) course else it }
            } else {
                listOf(course) + current.courses
            }
            current.copy(
                courses = nextCourses,
                selectedCourseId = course.courseId,
            )
        }
    }

    fun removeCourse(courseId: String) {
        _state.update { current ->
            val nextCourses = current.courses.filterNot { it.courseId == courseId }
            val nextSelectedId = current.selectedCourseId
                ?.takeIf { selectedId -> selectedId != courseId && nextCourses.any { it.courseId == selectedId } }
                ?: nextCourses.firstOrNull()?.courseId
            current.copy(
                courses = nextCourses,
                selectedCourseId = nextSelectedId,
            )
        }
    }
}
