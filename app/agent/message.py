"""
消息类型定义

兼容 OpenAI API 格式。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json


SCREENSHOT_MESSAGE_NAME = "system_screenshot"
SCREENSHOT_COMPRESSED_NAME = "system_screenshot_compressed"


def is_user_message(message: dict) -> bool:
    """判断消息是否使用 user 角色。"""
    return isinstance(message, dict) and message.get("role") == "user"


def is_screenshot_message(message: dict) -> bool:
    """判断消息是否为原始截图或已压缩截图。"""
    return is_user_message(message) and message.get("name") in (
        SCREENSHOT_MESSAGE_NAME,
        SCREENSHOT_COMPRESSED_NAME,
    )


def is_real_human_message(message: dict) -> bool:
    """判断消息是否为真实用户输入，而不是系统注入的截图。"""
    return is_user_message(message) and not is_screenshot_message(message)


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ContentPart:
    """多模态内容块"""
    type: str  # "text" | "image_url"
    text: str | None = None
    image_url: dict | None = None  # {"url": "data:..."}

    @classmethod
    def text_part(cls, text: str) -> "ContentPart":
        """创建文本内容块"""
        return cls(type="text", text=text)

    @classmethod
    def image_part(cls, url: str) -> "ContentPart":
        """创建图片内容块"""
        return cls(type="image_url", image_url={"url": url})

    def to_dict(self) -> dict:
        """转换为字典格式"""
        result = {"type": self.type}
        if self.text:
            result["text"] = self.text
        if self.image_url:
            result["image_url"] = self.image_url
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "ContentPart":
        """从字典创建"""
        return cls(
            type=data["type"],
            text=data.get("text"),
            image_url=data.get("image_url")
        )


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    args: dict
    extra_content: dict | None = None

    def to_dict(self) -> dict:
        """转换为 OpenAI 格式"""
        result = {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.args, ensure_ascii=False)
            }
        }
        if self.extra_content:
            result["extra_content"] = self.extra_content
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "ToolCall":
        """从 OpenAI 格式创建"""
        return cls(
            id=data["id"],
            name=data["function"]["name"],
            args=json.loads(data["function"]["arguments"]),
            extra_content=data.get("extra_content"),
        )


@dataclass
class Message:
    """消息基类"""
    role: MessageRole
    content: str | list[ContentPart]
    timestamp: datetime = field(default_factory=datetime.now)
    name: str | None = None  # 用于 tool 消息标识工具名称

    def to_openai_format(self) -> dict:
        """转换为 OpenAI API 格式"""
        result = {"role": self.role.value}
        if isinstance(self.content, str):
            result["content"] = self.content
        else:
            result["content"] = [p.to_dict() for p in self.content]
        if self.name:
            result["name"] = self.name
        return result

    @classmethod
    def from_openai_format(cls, data: dict) -> "Message":
        """从 OpenAI API 格式创建"""
        role = MessageRole(data["role"])
        content = data.get("content", "")

        # 处理多模态内容
        if isinstance(content, list):
            content = [ContentPart.from_dict(p) for p in content]

        return cls(
            role=role,
            content=content,
            name=data.get("name")
        )

    @classmethod
    def user_message(cls, content: str | list[ContentPart], name: str | None = None) -> "Message":
        """创建用户消息"""
        return cls(role=MessageRole.USER, content=content, name=name)

    @classmethod
    def assistant_message(cls, content: str, name: str | None = None) -> "Message":
        """创建助手消息"""
        return cls(role=MessageRole.ASSISTANT, content=content, name=name)

    @classmethod
    def system_message(cls, content: str) -> "Message":
        """创建系统消息"""
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def tool_message(cls, content: str, tool_name: str, tool_call_id: str | None = None) -> "ToolMessage":
        """创建工具消息"""
        return ToolMessage(
            role=MessageRole.TOOL,
            content=content,
            name=tool_name,
            tool_call_id=tool_call_id
        )


@dataclass
class ToolMessage(Message):
    """工具返回消息"""
    tool_call_id: str | None = None

    def to_openai_format(self) -> dict:
        """转换为 OpenAI API 格式（工具消息需要 tool_call_id）"""
        result = super().to_openai_format()
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class AssistantMessageWithTools(Message):
    """带工具调用的助手消息"""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def to_openai_format(self) -> dict:
        """转换为 OpenAI API 格式"""
        result = super().to_openai_format()
        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return result

    @classmethod
    def from_openai_format(cls, data: dict) -> "AssistantMessageWithTools":
        """从 OpenAI API 格式创建"""
        role = MessageRole(data["role"])
        content = data.get("content", "")

        tool_calls = []
        if "tool_calls" in data:
            tool_calls = [ToolCall.from_dict(tc) for tc in data["tool_calls"]]

        return cls(
            role=role,
            content=content,
            name=data.get("name"),
            tool_calls=tool_calls
        )


def messages_to_openai_format(messages: list[Message]) -> list[dict]:
    """将消息列表转换为 OpenAI API 格式"""
    return [msg.to_openai_format() for msg in messages]


def messages_from_openai_format(data_list: list[dict]) -> list[Message]:
    """从 OpenAI API 格式创建消息列表"""
    messages = []
    for data in data_list:
        role = MessageRole(data["role"])

        # 根据角色和内容选择合适的消息类型
        if role == MessageRole.ASSISTANT and "tool_calls" in data:
            messages.append(AssistantMessageWithTools.from_openai_format(data))
        elif role == MessageRole.TOOL:
            messages.append(ToolMessage(
                role=role,
                content=data.get("content", ""),
                name=data.get("name"),
                tool_call_id=data.get("tool_call_id")
            ))
        else:
            messages.append(Message.from_openai_format(data))

    return messages
