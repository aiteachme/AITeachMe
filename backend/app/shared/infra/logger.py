"""结构化日志配置。

开发模式: 彩色简洁输出
生产模式: JSON结构化
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.shared.infra.runtime import is_local_mode


def configure_logging(log_level: str = "INFO") -> None:
    """初始化 structlog。"""
    use_colors = is_local_mode() and sys.stderr.isatty()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S" if use_colors else "iso"),
        structlog.processors.format_exc_info,
    ]

    if use_colors:
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=final_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
