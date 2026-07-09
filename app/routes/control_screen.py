"""屏幕控制恢复路由。"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator

from app.dependencies import get_agent_service
from app.services.agent_service import AgentService
from app.utils.sse_formatter import SSEFormatter


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/control-screen", tags=["control-screen"])


class ControlScreenResponseRequest(BaseModel):
    """前端响应屏幕控制中断的请求体。"""

    session_id: str
    approved: bool | None = None
    screenshot_data: str | None = None
    width: int | None = None
    height: int | None = None
    executed: bool | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "ControlScreenResponseRequest":
        if self.screenshot_data and (self.width is None or self.height is None):
            raise ValueError("提供截图时必须同时提供 width 和 height")
        return self


@router.post("/respond")
async def respond_to_control_screen(
    payload: ControlScreenResponseRequest,
    agent_service: AgentService = Depends(get_agent_service),
) -> StreamingResponse:
    """恢复 control_screen 工具执行。"""
    logger.info(
        "[ControlScreenRoute] 收到屏幕控制响应: session_id=%s, approved=%s, executed=%s, has_data=%s",
        payload.session_id,
        payload.approved,
        payload.executed,
        payload.screenshot_data is not None,
    )

    async def event_stream():
        formatter = SSEFormatter()
        try:
            async for event in agent_service.resume_after_control_screen(
                payload.session_id,
                approved=payload.approved,
                screenshot_data=payload.screenshot_data,
                width=payload.width,
                height=payload.height,
                executed=payload.executed,
                error=payload.error,
            ):
                formatted = formatter.format(event)
                if formatted:
                    yield formatted
            yield formatter.done()
        except Exception as e:
            logger.exception("[ControlScreenRoute] 恢复屏幕控制失败")
            yield formatter.error(str(e))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
