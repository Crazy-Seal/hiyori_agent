import asyncio
from types import SimpleNamespace

from app.agent.context import HookContext, PluginHook
from app.agent.models import vlm
from app.agent.plugins import memory as memory_plugin_module
from app.agent.plugins.memory import MemoryPlugin
from app.agent.state import AgentState
from app.agent.utils.domain.images import get_image_task


def test_vlm_default_config(monkeypatch) -> None:
    monkeypatch.setenv("VLM_API_KEY", "test-key")
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    monkeypatch.delenv("VLM_MODEL", raising=False)

    assert vlm._vlm_config() == (
        "test-key",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3-vl-plus",
    )


def test_vlm_environment_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setenv("VLM_API_KEY", "test-key")
    monkeypatch.setenv("VLM_BASE_URL", "http://vlm.test/v1")
    monkeypatch.setenv("VLM_MODEL", "test-vlm")

    assert vlm._vlm_config() == (
        "test-key",
        "http://vlm.test/v1",
        "test-vlm",
    )


def test_vlm_client_is_closed(monkeypatch) -> None:
    clients = []

    class FakeCompletions:
        async def create(self, **kwargs):
            message = SimpleNamespace(content="description")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())
            self.closed = False
            clients.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(vlm, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(vlm, "save_multiple_images", lambda images: ["test.png"])
    monkeypatch.setenv("VLM_API_KEY", "test-key")

    result = asyncio.run(vlm.generate_multiple_image_descriptions(["image-data"]))

    assert result.description == "description"
    assert len(clients) == 1
    assert clients[0].closed is True


def test_memory_plugin_starts_and_consumes_image_task(monkeypatch) -> None:
    async def describe(*args, **kwargs):
        return memory_plugin_module.ImageTaskResult("一只猫", ["cat.png"])

    monkeypatch.setattr(
        memory_plugin_module,
        "generate_multiple_image_descriptions",
        describe,
    )

    async def scenario() -> None:
        plugin = MemoryPlugin()
        state = AgentState.create_new("test-session")
        state.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    },
                ],
            }
        )

        await plugin.execute(HookContext.create(PluginHook.ON_INVOKE, state))
        key = state.extra["image_task_key"]
        assert get_image_task(key) is not None

        description, filenames = await plugin._await_image(state)

        assert description == "一只猫"
        assert filenames == ["cat.png"]
        assert "image_task_key" not in state.extra
        assert get_image_task(key) is None
        assert key not in plugin._task_keys

    asyncio.run(scenario())


def test_memory_plugin_annotates_image_message_after_consuming_description(monkeypatch) -> None:
    async def describe(*args, **kwargs):
        return memory_plugin_module.ImageTaskResult("一只猫坐在桌子上。", ["cat.png"])

    class FakeMemoryManager:
        async def try_summary(self, *args, **kwargs):
            return None

        async def add(self, *args, **kwargs):
            return None

    def capture_task(coro, *, logger, task_name):
        coro.close()
        return None

    monkeypatch.setattr(
        memory_plugin_module,
        "generate_multiple_image_descriptions",
        describe,
    )
    monkeypatch.setattr(memory_plugin_module, "create_background_task", capture_task)

    async def scenario() -> AgentState:
        plugin = MemoryPlugin()
        monkeypatch.setattr(plugin, "_mm", lambda state: FakeMemoryManager())
        state = AgentState.create_new("test-session")
        state.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    },
                ],
            }
        )
        state.add_assistant_message("看到了。")

        await plugin.execute(HookContext.create(PluginHook.ON_INVOKE, state))
        await plugin.execute(HookContext.create(PluginHook.BEFORE_RESPONSE, state))
        return state

    state = asyncio.run(scenario())

    image_message = state.messages[0]
    assert image_message["image_description"] == "一只猫坐在桌子上。"
    assert image_message["image_filenames"] == ["cat.png"]


def test_memory_plugin_ignores_message_without_image(monkeypatch) -> None:
    called = False

    async def describe(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        memory_plugin_module,
        "generate_multiple_image_descriptions",
        describe,
    )

    async def scenario() -> None:
        plugin = MemoryPlugin()
        state = AgentState.create_new("test-session")
        state.add_user_message("只有文字")

        await plugin.execute(HookContext.create(PluginHook.ON_INVOKE, state))

        assert "image_task_key" not in state.extra
        assert plugin._task_keys == set()

    asyncio.run(scenario())
    assert called is False


def test_memory_plugin_cancels_unconsumed_task(monkeypatch) -> None:
    started = asyncio.Event()

    async def never_finishes(*args, **kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(
        memory_plugin_module, "generate_multiple_image_descriptions", never_finishes
    )

    async def scenario() -> None:
        plugin = MemoryPlugin()
        state = AgentState.create_new("test-session")
        state.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                ],
            }
        )
        context = HookContext.create(PluginHook.ON_INVOKE, state)

        await plugin.execute(context)
        await started.wait()
        key = state.extra["image_task_key"]
        task = get_image_task(key)
        assert task is not None

        await plugin.on_unregister()
        await asyncio.sleep(0)
        assert get_image_task(key) is None
        assert task.cancelled()

    asyncio.run(scenario())
