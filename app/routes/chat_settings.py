from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chat_settings_service
from app.schemas.chat_settings import ChatSettings
from app.schemas.result import Result
from app.services.chat_settings_service import ChatSettingsService

router = APIRouter(tags=["chat_settings"])


# 增
@router.post("/chat_settings", response_model=Result)
def add_api_key(
    chat_settings: ChatSettings,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    try:
        chat_settings_service.add_chat_settings(chat_settings)
        return Result(data=None, msg="success", code=200)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# 删
@router.delete("/chat_settings/{session_id}", response_model=Result)
def delete_api_key(
    session_id: str,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    try:
        chat_settings_service.delete_chat_settings(session_id)
        return Result(data=None, msg="success", code=200)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# 查
@router.get("/chat_settings/{session_id}", response_model=Result)
def get_api_key(
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
def update_api_key(
    chat_settings: ChatSettings,
    chat_settings_service: ChatSettingsService = Depends(get_chat_settings_service),
) -> Result:
    try:
        chat_settings_service.update_chat_settings(chat_settings)
        return Result(data=None, msg="success", code=200)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
