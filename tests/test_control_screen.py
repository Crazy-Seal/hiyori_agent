import asyncio

from app.agent.context import ToolContext
from app.agent.tools.control_screen import control_screen, restore_vlm_point


def _context(resume_data=None, resume_state=None) -> ToolContext:
    async def emit_event(_event_type, _data):
        return None

    return ToolContext(
        session_id="test",
        state=None,
        emit_event=emit_event,
        get_checkpoint=lambda: {},
        set_checkpoint=lambda _data: None,
        resume_data=resume_data,
        resume_state=resume_state,
    )


def test_restore_vlm_point_maps_1000_canvas_to_screenshot_size() -> None:
    result = restore_vlm_point([400, 200, 600, 400], 1920, 1080)

    assert result["bbox"] == [400, 200, 600, 400]
    assert result["x_ratio"] == 0.5
    assert result["y_ratio"] == 0.3
    assert result["x"] == 960
    assert result["y"] == 324
    assert result["width"] == 1920
    assert result["height"] == 1080


def test_control_screen_initial_interrupt_requests_capture_without_confirmation() -> None:
    async def run():
        tool = control_screen()
        return await tool.execute({"target": "搜索框"}, _context())

    result = asyncio.run(run())

    assert result.interrupt is not None
    assert result.interrupt.type == "control_screen_capture_request"
    assert result.interrupt.data == {}
    assert result.resume_state["phase"] == "awaiting_capture"
    assert result.resume_state["action"]["operation"] == "double"
    assert result.resume_state["action"]["press_enter"] is True


def test_control_screen_rejects_scroll_without_direction() -> None:
    async def run():
        tool = control_screen()
        return await tool.execute(
            {"target": "列表", "operation": "scroll", "scroll_direction": "none"},
            _context(),
        )

    result = asyncio.run(run())

    assert result.interrupt is None
    assert result.content.startswith("错误:")
    assert "滚动操作必须指定" in result.content


def test_control_screen_capture_resume_sends_execute_payload(monkeypatch) -> None:
    async def fake_locate(_self, intent, image_data_url):
        assert intent == "搜索框"
        assert image_data_url == "data:image/png;base64,AAA"
        return [400, 200, 600, 400]

    monkeypatch.setattr("app.agent.models.vlm.VLMService.locate", fake_locate)

    async def run():
        tool = control_screen()
        return await tool.execute(
            {
                "target": "搜索框",
                "operation": "click",
                "text": "hello",
                "press_enter": False,
                "wait_seconds": 1,
            },
            _context(
                resume_data={
                    "screenshot_data": "data:image/png;base64,AAA",
                    "width": 1920,
                    "height": 1080,
                },
                resume_state={
                    "phase": "awaiting_capture",
                },
            ),
        )

    result = asyncio.run(run())

    assert result.interrupt is not None
    assert result.interrupt.type == "control_screen_execute_request"
    assert result.interrupt.data["target"] == "搜索框"
    assert result.interrupt.data["operation"] == "click"
    assert result.interrupt.data["text"] == "hello"
    assert result.interrupt.data["press_enter"] is False
    assert result.interrupt.data["coordinates"]["x"] == 960
    assert result.interrupt.data["coordinates"]["y"] == 324
    assert result.resume_state["phase"] == "awaiting_execution"


def test_control_screen_execution_resume_injects_screenshot() -> None:
    async def run():
        tool = control_screen()
        return await tool.execute(
            {"target": "搜索框"},
            _context(
                resume_data={
                    "approved": True,
                    "executed": True,
                    "screenshot_data": "data:image/png;base64,BBB",
                },
                resume_state={"phase": "awaiting_execution"},
            ),
        )

    result = asyncio.run(run())

    assert result.content == "屏幕操作完成，已收到操作后的截图。"
    assert result.image_url == "data:image/png;base64,BBB"


def test_control_screen_execution_resume_handles_rejection() -> None:
    async def run():
        tool = control_screen()
        return await tool.execute(
            {"target": "搜索框"},
            _context(
                resume_data={"approved": False},
                resume_state={"phase": "awaiting_execution"},
            ),
        )

    result = asyncio.run(run())

    assert result.content == "屏幕操作请求被用户拒绝。"
    assert result.image_url is None
