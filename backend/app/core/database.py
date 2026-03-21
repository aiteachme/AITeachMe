"""数据库初始化、schema 校验与会话管理。"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import structlog

logger = structlog.get_logger()


def _auto_install_dependency(package_name: str) -> bool:
    """依赖缺失时尝试自动安装。"""

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        logger.error("dependency_auto_install_failed", package=package_name, error=str(exc))
        return False

    if result.returncode == 0:
        logger.warning("dependency_auto_installed", package=package_name)
        return True

    logger.error(
        "dependency_auto_install_failed",
        package=package_name,
        returncode=result.returncode,
        output=(result.stdout or result.stderr or "").strip()[-500:],
    )
    return False


def _bootstrap_sqlite_driver() -> str:
    """确保 sqlite3 驱动可用。"""

    try:
        import pysqlite3 as sqlite3  # type: ignore[import-not-found]

        sys.modules["sqlite3"] = sqlite3
        return "pysqlite3-binary"
    except ImportError:
        pass

    try:
        import sqlite3 as _sqlite3  # noqa: F401

        return "stdlib-sqlite3"
    except Exception as exc:
        if _auto_install_dependency("pysqlite3-binary"):
            try:
                import pysqlite3 as sqlite3  # type: ignore[import-not-found]

                sys.modules["sqlite3"] = sqlite3
                return "pysqlite3-binary(auto)"
            except ImportError as retry_exc:
                raise RuntimeError("自动安装 pysqlite3-binary 后仍无法导入 sqlite3 驱动。") from retry_exc
        raise RuntimeError("当前 Python 环境缺少 sqlite3 驱动，且自动安装失败。") from exc


def _bootstrap_sqlite_vec():
    """确保 sqlite-vec 包可导入。"""

    try:
        import sqlite_vec as sqlite_vec_module

        return sqlite_vec_module
    except ImportError as exc:
        if _auto_install_dependency("sqlite-vec"):
            try:
                import sqlite_vec as sqlite_vec_module

                return sqlite_vec_module
            except ImportError as retry_exc:
                raise RuntimeError("自动安装 sqlite-vec 后仍无法导入。") from retry_exc
        raise RuntimeError("当前环境缺少 sqlite-vec，且自动安装失败。") from exc


_SQLITE_DRIVER = _bootstrap_sqlite_driver()
sqlite_vec = _bootstrap_sqlite_vec()

try:
    import sqlite3 as _sqlite3  # noqa: F401
except Exception:
    # sqlite3 由 _bootstrap_sqlite_driver 保证，不应走到这里。
    pass

import sqlalchemy as sa
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError

_engine = None
_vec_ready: bool | None = None
_vec_error: str | None = None


class OutdatedSchemaError(RuntimeError):
    """数据库 schema 过期异常。"""

    def __init__(self, *, table_name: str, missing_columns: list[str], existing_columns: list[str]) -> None:
        self.table_name = table_name
        self.missing_columns = missing_columns
        self.existing_columns = existing_columns
        super().__init__(
            "当前开发数据库 schema 已过期。"
            f"表 `{table_name}` 缺少字段: {', '.join(missing_columns)}。"
        )


_SCHEMA_REQUIREMENTS: dict[str, set[str]] = {
    "raw_file": {
        "id",
        "subject",
        "filename",
        "filetype",
        "file_path",
        "markdown_path",
        "asset_dir",
        "status",
        "error_message",
        "created_at",
        "updated_at",
        "content_hash",
        "file_size_bytes",
        "estimated_pages",
        "detected_language",
        "classification_result",
        "quality_score",
        "parse_metadata",
        "image_count",
        "ingest_status",
    },
    "document": {
        "id",
        "subject",
        "source_file_id",
        "title",
        "markdown_content",
        "current_step",
        "created_at",
        "updated_at",
    },
    "graph_digest_job": {
        "id",
        "subject",
        "idempotency_key",
        "status",
        "progress",
        "current_step",
        "input_file_ids_json",
        "input_chunk_count",
        "error_message",
        "created_at",
        "updated_at",
    },
    "curriculum_derive_job": {
        "id",
        "subject",
        "graph_job_id",
        "status",
        "progress",
        "current_step",
        "error_message",
        "created_at",
        "updated_at",
    },
}

_ASSESSMENT_TABLES: set[str] = {
    "question_template",
    "question_template_node_link",
    "exam_paper",
    "exam_paper_item",
    "user_answer_attempt",
    "user_knowledge_state",
    "review_task",
    "exam_paper_generation_context",
    "question_build_job",
    "exam_generate_job",
    "exam_grade_job",
}

_ASSESSMENT_PARTIAL_UNIQUE_INDEX_DDLS: tuple[str, ...] = (
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_task_pending "
        "ON review_task (user_id, subject, target_id, target_granularity) "
        "WHERE status = 'pending'"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_job_active "
        "ON exam_grade_job (exam_paper_id) "
        "WHERE status IN ('pending', 'running')"
    ),
)


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    """返回向量扩展是否可用。"""

    return bool(_vec_ready)


def require_vec_ready() -> None:
    """要求 sqlite-vec 已可用。"""

    if not is_vec_ready():
        raise VectorExtensionUnavailableError(_vec_error or "")


def get_vec_status() -> tuple[bool | None, str | None]:
    """返回向量扩展状态与错误信息。"""

    return _vec_ready, _vec_error


def reset_runtime_state() -> None:
    """重置全局单例，便于本地冒烟测试。"""

    global _engine, _vec_ready, _vec_error
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _vec_ready = None
    _vec_error = None


def _load_vec_extension(dbapi_conn) -> None:
    can_toggle_extensions = hasattr(dbapi_conn, "enable_load_extension")

    try:
        if can_toggle_extensions:
            dbapi_conn.enable_load_extension(True)

        sqlite_vec.load(dbapi_conn)
        _set_vec_status(True, None)
        logger.info(
            "sqlite_vec_loaded",
            sqlite_driver=_SQLITE_DRIVER,
            supports_enable_load_extension=can_toggle_extensions,
        )
    except Exception as exc:
        _set_vec_status(False, str(exc))
        logger.warning(
            "sqlite_vec_unavailable",
            sqlite_driver=_SQLITE_DRIVER,
            supports_enable_load_extension=can_toggle_extensions,
            error=str(exc),
        )
    finally:
        if can_toggle_extensions:
            try:
                dbapi_conn.enable_load_extension(False)
            except Exception as exc:
                logger.warning("sqlite_extension_disable_failed", error=str(exc))


def get_engine():
    """创建或返回数据库引擎。"""

    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    db_dir = Path(settings.data_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "aiteachme.db"

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(_engine, "connect")
    def load_vec_extension(dbapi_conn, connection_record):
        del connection_record
        _load_vec_extension(dbapi_conn)

    logger.info("database_engine_created", db_path=str(db_path), sqlite_driver=_SQLITE_DRIVER)
    return _engine


def _get_table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(sa.text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {row[1] for row in rows}


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = :table_name"
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _validate_runtime_schema(engine) -> None:
    """开发阶段直接校验 schema，不再兼容旧库自动迁移。"""

    database_url_path = getattr(engine.url, "database", "") or ""
    resolved_db_path = str(Path(database_url_path).resolve()) if database_url_path else "aiteachme.db"

    with engine.connect() as conn:
        for table_name, required_columns in _SCHEMA_REQUIREMENTS.items():
            if not _table_exists(conn, table_name):
                continue
            existing_columns = _get_table_columns(conn, table_name)
            missing_columns = sorted(required_columns - existing_columns)
            if not missing_columns:
                continue
            logger.error(
                "database_schema_outdated",
                table_name=table_name,
                missing_columns=missing_columns,
                existing_columns=sorted(existing_columns),
            )
            raise RuntimeError(
                "当前开发数据库 schema 已过期。"
                f"表 `{table_name}` 缺少字段: {', '.join(missing_columns)}。"
                f"请备份后删除 `{resolved_db_path}` 并重启服务。"
            )


def _ensure_assessment_schema_integrity(engine) -> None:
    """确保 assessment 表与部分唯一索引已建立。"""

    with engine.begin() as conn:
        for ddl in _ASSESSMENT_PARTIAL_UNIQUE_INDEX_DDLS:
            conn.execute(sa.text(ddl))

        missing_tables = sorted(
            table_name
            for table_name in _ASSESSMENT_TABLES
            if not _table_exists(conn, table_name)
        )
        if missing_tables:
            raise RuntimeError(
                "assessment 模块表结构缺失："
                f"{', '.join(missing_tables)}。"
                "请检查模型导入与数据库初始化流程。"
            )

        logger.info(
            "assessment_schema_ready",
            table_count=len(_ASSESSMENT_TABLES),
            ensured_indexes=["uq_review_task_pending", "uq_grade_job_active"],
        )


def init_db() -> None:
    """初始化数据库与向量表。"""

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.schema_outdated.{timestamp}{db_path.suffix}")
    index = 1
    while backup_path.exists():
        backup_path = db_path.with_name(
            f"{db_path.stem}.schema_outdated.{timestamp}.{index}{db_path.suffix}"
        )
        index += 1

    db_path.rename(backup_path)
    for sidecar_suffix in ("-wal", "-shm", "-journal"):
        old_sidecar = Path(f"{db_path}{sidecar_suffix}")
        if not old_sidecar.exists():
            continue
        new_sidecar = Path(f"{backup_path}{sidecar_suffix}")
        old_sidecar.rename(new_sidecar)

    return backup_path


def _init_db_once(engine, settings) -> None:
    SQLModel.metadata.create_all(engine)
    _validate_runtime_schema(engine)
    _ensure_assessment_schema_integrity(engine)

    if is_vec_ready():
        with engine.connect() as conn:
            conn.execute(
                sa.text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
                    f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{settings.embedding_dim}])"
                )
            )
            conn.commit()
    else:
        logger.warning(
            "database_initialized_without_vec",
            embedding_dim=settings.embedding_dim,
            sqlite_driver=_SQLITE_DRIVER,
            vec_error=_vec_error,
        )

    logger.info(
        "database_initialized",
        embedding_dim=settings.embedding_dim,
        sqlite_driver=_SQLITE_DRIVER,
        vec_ready=is_vec_ready(),
    )


def init_db() -> None:
    """初始化数据库与向量表。"""

    from app import models as _  # noqa: F401

    settings = get_settings()
    db_path = Path(settings.data_dir) / "aiteachme.db"
    engine = get_engine()

    try:
        _init_db_once(engine, settings)
    except OutdatedSchemaError as exc:
        logger.warning(
            "database_schema_outdated_auto_rebuild_start",
            table_name=exc.table_name,
            missing_columns=exc.missing_columns,
            existing_columns=exc.existing_columns,
        )

        reset_runtime_state()

        if not db_path.exists():
            raise RuntimeError("检测到 schema 过期，但未找到数据库文件，无法自动备份重建。") from exc

        backup_path = _backup_outdated_db(db_path)
        logger.warning(
            "database_schema_outdated_auto_backup_created",
            db_path=str(db_path),
            backup_path=str(backup_path),
        )

        engine = get_engine()
        _init_db_once(engine, settings)
        logger.warning(
            "database_schema_outdated_auto_rebuild_done",
            db_path=str(db_path),
            backup_path=str(backup_path),
        )


def get_session() -> Session:
    """返回一个新的数据库会话。

    .. deprecated:: 0.3.0
        优先使用 ``managed_session()`` 上下文管理器，它提供自动 commit/rollback/close。
    """

    return Session(get_engine())


@contextmanager
def managed_session() -> Generator[Session, None, None]:
    """安全的 session 上下文管理器：成功时 commit，异常时 rollback，最终 close。"""

    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
