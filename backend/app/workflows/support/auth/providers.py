"""Google OIDC, QQ Connect, and WeChat Open Platform Web OAuth."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta, timezone
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

import httpx
import jwt
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import AuthIdentity, OAuthFlow, User
from app.repositories.user_repo import create_user, get_user_by_email, get_user_by_username
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow

_PROVIDERS = ("google", "qq", "wechat")
_LABELS = {"google": "Google", "qq": "QQ", "wechat": "微信"}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    app_id: str
    secret: str
    redirect_uri: str


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    app_id: str
    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None
    avatar_url: str | None
    profile: dict


@dataclass(frozen=True)
class OAuthCompletion:
    status: str
    flow: OAuthFlow
    user: User | None = None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def provider_config(provider: str) -> ProviderConfig | None:
    normalized = provider.strip().lower()
    if normalized == "google":
        values = (
            get_env("GOOGLE_OAUTH_CLIENT_ID"),
            get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
            get_env("GOOGLE_OAUTH_REDIRECT_URI"),
        )
    elif normalized == "qq":
        values = (
            get_env("QQ_OAUTH_APP_ID"),
            get_env("QQ_OAUTH_APP_KEY"),
            get_env("QQ_OAUTH_REDIRECT_URI"),
        )
    elif normalized == "wechat":
        values = (
            get_env("WECHAT_OPEN_APP_ID"),
            get_env("WECHAT_OPEN_APP_SECRET"),
            get_env("WECHAT_OPEN_REDIRECT_URI"),
        )
    else:
        return None
    app_id, secret, redirect_uri = ((value or "").strip() for value in values)
    if not app_id or not secret or not redirect_uri:
        return None
    return ProviderConfig(normalized, app_id, secret, redirect_uri)


def configured_providers() -> list[dict[str, str]]:
    return [
        {"provider": provider, "label": _LABELS[provider]}
        for provider in _PROVIDERS
        if provider_config(provider) is not None
    ]


def safe_return_to(value: str | None) -> str:
    normalized = (value or "/").strip()
    if not normalized.startswith("/") or normalized.startswith("//") or "\\" in normalized:
        return "/"
    return normalized[:500]


def start_oauth_flow(
    session: Session,
    *,
    provider: str,
    mode: str,
    return_to: str,
    initiating_user: User | None,
    source_guest_user_id: str | None,
) -> tuple[OAuthFlow, str]:
    config = provider_config(provider)
    if config is None:
        raise AITeachMeError(
            detail="该第三方登录尚未完成配置。",
            status_code=404,
            error_code="OAUTH_PROVIDER_UNAVAILABLE",
        )
    if mode == "link" and (initiating_user is None or not initiating_user.is_registered):
        raise AITeachMeError(detail="绑定登录方式前请先登录。", status_code=401, error_code="AUTH_REQUIRED")

    raw_state = secrets.token_urlsafe(40)
    verifier = secrets.token_urlsafe(64) if provider == "google" else None
    nonce = secrets.token_urlsafe(32) if provider == "google" else None
    now = utcnow()
    flow = OAuthFlow(
        id=f"oaf_{uuid4().hex}",
        state_hash=_sha256(raw_state),
        provider=provider,
        mode=mode,
        provider_app_id=config.app_id,
        initiating_user_id=initiating_user.id if initiating_user else None,
        source_guest_user_id=source_guest_user_id,
        pkce_verifier=verifier,
        nonce=nonce,
        return_to=safe_return_to(return_to),
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    session.add(flow)
    session.commit()
    return flow, _authorization_url(config, flow=flow, state=raw_state)


def _authorization_url(config: ProviderConfig, *, flow: OAuthFlow, state: str) -> str:
    if config.provider == "google":
        challenge = _b64url(hashlib.sha256((flow.pkce_verifier or "").encode("ascii")).digest())
        params = {
            "client_id": config.app_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": flow.nonce or "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    if config.provider == "qq":
        params = {
            "response_type": "code",
            "client_id": config.app_id,
            "redirect_uri": config.redirect_uri,
            "state": state,
            "scope": "get_user_info",
        }
        return "https://graph.qq.com/oauth2.0/authorize?" + urlencode(params)
    params = {
        "appid": config.app_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": "snsapi_login",
        "state": state,
    }
    return "https://open.weixin.qq.com/connect/qrconnect?" + urlencode(params) + "#wechat_redirect"


def _consume_flow(session: Session, *, provider: str, state: str) -> OAuthFlow:
    now = utcnow()
    flow_id = session.exec(
        sa.update(OAuthFlow)
        .where(
            OAuthFlow.provider == provider,
            OAuthFlow.state_hash == _sha256(state),
            OAuthFlow.consumed_at.is_(None),
            OAuthFlow.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(OAuthFlow.id)
    ).first()
    if flow_id is None:
        session.rollback()
        raise AITeachMeError(
            detail="OAuth state 无效、已使用或已过期。",
            status_code=400,
            error_code="OAUTH_STATE_INVALID",
        )
    session.commit()
    flow = session.get(OAuthFlow, flow_id)
    if flow is None:
        raise RuntimeError("Consumed OAuth flow disappeared.")
    return flow


def reject_oauth_flow(session: Session, *, provider: str, state: str) -> OAuthFlow:
    """Consume a provider-denied flow so its state cannot be replayed."""

    return _consume_flow(session, provider=provider, state=state)


async def _google_identity(config: ProviderConfig, flow: OAuthFlow, code: str) -> ExternalIdentity:
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": config.app_id,
                "client_secret": config.secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": flow.pkce_verifier,
            },
        )
        token_response.raise_for_status()
        id_token = str(token_response.json().get("id_token") or "")
        jwks_response = await client.get("https://www.googleapis.com/oauth2/v3/certs")
        jwks_response.raise_for_status()
    if not id_token:
        raise AITeachMeError(detail="Google 未返回身份令牌。", status_code=400, error_code="OAUTH_ID_TOKEN_MISSING")
    header = jwt.get_unverified_header(id_token)
    key_data = next(
        (item for item in jwks_response.json().get("keys", []) if item.get("kid") == header.get("kid")),
        None,
    )
    if key_data is None:
        raise AITeachMeError(detail="Google 签名密钥不匹配。", status_code=400, error_code="OAUTH_ID_TOKEN_INVALID")
    unverified = jwt.decode(id_token, options={"verify_signature": False})
    issuer = unverified.get("iss")
    if issuer not in {"https://accounts.google.com", "accounts.google.com"}:
        raise AITeachMeError(detail="Google issuer 无效。", status_code=400, error_code="OAUTH_ID_TOKEN_INVALID")
    claims = jwt.decode(
        id_token,
        jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data)),
        algorithms=["RS256"],
        audience=config.app_id,
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "nonce"]},
    )
    if not secrets.compare_digest(str(claims.get("nonce") or ""), str(flow.nonce or "")):
        raise AITeachMeError(detail="Google nonce 校验失败。", status_code=400, error_code="OAUTH_NONCE_INVALID")
    if claims.get("email_verified") is not True:
        raise AITeachMeError(detail="Google 邮箱尚未验证。", status_code=400, error_code="OAUTH_EMAIL_UNVERIFIED")
    return ExternalIdentity(
        provider="google",
        app_id=config.app_id,
        subject=str(claims["sub"]),
        email=str(claims.get("email") or "").lower() or None,
        email_verified=True,
        display_name=str(claims.get("name") or "") or None,
        avatar_url=str(claims.get("picture") or "") or None,
        profile={"locale": claims.get("locale")},
    )


def _parse_qq_jsonp(value: str) -> dict:
    match = re.search(r"callback\s*\(\s*(\{.*\})\s*\)\s*;?", value, flags=re.S)
    if not match:
        raise AITeachMeError(detail="QQ openid 响应无效。", status_code=400, error_code="OAUTH_PROVIDER_RESPONSE_INVALID")
    return json.loads(match.group(1))


async def _qq_identity(config: ProviderConfig, flow: OAuthFlow, code: str) -> ExternalIdentity:
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.get(
            "https://graph.qq.com/oauth2.0/token",
            params={
                "grant_type": "authorization_code",
                "client_id": config.app_id,
                "client_secret": config.secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        token_response.raise_for_status()
        token_data = parse_qs(token_response.text)
        access_token = (token_data.get("access_token") or [""])[0]
        me_response = await client.get("https://graph.qq.com/oauth2.0/me", params={"access_token": access_token})
        me_response.raise_for_status()
        me = _parse_qq_jsonp(me_response.text)
        openid = str(me.get("openid") or "")
        profile_response = await client.get(
            "https://graph.qq.com/user/get_user_info",
            params={"access_token": access_token, "oauth_consumer_key": config.app_id, "openid": openid},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
    if not access_token or not openid or int(profile.get("ret", -1)) != 0:
        raise AITeachMeError(detail="QQ 身份读取失败。", status_code=400, error_code="OAUTH_PROVIDER_RESPONSE_INVALID")
    return ExternalIdentity(
        provider="qq", app_id=config.app_id, subject=openid, email=None, email_verified=False,
        display_name=str(profile.get("nickname") or "") or None,
        avatar_url=str(profile.get("figureurl_qq_2") or profile.get("figureurl_qq_1") or "") or None,
        profile={"gender": profile.get("gender")},
    )


async def _wechat_identity(config: ProviderConfig, flow: OAuthFlow, code: str) -> ExternalIdentity:
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={"appid": config.app_id, "secret": config.secret, "code": code, "grant_type": "authorization_code"},
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = str(token_data.get("access_token") or "")
        openid = str(token_data.get("openid") or "")
        profile_response = await client.get(
            "https://api.weixin.qq.com/sns/userinfo",
            params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
    if not access_token or not openid or profile.get("errcode"):
        raise AITeachMeError(detail="微信身份读取失败。", status_code=400, error_code="OAUTH_PROVIDER_RESPONSE_INVALID")
    unionid = str(profile.get("unionid") or token_data.get("unionid") or "")
    subject = f"unionid:{unionid}" if unionid else f"openid:{openid}"
    return ExternalIdentity(
        provider="wechat", app_id=config.app_id, subject=subject, email=None, email_verified=False,
        display_name=str(profile.get("nickname") or "") or None,
        avatar_url=str(profile.get("headimgurl") or "") or None,
        profile={"unionid_present": bool(unionid), "country": profile.get("country"), "province": profile.get("province")},
    )


def _identity_record(session: Session, identity: ExternalIdentity) -> AuthIdentity | None:
    return session.exec(
        select(AuthIdentity).where(
            AuthIdentity.provider == identity.provider,
            AuthIdentity.provider_app_id == identity.app_id,
            AuthIdentity.provider_subject == identity.subject,
        )
    ).first()


def _link_identity(session: Session, *, user: User, identity: ExternalIdentity) -> AuthIdentity:
    existing = _identity_record(session, identity)
    if existing is not None:
        if existing.user_id != user.id:
            raise AITeachMeError(detail="该第三方身份已绑定其他账号。", status_code=409, error_code="OAUTH_IDENTITY_CONFLICT")
        return existing
    record = AuthIdentity(
        id=f"aid_{uuid4().hex}", user_id=user.id, provider=identity.provider,
        provider_app_id=identity.app_id, provider_subject=identity.subject,
        provider_email=identity.email, provider_email_verified=identity.email_verified,
        profile_json=identity.profile, created_at=utcnow(), updated_at=utcnow(), last_login_at=utcnow(),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _identity_record(session, identity)
        if existing is None or existing.user_id != user.id:
            raise AITeachMeError(detail="第三方身份绑定冲突。", status_code=409, error_code="OAUTH_IDENTITY_CONFLICT")
        return existing
    return record


def _oauth_username(session: Session, identity: ExternalIdentity) -> str:
    prefix = {"google": "google", "qq": "qq", "wechat": "wx"}[identity.provider]
    base = f"{prefix}_{hashlib.sha256(identity.subject.encode('utf-8')).hexdigest()[:12]}"
    candidate = base
    suffix = 1
    while get_user_by_username(session, candidate) is not None:
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate


async def complete_oauth_flow(
    session: Session,
    *,
    provider: str,
    state: str,
    code: str,
    current_user: User | None,
) -> OAuthCompletion:
    config = provider_config(provider)
    if config is None:
        raise AITeachMeError(detail="该第三方登录不可用。", status_code=404, error_code="OAUTH_PROVIDER_UNAVAILABLE")
    flow = _consume_flow(session, provider=provider, state=state)
    if flow.provider_app_id != config.app_id:
        raise AITeachMeError(detail="OAuth 应用标识不匹配。", status_code=400, error_code="OAUTH_APP_MISMATCH")
    try:
        if provider == "google":
            identity = await _google_identity(config, flow, code)
        elif provider == "qq":
            identity = await _qq_identity(config, flow, code)
        else:
            identity = await _wechat_identity(config, flow, code)
    except httpx.HTTPError as exc:
        raise AITeachMeError(
            detail="第三方登录服务暂时不可用，请稍后重试。",
            status_code=502,
            error_code="OAUTH_PROVIDER_UNAVAILABLE",
        ) from exc

    existing = _identity_record(session, identity)
    if flow.mode == "link":
        if current_user is None or current_user.id != flow.initiating_user_id:
            raise AITeachMeError(detail="绑定会话已变化，请重新发起。", status_code=403, error_code="OAUTH_LINK_SESSION_MISMATCH")
        if existing is not None and existing.user_id != current_user.id:
            raise AITeachMeError(detail="该第三方身份已绑定其他账号。", status_code=409, error_code="OAUTH_IDENTITY_CONFLICT")
        _link_identity(session, user=current_user, identity=identity)
        return OAuthCompletion("linked", flow, current_user)

    if existing is not None:
        user = session.get(User, existing.user_id)
        if user is None or not user.is_registered or user.merged_into_user_id is not None:
            raise AITeachMeError(detail="绑定账号不可用。", status_code=409, error_code="OAUTH_ACCOUNT_UNAVAILABLE")
        existing.last_login_at = utcnow()
        session.add(existing)
        session.commit()
        return OAuthCompletion("authenticated", flow, user)

    if identity.email_verified and identity.email:
        same_email = get_user_by_email(session, identity.email)
        if same_email is not None and same_email.is_registered:
            confirmation_started_at = utcnow()
            flow.pending_identity_json = {
                "provider": identity.provider, "app_id": identity.app_id, "subject": identity.subject,
                "email": same_email.email, "email_verified": True, "target_user_id": same_email.id,
                "display_name": identity.display_name,
                "avatar_url": identity.avatar_url, "profile": identity.profile,
            }
            # The provider callback consumes the original OAuth state. Give the
            # explicit account-ownership confirmation its own short deadline.
            flow.expires_at = confirmation_started_at + timedelta(minutes=10)
            session.add(flow)
            session.commit()
            return OAuthCompletion("confirmation_required", flow, None)

    user = create_user(
        session,
        username=_oauth_username(session, identity),
        email=identity.email if identity.email_verified else None,
        is_registered=True,
    )
    user.display_name = identity.display_name
    user.avatar_url = identity.avatar_url
    user.email_verified_at = utcnow() if identity.email_verified else None
    session.add(user)
    session.commit()
    _link_identity(session, user=user, identity=identity)
    return OAuthCompletion("authenticated", flow, user)


def confirm_pending_oauth_identity(
    session: Session,
    *,
    flow_id: str,
    user: User,
) -> User:
    flow = session.get(OAuthFlow, flow_id)
    pending = dict(flow.pending_identity_json or {}) if flow is not None else {}
    now = utcnow()
    expired = (
        flow is not None
        and flow.expires_at.replace(tzinfo=flow.expires_at.tzinfo or timezone.utc) <= now
    )
    if (
        flow is None
        or flow.mode != "login"
        or flow.consumed_at is None
        or expired
        or not pending
        or pending.get("target_user_id") != user.id
        or pending.get("email") != user.email
        or not user.is_registered
        or user.merged_into_user_id is not None
    ):
        raise AITeachMeError(detail="待确认身份不存在或不匹配。", status_code=400, error_code="OAUTH_CONFIRMATION_INVALID")
    identity = ExternalIdentity(
        provider=str(pending["provider"]), app_id=str(pending["app_id"]), subject=str(pending["subject"]),
        email=str(pending.get("email") or "") or None, email_verified=bool(pending.get("email_verified")),
        display_name=str(pending.get("display_name") or "") or None,
        avatar_url=str(pending.get("avatar_url") or "") or None,
        profile=dict(pending.get("profile") or {}),
    )
    _link_identity(session, user=user, identity=identity)
    flow.pending_identity_json = {}
    session.add(flow)
    session.commit()
    return user


def unlink_identity(session: Session, *, user: User, identity_id: str) -> None:
    identity = session.get(AuthIdentity, identity_id)
    if identity is None or identity.user_id != user.id:
        raise AITeachMeError(detail="登录方式不存在。", status_code=404, error_code="AUTH_IDENTITY_NOT_FOUND")
    identities = session.exec(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).all()
    if not user.password_hash and len(identities) <= 1:
        raise AITeachMeError(detail="账号必须保留至少一种登录方式。", status_code=409, error_code="AUTH_LAST_IDENTITY")
    session.delete(identity)
    session.commit()
