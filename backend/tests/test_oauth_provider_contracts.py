from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.auth import _redirect_with_query
from app.models import AuthIdentity, OAuthFlow, User
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.auth import providers

_HTTPX_ASYNC_CLIENT = httpx.AsyncClient


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, OAuthFlow.__table__, AuthIdentity.__table__],
    )
    return engine


def _user(user_id: str, *, password_hash: str | None = None) -> User:
    return User(
        id=user_id,
        username=user_id,
        email=f"{user_id}@example.com",
        password_hash=password_hash,
        is_registered=True,
    )


def _config(provider: str) -> providers.ProviderConfig:
    return providers.ProviderConfig(
        provider=provider,
        app_id=f"{provider}-app",
        secret=f"{provider}-secret",
        redirect_uri=f"https://example.com/api/v1/auth/oauth/{provider}/callback",
    )


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = httpx.MockTransport(handler)

    def build_client(*args, **kwargs):
        return _HTTPX_ASYNC_CLIENT(*args, transport=transport, **kwargs)

    monkeypatch.setattr(providers.httpx, "AsyncClient", build_client)


def _state_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def test_oauth_redirect_query_is_inserted_before_fragment() -> None:
    assert _redirect_with_query(
        "/courses/one?view=docs&oauth=denied#chapter-2",
        oauth="authenticated",
        merge_job_id="merge-1",
    ) == "/courses/one?view=docs&oauth=authenticated&merge_job_id=merge-1#chapter-2"


def test_rejected_oauth_flow_consumes_state(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config("qq")
    monkeypatch.setattr(providers, "provider_config", lambda provider: config if provider == "qq" else None)
    with Session(_engine(), expire_on_commit=False) as session:
        _, authorization_url = providers.start_oauth_flow(
            session,
            provider="qq",
            mode="login",
            return_to="/",
            initiating_user=None,
            source_guest_user_id=None,
        )
        state = _state_from_url(authorization_url)
        assert providers.reject_oauth_flow(session, provider="qq", state=state).consumed_at is not None
        with pytest.raises(AITeachMeError) as replay:
            providers.reject_oauth_flow(session, provider="qq", state=state)
        assert replay.value.error_code == "OAUTH_STATE_INVALID"


@pytest.mark.anyio
async def test_google_oidc_validates_signature_nonce_and_verified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("google")
    flow = OAuthFlow(
        id="flow-google",
        state_hash="state",
        provider="google",
        provider_app_id=config.app_id,
        pkce_verifier="pkce-verifier",
        nonce="expected-nonce",
        expires_at=providers.utcnow(),
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = "test-key"

    def encoded_token(nonce: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": "https://accounts.google.com",
                "aud": config.app_id,
                "sub": "google-subject",
                "iat": now,
                "exp": now + 300,
                "nonce": nonce,
                "email": "learner@example.com",
                "email_verified": True,
                "name": "Learner",
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    token = encoded_token("expected-nonce")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json={"keys": [public_jwk]})

    _patch_http(monkeypatch, handler)
    identity = await providers._google_identity(config, flow, "authorization-code")
    assert identity.subject == "google-subject"
    assert identity.email_verified is True

    token = encoded_token("replayed-nonce")
    with pytest.raises(AITeachMeError) as invalid_nonce:
        await providers._google_identity(config, flow, "authorization-code")
    assert invalid_nonce.value.error_code == "OAUTH_NONCE_INVALID"


@pytest.mark.anyio
async def test_qq_and_wechat_read_stable_provider_subjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def qq_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2.0/token":
            return httpx.Response(200, text="access_token=qq-token&expires_in=3600")
        if request.url.path == "/oauth2.0/me":
            return httpx.Response(200, text='callback( {"client_id":"qq-app","openid":"qq-openid"} );')
        return httpx.Response(200, json={"ret": 0, "nickname": "QQ User", "figureurl_qq_2": "https://img/qq"})

    _patch_http(monkeypatch, qq_handler)
    qq_identity = await providers._qq_identity(
        _config("qq"),
        OAuthFlow(id="qq", state_hash="s", provider="qq", provider_app_id="qq-app", expires_at=providers.utcnow()),
        "code",
    )
    assert qq_identity.subject == "qq-openid"
    assert qq_identity.email is None

    def wechat_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sns/oauth2/access_token":
            return httpx.Response(200, json={"access_token": "wx-token", "openid": "wx-openid"})
        return httpx.Response(
            200,
            json={"openid": "wx-openid", "unionid": "wx-unionid", "nickname": "WX User"},
        )

    _patch_http(monkeypatch, wechat_handler)
    wechat_identity = await providers._wechat_identity(
        _config("wechat"),
        OAuthFlow(id="wx", state_hash="s", provider="wechat", provider_app_id="wechat-app", expires_at=providers.utcnow()),
        "code",
    )
    assert wechat_identity.subject == "unionid:wx-unionid"
    assert "wx-token" not in str(wechat_identity.profile)


@pytest.mark.anyio
async def test_oauth_state_is_single_use_and_return_path_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("qq")
    monkeypatch.setattr(providers, "provider_config", lambda provider: config if provider == "qq" else None)

    async def identity_reader(_config, _flow, _code):
        return providers.ExternalIdentity(
            provider="qq",
            app_id=config.app_id,
            subject="subject-new",
            email=None,
            email_verified=False,
            display_name="QQ User",
            avatar_url=None,
            profile={},
        )

    monkeypatch.setattr(providers, "_qq_identity", identity_reader)
    with Session(_engine(), expire_on_commit=False) as session:
        flow, authorization_url = providers.start_oauth_flow(
            session,
            provider="qq",
            mode="login",
            return_to="https://evil.example/steal",
            initiating_user=None,
            source_guest_user_id=None,
        )
        assert flow.return_to == "/"
        state = _state_from_url(authorization_url)
        completion = await providers.complete_oauth_flow(
            session,
            provider="qq",
            state=state,
            code="code",
            current_user=None,
        )
        assert completion.status == "authenticated"
        assert completion.user is not None

        with pytest.raises(AITeachMeError) as replay:
            await providers.complete_oauth_flow(
                session,
                provider="qq",
                state=state,
                code="code",
                current_user=None,
            )
        assert replay.value.error_code == "OAUTH_STATE_INVALID"


@pytest.mark.anyio
async def test_link_mode_never_switches_to_identity_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("qq")
    monkeypatch.setattr(providers, "provider_config", lambda provider: config if provider == "qq" else None)
    external = providers.ExternalIdentity(
        provider="qq",
        app_id=config.app_id,
        subject="already-owned",
        email=None,
        email_verified=False,
        display_name=None,
        avatar_url=None,
        profile={},
    )

    async def identity_reader(_config, _flow, _code):
        return external

    monkeypatch.setattr(providers, "_qq_identity", identity_reader)
    with Session(_engine(), expire_on_commit=False) as session:
        owner = _user("owner")
        linker = _user("linker")
        session.add_all([owner, linker])
        session.commit()
        providers._link_identity(session, user=owner, identity=external)
        _, authorization_url = providers.start_oauth_flow(
            session,
            provider="qq",
            mode="link",
            return_to="/account",
            initiating_user=linker,
            source_guest_user_id=None,
        )

        with pytest.raises(AITeachMeError) as conflict:
            await providers.complete_oauth_flow(
                session,
                provider="qq",
                state=_state_from_url(authorization_url),
                code="code",
                current_user=linker,
            )
        assert conflict.value.error_code == "OAUTH_IDENTITY_CONFLICT"
        assert session.exec(select(AuthIdentity).where(AuthIdentity.user_id == linker.id)).all() == []


def test_unlink_preserves_at_least_one_login_method() -> None:
    identity = providers.ExternalIdentity(
        provider="wechat",
        app_id="wechat-app",
        subject="unionid:only-login",
        email=None,
        email_verified=False,
        display_name=None,
        avatar_url=None,
        profile={},
    )
    with Session(_engine(), expire_on_commit=False) as session:
        user = _user("oauth-only")
        session.add(user)
        session.commit()
        linked = providers._link_identity(session, user=user, identity=identity)
        with pytest.raises(AITeachMeError) as last_identity:
            providers.unlink_identity(session, user=user, identity_id=linked.id)
        assert last_identity.value.error_code == "AUTH_LAST_IDENTITY"


def test_pending_identity_confirmation_is_short_lived_and_single_use() -> None:
    identity = {
        "provider": "google",
        "app_id": "google-app",
        "subject": "google-subject",
        "email": "owner@example.com",
        "email_verified": True,
        "target_user_id": "owner",
        "display_name": "Owner",
        "avatar_url": None,
        "profile": {},
    }
    with Session(_engine(), expire_on_commit=False) as session:
        owner = _user("owner")
        flow = OAuthFlow(
            id="pending-flow",
            state_hash="pending-state",
            provider="google",
            mode="login",
            provider_app_id="google-app",
            pending_identity_json=identity,
            consumed_at=providers.utcnow(),
            expires_at=providers.utcnow() + timedelta(minutes=10),
        )
        session.add_all([owner, flow])
        session.commit()

        assert providers.confirm_pending_oauth_identity(session, flow_id=flow.id, user=owner).id == owner.id
        with pytest.raises(AITeachMeError) as replay:
            providers.confirm_pending_oauth_identity(session, flow_id=flow.id, user=owner)
        assert replay.value.error_code == "OAUTH_CONFIRMATION_INVALID"

        expired = OAuthFlow(
            id="expired-flow",
            state_hash="expired-state",
            provider="google",
            mode="login",
            provider_app_id="google-app",
            pending_identity_json=identity,
            consumed_at=providers.utcnow(),
            expires_at=providers.utcnow() - timedelta(seconds=1),
        )
        session.add(expired)
        session.commit()
        with pytest.raises(AITeachMeError) as expired_confirmation:
            providers.confirm_pending_oauth_identity(session, flow_id=expired.id, user=owner)
        assert expired_confirmation.value.error_code == "OAUTH_CONFIRMATION_INVALID"
