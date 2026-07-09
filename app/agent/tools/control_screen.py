"""屏幕控制工具。

后端只负责截图定位和恢复编排；实际鼠标键盘操作由前端执行，并在用户确认后回传操作后的截图。
"""

from typing import Annotated, Literal

from app.agent.context import ToolContext, ToolResult
from app.agent.models.vlm import VLMService, clamp_bbox
from app.agent.tools.decorator import tool

Operation = Literal["click", "double", "right", "scroll"]
ScrollDirection = Literal["none", "down", "up"]

VLM_CANVAS_SIZE = 1000


def _validate_args(
    target: str | None,
    operation: str | None,
    text: str | None,
    press_enter: bool | None,
    wait_seconds: int | None,
    scroll_direction: str | None,
) -> tuple[str, Operation, str, bool, int, ScrollDirection] | str:
    resolved_target = (target or "").strip()
    if not resolved_target:
        return "缺少要操作的元素描述。"

    resolved_operation = operation or "double"
    if resolved_operation not in {"click", "double", "right", "scroll"}:
        return "操作方式必须是 click、double、right 或 scroll。"

    resolved_scroll_direction = scroll_direction or "none"
    if resolved_scroll_direction not in {"none", "down", "up"}:
        return "滚动方向必须是 none、down 或 up。"
    if resolved_operation == "scroll" and resolved_scroll_direction == "none":
        return "滚动操作必须指定 scroll_direction 为 down 或 up。"

    resolved_wait_seconds = 3 if wait_seconds is None else wait_seconds
    if resolved_wait_seconds < 0 or resolved_wait_seconds > 60:
        return "等待时长必须在 0 到 60 秒之间。"

    return (
        resolved_target,
        resolved_operation,  # type: ignore[return-value]
        text or "",
        True if press_enter is None else bool(press_enter),
        resolved_wait_seconds,
        resolved_scroll_direction,  # type: ignore[return-value]
    )


def restore_vlm_point(
    bbox: list[int],
    width: int,
    height: int,
) -> dict:
    """把 VLM 的 1000x1000 bbox 中心点还原为截图坐标和比例坐标。"""
    if width <= 0 or height <= 0:
        raise ValueError("截图尺寸无效。")

    x1, y1, x2, y2 = clamp_bbox(bbox, VLM_CANVAS_SIZE, VLM_CANVAS_SIZE)
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    x_ratio = max(0.0, min(center_x / VLM_CANVAS_SIZE, 1.0))
    y_ratio = max(0.0, min(center_y / VLM_CANVAS_SIZE, 1.0))

    return {
        "bbox": [x1, y1, x2, y2],
        "x_ratio": x_ratio,
        "y_ratio": y_ratio,
        "x": round(x_ratio * width),
        "y": round(y_ratio * height),
        "width": width,
        "height": height,
    }


@tool(is_resumable=True)
async def control_screen(
    target: Annotated[str, "要操作的光标位置描述，如'页面上方的搜索框''确认界面中左下方的确认按钮'。必须输入。"],
    operation: Annotated[Operation, "操作方式：click 单击、double 双击、right 右键、scroll 滚动。"] = "double",
    text: Annotated[str, "操作后要在该位置输入的文字；为空则不输入。"] = "",
    press_enter: Annotated[bool, "输入文字后是否按回车。"] = True,
    wait_seconds: Annotated[int, "操作后的等待时长，单位秒，用于等待页面加载。"] = 3,
    scroll_direction: Annotated[ScrollDirection, "滚动方向：none、down 或 up。仅 scroll 操作需要指定。"] = "none",
    context: ToolContext | None = None,
) -> ToolResult:
    """操作用户的屏幕，并回传操作后的屏幕截图。调用此工具前，你需要知道屏幕上的情况，如不知道，可以通过截屏工具获取"""
    normalized = _validate_args(target, operation, text, press_enter, wait_seconds, scroll_direction)
    if isinstance(normalized, str):
        return ToolResult.error(normalized)

    resolved_target, resolved_operation, resolved_text, resolved_press_enter, resolved_wait, resolved_scroll = normalized
    action_state = {
        "target": resolved_target,
        "operation": resolved_operation,
        "text": resolved_text,
        "press_enter": resolved_press_enter,
        "wait_seconds": resolved_wait,
        "scroll_direction": resolved_scroll,
    }

    if context is None:
        return ToolResult.error("缺少工具上下文。")

    if context.resume_data is None:
        return ToolResult.needs_input(
            type="control_screen_capture_request",
            message="Agent 需要截取屏幕以定位要操作的位置。",
            resume_state={
                "phase": "awaiting_capture",
                "action": action_state,
            },
        )

    phase = (context.resume_state or {}).get("phase")

    if phase == "awaiting_execution":
        if not context.resume_data.get("approved"):
            return ToolResult.success("屏幕操作请求被用户拒绝。")

        if not context.resume_data.get("executed", False):
            error_message = context.resume_data.get("error") or "前端未完成屏幕操作。"
            return ToolResult.success(f"屏幕操作失败: {error_message}")

        screenshot_data = context.resume_data.get("screenshot_data")
        if not screenshot_data:
            return ToolResult.success("屏幕操作完成，但未收到操作后的截图。")
        return ToolResult.success("屏幕操作完成，已收到操作后的截图。", image_url=screenshot_data)

    screenshot_data = context.resume_data.get("screenshot_data")
    width = context.resume_data.get("width")
    height = context.resume_data.get("height")
    if not screenshot_data:
        return ToolResult.error("未收到用于定位的屏幕截图。")
    if not isinstance(width, int) or not isinstance(height, int):
        return ToolResult.error("未收到有效的截图尺寸。")

    bbox = await VLMService().locate(resolved_target, screenshot_data)
    coordinates = restore_vlm_point(bbox, width, height)
    execute_data = {
        **action_state,
        "coordinates": coordinates,
    }

    return ToolResult.needs_input(
        type="control_screen_execute_request",
        message=(
            f"Agent 请求对“{resolved_target}”执行 {resolved_operation} 操作。"
            "请确认是否允许。"
        ),
        data=execute_data,
        resume_state={
            "phase": "awaiting_execution",
            "action": action_state,
            "coordinates": coordinates,
        },
    )
