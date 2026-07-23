"""agent 引擎回归测试（离线，无需网络）。

覆盖以下核心行为：
- 带工具调用的助手消息可正确序列化
- 流式工具调用在流末仅产出一次
- 中断恢复可重入同一工具并注入截屏图片
"""

import asyncio
import types

import pytest

from app.agent.agent import AgentConfig
from app.agent.context import BaseTool, ToolResult
from app.agent.context_strategy import ContextStrategyConfig, ContextStrategyManager
from app.agent.core.event_router import EventRouter, EventType
from app.agent.core.pipeline import ExecutionPipeline
from app.agent.core.plugin_manager import PluginManager
from app.agent.core.tool_manager import ToolManager
from app.agent.message import (
    SCREENSHOT_MESSAGE_NAME,
    AssistantMessageWithTools,
    MessageRole,
    ToolCall,
)
from app.agent.state import AgentState
from app.agent.models.llm_client import LLMClient, LLMConfig, StreamChunk


# ==================== 测试替身 ====================

def _delta(content=None, tool_calls=None, finish_reason=None):
    """构造一个伪 openai 流式 chunk"""
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


def _tc_delta(index, id=None, name=None, arguments=None):
    fn = types.SimpleNamespace(name=name, arguments=arguments)
    return types.SimpleNamespace(index=index, id=id, function=fn)


class _FakeScreenshotTool(BaseTool):
    name = "screenshot"
    description = "截屏"
    parameters_schema = {"type": "object", "properties": {}}
    is_resumable = True

    async def execute(self, args, context):
        if context.resume_data is None:
            return ToolResult.needs_input("screenshot_request", "允许截屏？")
        if not context.resume_data.get("approved"):
            return ToolResult.success("用户拒绝截屏")
        return ToolResult.success("截屏成功", image_url=context.resume_data.get("screenshot_data"))


class _FakeSearchTool(BaseTool):
    name = "search_memory"
    description = "搜索记忆"
    parameters_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, args, context):
        return ToolResult.success(f"检索结果: {args['query']}")


class _FakeLLM:
    """按调用次序回放脚本的伪 LLM 客户端。"""

    def __init__(self, scripts):
        self.scripts = scripts
        self.calls = 0
        self.messages = []

    async def astream(self, messages, tools=None):
        self.messages.append(messages)
        script = self.scripts[self.calls]
        self.calls += 1
        for chunk in script:
            yield chunk


class _FakeAgent:
    def __init__(self, llm, tools):
        self.config = AgentConfig(
            session_id="t", model_name="m", api_key="k",
            context_strategy=ContextStrategyConfig(), system_prompt="sys",
        )
        self.tool_manager = ToolManager()
        for t in tools:
            self.tool_manager.register(t)
        self.plugin_manager = PluginManager()
        self.event_router = EventRouter()
        self.context_strategy = ContextStrategyManager(self.config.context_strategy)
        self.llm_client = llm
        self.pipeline = ExecutionPipeline(self)


async def _drain(agen):
    return [ev async for ev in agen]


# ==================== 流式工具调用聚合 ====================

def test_astream_emits_each_tool_call_once():
    async def run():
        client = LLMClient(LLMConfig(model="m", api_key="k", base_url="http://x/v1"))

        async def fake_create(**kwargs):
            async def gen():
                yield _delta(content="好的")
                yield _delta(tool_calls=[_tc_delta(0, id="call_1", name="screenshot", arguments="")])
                yield _delta(tool_calls=[_tc_delta(0, arguments="{}")])
                yield _delta(finish_reason="tool_calls")
            return gen()

        client._client.chat.completions.create = fake_create
        chunks = [c async for c in client.astream([{"role": "user", "content": "hi"}], tools=[{}])]
        await client.close()
        return chunks

    chunks = asyncio.run(run())
    tool_calls = [c.tool_call for c in chunks if c.tool_call is not None]
    texts = [c.content for c in chunks if c.content]
    assert texts == ["好的"]
    assert len(tool_calls) == 1, f"工具调用应只产出一次，实际 {len(tool_calls)}"
    assert tool_calls[0].name == "screenshot"
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].args == {}


def test_astream_accumulates_fragmented_arguments_and_signature():
    async def run():
        client = LLMClient(LLMConfig(model="m", api_key="k", base_url="http://x/v1"))

        async def fake_create(**kwargs):
            async def gen():
                first_delta = _tc_delta(
                    0,
                    id="call_1",
                    name="search_memory",
                    arguments='{"query":',
                )
                first_delta.extra_content = {
                    "google": {"thought_signature": "signature-value"}
                }
                yield _delta(tool_calls=[
                    first_delta
                ])
                yield _delta(tool_calls=[
                    _tc_delta(0, arguments='"代码优化"}')
                ])
                yield _delta(finish_reason="tool_calls")
            return gen()

        client._client.chat.completions.create = fake_create
        try:
            return [
                chunk async for chunk in client.astream(
                    [{"role": "user", "content": "hi"}], tools=[{}]
                )
            ]
        finally:
            await client.close()

    chunks = asyncio.run(run())
    tool_calls = [chunk.tool_call for chunk in chunks if chunk.tool_call is not None]
    assert len(tool_calls) == 1
    assert tool_calls[0].args == {"query": "代码优化"}
    assert tool_calls[0].extra_content == {
        "google": {"thought_signature": "signature-value"}
    }


def test_astream_separates_different_calls_that_reuse_index():
    async def run():
        client = LLMClient(LLMConfig(model="m", api_key="k", base_url="http://x/v1"))

        async def fake_create(**kwargs):
            async def gen():
                screenshot = _tc_delta(
                    0,
                    id="call_screenshot",
                    name="screenshot",
                    arguments="",
                )
                screenshot.extra_content = {
                    "google": {"thought_signature": "screenshot-signature"}
                }
                yield _delta(tool_calls=[screenshot])

                screenshot_args = _tc_delta(0, arguments="{}")
                screenshot_args.extra_content = {
                    "google": {"thought_signature": "screenshot-signature"}
                }
                yield _delta(tool_calls=[screenshot_args])

                yield _delta(tool_calls=[_tc_delta(
                    0,
                    id="call_diary",
                    name="search_diary",
                    arguments='{"end":"2026-06-19","start":"2026-06-15"}',
                )])
                yield _delta(finish_reason="tool_calls")
            return gen()

        client._client.chat.completions.create = fake_create
        try:
            return [
                chunk async for chunk in client.astream(
                    [{"role": "user", "content": "测试多个工具"}], tools=[{}]
                )
            ]
        finally:
            await client.close()

    chunks = asyncio.run(run())
    tool_calls = [chunk.tool_call for chunk in chunks if chunk.tool_call is not None]
    assert [(call.id, call.name, call.args) for call in tool_calls] == [
        ("call_screenshot", "screenshot", {}),
        (
            "call_diary",
            "search_diary",
            {"end": "2026-06-19", "start": "2026-06-15"},
        ),
    ]
    assert tool_calls[0].extra_content == {
        "google": {"thought_signature": "screenshot-signature"}
    }
    assert tool_calls[1].extra_content is None


@pytest.mark.parametrize(
    "raw_arguments",
    ['{"query":', "[]", '{} trailing', '{}{"query":"代码优化"}'],
)
def test_astream_rejects_invalid_tool_arguments(raw_arguments):
    async def run():
        client = LLMClient(LLMConfig(model="m", api_key="k", base_url="http://x/v1"))

        async def fake_create(**kwargs):
            async def gen():
                yield _delta(tool_calls=[
                    _tc_delta(
                        0,
                        id="call_1",
                        name="search_memory",
                        arguments=raw_arguments,
                    )
                ])
                yield _delta(finish_reason="tool_calls")
            return gen()

        client._client.chat.completions.create = fake_create
        try:
            return [
                chunk async for chunk in client.astream(
                    [{"role": "user", "content": "hi"}], tools=[{}]
                )
            ]
        finally:
            await client.close()

    with pytest.raises(ValueError, match="工具参数解析失败"):
        asyncio.run(run())


# ==================== 助手工具调用序列化 ====================

def test_assistant_message_with_tools_serializes():
    msg = AssistantMessageWithTools(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="c1", name="screenshot", args={})],
    )
    d = msg.to_openai_format()
    assert d["role"] == "assistant"
    assert d["tool_calls"][0]["function"]["name"] == "screenshot"


def test_tool_call_extra_content_roundtrips_into_followup_request():
    async def run():
        signature = {"google": {"thought_signature": "signature-value"}}
        llm = _FakeLLM(scripts=[
            [StreamChunk(tool_call=ToolCall(
                id="c1",
                name="search_memory",
                args={"query": "测试"},
                extra_content=signature,
            ))],
            [StreamChunk(content="搜索功能正常")],
        ])
        agent = _FakeAgent(llm, tools=[_FakeSearchTool()])
        state = AgentState.create_new("t")
        state.add_user_message("测试搜索")
        events = await _drain(agent.pipeline.execute(state))
        return llm, state, events

    llm, state, events = asyncio.run(run())
    assert events[-1].type == EventType.DONE
    assert llm.messages[0][0] == llm.messages[1][0]
    assert "当前本地日期时间：" in llm.messages[0][0]["content"]

    assistant_call = next(
        message for message in llm.messages[1]
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert assistant_call["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-value"}
    }

    restored = AgentState.from_checkpoint(state.to_checkpoint())
    restored_call = next(
        message for message in restored.messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    assert restored_call["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-value"}
    }


# ==================== 可恢复工具与图片注入 ====================

def test_resumable_screenshot_roundtrip():
    async def run():
        llm = _FakeLLM(scripts=[
            # 第 1 次：模型请求截屏
            [StreamChunk(tool_call=ToolCall(id="c1", name="screenshot", args={}))],
            # 恢复后第 2 次：模型基于截图作答
            [StreamChunk(content="我看到一只猫")],
        ])
        agent = _FakeAgent(llm, tools=[_FakeScreenshotTool()])
        state = AgentState.create_new("t")
        state.add_user_message("看看我的屏幕")

        events1 = await _drain(agent.pipeline.execute(state))
        assert events1[-1].type == EventType.INTERRUPT
        # 中断路由信息已持久化
        assert state.interrupt_data["tool_name"] == "screenshot"
        assert state.interrupt_data["tool_call_id"] == "c1"
        assert "resume_state" in state.interrupt_data
        # 发给前端的只有最小字段
        client_payload = events1[-1].data
        assert set(client_payload.keys()) == {"type", "request_id", "message"}

        events2 = await _drain(agent.pipeline.resume_tools(
            state, {"approved": True, "screenshot_data": "data:image/png;base64,AAA"}
        ))
        assert events2[-1].type == EventType.DONE
        return state

    state = asyncio.run(run())
    msgs = state.messages
    # 工具槽位只留文本
    assert any(m.get("role") == "tool" and m.get("content") == "截屏成功" for m in msgs)
    # 截图作为 user 消息注入，带 system_screenshot 名
    shot = [m for m in msgs if m.get("role") == "user" and m.get("name") == SCREENSHOT_MESSAGE_NAME]
    assert shot, "应注入一条 system_screenshot 用户消息"
    assert any(p.get("type") == "image_url" for p in shot[0]["content"])
    # 模型最终基于截图作答
    assistant_texts = [m["content"] for m in msgs
                       if m.get("role") == "assistant" and isinstance(m.get("content"), str)]
    assert "我看到一只猫" in assistant_texts
    # 中断状态已清除
    assert state.interrupt_data is None


# ==================== 核心上下文策略 ====================

def test_context_strategy_builds_without_temporary_state():
    async def run():
        llm = _FakeLLM(scripts=[[StreamChunk(content="你好呀")]])
        agent = _FakeAgent(llm, tools=[])
        state = AgentState.create_new("t")
        state.add_user_message("在吗")
        events = await _drain(agent.pipeline.execute(state))
        return state, events

    state, events = asyncio.run(run())
    assert events[-1].type == EventType.DONE
    assert state.extra == {}
    # state.messages 仍含完整对话
    roles = [m.get("role") for m in state.messages]
    assert roles == ["user", "assistant"]


@pytest.mark.parametrize("content", [None, "", "   \n\t"])
def test_pipeline_rejects_empty_final_response(content):
    async def run():
        script = [StreamChunk(finish_reason="stop")]
        if content is not None:
            script.insert(0, StreamChunk(content=content))
        agent = _FakeAgent(_FakeLLM(scripts=[script]), tools=[])
        state = AgentState.create_new("t")
        state.add_user_message("在吗")
        return state, await _drain(agent.pipeline.execute(state))

    state, events = asyncio.run(run())
    assert events[-1].type == EventType.ERROR
    assert events[-1].data == "模型未返回有效文本（finish_reason=stop）"
    assert all(event.type != EventType.DONE for event in events)
    assert [message["role"] for message in state.messages] == ["user"]


def test_pipeline_keeps_content_filter_error():
    async def run():
        agent = _FakeAgent(
            _FakeLLM(scripts=[[StreamChunk(finish_reason="content_filter")]]),
            tools=[],
        )
        state = AgentState.create_new("t")
        state.add_user_message("在吗")
        return await _drain(agent.pipeline.execute(state))

    events = asyncio.run(run())
    assert events[-1].type == EventType.ERROR
    assert events[-1].data == "触发 API 内容过滤"


# ==================== SSE 格式与 AgentService ====================

def test_sse_formatter_v2_events_byte_compatible():
    from app.agent.core.event_router import AgentEvent, EventType as ET
    from app.utils.sse_formatter import SSEFormatter

    f = SSEFormatter.format
    assert f(AgentEvent(ET.TEXT_CHUNK, "你好")) == 'data: {"response": "你好"}\n\n'
    assert f(AgentEvent(ET.TOOL_CALL, "screenshot")) == \
        'event: tool_call\ndata: {"tool_name": "screenshot"}\n\n'
    interrupt_val = {"type": "screenshot_request", "request_id": "r1", "message": "允许？"}
    assert f(AgentEvent(ET.INTERRUPT, interrupt_val)) == \
        'event: interrupt\ndata: {"value": {"type": "screenshot_request", "request_id": "r1", "message": "允许？"}}\n\n'
    interrupt_with_data = {
        "type": "control_screen_execute_request",
        "request_id": "r2",
        "message": "允许操作？",
        "data": {"x": 1},
    }
    assert f(AgentEvent(ET.INTERRUPT, interrupt_with_data)) == \
        'event: interrupt\ndata: {"value": {"type": "control_screen_execute_request", "request_id": "r2", "message": "允许操作？", "data": {"x": 1}}}\n\n'
    # DONE 交给路由 done()，format 返回 None
    assert f(AgentEvent(ET.DONE, None)) is None


def test_agent_service_v2_stream_and_close():
    from app.agent.core.event_router import AgentEvent, EventType as ET
    from app.services.agent_service import AgentService
    from app.utils.sse_formatter import SSEFormatter

    class _StubAgent:
        def __init__(self):
            self.closed = False
            self.received_message = None

        async def run(self, message, images=None):
            self.received_message = message
            yield AgentEvent(ET.TEXT_CHUNK, "在")
            yield AgentEvent(ET.TOOL_CALL, "search_memory")
            yield AgentEvent(ET.TEXT_CHUNK, "的")
            yield AgentEvent(ET.DONE, None)

        async def close(self):
            self.closed = True

    stub = _StubAgent()

    class _CS:
        model_name = "m"

    svc = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda sid: _CS(),
        agent_factory=lambda cs: stub,
    )

    async def run():
        out = []
        async for ev in svc.stream_chat(_AInput("在吗"), "s"):
            sse = SSEFormatter.format(ev)
            if sse:
                out.append(sse)
        return out

    sse_list = asyncio.run(run())
    assert sse_list == [
        'data: {"response": "在"}\n\n',
        'event: tool_call\ndata: {"tool_name": "search_memory"}\n\n',
        'data: {"response": "的"}\n\n',
    ]
    # 正常结束（无中断）后 agent 被关闭
    assert stub.closed is True
    assert stub.received_message == "在吗"


class _AInput:
    """最小化的 AgentInput 替身（避免引入 pydantic 校验）。"""
    def __init__(self, message, images=None):
        self.message = message
        self.images = images


def test_agent_service_v2_error_raises_and_closes():
    from app.agent.core.event_router import AgentEvent, EventType as ET
    from app.services.agent_service import AgentService

    class _StubAgent:
        def __init__(self):
            self.closed = False

        async def run(self, message, images=None):
            yield AgentEvent(ET.TEXT_CHUNK, "x")
            yield AgentEvent(ET.ERROR, "boom")

        async def close(self):
            self.closed = True

    stub = _StubAgent()

    class _CS:
        model_name = "m"

    svc = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda sid: _CS(),
        agent_factory=lambda cs: stub,
    )

    async def run():
        got_error = False
        try:
            async for _ev in svc.stream_chat(_AInput("hi"), "s"):
                pass
        except RuntimeError:
            got_error = True
        return got_error

    got_error = asyncio.run(run())
    assert got_error is True
    assert stub.closed is True


def test_pending_interrupt_reads_state_manager_without_initializing_agent(monkeypatch):
    from app.services import agent_service as agent_service_module
    from app.services.agent_service import AgentService

    state = AgentState.create_new("pending-session")
    state.set_interrupt(
        {
            "type": "screenshot_request",
            "request_id": "request-1",
            "message": "允许截屏？",
            "data": {"source": "checkpoint"},
            "tool_name": "screenshot",
        }
    )
    closed: list[str] = []

    class FakeStateManager:
        def __init__(self, session_id: str):
            assert session_id == "pending-session"

        async def load(self):
            return state

        async def close(self):
            closed.append("closed")

    monkeypatch.setattr(
        agent_service_module,
        "StateManager",
        FakeStateManager,
        raising=False,
    )

    service = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda _session_id: (_ for _ in ()).throw(
            AssertionError("pending 查询不应读取聊天设置")
        ),
        agent_factory=lambda _settings: (_ for _ in ()).throw(
            AssertionError("pending 查询不应构造 Agent")
        ),
    )

    result = asyncio.run(service.get_pending_interrupt("pending-session"))

    assert result == {
        "pending": True,
        "interrupt": {
            "value": {
                "type": "screenshot_request",
                "request_id": "request-1",
                "message": "允许截屏？",
                "data": {"source": "checkpoint"},
            }
        },
    }
    assert closed == ["closed"]


# ==================== Skill 与 MCP ====================

def test_skill_loads_tools_and_prompt_fragment():
    from app.agent.agent import Agent, AgentConfig
    from app.agent.skills.base import BaseSkill
    from app.agent.skills.registry import SkillRegistry

    @SkillRegistry.register("test_skill")
    class _TestSkill(BaseSkill):
        name = "test_skill"
        system_prompt_fragment = "你已获得读文件能力。"
        tools = ["read_file"]
        plugins = []

    async def run():
        config = AgentConfig(session_id="t", model_name="m", api_key="k",
                             context_strategy=ContextStrategyConfig(),
                             system_prompt="基础", skills=["test_skill"])
        agent = Agent(config)
        await agent.initialize()
        return agent

    try:
        agent = asyncio.run(run())
        assert agent.tool_manager.has("read_file"), "Skill 的工具应被注册"
        assert "你已获得读文件能力。" in agent.config.system_prompt
        assert agent.config.system_prompt.startswith("基础")
    finally:
        SkillRegistry.clear()
