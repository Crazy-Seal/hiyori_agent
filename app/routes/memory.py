from fastapi import APIRouter, Depends, Query

from app.dependencies import get_memory_service
from app.schemas.chat import ChatHistoryItem
from app.schemas.result import Result
from app.services.memory_service import MemoryService

router = APIRouter(tags=["memory"])


@router.get("/chat_history/{session_id}")
def list_chat_history(
    session_id: str,
    start: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
    memory_service: MemoryService = Depends(get_memory_service),
) -> Result:
    history = memory_service.get_chat_history_data(session_id=session_id, start=start, limit=limit)
    items = [ChatHistoryItem(**item).model_dump() for item in history]
    return Result(data=items, msg="success", code=200)

