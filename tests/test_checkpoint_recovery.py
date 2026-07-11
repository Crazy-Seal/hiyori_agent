import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from app.agent.agent import Agent, AgentConfig, INTERRUPTED_TOOL_RESULT
from app.agent.context import BasePlugin, BaseTool, HookContext, PluginHook, ToolContext, ToolResult
from app.agent.context_strategy import ContextStrategyConfig, ContextStrategyManager
from app.agent.core.event_router import EventType
from app.agent.core.pipeline import ExecutionPipeline
from app.agent.core.state_manager import StateManager
from app.agent.message import ToolCall
from app.agent.models.llm_client import StreamChunk
from app.agent.state import AgentState
from app.schemas.chat import AgentInput
from app.services.agent_service import AgentService


class ScriptedLLM:
    """按调用顺序回放流式结果或异常。"""

    def __init__(self, scripts: list[list[StreamChunk] | BaseException]):
        self.scripts = list(scripts)
        self.closed = False

    async def astream(self, messages, tools=None):
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        for chunk in script:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class StepTool(BaseTool):
    name = "step"
    description = "执行测试步骤"
    parameters_schema = {"type": "object", "properties": {"label": {"type": "string"}}}

    def __init__(self, crash_on: str | None = None):
        self.crash_on = crash_on
        self.executed: list[str] = []

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        label = args.get("label", "")
        self.executed.append(label)
        if label == self.crash_on:
            raise asyncio.CancelledError()
        return ToolResult.success(f"完成 {label}")


class ErrorTool(BaseTool):
    name = "error_step"
    description = "返回工具错误"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        raise RuntimeError("测试工具失败")


class ResumableScreenshotTool(BaseTool):
    name = "screenshot"
    description = "测试截屏中断"
    parameters_schema = {"type": "object", "properties": {}}
    is_resumable = True

    def __init__(self, resumed_calls: list[bool]):
        self.resumed_calls = resumed_calls

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        if context.resume_data is None:
            return ToolResult.needs_input("screenshot_request", "允许截屏？")
        self.resumed_calls.append(bool(context.resume_data.get("approved")))
        return ToolResult.success("截屏恢复完成")


async def make_agent(
    db_path: Path,
    scripts: list[list[StreamChunk] | BaseException],
    tool: BaseTool,
    session_id: str = "checkpoint-test",
) -> Agent:
    agent = Agent(
        AgentConfig(
            session_id=session_id,
            model_name="test",
            api_key="test",
            context_strategy=ContextStrategyConfig(),
        ),
        db_path=str(db_path),
    )
    await agent.llm_client.close()
    agent.llm_client = ScriptedLLM(scripts)
    agent.tool_manager.register(tool)
    return agent


async def drain(stream) -> list:
    return [event async for event in stream]


async def checkpoint_types(manager: StateManager) -> list[str]:
    db = await manager._get_db()
    async with db.execute(
        """
        SELECT checkpoint_type FROM checkpoints
        WHERE session_id = ? ORDER BY id
        """,
        (manager.session_id,),
    ) as cursor:
        return [row[0] for row in await cursor.fetchall()]


def tool_call(call_id: str, name: str = "step", label: str = "") -> StreamChunk:
    args = {"label": label} if label else {}
    return StreamChunk(tool_call=ToolCall(id=call_id, name=name, args=args))


class CommitOrderPlugin(BasePlugin):
    name = "commit_order"

    def __init__(self, order: list[str]):
        self.order = order

    @property
    def hooks(self) -> list[PluginHook]:
        return [
            PluginHook.BEFORE_RESPONSE_COMMIT,
            PluginHook.AFTER_RESPONSE_COMMIT,
        ]

    async def execute(self, context: HookContext) -> HookContext:
        if context.hook == PluginHook.BEFORE_RESPONSE_COMMIT:
            self.order.append("before_commit")
            context.data["prepared"] = True
            context.agent_state.summary_counter += 1
        elif context.hook == PluginHook.AFTER_RESPONSE_COMMIT:
            assert context.data == {"prepared": True}
            self.order.append("after_commit")
        return context


def test_response_commit_hooks_wrap_completed_checkpoint(tmp_path: Path) -> None:
    async def scenario() -> list[str]:
        order: list[str] = []
        agent = await make_agent(
            tmp_path / "checkpoints.sqlite3",
            [[StreamChunk(content="完成")]],
            StepTool(),
        )
        await agent.plugin_manager.register(CommitOrderPlugin(order), agent)
        original_save = agent.state_manager.save

        async def tracked_save(state, *, checkpoint_type):
            checkpoint_id = await original_save(state, checkpoint_type=checkpoint_type)
            order.append(f"save_{checkpoint_type}")
            return checkpoint_id

        agent.state_manager.save = tracked_save
        try:
            await drain(agent.run("开始"))
            return order
        finally:
            await agent.close()

    assert asyncio.run(scenario()) == [
        "save_intermediate",
        "before_commit",
        "save_completed",
        "after_commit",
    ]


def test_completed_checkpoint_failure_skips_after_commit_hook(tmp_path: Path) -> None:
    async def scenario() -> tuple[list[str], int]:
        order: list[str] = []
        db_path = tmp_path / "checkpoints.sqlite3"
        agent = await make_agent(
            db_path,
            [[StreamChunk(content="完成")]],
            StepTool(),
        )
        await agent.plugin_manager.register(CommitOrderPlugin(order), agent)
        original_save = agent.state_manager.save

        async def failing_save(state, *, checkpoint_type):
            if checkpoint_type == "completed":
                order.append("save_completed_failed")
                raise RuntimeError("模拟 completed 保存失败")
            return await original_save(state, checkpoint_type=checkpoint_type)

        agent.state_manager.save = failing_save
        try:
            with pytest.raises(RuntimeError, match="completed 保存失败"):
                await drain(agent.run("开始"))
        finally:
            await agent.close()

        manager = StateManager("checkpoint-test", db_path=str(db_path))
        try:
            persisted = await manager.load()
            return order, persisted.summary_counter
        finally:
            await manager.close()

    order, persisted_counter = asyncio.run(scenario())
    assert order == ["before_commit", "save_completed_failed"]
    assert persisted_counter == 1


def test_completed_tool_results_survive_later_llm_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        tool = StepTool()
        agent = await make_agent(
            db_path,
            [
                [tool_call("call-a", label="A")],
                [tool_call("call-b", label="B")],
                [tool_call("call-c", label="C")],
                RuntimeError("LLM 崩溃"),
            ],
            tool,
        )
        try:
            events = await drain(agent.run("执行三个步骤"))
            assert events[-1].type == EventType.ERROR

            state = await agent.state_manager.load()
            tool_messages = [item for item in state.messages if item.get("role") == "tool"]
            assert [item["content"] for item in tool_messages] == ["完成 A", "完成 B", "完成 C"]
            assert state.pending_tool_calls == []
            assert state.summary_counter == 1
            assert await checkpoint_types(agent.state_manager) == ["intermediate"]
        finally:
            await agent.close()

    asyncio.run(scenario())


def test_new_message_after_llm_failure_counts_both_human_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        first_agent = await make_agent(
            db_path,
            [
                [tool_call("call-a", label="A")],
                RuntimeError("stream disconnected"),
            ],
            StepTool(),
        )
        try:
            events = await drain(first_agent.run("first human message"))
            assert events[-1].type == EventType.ERROR
            failed_state = await first_agent.state_manager.load()
            assert failed_state.summary_counter == 1
        finally:
            await first_agent.close()

        second_agent = await make_agent(
            db_path,
            [[StreamChunk(content="continued")]],
            StepTool(),
        )
        try:
            events = await drain(second_agent.run("please continue"))
            assert events[-1].type == EventType.DONE
            completed_state = await second_agent.state_manager.load()
            assert completed_state.summary_counter == 2
        finally:
            await second_agent.close()

    asyncio.run(scenario())


def test_initial_empty_response_keeps_user_intermediate_checkpoint(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = await make_agent(
            tmp_path / "checkpoints.sqlite3",
            [[StreamChunk(finish_reason="stop")]],
            StepTool(),
        )
        try:
            events = await drain(agent.run("在吗"))
            assert events[-1].type == EventType.ERROR
            assert "finish_reason=stop" in events[-1].data
            assert await checkpoint_types(agent.state_manager) == ["intermediate"]
            state = await agent.state_manager.load()
            assert state.messages[-1]["role"] == "user"
            assert "在吗" in state.messages[-1]["content"]
        finally:
            await agent.close()

    asyncio.run(scenario())


def test_empty_response_after_tool_keeps_intermediate_checkpoint(tmp_path: Path) -> None:
    async def scenario() -> None:
        tool = StepTool()
        agent = await make_agent(
            tmp_path / "checkpoints.sqlite3",
            [
                [tool_call("call-a", label="A")],
                [StreamChunk(finish_reason="stop")],
            ],
            tool,
        )
        try:
            events = await drain(agent.run("执行一步"))
            assert events[-1].type == EventType.ERROR
            assert "finish_reason=stop" in events[-1].data

            state = await agent.state_manager.load()
            tool_messages = [item for item in state.messages if item.get("role") == "tool"]
            assert [item["content"] for item in tool_messages] == ["完成 A"]
            assert state.pending_tool_calls == []
            assert await checkpoint_types(agent.state_manager) == ["intermediate"]
        finally:
            await agent.close()

    asyncio.run(scenario())


def test_tool_error_result_is_checkpointed(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = await make_agent(
            tmp_path / "checkpoints.sqlite3",
            [[tool_call("call-error", name="error_step")], RuntimeError("LLM 崩溃")],
            ErrorTool(),
        )
        try:
            await drain(agent.run("执行失败工具"))
            state = await agent.state_manager.load()
            tool_messages = [item for item in state.messages if item.get("role") == "tool"]
            assert tool_messages[-1]["content"] == "错误: 测试工具失败"
            assert state.pending_tool_calls == []
        finally:
            await agent.close()

    asyncio.run(scenario())


def test_partial_tool_batch_is_marked_interrupted_without_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        crashing_tool = StepTool(crash_on="B")
        first_agent = await make_agent(
            db_path,
            [[
                tool_call("call-a", label="A"),
                tool_call("call-b", label="B"),
                tool_call("call-c", label="C"),
            ]],
            crashing_tool,
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await drain(first_agent.run("执行批量工具"))
        finally:
            await first_agent.close()

        recovery_tool = StepTool()
        second_agent = await make_agent(
            db_path,
            [[StreamChunk(content="已继续处理新消息")]],
            recovery_tool,
        )
        try:
            await drain(second_agent.run("新的用户消息"))
            state = await second_agent.state_manager.load()
            by_id = {
                item.get("tool_call_id"): item.get("content")
                for item in state.messages
                if item.get("role") == "tool"
            }
            assert by_id["call-a"] == "完成 A"
            assert by_id["call-b"] == INTERRUPTED_TOOL_RESULT
            assert by_id["call-c"] == INTERRUPTED_TOOL_RESULT
            assert recovery_tool.executed == []
            assert state.pending_tool_calls == []
            assert await checkpoint_types(second_agent.state_manager) == [
                "completed",
                "completed",
            ]
        finally:
            await second_agent.close()

    asyncio.run(scenario())


def test_checkpoint_failure_keeps_tool_marked_pending() -> None:
    class FakeAgent:
        def __init__(self):
            from app.agent.core.event_router import EventRouter
            from app.agent.core.plugin_manager import PluginManager
            from app.agent.core.tool_manager import ToolManager

            self.config = AgentConfig(
                session_id="test",
                model_name="test",
                api_key="test",
                context_strategy=ContextStrategyConfig(),
            )
            self.context_strategy = ContextStrategyManager(self.config.context_strategy)
            self.plugin_manager = PluginManager()
            self.tool_manager = ToolManager()
            self.tool_manager.register(StepTool())
            self.event_router = EventRouter()
            self.llm_client = ScriptedLLM([[tool_call("call-a", label="A")]])

    async def scenario() -> None:
        agent = FakeAgent()
        pipeline = ExecutionPipeline(agent)
        state = AgentState.create_new("test")
        state.add_user_message("执行工具")
        snapshots: list[dict] = []

        async def checkpoint(
            current: AgentState,
            *,
            checkpoint_type: str,
        ) -> int:
            assert checkpoint_type == "intermediate"
            if snapshots:
                raise RuntimeError("模拟 checkpoint 写入失败")
            snapshots.append(deepcopy(current.to_checkpoint()))
            return 1

        with pytest.raises(RuntimeError, match="checkpoint 写入失败"):
            await drain(pipeline.execute(state, checkpoint=checkpoint))

        persisted = AgentState.from_checkpoint(snapshots[0])
        assert [item["id"] for item in persisted.pending_tool_calls] == ["call-a"]
        assert not any(item.get("role") == "tool" for item in persisted.messages)

    asyncio.run(scenario())


def test_interrupt_recovers_across_fresh_agents_and_repeated_response_fails(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        resumed_calls: list[bool] = []
        all_agents = [
            await make_agent(db_path, [[tool_call("shot-1", name="screenshot")]], ResumableScreenshotTool(resumed_calls)),
            await make_agent(db_path, [[tool_call("shot-2", name="screenshot")]], ResumableScreenshotTool(resumed_calls)),
            await make_agent(db_path, [[StreamChunk(content="恢复完成")]], ResumableScreenshotTool(resumed_calls)),
            await make_agent(db_path, [], ResumableScreenshotTool(resumed_calls)),
        ]
        agents = list(all_agents)

        class Settings:
            model_name = "test"

        service = AgentService(
            chat_history_dao=None,
            chat_settings_loader=lambda session_id: Settings(),
            agent_factory=lambda settings: agents.pop(0),
        )

        first_stream = service.stream_chat(AgentInput(message="截屏"), "checkpoint-test")
        assert (await anext(first_stream)).type == EventType.TOOL_CALL
        assert (await anext(first_stream)).type == EventType.INTERRUPT

        # 生成器仍停在 interrupt yield 处时，另一连接已经能读取中断 checkpoint。
        manager = StateManager("checkpoint-test", db_path=str(db_path))
        try:
            first_interrupt = await manager.load()
            assert first_interrupt.is_interrupted()
            assert first_interrupt.summary_counter == 1
            assert await checkpoint_types(manager) == ["intermediate"]
        finally:
            await manager.close()
        await first_stream.aclose()
        assert all_agents[0].llm_client.closed is True

        # 即使创建新的 Agent，请求也能从 checkpoint 恢复，并再次产生持久化中断。
        second_events = await drain(service.resume_after_screenshot("checkpoint-test", True, "image"))
        assert second_events[-1].type == EventType.INTERRUPT
        assert all_agents[1].llm_client.closed is True

        third_events = await drain(service.resume_after_screenshot("checkpoint-test", False))
        assert any(event.type == EventType.TEXT_CHUNK for event in third_events)
        assert resumed_calls == [True, False]
        assert all_agents[2].llm_client.closed is True

        manager = StateManager("checkpoint-test", db_path=str(db_path))
        try:
            resumed_state = await manager.load()
            assert resumed_state.summary_counter == 1
        finally:
            await manager.close()

        # 中断已消费，重复响应不得再次执行工具。
        with pytest.raises(RuntimeError, match="没有中断状态需要恢复"):
            await drain(service.resume_after_screenshot("checkpoint-test", False))
        assert resumed_calls == [True, False]
        assert all_agents[3].llm_client.closed is True

    asyncio.run(scenario())


def test_chat_resolves_unresolved_interrupt_before_new_message(tmp_path: Path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        resumed_calls: list[bool] = []
        first_agent = await make_agent(
            db_path,
            [[tool_call("shot-1", name="screenshot")]],
            ResumableScreenshotTool(resumed_calls),
        )
        try:
            await drain(first_agent.run("请求截屏"))
        finally:
            await first_agent.close()

        second_agent = await make_agent(
            db_path,
            [[StreamChunk(content="开始新任务")]],
            ResumableScreenshotTool(resumed_calls),
        )
        try:
            events = await drain(second_agent.run("新消息"))
            assert events[-1].type == EventType.DONE
            after = await second_agent.state_manager.load()
            assert after.interrupt_data is None
            assert any(
                message.get("role") == "tool"
                and "已拒绝" in message.get("content", "")
                for message in after.messages
            )
            assert any(
                message.get("role") == "user"
                and "新消息" in message.get("content", "")
                for message in after.messages
            )
        finally:
            await second_agent.close()

    asyncio.run(scenario())


def test_new_message_cancels_interrupted_tool_batch_before_starting_turn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "checkpoints.sqlite3"
        resumed_calls: list[bool] = []
        first_agent = await make_agent(
            db_path,
            [[
                tool_call("shot-1", name="screenshot"),
                tool_call("step-2", label="B"),
            ]],
            ResumableScreenshotTool(resumed_calls),
        )
        try:
            await drain(first_agent.run("请求截屏"))
        finally:
            await first_agent.close()

        second_agent = await make_agent(
            db_path,
            [[StreamChunk(content="已切换到新任务")]],
            ResumableScreenshotTool(resumed_calls),
        )
        try:
            events = await drain(second_agent.run("改做别的事情"))
            assert any(event.type == EventType.TEXT_CHUNK for event in events)

            state = await second_agent.state_manager.load()
            tool_results = {
                message.get("tool_call_id"): message.get("content")
                for message in state.messages
                if message.get("role") == "tool"
            }
            assert "已拒绝" in tool_results["shot-1"]
            assert "已取消" in tool_results["step-2"]
            assert state.interrupt_data is None
            assert state.pending_actions == []
            assert state.messages[-2]["role"] == "user"
            assert "改做别的事情" in state.messages[-2]["content"]
            assert resumed_calls == []
        finally:
            await second_agent.close()

    asyncio.run(scenario())


def test_successful_turn_replaces_intermediate_with_completed(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = await make_agent(
            tmp_path / "checkpoints.sqlite3",
            [
                [tool_call("call-a", label="A")],
                [StreamChunk(content="全部完成")],
            ],
            StepTool(),
        )
        try:
            events = await drain(agent.run("执行一步"))
            assert events[-1].type == EventType.DONE
            assert await checkpoint_types(agent.state_manager) == ["completed"]
        finally:
            await agent.close()

    asyncio.run(scenario())
