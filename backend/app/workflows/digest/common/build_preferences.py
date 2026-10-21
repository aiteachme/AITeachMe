"""Persist the user's Digest lane choice without changing embedding settings."""

from collections.abc import Sequence

from app.models.course import Course
from app.models.raw_file import RawFile
from app.shared.infra.course.settings import dump_course_settings, load_course_settings


def get_image_understanding_enabled(course: Course) -> bool:
    preferences = (load_course_settings(course).model_extra or {}).get("digest", {})
    return isinstance(preferences, dict) and preferences.get("image_understanding_enabled") is True


def set_image_understanding_enabled(course: Course, enabled: bool) -> None:
    settings = load_course_settings(course)
    previous = (settings.model_extra or {}).get("digest", {})
    preferences = dict(previous) if isinstance(previous, dict) else {}
    preferences["image_understanding_enabled"] = enabled
    dump_course_settings(course, settings.model_copy(update={"digest": preferences}))


def resolve_image_understanding_enabled(enabled: bool, files: Sequence[RawFile]) -> bool:
    # Missing counts mean discovery has not run yet, rather than no images.
    return enabled and any(file.image_count is None or file.image_count > 0 for file in files)
