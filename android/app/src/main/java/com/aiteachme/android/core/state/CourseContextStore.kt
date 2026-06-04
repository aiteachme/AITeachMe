package com.aiteachme.android.core.state

import android.content.Context
import com.aiteachme.android.core.network.dto.CourseItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class CourseContextState(
    val courses: List<CourseItem> = emptyList(),
    val selectedCourseId: String? = null,
) {
    val selectedCourse: CourseItem?
        get() = courses.firstOrNull { it.courseId == selectedCourseId }
}

class CourseContextStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(
        CourseContextState(
            selectedCourseId = readPersistedCourseId(),
        ),
    )
    val state: StateFlow<CourseContextState> = _state.asStateFlow()

    fun setCourses(courses: List<CourseItem>) {
        val current = _state.value
        val persistedSelectedId = readPersistedCourseId()
        val nextSelectedId = current.selectedCourseId
            ?.takeIf { selectedId -> courses.any { it.courseId == selectedId } }
            ?: persistedSelectedId?.takeIf { selectedId -> courses.any { it.courseId == selectedId } }
            ?: courses.firstOrNull()?.courseId
        _state.value = current.copy(
            courses = courses,
            selectedCourseId = nextSelectedId,
        )
        persistSelectedCourseId(nextSelectedId)
    }

    fun selectCourse(courseId: String) {
        val selectedId = courseId.trim().takeIf { it.isNotBlank() } ?: return
        val current = _state.value
        val nextSelectedId = selectedId.takeIf {
            current.courses.isEmpty() || current.courses.any { course -> course.courseId == selectedId }
        } ?: current.selectedCourseId
        _state.value = current.copy(selectedCourseId = nextSelectedId)
        persistSelectedCourseId(nextSelectedId)
    }

    fun upsertCourse(course: CourseItem) {
        val current = _state.value
        val exists = current.courses.any { it.courseId == course.courseId }
        val nextCourses = if (exists) {
            current.courses.map { if (it.courseId == course.courseId) course else it }
        } else {
            listOf(course) + current.courses
        }
        _state.value = current.copy(
            courses = nextCourses,
            selectedCourseId = course.courseId,
        )
        persistSelectedCourseId(course.courseId)
    }

    fun removeCourse(courseId: String) {
        val current = _state.value
        val nextCourses = current.courses.filterNot { it.courseId == courseId }
        val nextSelectedId = current.selectedCourseId
            ?.takeIf { selectedId -> selectedId != courseId && nextCourses.any { it.courseId == selectedId } }
            ?: nextCourses.firstOrNull()?.courseId
        _state.value = current.copy(
            courses = nextCourses,
            selectedCourseId = nextSelectedId,
        )
        persistSelectedCourseId(nextSelectedId)
    }

    private fun readPersistedCourseId(): String? {
        return prefs.getString(KEY_SELECTED_COURSE_ID, null)?.takeIf { it.isNotBlank() }
    }

    private fun persistSelectedCourseId(courseId: String?) {
        if (courseId.isNullOrBlank()) {
            prefs.edit().remove(KEY_SELECTED_COURSE_ID).apply()
        } else {
            prefs.edit().putString(KEY_SELECTED_COURSE_ID, courseId).apply()
        }
    }

    private companion object {
        const val PREFS_NAME = "aiteachme_course_context"
        const val KEY_SELECTED_COURSE_ID = "selected_course_id"
    }
}
