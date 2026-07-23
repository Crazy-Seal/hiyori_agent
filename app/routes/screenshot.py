"""截屏确认路由"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.dependencies import get_agent_service
from app.services.agent_service import AgentService
from app.utils.sse_formatter import SSEFormatter


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screenshot", tags=["screenshot"])


class ScreenshotResponseRequest(BaseModel):
    """用户响应截屏请求的请求体"""
    session_id: str
    request_id: str = Field(min_length=1)
    approved: bool
    screenshot_data: str | None = None  # 完整 data URL 格式，如 data:image/png;base64,xxx
    width: int | None = None            # 截屏宽度（像素）
    height: int | None = None           # 截屏高度（像素）

    @model_validator(mode='after')
    def validate_screenshot_data(self) -> 'ScreenshotResponseRequest':
        if self.approved and not self.screenshot_data:
            raise ValueError('允许截屏但未提供图像')
        return self


@router.post("/respond")
async def respond_to_screenshot(
    payload: ScreenshotResponseRequest,
    agent_service: AgentService = Depends(get_agent_service),
) -> StreamingResponse:
    """用户响应截屏请求，恢复对话执行。

    用户确认后，前端截取屏幕并发送截图数据，Agent 继续执行。

    Args:
        payload: 包含 session_id、approved、screenshot_data、width、height 的请求体

    Returns:
        SSE 流式响应，格式与 /chat 相同
    """
    logger.info("[ScreenshotRoute] 收到截屏响应: session_id=%s, approved=%s, has_data=%s",
                payload.session_id, payload.approved, payload.screenshot_data is not None)

    async def event_stream():
        formatter = SSEFormatter()
        try:
            async for event in agent_service.resume_after_screenshot(
                payload.session_id,
                request_id=payload.request_id,
                approved=payload.approved,
                screenshot_data=payload.screenshot_data,
                width=payload.width,
                height=payload.height,
            ):
                formatted = formatter.format(event)
                if formatted:
                    yield formatted
            yield formatter.done()
        except Exception as e:
            logger.exception("[ScreenshotRoute] 恢复对话失败")
            yield formatter.error(str(e))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
