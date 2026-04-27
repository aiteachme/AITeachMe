from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from app.models.email_confirmation import EmailConfirmation
from app.schemas.system import FeedbackRequest
from app.shared.infra.exceptions import AuthNotReadyError
from app.workflows.support.auth.sessions import _auth_token_secret, purge_expired_email_confirmations
from app.utils.time import utcnow


def test_cloud_auth_requires_configured_token_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "cloud")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "")

    with pytest.raises(AuthNotReadyError):
        _auth_token_secret()


def test_local_auth_can_use_dev_token_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "")

    assert _auth_token_secret() == "aiteachme-dev-token-secret"


def test_feedback_rejects_empty_or_large_content() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(content="")

    with pytest.raises(ValidationError):
        FeedbackRequest(content="x" * 2001)


def test_feedback_rejects_invalid_or_excessive_images() -> None:
    valid_image = "data:image/png;base64,abcd"
    FeedbackRequest(content="页面有问题", images=[valid_image])

    with pytest.raises(ValidationError):
        FeedbackRequest(content="页面有问题", images=["https://example.com/a.png"])

    with pytest.raises(ValidationError):
        FeedbackRequest(content="页面有问题", images=[valid_image, valid_image, valid_image, valid_image])


def test_purge_expired_email_confirmations_removes_stale_rows(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_EMAIL_CONFIRMATION_RETENTION_DAYS", "7")
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[EmailConfirmation.__table__])
    now = utcnow()

    with Session(engine) as session:
        stale = EmailConfirmation(
            email="old@example.com",
            code_hash="old",
            expires_at=now.replace(year=2020),
        )
        fresh = EmailConfirmation(
            email="fresh@example.com",
            code_hash="fresh",
            expires_at=now,
        )
        session.add(stale)
        session.add(fresh)
        session.commit()

        deleted = purge_expired_email_confirmations(session, now=now)
        remaining = session.get(EmailConfirmation, fresh.id)

    assert deleted == 1
    assert remaining is not None
