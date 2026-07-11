"""
执行管道

负责编排 LLM 调用和工具执行循环。

中断/恢复采用「可持久化」模型：被中断工具的全部路由信息（tool_name/
tool_call_id/tool_args/resume_state）写入 state.interrupt_data，使恢复能
在另一个请求（甚至进程重启后）重入同一工具——无需依赖存活的协程。
"""

import logging
from typing import AsyncIterator, Protocol, TYPE_CHECKING

from app.agent.context import (
    ToolContext,
    ToolResult,
    PluginHook,
)
from app.agent.core.event_router import EventType, AgentEvent
from app.agent.message import (
    SCREENSHOT_MESSAGE_NAME,
    ToolCall,
    Message,
    ContentPart,
    MessageRole,
    AssistantMessageWithTools,
)
from app.agent.state import AgentState
from app.agent.models.llm_client import StreamChunk
from app.agent.core.state_manager import CheckpointType
if TYPE_CHECKING:
    from app.agent.agent import Agent

logger = logging.getLogger(__name__)


class CheckpointCallback(Protocol):
    """持久化回调必须显式声明 checkpoint 类型。"""

    async def __call__(
        self,
        state: AgentState,
        *,
        checkpoint_type: CheckpointType,
    ) -> int: ...


class ExecutionPipeline:
    """执行管道 - 编排 LLM 调用和工具执行"""

    def __init__(self, agent: "Agent"):
        self.agent = agent

    # ==================== 主入口 ====================

    async def execute(
        self,
        state: AgentState,
        checkpoint: CheckpointCallback | None = None,
        commit_context: dict | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """执行主循环（一轮对话的起点）"""
        # ON_INVOKE 钩子 - 每轮仅在此触发一次
        state = await self.agent.plugin_manager.run_hooks(
            PluginHook.ON_INVOKE, state
        )

        async for event in self._run_loop(state, checkpoint, commit_context):
            yield event

    async def resume_tools(
        self,
        state: AgentState,
        resume_data: dict,
        checkpoint: CheckpointCallback | None = None,
        commit_context: dict | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """从中断恢复：先跑完被中断的工具与剩余待执行工具，再回到 LLM 循环。

        注意：这里不再触发 ON_INVOKE（它属于「新一轮」语义），避免重复副作用。
        """
        interrupt_data = state.interrupt_data or {}
        pending_actions = list(state.pending_actions)
        state.clear_interrupt()

        resumed_calls: list[ToolCall] = []
        tool_name = interrupt_data.get("tool_name")
        if tool_name:
            resumed_calls.append(ToolCall(
                id=interrupt_data.get("tool_call_id", ""),
                name=tool_name,
                args=interrupt_data.get("tool_args", {}),
            ))
        resumed_calls.extend(ToolCall.from_dict(item) for item in pending_actions)
        state.set_pending_tool_calls(resumed_calls)

        # 1. 重入被中断的工具（用持久化的路由信息重建 ToolCall）
        if tool_name:
            interrupted_call = resumed_calls[0]
            result = await self._execute_tool(
                state,
                interrupted_call,
                resume_data=resume_data,
                resume_state=interrupt_data.get("resume_state", {}),
            )

            # 恢复执行时又触发了新的中断
            if result.interrupt:
                self._persist_interrupt(state, interrupted_call, result, pending_actions)
                await self._checkpoint(state, checkpoint)
                yield AgentEvent(EventType.INTERRUPT, result.interrupt.to_client())
                return

            self._append_tool_result(state, interrupted_call, result)
            state.remove_pending_tool_call(interrupted_call.id)
            await self._checkpoint(state, checkpoint)

        # 2. 执行中断时尚未轮到的剩余工具
        for i, tc_dict in enumerate(pending_actions):
            tool_call = ToolCall.from_dict(tc_dict)
            yield AgentEvent(EventType.TOOL_CALL, tool_call.name)

            result = await self._execute_tool(state, tool_call)
            if result.interrupt:
                self._persist_interrupt(state, tool_call, result, pending_actions[i + 1:])
                await self._checkpoint(state, checkpoint)
                yield AgentEvent(EventType.INTERRUPT, result.interrupt.to_client())
                return

            self._append_tool_result(state, tool_call, result)
            state.remove_pending_tool_call(tool_call.id)
            await self._checkpoint(state, checkpoint)

        # 3. 回到 LLM 循环（不重跑 ON_INVOKE）
        async for event in self._run_loop(state, checkpoint, commit_context):
            yield event

    # ==================== 核心循环 ====================

    async def _run_loop(
        self,
        state: AgentState,
        checkpoint: CheckpointCallback | None = None,
        commit_context: dict | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """LLM ↔ 工具循环主体（不含 ON_INVOKE）"""
        while True:
            # 1. BEFORE_LLM 钩子
            state = await self.agent.plugin_manager.run_hooks(
                PluginHook.BEFORE_LLM, state
            )

            # 2. 调用 LLM（流式）
            accumulated_content = ""
            tool_calls: list[ToolCall] = []
            finish_reason: str | None = None

            try:
                async for chunk in self._call_llm(state):
                    if chunk.content:
                        accumulated_content += chunk.content
                        yield AgentEvent(EventType.TEXT_CHUNK, chunk.content)
                    if chunk.tool_call:
                        tool_calls.append(chunk.tool_call)
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason

                if not tool_calls and not accumulated_content.strip():
                    reason = finish_reason or "unknown"
                    raise RuntimeError(f"模型未返回有效文本（finish_reason={reason}）")
            except Exception as e:
                logger.error("LLM 调用失败: %s", e)
                await self.agent.plugin_manager.run_hooks(
                    PluginHook.ON_ERROR, state, data={"error": e}
                )
                yield AgentEvent(EventType.ERROR, str(e))
                return

            # 3. AFTER_LLM 钩子
            state = await self.agent.plugin_manager.run_hooks(
                PluginHook.AFTER_LLM, state,
                data={"content": accumulated_content, "tool_calls": tool_calls},
            )

            # 4. 助手消息入状态
            if accumulated_content or tool_calls:
                self._add_assistant_message(state, accumulated_content, tool_calls)

            if tool_calls:
                state.set_pending_tool_calls(tool_calls)
                await self._checkpoint(state, checkpoint)

            # 5. 无工具调用 → 本轮结束
            if not tool_calls:
                break

            # 6. 工具循环
            for i, tool_call in enumerate(tool_calls):
                yield AgentEvent(EventType.TOOL_CALL, tool_call.name)

                result = await self._execute_tool(state, tool_call)

                # 中断：持久化路由信息 + 剩余工具，仅发最小字段给前端
                if result.interrupt:
                    remaining = [tc.to_dict() for tc in tool_calls[i + 1:]]
                    self._persist_interrupt(state, tool_call, result, remaining)
                    await self.agent.plugin_manager.run_hooks(
                        PluginHook.ON_INTERRUPT, state,
                        data={"interrupt": result.interrupt},
                    )
                    await self._checkpoint(state, checkpoint)
                    yield AgentEvent(EventType.INTERRUPT, result.interrupt.to_client())
                    return

                self._append_tool_result(state, tool_call, result)
                state.remove_pending_tool_call(tool_call.id)
                await self._checkpoint(state, checkpoint)

            # 7. 清空待处理工具，继续循环
            state.clear_pending_tool_calls()

        # 8. 最终响应提交前准备：标注图片、准备记忆快照并裁剪 checkpoint。
        state = await self.agent.plugin_manager.run_hooks(
            PluginHook.BEFORE_RESPONSE_COMMIT,
            state,
            data=commit_context if commit_context is not None else {},
        )
        memory_human_floor = 0
        if commit_context is not None:
            memory_human_floor = int(
                commit_context.get("memory_checkpoint_human_floor", 0) or 0
            )
        self.agent.context_strategy.compact_checkpoint(
            state,
            memory_human_floor=memory_human_floor,
        )

        yield AgentEvent(EventType.DONE, None)

    @staticmethod
    async def _checkpoint(
        state: AgentState,
        checkpoint: CheckpointCallback | None,
    ) -> None:
        """在启用持久化的执行入口中保存工具进度。"""
        if checkpoint is not None:
            await checkpoint(state, checkpoint_type="intermediate")

    # ==================== LLM 调用 ====================

    async def _call_llm(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        """调用 LLM，保留文本、工具调用和终止原因。"""
        messages = self._build_messages(state)
        tools = self.agent.tool_manager.get_openai_tools()

        async for chunk in self.agent.llm_client.astream(messages, tools=tools or None):
            if chunk.finish_reason == "content_filter":
                # 内容被 API 过滤：抛出，由 _run_loop 的 try/except 统一转成 ERROR 事件
                # （本轮不写 checkpoint，且前端能看到明确报错）
                raise RuntimeError("触发 API 内容过滤")
            yield chunk

    def _build_messages(self, state: AgentState) -> list[dict]:
        """构建发送给 LLM 的消息列表

        上下文策略是必经核心能力，不允许退回完整历史。
        """
        messages: list[dict] = []

        # 系统提示词（拼接记忆上下文）
        system_prompt = self.agent.config.system_prompt
        if state.memory_context:
            system_prompt = f"{system_prompt}\n\n{state.memory_context}"
        if system_prompt:
            messages.append(Message.system_message(system_prompt).to_openai_format())

        # 上下文策略生成临时窗口，不修改持久化消息。
        history = self.agent.context_strategy.build_model_window(state)
        messages.extend(history)

        return messages

    # ==================== 工具执行 ====================

    async def _execute_tool(
        self,
        state: AgentState,
        tool_call: ToolCall,
        resume_data: dict | None = None,
        resume_state: dict | None = None,
    ) -> ToolResult:
        """执行单个工具（支持中断后恢复执行：传入 resume_data + resume_state）"""
        await self.agent.plugin_manager.run_hooks(
            PluginHook.BEFORE_TOOL, state,
            data={"tool_call": tool_call.to_dict()},
        )

        tool = self.agent.tool_manager.get(tool_call.name)
        if not tool:
            logger.warning("工具 '%s' 不存在", tool_call.name)
            return ToolResult.error(f"工具 '{tool_call.name}' 不存在")

        context = ToolContext(
            session_id=state.session_id,
            state=state,
            emit_event=self.agent.event_router.emit,
            get_checkpoint=state.to_checkpoint,
            set_checkpoint=lambda d: state.update_extra(d),
            resume_data=resume_data,
            resume_state=resume_state,
        )

        try:
            result = await tool.execute(tool_call.args, context)
        except Exception as e:
            logger.error("工具 '%s' 执行失败: %s", tool_call.name, e)
            result = ToolResult.error(str(e))

        await self.agent.plugin_manager.run_hooks(
            PluginHook.AFTER_TOOL, state,
            data={"tool_call": tool_call.to_dict(), "result": result},
        )

        return result

    def _append_tool_result(
        self,
        state: AgentState,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> None:
        """把工具结果落入状态；若工具产出图片，注入为用户消息让模型看见。"""
        if result.state_updates:
            state.update_extra(result.state_updates)

        state.add_tool_message(
            content=result.content,
            tool_name=tool_call.name,
            tool_call_id=tool_call.id,
        )

        if result.image_url:
            # 图片以 user 消息进入，工具槽位只留文本
            state.add_message(Message.user_message(
                [
                    ContentPart.text_part("[系统消息]屏幕截图: "),
                    ContentPart.image_part(result.image_url),
                ],
                name=SCREENSHOT_MESSAGE_NAME,
            ))

    def _persist_interrupt(
        self,
        state: AgentState,
        tool_call: ToolCall,
        result: ToolResult,
        pending_actions: list[dict],
    ) -> None:
        """把中断的完整路由信息写入 state，供跨请求恢复。"""
        interrupt = result.interrupt
        interrupt.tool_name = tool_call.name
        interrupt.tool_call_id = tool_call.id
        interrupt.tool_args = tool_call.args
        interrupt.resume_state = result.resume_state
        state.set_interrupt(
            interrupt_data=interrupt.to_state(),
            pending_actions=pending_actions,
        )
        state.clear_pending_tool_calls()

    # ==================== 助手消息 ====================

    def _add_assistant_message(
        self,
        state: AgentState,
        content: str,
        tool_calls: list[ToolCall],
    ) -> None:
        """添加助手消息到状态"""
        if tool_calls:
            msg = AssistantMessageWithTools(
                role=MessageRole.ASSISTANT,   # 必须用枚举，否则 to_openai_format 取 .value 崩溃
                content=content,
                tool_calls=tool_calls,
            )
            state.add_message(msg)
            state.updated_at = msg.timestamp
        else:
            state.add_assistant_message(content)
