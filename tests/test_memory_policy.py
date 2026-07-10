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

    assert constructed == []
    assert manager.summary_memory is None
    assert manager.episodic_memory is None
    assert manager.semantic_memory is None


def test_memory_manager_uses_mem0_even_with_legacy_backend_env(monkeypatch) -> None:
    constructed: list[tuple[str, str]] = []

    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            pass

    class DisabledSubsystem:
        def __init__(self, *args, **kwargs):
            raise AssertionError("disabled memory subsystem should not initialize")

    class FakeMem0SemanticMemory:
        def __init__(self, session_id, config, chat_settings):
            constructed.append((session_id, chat_settings.session_id))

    monkeypatch.setenv("SEMANTIC_BACKEND", "native")
    monkeypatch.setenv("NEO4J_URI", "bolt://legacy.example:7687")
    monkeypatch.setattr(memory_manager_module, "ChatHistoryStore", FakeChatHistoryStore)
    monkeypatch.setattr(memory_manager_module, "SummaryMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "EpisodicMemory", DisabledSubsystem)
    monkeypatch.setattr(memory_manager_module, "Mem0SemanticMemory", FakeMem0SemanticMemory)

    manager = MemoryManager(
        "test-session",
        MemoryConfig.from_env(),
        _chat_settings(
            enable_diary=False,
            enable_episodic=False,
            enable_semantic=True,
        ),
    )

    assert constructed == [("test-session", "test-session")]
    assert isinstance(manager.semantic_memory, FakeMem0SemanticMemory)


def test_memory_manager_does_not_save_core_chat_history(monkeypatch) -> None:
    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            pass

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
        await manager.check_summary()

    asyncio.run(scenario())


def test_memory_manager_check_summary_uses_persisted_history(monkeypatch) -> None:
    checked_dates: list[date] = []

    class FakeChatHistoryStore:
        def __init__(self, *args, **kwargs):
            pass

    class FakeSummaryMemory:
        def __init__(self, *args, **kwargs):
            pass

        async def check_and_generate(self, effective_date: date) -> None:
            checked_dates.append(effective_date)

    monkeypatch.setattr(memory_manager_module, "ChatHistoryStore", FakeChatHistoryStore)
    monkeypatch.setattr(memory_manager_module, "SummaryMemory", FakeSummaryMemory)

    manager = MemoryManager(
        "test-session",
        MemoryConfig(),
        _chat_settings(
            enable_diary=True,
            enable_episodic=False,
            enable_semantic=False,
        ),
    )
    asyncio.run(manager.check_summary())

    assert checked_dates


def test_memory_plugin_keeps_counter_when_commit_job_preparation_fails(monkeypatch) -> None:
    async def scenario() -> tuple[AgentState, dict]:
        plugin = MemoryPlugin(summary_every_human_messages=3)
        monkeypatch.setattr(
            plugin,
            "_mm",
            lambda state: (_ for _ in ()).throw(RuntimeError("初始化记忆失败")),
        )
        state = AgentState.create_new("test-session")
        state.summary_counter = 2
        state.add_user_message("你好")
        state.add_assistant_message("你好呀")
        commit_context: dict = {}

        await plugin.execute(
            HookContext.create(
                PluginHook.BEFORE_RESPONSE_COMMIT,
                state,
                data=commit_context,
            )
        )
        return state, commit_context

    state, commit_context = asyncio.run(scenario())

    assert state.summary_counter == 3
    assert "memory" not in commit_context

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
