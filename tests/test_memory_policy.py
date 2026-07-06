import asyncio

from app.agent.context import HookContext, PluginHook
from app.agent.plugins import memory as memory_plugin_module
from app.agent.plugins.memory import MemoryPlugin
from app.agent.state import AgentState


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
