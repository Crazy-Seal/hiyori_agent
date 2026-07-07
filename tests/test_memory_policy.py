import asyncio
from datetime import date

from app.agent.context import HookContext, PluginHook
from app.agent.memory import manager as memory_manager_module
from app.agent.memory.config import MemoryConfig
from app.agent.memory.manager import MemoryManager
from app.agent.message import Message
from app.agent.plugins import memory as memory_plugin_module
from app.agent.plugins.memory import MemoryPlugin
from app.agent.state import AgentState
from app.schemas.chat_settings import AgentPluginSettings, ChatSettings


def _chat_settings(*, enable_diary=True, enable_episodic=True, enable_semantic=True):
    return ChatSettings(
        session_id="test-session",
        model_name="test-model",
        openai_api_key="test-key",
        openai_base_url="http://127.0.0.1:1/v1",
        temperature=0.1,
        system_prompt="test",
        tools_list=[],
        agent_plugins={
            "memory": AgentPluginSettings(
                enabled=True,
                config={
                    "enable_diary": enable_diary,
                    "enable_episodic": enable_episodic,
                    "enable_semantic": enable_semantic,
                },
            )
        },
        skills=[],
    )


def test_memory_persistence_runs_every_ten_human_messages(monkeypatch) -> None:
    scheduled_tasks: list[str] = []

    def capture_task(coro, *, logger, task_name):
        scheduled_tasks.append(task_name)
        coro.close()
        return None

    class FakeMemoryManager:
        async def try_summary(self, *args, **kwargs):
            return None

        async def add(self, *args, **kwargs):
            return None

    monkeypatch.setattr(memory_plugin_module, "create_background_task", capture_task)

    async def scenario() -> AgentState:
        plugin = MemoryPlugin()
        monkeypatch.setattr(plugin, "_mm", lambda state: FakeMemoryManager())
        state = AgentState.create_new("test-session")
        state.summary_counter = 9
        for index in range(10):
            state.add_user_message(f"human-{index}")
            state.add_assistant_message(f"assistant-{index}")

        await plugin.execute(HookContext.create(PluginHook.BEFORE_RESPONSE, state))
        return state

    state = asyncio.run(scenario())

    assert "memory.persist" in scheduled_tasks
    assert state.summary_counter == 0


def test_memory_plugin_respects_summary_interval_and_disabled_types(monkeypatch) -> None:
    scheduled_tasks: list[str] = []

    def capture_task(coro, *, logger, task_name):
        scheduled_tasks.append(task_name)
        coro.close()
        return None

    class FakeMemoryManager:
        async def try_summary(self, *args, **kwargs):
            return None

        async def add(self, *args, **kwargs):
            raise AssertionError("disabled memory types should skip add")

    monkeypatch.setattr(memory_plugin_module, "create_background_task", capture_task)

    async def scenario() -> AgentState:
        plugin = MemoryPlugin(
            enable_diary=False,
            enable_episodic=False,
            enable_semantic=False,
            summary_every_human_messages=3,
        )
        monkeypatch.setattr(plugin, "_mm", lambda state: FakeMemoryManager())
        state = AgentState.create_new("test-session")
        state.summary_counter = 2
        state.add_user_message("human")
        state.add_assistant_message("assistant")

        await plugin.execute(HookContext.create(PluginHook.BEFORE_RESPONSE, state))
        return state

    state = asyncio.run(scenario())

    assert scheduled_tasks == ["memory.try_summary"]
    assert state.summary_counter == 0


def test_memory_manager_skips_disabled_memory_subsystems(monkeypatch) -> None:
    constructed: list[str] = []

    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            constructed.append("chat_history")

    class DisabledSubsystem:
        def __init__(self, *args, **kwargs):
            raise AssertionError("disabled memory subsystem should not initialize")

    monkeypatch.setattr(memory_manager_module, "ChatHistoryStore", FakeChatHistoryStore)
    monkeypatch.setattr(memory_manager_module, "SummaryMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "EpisodicMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "SemanticMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "Mem0SemanticMemory", DisabledSubsystem)

    manager = MemoryManager(
        "test-session",
        MemoryConfig(),
        _chat_settings(
            enable_diary=False,
            enable_episodic=False,
            enable_semantic=False,
        ),
    )

    assert constructed == ["chat_history"]
    assert manager.summary_memory is None
    assert manager.episodic_memory is None
    assert manager.semantic_memory is None


def test_memory_manager_saves_chat_history_when_diary_is_disabled(monkeypatch) -> None:
    saved_messages: list[tuple[str, str, str]] = []

    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            pass

        async def save_chat_message(
            self,
            session_id,
            role,
            content,
            image_description=None,
            image_filenames=None,
        ):
            saved_messages.append((session_id, role, content))

    class DisabledSummaryMemory:
        def __init__(self, *args, **kwargs):
            raise AssertionError("diary disabled should not initialize SummaryMemory")

    monkeypatch.setattr(memory_manager_module, "ChatHistoryStore", FakeChatHistoryStore)
    monkeypatch.setattr(memory_manager_module, "SummaryMemory", DisabledSummaryMemory)

    async def scenario() -> None:
        manager = MemoryManager(
            "test-session",
            MemoryConfig(),
            _chat_settings(
                enable_diary=False,
                enable_episodic=False,
                enable_semantic=False,
            ),
        )
        await manager.try_summary(
            "你好",
            [{"content": "你好呀", "tool_calls": []}],
            enable_diary=False,
        )

    asyncio.run(scenario())

    assert saved_messages == [
        ("test-session", "Human", "你好"),
        ("test-session", "AI", "你好呀"),
    ]


def test_disabled_memory_subsystems_are_not_accessed(monkeypatch) -> None:
    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            pass

    class DisabledSubsystem:
        def __init__(self, *args, **kwargs):
            raise AssertionError("disabled memory subsystem should not initialize")

    monkeypatch.setattr(memory_manager_module, "ChatHistoryStore", FakeChatHistoryStore)
    monkeypatch.setattr(memory_manager_module, "SummaryMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "EpisodicMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "SemanticMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "Mem0SemanticMemory", DisabledSubsystem)

    async def scenario() -> tuple[dict[str, int], str, str, str]:
        manager = MemoryManager(
            "test-session",
            MemoryConfig(),
            _chat_settings(
                enable_diary=False,
                enable_episodic=False,
                enable_semantic=False,
            ),
        )
        add_result = await manager.add(
            [Message.user_message("近期对话")],
            enable_episodic=False,
            enable_semantic=False,
        )
        context = await manager.get_context(
            "查询",
            include_diary=True,
            include_episodic=True,
            include_semantic=True,
        )
        search_result = await manager.search("查询", "all")
        diary_result = await manager.search_diary(date(2024, 1, 1), date(2024, 1, 2))
        return add_result, context, search_result, diary_result

    add_result, context, search_result, diary_result = asyncio.run(scenario())

    assert add_result == {"episodic": 0, "semantic": 0}
    assert context == ""
    assert search_result == "未找到相关记忆"
    assert diary_result == "日记记忆未启用"
