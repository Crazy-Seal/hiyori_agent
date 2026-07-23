"""
上下文类型定义

包含工具执行上下文、插件钩子上下文、中断事件等。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable
import uuid


# ==================== 中断事件 ====================

@dataclass
class InterruptEvent:
    """中断事件 - 用于需要用户确认的场景

    区分两类序列化：
    - to_client(): 只发给前端的最小字段（保持 SSE 字节兼容）
    - to_state():  写入 AgentState.interrupt_data 的完整快照，
                   含恢复同一工具所需的全部路由信息（可持久化、跨请求）
    """
    type: str                    # 中断类型，如 "screenshot_request"
    request_id: str              # 请求唯一标识
    message: str                 # 展示给用户的提示
    data: dict = field(default_factory=dict)  # 额外数据（发给前端的附加内容）

    # 恢复路由（持久化，不一定发给前端）
    tool_name: str = ""          # 被中断的工具名
    tool_call_id: str = ""       # 被中断的工具调用 id
    tool_args: dict = field(default_factory=dict)  # 工具原始参数
    resume_state: dict = field(default_factory=dict)  # 工具中间态（如 VLM 坐标）

    @classmethod
    def create(cls, type: str, message: str, data: dict | None = None) -> "InterruptEvent":
        """创建中断事件"""
        return cls(
            type=type,
            request_id=str(uuid.uuid4()),
            message=message,
            data=data or {}
        )

    def to_client(self) -> dict:
        """
        发给前端的最小字段（SSE value）。
        """
        payload = {
            "type": self.type,
            "request_id": self.request_id,
            "message": self.message,
        }
        if self.data:
            payload["data"] = self.data
        return payload

    def to_state(self) -> dict:
        """写入 AgentState.interrupt_data 的完整持久化快照"""
        return {
            "type": self.type,
            "request_id": self.request_id,
            "message": self.message,
            "data": self.data,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "tool_args": self.tool_args,
            "resume_state": self.resume_state,
        }

    # 默认序列化为客户端字段，避免持久化路由信息进入 SSE。
    def to_dict(self) -> dict:
        return self.to_client()


# ==================== 工具相关 ====================

@dataclass
class ToolContext:
    """工具执行上下文"""
    session_id: str
    state: Any  # AgentState（避免循环引用，使用 Any）
    emit_event: Callable[[str, Any], Awaitable[None]]  # 发送 SSE 事件
    get_checkpoint: Callable[[], dict]                  # 获取当前 checkpoint
    set_checkpoint: Callable[[dict], None]              # 设置 checkpoint
    resume_data: dict | None = None                     # 中断恢复时用户回传的数据
    resume_state: dict | None = None                    # 中断前工具暂存的中间态（恢复执行时读取）


@dataclass
class ToolResult:
    """工具执行结果"""
    content: str                                         # 返回给 LLM 的内容
    interrupt: InterruptEvent | None = None              # 如果需要中断
    state_updates: dict = field(default_factory=dict)    # 状态更新（写入 state.extra）
    resume_state: dict = field(default_factory=dict)     # 中断前暂存、恢复执行时要用的中间态
    image_url: str | None = None                         # 工具产出的图片（注入为用户消息，让模型看见）
    image_urls: list[str] = field(default_factory=list)  # 工具产出的多张图片
    image_message_name: str | None = None                # 用于上下文策略区分图片来源

    @classmethod
    def success(cls, content: str, state_updates: dict | None = None,
                image_url: str | None = None,
                image_urls: list[str] | None = None,
                image_message_name: str | None = None) -> "ToolResult":
        """创建成功结果"""
        return cls(
            content=content,
            state_updates=state_updates or {},
            image_url=image_url,
            image_urls=image_urls or [],
            image_message_name=image_message_name,
        )

    @classmethod
    def error(cls, error_message: str) -> "ToolResult":
        """创建错误结果"""
        return cls(content=f"错误: {error_message}")

    @classmethod
    def interrupt_result(cls, interrupt: InterruptEvent) -> "ToolResult":
        """创建中断结果"""
        return cls(content="", interrupt=interrupt)

    @classmethod
    def needs_input(
        cls,
        type: str,
        message: str,
        resume_state: dict | None = None,
        data: dict | None = None,
    ) -> "ToolResult":
        """创建「需要用户输入」的中断结果（可恢复工具在首次执行、尚未拿到用户输入时使用）

        Args:
            type: 中断类型，如 "screenshot_request"
            message: 展示给用户的提示
            resume_state: 恢复执行时需要的中间态（如 VLM 算出的坐标）
            data: 发给前端的附加数据
        """
        return cls(
            content="",
            interrupt=InterruptEvent.create(type=type, message=message, data=data),
            resume_state=resume_state or {},
        )


# ==================== 插件相关 ====================

class PluginHook(str, Enum):
    """插件钩子点"""
    ON_INVOKE = "on_invoke"             # 初次进入执行循环时（首个消息处理前）
    BEFORE_LLM = "before_llm"           # LLM 调用前
    AFTER_LLM = "after_llm"             # LLM 调用后
    BEFORE_TOOL = "before_tool"         # 工具执行前
    AFTER_TOOL = "after_tool"           # 工具执行后
    BEFORE_RESPONSE_COMMIT = "before_response_commit"  # 最终响应提交前
    AFTER_RESPONSE_COMMIT = "after_response_commit"    # 最终响应提交后
    ON_INTERRUPT = "on_interrupt"       # 中断发生时
    ON_ERROR = "on_error"               # 错误发生时


@dataclass
class HookContext:
    """钩子上下文"""
    hook: PluginHook
    agent_state: Any  # AgentState（避免循环引用）
    data: Any         # 钩子相关的数据
    metadata: dict = field(default_factory=dict)  # 元数据

    @classmethod
    def create(
        cls,
        hook: PluginHook,
        state: Any,
        data: Any = None,
        metadata: dict | None = None
    ) -> "HookContext":
        """创建钩子上下文"""
        return cls(
            hook=hook,
            agent_state=state,
            data=data,
            metadata=metadata or {}
        )


# ==================== 工具基类 ====================

class BaseTool(ABC):
    """工具基类"""

    name: str                    # 工具名称
    description: str             # 工具描述（给 LLM 看）
    parameters_schema: dict      # JSON Schema 格式的参数定义
    is_resumable: bool = False   # 是否为可恢复工具（execute 内靠 context.resume_data 分支）

    @abstractmethod
    async def execute(
        self,
        args: dict,
        context: ToolContext
    ) -> ToolResult:
        """执行工具"""
        pass

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI Tool 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema
            }
        }


# ==================== 插件基类 ====================

class BasePlugin(ABC):
    """插件基类"""

    name: str
    description: str = ""
    inherent: bool = False
    config_model: Any = None
    version: str = "1.0.0"
    priority: int = 100    # 优先级，数值小的先执行

    @property
    @abstractmethod
    def hooks(self) -> list[PluginHook]:
        """订阅的钩子列表"""
        pass

    @abstractmethod
    async def execute(self, context: HookContext) -> HookContext:
        """执行插件逻辑，返回可能修改后的上下文"""
        pass

    async def on_register(self, agent: Any) -> None:
        """注册时的初始化"""
        pass

    async def on_unregister(self) -> None:
        """注销时的清理"""
        pass
