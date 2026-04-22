"""Structured logging helpers for local and production runtimes."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog

from app.shared.infra.runtime import is_local_mode

_DEFAULT_LOG_LEVEL = logging.INFO
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "credential",
    "session_key",
    "private_key",
    "webhook",
)
_REDACTED = "***"
_NOISY_LOGGER_LEVELS: dict[str, int] = {
    "uvicorn.access": logging.WARNING,
    "httpx": logging.WARNING,
    "LiteLLM": logging.WARNING,
    "watchfiles.main": logging.WARNING,
}
_FORWARDED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "gunicorn",
    "gunicorn.error",
    "gunicorn.access",
)


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): (
                _REDACTED if _looks_sensitive_key(str(child_key)) else _redact_value(child_value)
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, set):
        return {_redact_value(item) for item in value}
    return value


def _redact_event_dict(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    del logger, method_name
    sanitized: dict[str, Any] = {}
    for key, value in event_dict.items():
        sanitized[key] = _REDACTED if _looks_sensitive_key(str(key)) else _redact_value(value)
    return sanitized


def clear_logging_context() -> None:
    structlog.contextvars.clear_contextvars()


def bind_logging_context(**values: Any) -> None:
    normalized = {
        key: value
        for key, value in values.items()
        if value not in (None, "", [], {}, ())
    }
    if normalized:
        structlog.contextvars.bind_contextvars(**normalized)


def _build_renderer(*, log_format: str, use_colors: bool):
    if log_format == "json":
        return structlog.processors.JSONRenderer(ensure_ascii=False, sort_keys=True)
    return structlog.dev.ConsoleRenderer(colors=use_colors)


def configure_logging() -> None:
    """Configure structlog for the whole backend process."""

    local_mode = is_local_mode()
    resolved_format = "pretty" if local_mode else "json"
    use_colors = local_mode and sys.stderr.isatty()

    base_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="%H:%M:%S" if use_colors else "iso", utc=not use_colors),
        _redact_event_dict,
        structlog.processors.format_exc_info,
    ]
    structlog_processors = [
        structlog.stdlib.filter_by_level,
        *base_processors,
    ]

    renderer = _build_renderer(log_format=resolved_format, use_colors=use_colors)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=base_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    structlog.configure(
        processors=structlog_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(_DEFAULT_LOG_LEVEL)

    for logger_name in _FORWARDED_LOGGERS:
        forwarded_logger = logging.getLogger(logger_name)
        forwarded_logger.handlers.clear()
        forwarded_logger.propagate = True

    for logger_name, level in _NOISY_LOGGER_LEVELS.items():
        logging.getLogger(logger_name).setLevel(level)

    logging.captureWarnings(True)


__all__ = [
    "bind_logging_context",
    "clear_logging_context",
    "configure_logging",
]
