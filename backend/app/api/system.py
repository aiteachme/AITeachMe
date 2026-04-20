"""系统初始化接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

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
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[bool]:
    """提交用户反馈。"""

    import base64
    import logging
    import os
    import time
    
    import httpx

    logger = logging.getLogger(__name__)
    
    # 打印日志
    logger.info(f"[Feedback] User {user.user_id} ({user.email or 'Guest'}) submitted feedback:")
    logger.info(f"Content: {payload.content}")

    screenshot_msg = ""
    # 若有截图则保存在本地服务器 data 目录，以防丢失
    if payload.screenshot and payload.screenshot.startswith("data:image"):
        try:
            header, encoded = payload.screenshot.split(",", 1)
            img_data = base64.b64decode(encoded)
            save_dir = os.path.join("data", "feedbacks")
            os.makedirs(save_dir, exist_ok=True)
            filename = f"feedback_{int(time.time())}_{user.user_id[:8]}.png"
            screenshot_path = os.path.join(save_dir, filename)
            with open(screenshot_path, "wb") as f:
                f.write(img_data)
            logger.info(f"Screenshot saved to {screenshot_path}")
            screenshot_msg = f"\n📎 用户附带了截图，已保存在服务器本地：{screenshot_path}"
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")
            screenshot_msg = "\n📎 用户附带了截图，但保存失败。"
            
    # 推送至飞书群机器人（如果环境当中配置了 FEISHU_WEBHOOK_URL）
    feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL")
    if feishu_webhook:
        user_info = user.email or f"访客 {user.user_id}"
        text = f"📢 新的用户反馈 (来自: {user_info})\n\n"
        text += f"内容：\n{payload.content}"
        text += screenshot_msg
        
        try:
            # Fire-and-forget style push so we don't block
            async with httpx.AsyncClient() as client:
                await client.post(
                    feishu_webhook,
                    json={
                        "msg_type": "text",
                        "content": {"text": text}
                    },
                    timeout=5.0
                )
        except Exception as e:
            logger.error(f"Failed to push feedback to Feishu webhook: {e}")

    return ok_response(True)
