import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.chat_settings import ChatSettings
from app.services import agent_service as agent_service_module
from app.services.agent_service import AgentService


class FakeChatHistoryDao:
    def __init__(self):
        self.saved: list[tuple[str, str, str]] = []

    def save_chat_message(self, session_id: str, role: str, content: str) -> None:
        self.saved.append((session_id, role, content))


class DummyChunk:
    def __init__(self, content: object, text_value: str = ""):
        self.content = content
        self._text_value = text_value

    def text(self) -> str:
        return self._text_value


def _build_settings(session_id: str) -> ChatSettings:
    return ChatSettings(
        session_id=session_id,
        model_name="gpt-4o-mini",
        openai_api_key="sk-test",
        openai_base_url="https://example.com/v1",
        temperature=0.2,
        system_prompt="test",
        tools_list=[],
    )


def test_stream_chat_rolls_back_and_returns_error_when_model_returns_no_text(monkeypatch):
    rollback_calls: list[tuple[str, int]] = []

    def fake_stream(_message: str, _settings: ChatSettings):
        yield DummyChunk(content=[])
        yield DummyChunk(content="")

    def fake_watermark(_session_id: str) -> int:
        return 5

    def fake_rollback(session_id: str, baseline: int):
        rollback_calls.append((session_id, baseline))
        return (2, 3)

    monkeypatch.setattr(agent_service_module, "invoke_agent_stream", fake_stream)
    monkeypatch.setattr(agent_service_module, "get_thread_checkpoint_watermark", fake_watermark)
    monkeypatch.setattr(agent_service_module, "rollback_thread_checkpoints_after", fake_rollback)

    dao = FakeChatHistoryDao()
    service = AgentService(chat_history_dao=dao, chat_settings_loader=_build_settings)

    outputs = list(service.stream_chat("hello", "sid-no-text"))

    assert outputs == ["[错误：未返回内容]"]
    assert rollback_calls == [("sid-no-text", 5)]
    assert dao.saved == []


def test_stream_chat_extracts_text_from_mixed_content(monkeypatch):
    def fake_stream(_message: str, _settings: ChatSettings):
        yield DummyChunk(content=["你好", {"text": "世界"}])

    monkeypatch.setattr(agent_service_module, "invoke_agent_stream", fake_stream)
    monkeypatch.setattr(agent_service_module, "get_thread_checkpoint_watermark", lambda _sid: 0)

    dao = FakeChatHistoryDao()
    service = AgentService(chat_history_dao=dao, chat_settings_loader=_build_settings)

    outputs = list(service.stream_chat("hello", "sid-text"))

    assert outputs == ["你好世界"]
    assert dao.saved[-1] == ("sid-text", "AI", "你好世界")


def test_stream_chat_falls_back_to_chunk_text_method(monkeypatch):
    def fake_stream(_message: str, _settings: ChatSettings):
        yield DummyChunk(content={"type": "tool_call"}, text_value="tool result text")

    monkeypatch.setattr(agent_service_module, "invoke_agent_stream", fake_stream)
    monkeypatch.setattr(agent_service_module, "get_thread_checkpoint_watermark", lambda _sid: 0)

    dao = FakeChatHistoryDao()
    service = AgentService(chat_history_dao=dao, chat_settings_loader=_build_settings)

    outputs = list(service.stream_chat("hello", "sid-text-method"))

    assert outputs == ["tool result text"]
    assert dao.saved[-1] == ("sid-text-method", "AI", "tool result text")


def test_stream_chat_rolls_back_and_returns_error_when_graph_raises(monkeypatch):
    rollback_calls: list[tuple[str, int]] = []

    def fake_stream(_message: str, _settings: ChatSettings):
        raise RuntimeError("graph failed")
        yield DummyChunk(content="never")

    monkeypatch.setattr(agent_service_module, "invoke_agent_stream", fake_stream)
    monkeypatch.setattr(agent_service_module, "get_thread_checkpoint_watermark", lambda _sid: 7)
    monkeypatch.setattr(
        agent_service_module,
        "rollback_thread_checkpoints_after",
        lambda session_id, baseline: rollback_calls.append((session_id, baseline)) or (1, 1),
    )

    dao = FakeChatHistoryDao()
    service = AgentService(chat_history_dao=dao, chat_settings_loader=_build_settings)

    outputs = list(service.stream_chat("hello", "sid-error"))

    assert outputs == ["[错误：未返回内容]"]
    assert rollback_calls == [("sid-error", 7)]
    assert dao.saved == []
