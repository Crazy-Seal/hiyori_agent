from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.core.event_router import AgentEvent, EventType
from app.agent.state import AgentState
from app.routes.control_screen import ControlScreenResponseRequest
from app.routes.control_screen import router as control_screen_router
from app.routes.screenshot import ScreenshotResponseRequest
from app.routes.screenshot import router as screenshot_router
from app.dependencies import get_agent_service
from app.services.agent_service import AgentService


class _StateManager:
    """返回测试预设中断状态的最小 StateManager 替身。"""

    state: AgentState

    def __init__(self, _session_id: str) -> None:
        pass

    async def load(self) -> AgentState:
        return self.state

    async def close(self) -> None:
        pass


class _Agent:
    """记录恢复参数的最小 Agent 替身。"""

    def __init__(self) -> None:
        self.resume_calls: list[dict] = []
        self.closed = False

    async def resume(self, data: dict) -> AsyncIterator[AgentEvent]:
        self.resume_calls.append(data)
        yield AgentEvent(EventType.TEXT_CHUNK, "继续")

    async def close(self) -> None:
        self.closed = True


def _state(interrupt_type: str | None, request_id: str = "request-current") -> AgentState:
    state = AgentState.create_new("session-a")
    if interrupt_type is not None:
        state.set_interrupt({
            "type": interrupt_type,
            "request_id": request_id,
            "message": "请确认",
        })
    return state


def _service(monkeypatch, state: AgentState) -> tuple[AgentService, _Agent, list[str]]:
    from app.services import agent_service as agent_service_module

    _StateManager.state = state
    monkeypatch.setattr(agent_service_module, "StateManager", _StateManager)
    agent = _Agent()
    constructed: list[str] = []

    def factory(_settings) -> _Agent:
        constructed.append("agent")
        return agent

    service = AgentService(
        chat_history_dao=None,
        chat_settings_loader=lambda _session_id: object(),
        agent_factory=factory,
    )
    return service, agent, constructed


async def _drain(stream: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in stream]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interrupt_type", "resume"),
    [
        (
            "mcp_tool_approval_request",
            lambda service: service.resume_after_screenshot(
                "session-a",
                request_id="request-current",
                approved=True,
                screenshot_data="image",
            ),
        ),
        (
            "screenshot_request",
            lambda service: service.resume_after_control_screen(
                "session-a",
                request_id="request-current",
                approved=True,
            ),
        ),
    ],
)
async def test_resume_endpoint_rejects_other_interrupt_types(
    monkeypatch,
    interrupt_type: str,
    resume: Callable[[AgentService], AsyncIterator[AgentEvent]],
) -> None:
    service, _agent, constructed = _service(monkeypatch, _state(interrupt_type))

    with pytest.raises(ValueError, match="类型与响应接口不匹配"):
        await _drain(resume(service))

    assert constructed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interrupt_type", "resume"),
    [
        (
            "screenshot_request",
            lambda service: service.resume_after_screenshot(
                "session-a", request_id="request-stale", approved=False
            ),
        ),
        (
            "control_screen_capture_request",
            lambda service: service.resume_after_control_screen(
                "session-a", request_id="request-stale", approved=False
            ),
        ),
    ],
)
async def test_resume_endpoint_rejects_stale_request_id_before_agent_creation(
    monkeypatch,
    interrupt_type: str,
    resume: Callable[[AgentService], AsyncIterator[AgentEvent]],
) -> None:
    service, _agent, constructed = _service(monkeypatch, _state(interrupt_type))

    with pytest.raises(ValueError, match="确认请求已过期"):
        await _drain(resume(service))

    assert constructed == []


@pytest.mark.asyncio
async def test_resume_endpoint_rejects_missing_interrupt_before_agent_creation(
    monkeypatch,
) -> None:
    service, _agent, constructed = _service(monkeypatch, _state(None))

    with pytest.raises(ValueError, match="没有待处理的确认请求"):
        await _drain(service.resume_after_screenshot(
            "session-a",
            request_id="request-current",
            approved=False,
        ))

    assert constructed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interrupt_type", "resume", "expected_data"),
    [
        (
            "screenshot_request",
            lambda service: service.resume_after_screenshot(
                "session-a",
                request_id="request-current",
                approved=False,
            ),
            {"approved": False},
        ),
        (
            "control_screen_capture_request",
            lambda service: service.resume_after_control_screen(
                "session-a",
                request_id="request-current",
                screenshot_data="image",
                width=10,
                height=20,
            ),
            {"screenshot_data": "image", "width": 10, "height": 20},
        ),
        (
            "control_screen_execute_request",
            lambda service: service.resume_after_control_screen(
                "session-a",
                request_id="request-current",
                approved=True,
                executed=True,
            ),
            {"approved": True, "executed": True},
        ),
    ],
)
async def test_matching_interrupt_resumes_once(
    monkeypatch,
    interrupt_type: str,
    resume: Callable[[AgentService], AsyncIterator[AgentEvent]],
    expected_data: dict,
) -> None:
    service, agent, constructed = _service(monkeypatch, _state(interrupt_type))

    events = await _drain(resume(service))

    assert [event.data for event in events] == ["继续"]
    assert agent.resume_calls == [expected_data]
    assert agent.closed is True
    assert constructed == ["agent"]


def test_old_resume_routes_require_non_empty_request_id() -> None:
    with pytest.raises(ValidationError):
        ScreenshotResponseRequest.model_validate({"session_id": "session-a", "approved": False})
    with pytest.raises(ValidationError):
        ScreenshotResponseRequest.model_validate({
            "session_id": "session-a",
            "request_id": "",
            "approved": False,
        })
    with pytest.raises(ValidationError):
        ControlScreenResponseRequest.model_validate({"session_id": "session-a"})
    with pytest.raises(ValidationError):
        ControlScreenResponseRequest.model_validate({
            "session_id": "session-a",
            "request_id": "",
        })


@pytest.mark.parametrize("path", ["/screenshot/respond", "/control-screen/respond"])
@pytest.mark.parametrize("request_id", [None, ""])
def test_old_resume_http_routes_reject_missing_or_empty_request_id(
    path: str,
    request_id: str | None,
) -> None:
    app = FastAPI()
    app.include_router(screenshot_router)
    app.include_router(control_screen_router)
    app.dependency_overrides[get_agent_service] = lambda: object()
    payload = {"session_id": "session-a", "approved": False}
    if request_id is not None:
        payload["request_id"] = request_id

    with TestClient(app) as client:
        response = client.post(path, json=payload)

    assert response.status_code == 422


class _RouteAgentService:
    """记录旧恢复路由转发参数的 AgentService 替身。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def resume_after_screenshot(
        self,
        session_id: str,
        *,
        request_id: str,
        **_kwargs,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(("screenshot", session_id, request_id))
        yield AgentEvent(EventType.TEXT_CHUNK, "ok")

    async def resume_after_control_screen(
        self,
        session_id: str,
        *,
        request_id: str,
        **_kwargs,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(("control", session_id, request_id))
        yield AgentEvent(EventType.TEXT_CHUNK, "ok")


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/screenshot/respond", "screenshot"),
        ("/control-screen/respond", "control"),
    ],
)
def test_old_resume_http_routes_forward_interrupt_request_id(
    path: str,
    kind: str,
) -> None:
    app = FastAPI()
    app.include_router(screenshot_router)
    app.include_router(control_screen_router)
    service = _RouteAgentService()
    app.dependency_overrides[get_agent_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(path, json={
            "session_id": "session-a",
            "request_id": "interrupt-123",
            "approved": False,
        })

    assert response.status_code == 200
    assert service.calls == [(kind, "session-a", "interrupt-123")]
