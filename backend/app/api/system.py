"""系统初始化接口。"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Response

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
    responses=build_error_responses([500]),
)
async def submit_feedback(
    payload: FeedbackRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[bool]:
    """提交用户反馈。"""

    import base64
    import os
    
    import httpx

    logger.info(
        "feedback_submitted",
        user_id=user.user_id,
        has_email=bool(user.email),
        email_domain=(user.email.rsplit("@", 1)[-1].lower() if user.email and "@" in user.email else None),
        content_chars=len(payload.content),
        image_count=len(payload.images),
    )

    feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL")
    feishu_app_id = os.getenv("FEISHU_APP_ID")
    feishu_app_secret = os.getenv("FEISHU_APP_SECRET")
    
    if feishu_webhook:
        user_info = user.email or f"访客 {user.user_id}"
        
        async def push_to_feishu():
            try:
                # Fire-and-forget style push so we don't block
                async with httpx.AsyncClient() as client:
                    tenant_access_token = None
                    if feishu_app_id and feishu_app_secret and payload.images:
                        auth_resp = await client.post(
                            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                            json={"app_id": feishu_app_id, "app_secret": feishu_app_secret},
                            timeout=5.0
                        )
                        if auth_resp.status_code == 200:
                            data = auth_resp.json()
                            if data.get("code") == 0:
                                tenant_access_token = data.get("tenant_access_token")

                    image_keys = []
                    if tenant_access_token and payload.images:
                        for idx, b64_img in enumerate(payload.images):
                            if not b64_img.startswith("data:image"):
                                continue
                            try:
                                header, encoded = b64_img.split(",", 1)
                                img_bytes = base64.b64decode(encoded)
                                upload_resp = await client.post(
                                    "https://open.feishu.cn/open-apis/im/v1/images",
                                    headers={"Authorization": f"Bearer {tenant_access_token}"},
                                    data={"image_type": "message"},
                                    files={"image": (f"screenshot_{idx}.png", img_bytes, "image/png")},
                                    timeout=10.0
                                )
                                if upload_resp.status_code == 200:
                                    resp_data = upload_resp.json()
                                    if resp_data.get("code") == 0:
                                        image_keys.append(resp_data["data"]["image_key"])
                            except Exception as e:
                                logger.error(
                                    "feedback_image_upload_failed",
                                    image_index=idx,
                                    error=str(e),
                                )

                    if image_keys:
                        post_content = [
                            [{"tag": "text", "text": f"内容：\n{payload.content}\n\n附件截图：\n"}]
                        ]
                        for key in image_keys:
                            post_content.append([{"tag": "img", "image_key": key}])
                            
                        await client.post(
                            feishu_webhook,
                            json={
                                "msg_type": "post",
                                "content": {
                                    "post": {
                                        "zh_cn": {
                                            "title": f"📢 新的用户反馈 (来自: {user_info})",
                                            "content": post_content
                                        }
                                    }
                                }
                            },
                            timeout=5.0
                        )
                    else:
                        text = f"📢 新的用户反馈 (来自: {user_info})\n\n内容：\n{payload.content}"
                        if payload.images:
                            text += f"\n\n📎 附带了 {len(payload.images)} 张截图。由于凭证问题或其他原因未能通过飞书接口上传图片展示。"
                        await client.post(
                            feishu_webhook,
                            json={"msg_type": "text", "content": {"text": text}},
                            timeout=5.0
                        )
            except Exception as e:
                logger.error("feedback_push_to_feishu_failed", error=str(e))

        # 使用 BackgroundTasks 进行真正的异步非阻塞执行
        background_tasks.add_task(push_to_feishu)

    return ok_response(True)
