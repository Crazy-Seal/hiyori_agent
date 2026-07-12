"""消息时间的存储、展示和临时投影。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def system_timezone():
    return datetime.now().astimezone().tzinfo


def normalize_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=system_timezone())
    return parsed.astimezone(timezone.utc)


def format_local_time(value: datetime | str) -> str:
    local = normalize_utc(value).astimezone()
    return f"{local.strftime('%Y-%m-%d %H:%M:%S %z')} {WEEKDAYS[local.weekday()]}"


def render_timed_text(content: str, timestamp: datetime | str) -> str:
    return f"[发送时间：{format_local_time(timestamp)}] {content}"


def _project_content(content: Any, timestamp: datetime | str) -> Any:
    if isinstance(content, str):
        return render_timed_text(content, timestamp)
    if not isinstance(content, list):
        return content
    projected = deepcopy(content)
    prefix = f"[发送时间：{format_local_time(timestamp)}]"
    for part in projected:
        if isinstance(part, dict) and part.get("type") == "text":
            part["text"] = f"{prefix} {part.get('text', '')}".rstrip()
            return projected
    projected.insert(0, {"type": "text", "text": prefix})
    return projected


def project_messages_with_time(messages: list[dict]) -> list[dict]:
    projected = deepcopy(messages)
    for message in projected:
        timestamp = message.get("_created_at")
        if not timestamp:
            continue
        role = message.get("role")
        is_plain_assistant = role == "assistant" and not message.get("tool_calls")
        if role != "user" and not is_plain_assistant:
            continue
        message["content"] = _project_content(message.get("content"), timestamp)
    return projected


@dataclass(frozen=True)
class RuntimeContext:
    started_at: datetime

    @classmethod
    def capture(cls) -> "RuntimeContext":
        return cls(started_at=utc_now())

    @property
    def system_text(self) -> str:
        return f"当前本地日期时间：{format_local_time(self.started_at)}"
