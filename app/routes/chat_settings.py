from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chat_settings_service
from app.schemas.chat_settings import ChatSettings
from app.schemas.result import Result
from app.services.chat_settings_service import ChatSettingsService

router = APIRouter(tags=["chat_settings"])


# 增
@router.post("/chat_settings", response_model=Result)
async def add_chat_settings(
    chat_settings: ChatSettings,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    """新增模型配置。

    Args:
        chat_settings: 待新增的模型配置。
        chat_settings_service: 由依赖注入提供的模型配置服务。

    Returns:
        统一成功响应。

    Raises:
        HTTPException: 配置写入发生冲突。
    """
    try:
        saved = await chat_settings_service.add_chat_settings(chat_settings)
        return Result(data=saved, msg="success", code=200)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# 删
@router.delete("/chat_settings/{session_id}", response_model=Result)
async def delete_chat_settings(
    session_id: str,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    """删除指定会话的模型配置。

    Args:
        session_id: 待删除配置的会话 ID。
        chat_settings_service: 由依赖注入提供的模型配置服务。

    Returns:
        统一成功响应。

    Raises:
        HTTPException: 指定配置不存在。
    """
    try:
        await chat_settings_service.delete_chat_settings(session_id)
        return Result(data=None, msg="success", code=200)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# 查
@router.get("/chat_settings/{session_id}", response_model=Result)
def get_chat_settings(
    session_id: str,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    try:
        data = chat_settings_service.get_chat_settings_by_session(session_id)
        return Result(data=data, msg="success", code=200)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# 改
@router.put("/chat_settings", response_model=Result)
async def update_chat_settings(
    chat_settings: ChatSettings,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    """更新模型配置及其 MCP 权限。

    Args:
        chat_settings: 更新后的完整模型配置。
        chat_settings_service: 由依赖注入提供的模型配置服务。

    Returns:
        统一成功响应。

    Raises:
        HTTPException: 指定配置不存在。
    """
    try:
        saved = await chat_settings_service.update_chat_settings(chat_settings)
        return Result(data=saved, msg="success", code=200)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
