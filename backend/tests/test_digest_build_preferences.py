import json

from app.models.course import Course
from app.workflows.digest.common.build_preferences import get_image_understanding_enabled, set_image_understanding_enabled


def test_image_preference_roundtrip_preserves_other_course_settings():
    course = Course(id="course_preference", user_id="u", name="Example", settings_json=json.dumps({
        "embedding": None, "icon_key": "calculator", "digest": {"future_option": "keep"},
    }))
    assert get_image_understanding_enabled(course) is False
    set_image_understanding_enabled(course, True)
    assert get_image_understanding_enabled(course) is True
    restored = Course(id=course.id, user_id=course.user_id, name=course.name, settings_json=course.settings_json)
    assert get_image_understanding_enabled(restored) is True
    set_image_understanding_enabled(restored, False)
    assert get_image_understanding_enabled(restored) is False
    settings = json.loads(restored.settings_json)
    assert settings["icon_key"] == "calculator"
    assert settings["digest"]["future_option"] == "keep"
    assert settings["embedding"] is None
