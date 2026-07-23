"""MCP 不可信目录与调用结果的统一资源配额。"""

from __future__ import annotations

import json
from typing import Any, Iterable

MAX_TOOL_RESULT_CHARS = 50_000
MAX_CONTENT_PARTS = 1_000
MAX_IMAGES_PER_CALL = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 25 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_TOOLS_PER_SERVER = 200
MAX_TOOL_NAME_CHARS = 256
MAX_TOOL_DESCRIPTION_CHARS = 8_000
MAX_SCHEMA_BYTES = 256 * 1024
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 10_000
MAX_ANNOTATIONS_BYTES = 64 * 1024
MAX_ANNOTATIONS_DEPTH = 16
MAX_ANNOTATIONS_NODES = 2_000
MAX_INSTRUCTIONS_CHARS = 20_000


class MCPResourceLimitError(ValueError):
    """表示 MCP 外部数据超过应用允许的资源配额。"""


class BoundedTextBuilder:
    """在固定字符预算内增量构造文本，避免复制完整远端结果。"""

    def __init__(self, limit: int = MAX_TOOL_RESULT_CHARS):
        self.limit = limit
        self._parts: list[str] = []
        self._length = 0
        self.truncated = False

    @property
    def remaining(self) -> int:
        """返回尚可写入的字符数。"""
        return max(0, self.limit - self._length)

    def append(self, value: Any) -> None:
        """写入不超过剩余预算的文本片段。"""
        if self.remaining <= 0:
            self.truncated = True
            return
        text = value if isinstance(value, str) else str(value)
        if len(text) > self.remaining:
            self._parts.append(text[: self.remaining])
            self._length = self.limit
            self.truncated = True
            return
        self._parts.append(text)
        self._length += len(text)

    def build(self) -> str:
        """返回最终文本，并在发生截断时添加标记。"""
        value = "".join(self._parts)
        return f"{value}\n\n[结果已截断]" if self.truncated else value


def validate_json_value(
    value: Any,
    *,
    label: str,
    max_depth: int,
    max_nodes: int,
    max_bytes: int,
) -> None:
    """在序列化前限制 JSON 值的深度、节点数和近似字节量。

    Args:
        value: 待验证的 JSON 兼容值。
        label: 错误消息中的数据名称。
        max_depth: 允许的最大嵌套深度。
        max_nodes: 允许遍历的最大节点数。
        max_bytes: 允许的近似 UTF-8 字节数。

    Raises:
        MCPResourceLimitError: 任一配额超限或对象不是 JSON 兼容值。
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    size = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise MCPResourceLimitError(f"{label} 的深度或节点数超过限制")
        if isinstance(current, dict):
            for key, item in current.items():
                key_text = str(key)
                size += len(key_text) if len(key_text) > max_bytes else len(key_text.encode("utf-8"))
                stack.append((item, depth + 1))
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            size += len(current) if len(current) > max_bytes else len(current.encode("utf-8"))
        elif current is not None and not isinstance(current, (bool, int, float)):
            raise MCPResourceLimitError(f"{label} 包含不可序列化值")
        else:
            size += 16
        if size > max_bytes:
            raise MCPResourceLimitError(f"{label} 大小超过限制")


def append_json(builder: BoundedTextBuilder, value: Any) -> None:
    """使用 JSON 增量编码器把值写入剩余文本预算。"""
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2, default=str)
    for chunk in encoder.iterencode(value):
        builder.append(chunk)
        if builder.remaining <= 0:
            break


def validate_tool_catalog(tools: Iterable[Any]) -> list[Any]:
    """在缓存或指纹计算前完整验证 MCP 工具目录。"""
    catalog = tools if isinstance(tools, list) else list(tools)
    if len(catalog) > MAX_TOOLS_PER_SERVER:
        raise MCPResourceLimitError("MCP 工具数量超过限制")
    for tool in catalog:
        name = str(getattr(tool, "name", ""))
        description = str(getattr(tool, "description", "") or "")
        if not name or len(name) > MAX_TOOL_NAME_CHARS:
            raise MCPResourceLimitError("MCP 工具名称为空或超过限制")
        if len(description) > MAX_TOOL_DESCRIPTION_CHARS:
            raise MCPResourceLimitError(f"MCP 工具 '{name}' 的 description 超过限制")
        validate_json_value(
            getattr(tool, "inputSchema", None) or {},
            label=f"MCP 工具 '{name}' 的 Schema",
            max_depth=MAX_SCHEMA_DEPTH,
            max_nodes=MAX_SCHEMA_NODES,
            max_bytes=MAX_SCHEMA_BYTES,
        )
        annotations = getattr(tool, "annotations", None)
        if hasattr(annotations, "model_dump"):
            annotations = annotations.model_dump(mode="json")
        validate_json_value(
            annotations or {},
            label=f"MCP 工具 '{name}' 的 annotations",
            max_depth=MAX_ANNOTATIONS_DEPTH,
            max_nodes=MAX_ANNOTATIONS_NODES,
            max_bytes=MAX_ANNOTATIONS_BYTES,
        )
    return catalog


def limit_instructions(value: Any) -> str | None:
    """截断过长的 Server instructions，并附带明确标记。"""
    if value is None:
        return None
    text = str(value)
    if len(text) <= MAX_INSTRUCTIONS_CHARS:
        return text
    return f"{text[:MAX_INSTRUCTIONS_CHARS]}\n\n[instructions 已截断]"
