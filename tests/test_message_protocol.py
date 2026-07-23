from app.agent.message import (
    MCP_TOOL_IMAGE_MESSAGE_NAME,
    SCREENSHOT_COMPRESSED_NAME,
    SCREENSHOT_MESSAGE_NAME,
    is_real_human_message,
    is_screenshot_message,
    is_user_message,
)
from app.agent.context import ToolResult
from app.agent.core.pipeline import ExecutionPipeline
from app.agent.message import ToolCall
from app.agent.state import AgentState


def test_message_identity_predicates() -> None:
    human = {"role": "user", "content": "你好"}
    screenshot = {
        "role": "user",
        "content": [],
        "name": SCREENSHOT_MESSAGE_NAME,
    }
    compressed = {
        "role": "user",
        "content": "已压缩",
        "name": SCREENSHOT_COMPRESSED_NAME,
    }
    assistant = {"role": "assistant", "content": "你好"}
    tool = {"role": "tool", "content": "完成"}

    assert is_user_message(human)
    assert is_real_human_message(human)
    assert not is_screenshot_message(human)

    assert is_user_message(screenshot)
    assert is_screenshot_message(screenshot)
    assert not is_real_human_message(screenshot)

    assert is_user_message(compressed)
    assert is_screenshot_message(compressed)
    assert not is_real_human_message(compressed)

    assert not is_user_message(assistant)
    assert not is_real_human_message(assistant)
    assert not is_user_message(tool)


def test_mcp_tool_image_is_system_injected_not_real_human() -> None:
    message = {
        "role": "user",
        "name": MCP_TOOL_IMAGE_MESSAGE_NAME,
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,MQ=="}}],
    }

    assert not is_real_human_message(message)


def test_tool_images_are_flushed_after_all_tool_messages() -> None:
    """同一批工具的图片不得插入尚未补齐的 tool 槽位之间。"""
    pipeline = object.__new__(ExecutionPipeline)
    state = AgentState.create_new("batch-images")
    first = ToolCall(id="a", name="image_tool", args={})
    second = ToolCall(id="b", name="text_tool", args={})

    pipeline._append_tool_result(
        state,
        first,
        ToolResult.success("image", image_urls=["data:image/png;base64,QQ=="]),
    )
    pipeline._append_tool_result(state, second, ToolResult.success("text"))

    assert [item["role"] for item in state.messages] == ["tool", "tool"]
    assert len(state.deferred_tool_images) == 1
    pipeline._flush_deferred_tool_images(state)
    assert [item["role"] for item in state.messages] == ["tool", "tool", "user"]
    assert state.deferred_tool_images == []


def test_deferred_tool_images_survive_checkpoint() -> None:
    """审批中断时延迟图片必须随 checkpoint 持久化。"""
    state = AgentState.create_new("checkpoint-images")
    state.deferred_tool_images.append({
        "tool_call_id": "a",
        "tool_name": "image_tool",
        "image_message_name": MCP_TOOL_IMAGE_MESSAGE_NAME,
        "image_urls": ["data:image/png;base64,QQ=="],
    })

    restored = AgentState.from_checkpoint(state.to_checkpoint())

    assert restored.deferred_tool_images == state.deferred_tool_images
