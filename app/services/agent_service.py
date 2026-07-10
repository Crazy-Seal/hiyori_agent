"""AgentService 

产出 AgentEvent（非 DONE/ERROR）；DONE 交给路由的 done() 收尾，ERROR 转为异常
"""

import logging
import asyncio
from datetime import datetime
from typing import AsyncIterator, Callable

from app.agent.agent import Agent
from app.agent.core.event_router import EventType
from app.agent.core.state_manager import StateManager
from app.crud.chat_history_dao import ChatHistoryDao
from app.schemas.chat import AgentInput
from app.schemas.chat_settings import ChatSettings
from app.services.agent_factory import build_agent

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        chat_history_dao: ChatHistoryDao,
        chat_settings_loader: Callable[[str], ChatSettings],
        agent_factory: Callable[[ChatSettings], Agent] | None = None,
    ):
        self.chat_history_dao = chat_history_dao
        self.chat_settings_loader = chat_settings_loader
        self.agent_factory = agent_factory or build_agent
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    def _build_timed_user_message(user_message: str) -> str:
        now = datetime.now().astimezone()
        weekday_text = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        now_text = f"{now.strftime('%Y-%m-%d %H:%M:%S %z')} {weekday_text}"
        return f"[{now_text}] {user_message}"

    def get_health_data(self, session_id: str) -> dict[str, str]:
        chat_settings = self.chat_settings_loader(session_id)
        return {"status": "ok", "model": chat_settings.model_name}

    async def _close(self, session_id: str, agent: Agent) -> None:
        try:
            await agent.close()
        except Exception:
            logger.exception("[AgentService][session=%s] 关闭 agent 失败", session_id)
    async def stream_chat(self, agent_input: AgentInput, session_id: str = "default") -> AsyncIterator:
        async with self._get_session_lock(session_id):
            chat_settings = self.chat_settings_loader(session_id)
            agent = self.agent_factory(chat_settings)

            message = self._build_timed_user_message(agent_input.message)
            try:
                async for event in agent.run(message, images=agent_input.images):
                    if event.type == EventType.ERROR:
                        raise RuntimeError(event.data)
                    if event.type == EventType.DONE:
                        continue
                    yield event
            except Exception as e:
                logger.exception("[AgentService][session=%s] 运行出错: %s", session_id, e)
                raise RuntimeError(f"Agent 执行出错: {e}") from e
            finally:
                # checkpoint 是跨请求恢复的唯一数据源，不保留活跃 Agent。
                await self._close(session_id, agent)

    async def resume_after_screenshot(
        self,
        session_id: str,
        approved: bool,
        screenshot_data: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> AsyncIterator:
        resume_data: dict = {"approved": approved}
        if screenshot_data:
            resume_data["screenshot_data"] = screenshot_data
        if width is not None:
            resume_data["width"] = width
        if height is not None:
            resume_data["height"] = height

        async with self._get_session_lock(session_id):
            chat_settings = self.chat_settings_loader(session_id)
            agent = self.agent_factory(chat_settings)
            try:
                async for event in agent.resume(resume_data):
                    if event.type == EventType.ERROR:
                        raise RuntimeError(event.data)
                    if event.type == EventType.DONE:
                        continue
                    yield event
            except Exception as e:
                logger.exception("[AgentService][session=%s] 恢复对话失败", session_id)
                raise RuntimeError(f"恢复对话失败: {e}") from e
            finally:
                await self._close(session_id, agent)

    async def resume_after_control_screen(
        self,
        session_id: str,
        approved: bool | None = None,
        screenshot_data: str | None = None,
        width: int | None = None,
        height: int | None = None,
        executed: bool | None = None,
        error: str | None = None,
    ) -> AsyncIterator:
        resume_data: dict = {}
        if approved is not None:
            resume_data["approved"] = approved
        if screenshot_data:
            resume_data["screenshot_data"] = screenshot_data
        if width is not None:
            resume_data["width"] = width
        if height is not None:
            resume_data["height"] = height
        if executed is not None:
            resume_data["executed"] = executed
        if error:
            resume_data["error"] = error

        async with self._get_session_lock(session_id):
            chat_settings = self.chat_settings_loader(session_id)
            agent = self.agent_factory(chat_settings)
            try:
                async for event in agent.resume(resume_data):
                    if event.type == EventType.ERROR:
                        raise RuntimeError(event.data)
                    if event.type == EventType.DONE:
                        continue
                    yield event
            except Exception as e:
                logger.exception("[AgentService][session=%s] 恢复对话失败", session_id)
                raise RuntimeError(f"恢复对话失败: {e}") from e
            finally:
                await self._close(session_id, agent)

    async def get_pending_interrupt(self, session_id: str) -> dict:
        """读取可跨前端重启恢复的中断信息。"""
        async with self._get_session_lock(session_id):
            state_manager = StateManager(session_id)
            try:
                state = await state_manager.load()
                if not state.interrupt_data:
                    return {"pending": False}
                interrupt = state.interrupt_data
                value = {
                    "type": interrupt.get("type"),
                    "request_id": interrupt.get("request_id"),
                    "message": interrupt.get("message"),
                }
                if interrupt.get("data") is not None:
                    value["data"] = interrupt["data"]
                return {"pending": True, "interrupt": {"value": value}}
            finally:
                await state_manager.close()
