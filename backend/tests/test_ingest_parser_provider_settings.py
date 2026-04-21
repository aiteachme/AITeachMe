from app.shared.infra.settings.settings import Settings


def test_ingest_parser_provider_defaults_to_auto() -> None:
    settings = Settings.model_validate({})

    assert settings.ingest.default_parser_provider == "auto"


def test_ingest_parser_provider_normalizes_legacy_values_to_auto() -> None:
    for legacy_value in ("docling", "unstructured", "local", "", "unknown"):
        settings = Settings.model_validate(
            {"ingest": {"default_parser_provider": legacy_value}}
        )
        assert settings.ingest.default_parser_provider == "auto"


def test_ingest_parser_provider_keeps_supported_explicit_values() -> None:
    for value in ("auto", "markitdown", "mineru"):
        settings = Settings.model_validate(
            {"ingest": {"default_parser_provider": value}}
        )
        assert settings.ingest.default_parser_provider == value
