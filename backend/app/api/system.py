"""系统初始化接口。"""

from __future__ import annotations

import base64
import binascii

import httpx
import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Response

from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.system import (
    FeedbackRequest,
    InitData,
    InitRequest,
    ModelProbeRequest,
    ModelProbeResult,
    SettingsOverviewData,
    UpdateUserSettingsRequest,
)
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.system import (
    build_init_data,
    build_settings_overview_data,
    read_community_feishu_qr_bytes,
    read_community_wechat_qr_bytes,
    test_settings_model_connection,
    update_user_settings_overview_data,
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])
logger = structlog.get_logger(__name__)
_FEEDBACK_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _feishu_webhook_accepted(response: httpx.Response) -> bool:
    if not 200 <= response.status_code < 300:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False

    code = payload.get("code", payload.get("StatusCode"))
    return isinstance(code, int) and not isinstance(code, bool) and code == 0


async def _upload_feedback_images(
    client: httpx.AsyncClient,
    *,
    images: list[str],
    app_id: str | None,
    app_secret: str | None,
) -> list[str]:
    if not images or not app_id or not app_secret:
        return []

    try:
        auth_response = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=5.0,
        )
        auth_payload = auth_response.json()
        if (
            not 200 <= auth_response.status_code < 300
            or not isinstance(auth_payload, dict)
            or auth_payload.get("code") != 0
            or not auth_payload.get("tenant_access_token")
        ):
            logger.warning(
                "feedback_image_auth_failed",
                status_code=auth_response.status_code,
            )
            return []
        tenant_access_token = str(auth_payload["tenant_access_token"])
    except (httpx.RequestError, ValueError, TypeError) as exc:
        logger.warning(
            "feedback_image_auth_failed",
            error_type=type(exc).__name__,
        )
        return []

    image_keys: list[str] = []
    for index, data_url in enumerate(images):
        try:
            _, encoded = data_url.split(",", 1)
            image_bytes = base64.b64decode(encoded, validate=True)
            upload_response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {tenant_access_token}"},
                data={"image_type": "message"},
                files={"image": (f"screenshot_{index}.png", image_bytes, "image/png")},
                timeout=10.0,
            )
            upload_payload = upload_response.json()
            upload_data = upload_payload.get("data") if isinstance(upload_payload, dict) else None
            image_key = upload_data.get("image_key") if isinstance(upload_data, dict) else None
            if (
                200 <= upload_response.status_code < 300
                and isinstance(upload_payload, dict)
                and upload_payload.get("code") == 0
                and isinstance(image_key, str)
                and image_key
            ):
                image_keys.append(image_key)
            else:
                logger.warning(
                    "feedback_image_upload_failed",
                    image_index=index,
                    status_code=upload_response.status_code,
                )
        except (binascii.Error, httpx.RequestError, ValueError, TypeError) as exc:
            logger.warning(
                "feedback_image_upload_failed",
                image_index=index,
                error_type=type(exc).__name__,
            )

    return image_keys


async def _deliver_feedback_to_feishu(
    client: httpx.AsyncClient,
    *,
    webhook_url: str,
    user_info: str,
    content: str,
    images: list[str],
    app_id: str | None,
    app_secret: str | None,
) -> None:
    image_keys = await _upload_feedback_images(
        client,
        images=images,
        app_id=app_id,
        app_secret=app_secret,
    )

    if image_keys:
        post_content: list[list[dict[str, str]]] = [
            [{"tag": "text", "text": f"内容：\n{content}\n\n附件截图：\n"}]
        ]
        post_content.extend([[{"tag": "img", "image_key": key}] for key in image_keys])
        webhook_payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📢 新的用户反馈 (来自: {user_info})",
                        "content": post_content,
                    }
                }
            },
        }
    else:
        text = f"📢 新的用户反馈 (来自: {user_info})\n\n内容：\n{content}"
        if images:
            text += f"\n\n📎 附带了 {len(images)} 张截图，但截图上传失败，请联系用户补充。"
        webhook_payload = {"msg_type": "text", "content": {"text": text}}

    response = await client.post(webhook_url, json=webhook_payload, timeout=5.0)
    if not _feishu_webhook_accepted(response):
        logger.warning(
            "feedback_webhook_rejected",
            status_code=response.status_code,
        )
        raise AITeachMeError(
            detail="反馈接收服务拒绝了本次提交，请稍后重试或通过邮箱联系我们。",
            error_code="FEEDBACK_DELIVERY_REJECTED",
            status_code=502,
        )


async def _community_qr_response(read_image_bytes, *, media_type: str, unavailable_detail: str) -> Response:
    image_bytes = await read_image_bytes()
    if image_bytes is None:
        raise HTTPException(status_code=404, detail=unavailable_detail)

    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.post(
    "/init",
    response_model=ApiResponse[InitData],
    summary="初始化系统信息",
    description="返回前端初始化所需的运行时信息。",
    responses=build_error_responses([500]),
)
async def init_system(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[InitData]:
    """初始化系统元数据。"""

    return ok_response(
        build_init_data(
            user_id=user.user_id,
            email=user.email,
            is_local=user.is_local,
            device_key=user.device_key,
            is_authenticated=user.is_authenticated,
        )
    )


@router.get(
    "/community/wechat-qr",
    summary="读取社区微信二维码",
    description="从项目公开 assets 仓库的远程图片直链读取社区微信二维码，并以 no-store 返回给前端。",
    responses=build_error_responses([404, 500]),
)
async def get_community_wechat_qr() -> Response:
    """读取社区微信二维码图片。"""

    return await _community_qr_response(
        read_community_wechat_qr_bytes,
        media_type="image/jpeg",
        unavailable_detail="社区二维码暂不可用。",
    )


@router.get(
    "/community/feishu-qr",
    summary="读取社区飞书二维码",
    description="从项目公开 assets 仓库的远程图片直链读取社区飞书二维码，并以 no-store 返回给前端。",
    responses=build_error_responses([404, 500]),
)
async def get_community_feishu_qr() -> Response:
    """读取社区飞书二维码图片。"""

    return await _community_qr_response(
        read_community_feishu_qr_bytes,
        media_type="image/png",
        unavailable_detail="社区飞书二维码暂不可用。",
    )


@router.post(
    "/settings",
    response_model=ApiResponse[SettingsOverviewData],
    summary="读取后端设置总览",
    description="返回环境变量、代码默认值与可选项目 settings override 合并后的只读设置概览。",
    responses=build_error_responses([500]),
)
async def get_system_settings(
    _: InitRequest = Body(default=InitRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SettingsOverviewData]:
    """读取后端设置概览。"""

    return ok_response(build_settings_overview_data(session=session, user_id=user.user_id))


@router.patch(
    "/settings",
    response_model=ApiResponse[SettingsOverviewData],
    summary="更新本地模式服务端设置",
    description="本地模式下保存非敏感系统设置覆盖，并可写回本地 .env；云端普通用户无写权限。",
    responses=build_error_responses([422, 500]),
)
async def update_system_settings(
    payload: UpdateUserSettingsRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SettingsOverviewData]:
    """更新本地模式服务端设置。"""

    return ok_response(
        update_user_settings_overview_data(
            session=session,
            user_id=user.user_id,
            settings_payload=payload.settings,
            env_payload=payload.env,
            reset=payload.reset,
        )
    )


@router.post(
    "/settings/model-probe",
    response_model=ApiResponse[ModelProbeResult],
    summary="测试设置页模型连通性",
    description="按 reason / primary / light 槽位测试主模型网关或备用模型网关。主网关按当前主模型路由测试，备用网关强制 Chat Completions 并快速失败。",
    responses=build_error_responses([422, 500]),
)
async def probe_system_settings_model(
    payload: ModelProbeRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[ModelProbeResult]:
    """测试设置页模型连通性。"""

    logger.info(
        "settings_model_probe_requested",
        user_id=user.user_id,
        model_slot=payload.model_slot,
        endpoint_role=payload.endpoint_role,
    )
    return ok_response(await test_settings_model_connection(payload))


@router.post(
    "/feedback",
    response_model=ApiResponse[bool],
    summary="提交意见反馈",
    description="接收用户的意见反馈及可选截图。",
    responses=build_error_responses([401, 500, 502, 503]),
)
async def submit_feedback(
    payload: FeedbackRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[bool]:
    """提交用户反馈。"""

    if not user.is_local and not user.is_authenticated:
        raise AITeachMeError(
            detail="请登录后再提交反馈。",
            error_code="FEEDBACK_AUTHENTICATION_REQUIRED",
            status_code=401,
        )

    logger.info(
        "feedback_submission_received",
        user_id=user.user_id,
        has_email=bool(user.email),
        email_domain=(user.email.rsplit("@", 1)[-1].lower() if user.email and "@" in user.email else None),
        content_chars=len(payload.content),
        image_count=len(payload.images),
    )

    feishu_webhook = (get_env("FEISHU_WEBHOOK_URL") or "").strip()
    if not feishu_webhook:
        logger.warning("feedback_webhook_not_configured", user_id=user.user_id)
        raise AITeachMeError(
            detail="反馈接收服务暂未配置，请稍后重试或通过邮箱联系我们。",
            error_code="FEEDBACK_DELIVERY_NOT_CONFIGURED",
            status_code=503,
        )

    try:
        async with httpx.AsyncClient(timeout=_FEEDBACK_HTTP_TIMEOUT) as client:
            await _deliver_feedback_to_feishu(
                client,
                webhook_url=feishu_webhook,
                user_info=user.email or f"访客 {user.user_id}",
                content=payload.content,
                images=payload.images,
                app_id=(get_env("FEISHU_APP_ID") or "").strip() or None,
                app_secret=(get_env("FEISHU_APP_SECRET") or "").strip() or None,
            )
    except AITeachMeError:
        raise
    except httpx.RequestError as exc:
        logger.warning(
            "feedback_webhook_unavailable",
            user_id=user.user_id,
            error_type=type(exc).__name__,
        )
        raise AITeachMeError(
            detail="反馈接收服务暂时无法连接，请稍后重试或通过邮箱联系我们。",
            error_code="FEEDBACK_DELIVERY_UNAVAILABLE",
            status_code=503,
        ) from exc

    logger.info("feedback_delivered", user_id=user.user_id)

    return ok_response(True)
