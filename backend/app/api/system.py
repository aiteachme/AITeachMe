"""系统初始化接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends

from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.system import FeedbackRequest, InitData, InitRequest, SettingsOverviewData, UpdateUserSettingsRequest
from app.shared.infra.settings import DEFAULT_PROJECT_SETTINGS_FILENAME
from app.workflows.support.system import (
    build_init_data,
    build_settings_overview_data,
    update_user_settings_overview_data,
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


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


@router.post(
    "/settings",
    response_model=ApiResponse[SettingsOverviewData],
    summary="读取后端设置总览",
    description=f"返回环境变量与 {DEFAULT_PROJECT_SETTINGS_FILENAME} 合并后的只读设置概览。",
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
    summary="更新当前用户 settings",
    description=f"保存当前用户的非敏感 {DEFAULT_PROJECT_SETTINGS_FILENAME} 同构 settings 覆盖；密钥类环境变量不通过此接口保存。",
    responses=build_error_responses([422, 500]),
)
async def update_system_settings(
    payload: UpdateUserSettingsRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SettingsOverviewData]:
    """更新当前用户 settings 覆盖。"""

    return ok_response(
        update_user_settings_overview_data(
            session=session,
            user_id=user.user_id,
            settings_payload=payload.settings,
            reset=payload.reset,
        )
    )


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
    import logging
    import os
    
    import httpx

    logger = logging.getLogger(__name__)
    
    logger.info(f"[Feedback] User {user.user_id} ({user.email or 'Guest'}) submitted feedback:")
    logger.info(f"Content: {payload.content}")
    logger.info(f"Image count: {len(payload.images)}")

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
                                logger.error(f"Failed to upload image {idx} to feishu: {e}")

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
                logger.error(f"Failed to push feedback to Feishu webhook: {e}")

        # 使用 BackgroundTasks 进行真正的异步非阻塞执行
        background_tasks.add_task(push_to_feishu)

    return ok_response(True)
