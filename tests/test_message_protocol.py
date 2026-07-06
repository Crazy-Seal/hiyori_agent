from app.agent.message import (
    SCREENSHOT_COMPRESSED_NAME,
    SCREENSHOT_MESSAGE_NAME,
    is_real_human_message,
    is_screenshot_message,
    is_user_message,
)


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
