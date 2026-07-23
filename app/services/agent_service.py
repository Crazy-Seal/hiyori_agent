"""AgentService 

产出 AgentEvent（非 DONE/ERROR）；DONE 交给路由的 done() 收尾，ERROR 转为异常
"""

import logging
import asyncio
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

    def get_health_data(self, session_id: str) -> dict[str, str]:
        chat_settings = self.chat_settings_loader(session_id)
        return {"status": "ok", "model": chat_settings.model_name}

    async def _close(self, session_id: str, agent: Agent) -> None:
        try:
            await agent.close()
        except Exception:
            logger.exception("[AgentService][session=%s] 关闭 agent 失败", session_id)

    async def _resume_interrupted(
        self,
        session_id: str,
        *,
        request_id: str,
        expected_types: frozenset[str],
        resume_data: dict,
        operation_name: str,
    ) -> AsyncIterator:
        """校验并恢复当前会话中的指定中断。

        Args:
            session_id: 待恢复的会话 ID。
            request_id: 前端回传的持久化中断 ID。
            expected_types: 当前恢复入口允许消费的中断类型。
            resume_data: 传递给可恢复工具的用户响应数据。
            operation_name: 用于日志和异常消息的操作名称。

        Yields:
            恢复执行后产生的 Agent 事件。

        Raises:
            ValueError: 当前中断不存在、类型不匹配或请求已过期。
            RuntimeError: Agent 恢复执行失败。
        """
        async with self._get_session_lock(session_id):
            state_manager = StateManager(session_id)
            try:
                state = await state_manager.load()
                interrupt = state.interrupt_data
                if interrupt is None:
                    raise ValueError("当前没有待处理的确认请求")
                if interrupt.get("type") not in expected_types:
                    raise ValueError("当前确认请求类型与响应接口不匹配")
                if not request_id or interrupt.get("request_id") != request_id:
                    raise ValueError("确认请求已过期")
            finally:
                await state_manager.close()

            chat_settings = self.chat_settings_loader(session_id)
            agent = self.agent_factory(chat_settings)
            try:
                async for event in agent.resume(resume_data):
                    if event.type == EventType.ERROR:
                        raise RuntimeError(event.data)
                    if event.type == EventType.DONE:
                        continue
                    yield event
            except Exception as exc:
                logger.exception(
                    "[AgentService][session=%s] %s失败",
                    session_id,
                    operation_name,
                )
                raise RuntimeError(f"{operation_name}失败: {exc}") from exc
            finally:
                await self._close(session_id, agent)

    async def stream_chat(self, agent_input: AgentInput, session_id: str = "default") -> AsyncIterator:
        async with self._get_session_lock(session_id):
            chat_settings = self.chat_settings_loader(session_id)
            agent = self.agent_factory(chat_settings)

            try:
                async for event in agent.run(
                    agent_input.message,
                    images=agent_input.images,
                ):
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
        *,
        request_id: str,
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

        async for event in self._resume_interrupted(
            session_id,
            request_id=request_id,
            expected_types=frozenset({"screenshot_request"}),
            resume_data=resume_data,
            operation_name="恢复截屏工具",
        ):
            yield event

    async def resume_after_control_screen(
        self,
        session_id: str,
        *,
        request_id: str,
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

        async for event in self._resume_interrupted(
            session_id,
            request_id=request_id,
            expected_types=frozenset({
                "control_screen_capture_request",
                "control_screen_execute_request",
            }),
            resume_data=resume_data,
            operation_name="恢复屏幕控制工具",
        ):
            yield event

    async def resume_after_mcp_tool(
        self,
        session_id: str,
        *,
        request_id: str,
        approved: bool,
    ) -> AsyncIterator:
        """校验 MCP 中断标识并恢复单次工具调用。

        Args:
            session_id: 待恢复的会话 ID。
            request_id: 前端回传的审批请求 ID。
            approved: 用户是否批准本次工具调用。

        Yields:
            恢复执行后产生的 Agent 事件。

        Raises:
            ValueError: 当前不存在匹配的 MCP 审批请求。
            RuntimeError: Agent 恢复执行失败。
        """
        async for event in self._resume_interrupted(
            session_id,
            request_id=request_id,
            expected_types=frozenset({"mcp_tool_approval_request"}),
            resume_data={"approved": approved},
            operation_name="恢复 MCP 工具调用",
        ):
            yield event

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
