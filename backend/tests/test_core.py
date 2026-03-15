"""
测试基础设施层：config、exceptions、logger、subject 校验
"""

import pytest
from http import HTTPStatus


# ─── Config ───


class TestConfig:
    def test_settings_loads_with_env(self, monkeypatch):
        """Settings 能从环境变量加载。"""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "qwen-turbo")

        from app.core.config import Settings
        s = Settings()
        assert s.llm_api_key == "test-key"
        assert s.llm_model == "qwen-turbo"

    def test_settings_defaults(self, monkeypatch):
        """可选配置项有默认值。"""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.delenv("DATA_DIR", raising=False)
        from app.core.config import Settings
        s = Settings()
        assert s.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert s.llm_model == "qwen-plus"
        assert s.data_dir == "./data"
        assert s.max_upload_size_mb == 50
        assert s.rag_top_k == 5

    def test_embedding_dim_auto_derived(self, monkeypatch):
        """embedding_dim 由 embedding_model 自动推导。"""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        from app.core.config import Settings

        s = Settings(embedding_model="text-embedding-v3")
        assert s.embedding_dim == 1536

        s2 = Settings(embedding_model="text-embedding-3-large")
        assert s2.embedding_dim == 3072

    def test_embedding_dim_unknown_model_fallback(self, monkeypatch):
        """未知模型回退到默认维度 1536。"""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        from app.core.config import Settings
        s = Settings(embedding_model="unknown-model-xyz")
        assert s.embedding_dim == 1536

    def test_settings_missing_api_key_is_allowed(self, monkeypatch):
        """缺少 llm_api_key 时抛出错误。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        from app.core.config import Settings
        s = Settings(_env_file=None)
        assert s.llm_api_key is None

    def test_require_llm_api_key_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        from app.core.config import Settings
        from app.core.exceptions import MissingLLMApiKeyError
        s = Settings(_env_file=None)
        with pytest.raises(MissingLLMApiKeyError):
            s.require_llm_api_key()


# ─── Exceptions ───


class TestExceptions:
    def test_base_error(self):
        from app.core.exceptions import AITeachMeError
        err = AITeachMeError("test error")
        assert str(err) == "test error"
        assert err.detail == "test error"
        assert err.error_code == "AITEACHME_ERROR"
        assert err.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_invalid_subject_error(self):
        from app.core.exceptions import InvalidSubjectError
        err = InvalidSubjectError("bad/name")
        assert "bad/name" in err.detail
        assert err.error_code == "INVALID_SUBJECT"
        assert err.status_code == HTTPStatus.BAD_REQUEST

    def test_file_too_large_error(self):
        from app.core.exceptions import FileTooLargeError
        err = FileTooLargeError(50)
        assert "50MB" in err.detail
        assert err.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def test_unsupported_file_type_error(self):
        from app.core.exceptions import UnsupportedFileTypeError
        err = UnsupportedFileTypeError(".xyz")
        assert ".xyz" in err.detail

    def test_llm_call_error(self):
        from app.core.exceptions import LLMCallError
        err = LLMCallError("timeout")
        assert "timeout" in err.detail
        assert err.status_code == HTTPStatus.BAD_GATEWAY

    def test_exam_not_found_error(self):
        from app.core.exceptions import ExamNotFoundError
        err = ExamNotFoundError(42)
        assert "42" in err.detail
        assert err.status_code == HTTPStatus.NOT_FOUND

    def test_missing_llm_api_key_error(self):
        from app.core.exceptions import MissingLLMApiKeyError
        err = MissingLLMApiKeyError()
        assert "LLM_API_KEY" in err.detail
        assert err.error_code == "LLM_API_KEY_MISSING"
        assert err.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_custom_error_code_override(self):
        from app.core.exceptions import AITeachMeError
        err = AITeachMeError("custom", error_code="CUSTOM", status_code=418)
        assert err.error_code == "CUSTOM"
        assert err.status_code == 418


# ─── Logger ───


class TestLogger:
    def test_structlog_configured(self):
        """structlog 配置后能正常获取 logger。"""
        import structlog
        logger = structlog.get_logger()
        assert logger is not None


# ─── Subject Validation ───


class TestSubjectValidation:
    def test_valid_subject(self):
        from app.utils.subject import validate_subject
        assert validate_subject("math") == "math"
        assert validate_subject("Math-101") == "math-101"
        assert validate_subject("CS_200") == "cs_200"

    def test_subject_lowercased(self):
        from app.utils.subject import validate_subject
        assert validate_subject("PHYSICS") == "physics"
        assert validate_subject("Math") == "math"

    def test_invalid_subject_special_chars(self):
        from app.core.exceptions import InvalidSubjectError
        from app.utils.subject import validate_subject
        with pytest.raises(InvalidSubjectError):
            validate_subject("math/101")
        with pytest.raises(InvalidSubjectError):
            validate_subject("math\\101")
        with pytest.raises(InvalidSubjectError):
            validate_subject("math..101")

    def test_invalid_subject_empty(self):
        from app.core.exceptions import InvalidSubjectError
        from app.utils.subject import validate_subject
        with pytest.raises(InvalidSubjectError):
            validate_subject("")

    def test_invalid_subject_too_long(self):
        from app.core.exceptions import InvalidSubjectError
        from app.utils.subject import validate_subject
        with pytest.raises(InvalidSubjectError):
            validate_subject("a" * 65)

    def test_valid_subject_max_length(self):
        from app.utils.subject import validate_subject
        result = validate_subject("a" * 64)
        assert result == "a" * 64

    def test_invalid_subject_spaces(self):
        from app.core.exceptions import InvalidSubjectError
        from app.utils.subject import validate_subject
        with pytest.raises(InvalidSubjectError):
            validate_subject("math 101")
