"""将 MCP 工具目录适配到 Ayaya 的统一 ToolManager。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections import Counter
from typing import Any, TYPE_CHECKING

from app.agent.context import BaseTool, ToolContext, ToolResult
from app.agent.message import MCP_TOOL_IMAGE_MESSAGE_NAME
from app.mcp.identity import tool_contract_fingerprint
from app.mcp.types import MCPToolDescriptor
from app.mcp.limits import (
    ALLOWED_IMAGE_MIME_TYPES,
    BoundedTextBuilder,
    MAX_CONTENT_PARTS,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_CALL,
    MAX_SCHEMA_BYTES,
    MAX_SCHEMA_DEPTH,
    MAX_SCHEMA_NODES,
    MAX_TOTAL_IMAGE_BYTES,
    append_json,
    validate_json_value,
)
from app.schemas.mcp import MCPToolPolicy

if TYPE_CHECKING:
    from app.services.mcp_connection_manager import MCPConnectionManager
    from app.services.mcp_policy_resolver import MCPPolicyResolver


def build_exposed_tool_name(server_id: str, remote_tool_name: str) -> str:
    """生成唯一且符合模型 API 限制的 MCP 工具名称。

    Args:
        server_id: MCP Server ID。
        remote_tool_name: Server 中的原始工具名称。

    Returns:
        带 Server 命名空间、最长 64 字符的模型可见名称。
    """
    raw = f"mcp__{server_id}__{remote_tool_name}"
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if normalized == raw and len(normalized) <= 64:
        return normalized
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:54]}__{digest}"[:64]


class MCPToolAdapter(BaseTool):
    """把单个 MCP 工具适配到 Ayaya 的统一工具协议。"""

    def __init__(
        self,
        *,
        session_id: str,
        server_id: str,
        server_name: str,
        descriptor: MCPToolDescriptor,
        policy: MCPToolPolicy,
        connection_manager: "MCPConnectionManager",
        policy_resolver: "MCPPolicyResolver",
    ):
        """初始化 MCP 工具适配器。

        Args:
            session_id: 模型配置对应的会话 ID。
            server_id: MCP Server ID。
            server_name: MCP Server 显示名称。
            descriptor: 远端工具契约描述符。
            policy: 创建适配器时的工具权限快照。
            connection_manager: 进程级 MCP 连接管理器。
            policy_resolver: 会话级实时权限解析器。
        """
        self.session_id = session_id
        self.server_id = server_id
        self.server_name = server_name
        self.remote_tool_name = descriptor.name
        self.name = build_exposed_tool_name(server_id, descriptor.name)
        self.description = f"[MCP: {server_name}] {descriptor.description}".strip()
        self.parameters_schema = descriptor.input_schema or {"type": "object", "properties": {}}
        self.policy = policy
        self.tool_contract_fingerprint = tool_contract_fingerprint(descriptor)
        self.is_resumable = True
        self._connection_manager = connection_manager
        self._policy_resolver = policy_resolver

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        """校验实时权限并执行或中断 MCP 工具调用。

        Args:
            args: 模型生成的工具调用参数。
            context: 包含会话状态和中断恢复数据的工具上下文。

        Returns:
            执行结果、授权中断或安全校验错误。
        """
        if context.resume_data is not None and context.resume_data.get("approved") is not True:
            return ToolResult.error("用户拒绝了本次 MCP 工具调用")

        policy = self._policy_resolver.get_policy(
            self.session_id,
            self.server_id,
            self.remote_tool_name,
        )
        if policy == MCPToolPolicy.DENY:
            return ToolResult.error("此 MCP 工具不允许使用")

        if context.resume_data is not None:
            snapshot = context.resume_state or {}
            current_server_identity = self._connection_manager.get_server_identity(self.server_id)
            if (
                snapshot.get("server_id") != self.server_id
                or snapshot.get("server_identity_fingerprint") != current_server_identity
                or snapshot.get("tool_name") != self.remote_tool_name
                or snapshot.get("tool_contract_fingerprint") != self.tool_contract_fingerprint
                or snapshot.get("arguments") != args
            ):
                return ToolResult.error(
                    "MCP_APPROVAL_STALE: MCP 服务器配置或工具定义已变化，请重新发起调用并确认"
                )

        identity_error = self._validate_policy_identity()
        if identity_error:
            return ToolResult.error(identity_error)

        if policy == MCPToolPolicy.ASK:
            if context.resume_data is None:
                return ToolResult.needs_input(
                    type="mcp_tool_approval_request",
                    message=f"MCP 服务器 {self.server_name} 请求调用工具 {self.remote_tool_name}",
                    data={
                        "server_id": self.server_id,
                        "server_name": self.server_name,
                        "tool_name": self.remote_tool_name,
                        "description": self.description,
                        "arguments": args,
                    },
                    resume_state={
                        "server_id": self.server_id,
                        "server_identity_fingerprint": self._connection_manager.get_server_identity(
                            self.server_id
                        ),
                        "tool_name": self.remote_tool_name,
                        "tool_contract_fingerprint": self.tool_contract_fingerprint,
                        "arguments": args,
                    },
                )

        try:
            approved_contract = (
                self.tool_contract_fingerprint if context.resume_data is not None else None
            )
            result = await self._connection_manager.call_tool(
                self.server_id,
                self.remote_tool_name,
                args,
                execution_guard=lambda: self._execution_guard(approved_contract),
            )
        except Exception as exc:
            return ToolResult.error(str(exc))
        return self._convert_result(result)

    def _execution_guard(self, approved_contract: str | None = None) -> str | None:
        """在获得调用租约前执行最终权限和契约校验。

        Args:
            approved_contract: 用户批准时看到的工具契约指纹。

        Returns:
            校验失败时的错误消息；通过时返回 ``None``。
        """
        policy = self._policy_resolver.get_policy(
            self.session_id,
            self.server_id,
            self.remote_tool_name,
        )
        if policy == MCPToolPolicy.DENY:
            return "当前模型未获准使用此 MCP 工具"
        identity_error = self._validate_policy_identity()
        if identity_error:
            return identity_error
        if (
            approved_contract is not None
            and self._connection_manager.get_tool_contract_fingerprint(
                self.server_id, self.remote_tool_name
            ) != approved_contract
        ):
            return "MCP_APPROVAL_STALE: MCP 工具定义已变化，请重新发起调用并确认"
        return None

    def _validate_policy_identity(self) -> str | None:
        """校验实时会话权限是否绑定到当前 Server 身份。

        Returns:
            身份缺失或发生变化时的错误消息；校验通过时返回 ``None``。
        """
        expected = self._policy_resolver.get_bound_identity(
            self.session_id,
            self.server_id,
        )
        if expected != self._connection_manager.get_server_identity(self.server_id):
            return "MCP_IDENTITY_UNBOUND: 当前模型权限尚未绑定到此 MCP 服务器身份"
        return None

    @staticmethod
    def _convert_result(result: Any) -> ToolResult:
        """把 MCP SDK 调用结果转换为 Ayaya 工具结果。

        Args:
            result: MCP SDK 返回的原始调用结果。

        Returns:
            包含文本、结构化内容和图片的统一工具结果。
        """
        builder = BoundedTextBuilder()
        needs_separator = False
        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)

        images: list[str] = []
        ignored_images: Counter[str] = Counter()
        unsupported_count = 0
        skipped_content_parts = 0
        total_image_bytes = 0
        content_parts = getattr(result, "content", None) or []
        try:
            content_part_count = len(content_parts)
        except TypeError:
            content_part_count = None
        for index, part in enumerate(content_parts):
            if index >= MAX_CONTENT_PARTS:
                skipped_content_parts = (
                    max(1, content_part_count - index)
                    if content_part_count is not None
                    else 1
                )
                break
            part_type = getattr(part, "type", "unknown")
            if part_type == "text":
                text = getattr(part, "text", None)
                if text:
                    if needs_separator:
                        builder.append("\n")
                    builder.append(text)
                    needs_separator = True
            elif part_type == "image":
                data = getattr(part, "data", "")
                mime_value = getattr(part, "mimeType", getattr(part, "mime_type", ""))
                mime_type = mime_value if isinstance(mime_value, str) else ""
                reason: str | None = None
                decoded = b""
                if len(images) >= MAX_IMAGES_PER_CALL:
                    reason = "图片数量超过限制"
                elif mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                    reason = "MIME 不支持"
                elif not isinstance(data, str) or (len(data) * 3) // 4 > MAX_IMAGE_BYTES:
                    reason = "单张图片超过限制"
                else:
                    try:
                        decoded = base64.b64decode(data, validate=True)
                    except (binascii.Error, ValueError):
                        reason = "Base64 非法"
                if reason is None and len(decoded) > MAX_IMAGE_BYTES:
                    reason = "单张图片超过限制"
                if reason is None and total_image_bytes + len(decoded) > MAX_TOTAL_IMAGE_BYTES:
                    reason = "图片总量超过限制"
                if reason is None and not MCPToolAdapter._has_valid_image_signature(mime_type, decoded):
                    reason = "文件签名不匹配"
                if reason is not None:
                    ignored_images[reason] += 1
                else:
                    total_image_bytes += len(decoded)
                    images.append(f"data:{mime_type};base64,{data}")
            elif part_type != "text":
                unsupported_count += 1

        if unsupported_count:
            if needs_separator:
                builder.append("\n\n")
            builder.append(f"[已忽略 {unsupported_count} 个不支持的 MCP 内容类型]")
            needs_separator = True
        for reason, count in ignored_images.items():
            if needs_separator:
                builder.append("\n\n")
            builder.append(f"[已忽略 {count} 张 MCP 图片：{reason}]")
            needs_separator = True
        if skipped_content_parts:
            if needs_separator:
                builder.append("\n\n")
            builder.append(
                f"[已忽略 {skipped_content_parts} 个 MCP content parts：超过总数限制]"
            )
            needs_separator = True
        if structured is not None:
            if needs_separator:
                builder.append("\n\n")
            try:
                validate_json_value(
                    structured,
                    label="MCP structured content",
                    max_depth=MAX_SCHEMA_DEPTH,
                    max_nodes=MAX_SCHEMA_NODES,
                    max_bytes=MAX_SCHEMA_BYTES,
                )
                append_json(builder, structured)
            except ValueError as exc:
                builder.append(f"[已忽略 structured content: {exc}]")

        content = builder.build() or "(MCP 工具未返回内容)"
        if bool(getattr(result, "isError", getattr(result, "is_error", False))):
            return ToolResult.error(content or "MCP Server 返回错误")
        return ToolResult.success(
            content,
            image_urls=images,
            image_message_name=MCP_TOOL_IMAGE_MESSAGE_NAME,
        )

    @staticmethod
    def _has_valid_image_signature(mime_type: str, data: bytes) -> bool:
        """校验已解码图片的魔数是否与声明 MIME 匹配。"""
        if mime_type == "image/png":
            return data.startswith(b"\x89PNG\r\n\x1a\n")
        if mime_type == "image/jpeg":
            return data.startswith(b"\xff\xd8\xff")
        if mime_type == "image/webp":
            return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        return False
