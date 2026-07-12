"""
Agent 核心类

门面类，协调各管理器，提供统一的接口。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.agent.state import AgentState
from app.agent.message import ContentPart, ToolCall
from app.agent.context import BaseTool, BasePlugin, PluginHook
from app.agent.core.tool_manager import ToolManager
from app.agent.core.plugin_manager import PluginManager
from app.agent.core.state_manager import StateManager
from app.agent.core.event_router import EventRouter, EventType, AgentEvent
from app.agent.core.pipeline import ExecutionPipeline
from app.agent.models.llm_client import LLMClient, LLMConfig
from app.agent.context_strategy import ContextStrategyConfig, ContextStrategyManager
from app.agent.message_time import RuntimeContext

logger = logging.getLogger(__name__)

INTERRUPTED_TOOL_RESULT = (
    "上次工具链中断，未获得该工具的可靠结果；"
    "为避免重复副作用，本次未自动重试。"
)
USER_REJECTED_INTERRUPTED_TOOL_RESULT = (
    "用户发送了新的消息，待批准工具调用已拒绝。"
)
USER_CANCELLED_PENDING_TOOL_RESULT = (
    "用户发送了新的消息，本批后续工具调用已取消。"
)


@dataclass
class AgentConfig:
    """Agent 配置"""
    session_id: str
    model_name: str
    api_key: str
    context_strategy: ContextStrategyConfig
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    plugins: list[str | dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)


class Agent:
    """Agent 核心类"""

    def __init__(self, config: AgentConfig, db_path: str | None = None):
        self.config = config

        # 核心管理器
        self.tool_manager = ToolManager()
        self.plugin_manager = PluginManager()
        if db_path:
            self.state_manager = StateManager(config.session_id, db_path=db_path)
        else:
            self.state_manager = StateManager(config.session_id)
        self.event_router = EventRouter()
        self.context_strategy = ContextStrategyManager(config.context_strategy)

        # LLM 客户端
        self.llm_client = LLMClient(LLMConfig(
            model=config.model_name,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        ))

        # 执行管道
        self.pipeline = ExecutionPipeline(self)

        # 初始化标志
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 Agent（异步）"""
        if self._initialized:
            return

        # 加载工具
        await self._setup_tools()

        # 加载插件
        await self._setup_plugins()

        # 加载能力包（Skill）：可引入额外工具/插件/提示词片段
        await self._setup_skills()

        # 初始化 MCP
        await self._setup_mcp()

        self._initialized = True
        logger.info(f"Agent 初始化完成: {self.config.session_id}")

    async def _setup_tools(self) -> None:
        """根据配置加载工具"""
        # 从工具注册表加载
        from app.agent.tools.registry import ToolRegistry

        for tool_name in self.config.tools or []:
            tool_class = ToolRegistry.get(tool_name)
            if tool_class:
                tool = tool_class()
                self.tool_manager.register(tool)
                logger.info(f"加载工具: {tool_name}")
            else:
                logger.warning(f"工具 '{tool_name}' 不存在于注册表中")

    async def _setup_plugins(self) -> None:
        """根据配置加载插件"""
        # 从插件注册表加载
        from app.agent.plugins.registry import PluginRegistry

        for plugin_config in self.config.plugins or []:
            if isinstance(plugin_config, str):
                plugin_name = plugin_config
                plugin_params = {}
            else:
                plugin_name = plugin_config.get("name")
                plugin_params = plugin_config.get("config", {})

            plugin_class = PluginRegistry.get(plugin_name)
            if plugin_class:
                plugin = plugin_class(**plugin_params)
                await self.plugin_manager.register(plugin, self)
                logger.info(f"加载插件: {plugin_name}")
            else:
                logger.warning(f"插件 '{plugin_name}' 不存在于注册表中")

    async def _setup_skills(self) -> None:
        """加载能力包：注册其工具/插件并追加提示词片段。"""
        if not self.config.skills:
            return

        from app.agent.skills.registry import SkillRegistry
        from app.agent.tools.registry import ToolRegistry
        from app.agent.plugins.registry import PluginRegistry

        for skill_name in self.config.skills:
            skill_cls = SkillRegistry.get(skill_name)
            if not skill_cls:
                logger.warning("Skill '%s' 不存在于注册表中", skill_name)
                continue
            skill = skill_cls()

            # 引入工具
            for tool_name in skill.tools or []:
                if self.tool_manager.has(tool_name):
                    continue
                tool_cls = ToolRegistry.get(tool_name)
                if tool_cls:
                    self.tool_manager.register(tool_cls())
                else:
                    logger.warning("Skill '%s' 引用的工具 '%s' 不存在", skill_name, tool_name)

            # 引入插件
            for plugin_name in skill.plugins or []:
                if plugin_name in self.plugin_manager:
                    continue
                plugin_cls = PluginRegistry.get(plugin_name)
                if plugin_cls:
                    await self.plugin_manager.register(plugin_cls(), self)
                else:
                    logger.warning("Skill '%s' 引用的插件 '%s' 不存在", skill_name, plugin_name)

            # 追加提示词片段
            if skill.system_prompt_fragment:
                self.config.system_prompt = (
                    f"{self.config.system_prompt}\n\n{skill.system_prompt_fragment}"
                    if self.config.system_prompt
                    else skill.system_prompt_fragment
                )

            await skill.on_load(self)
            logger.info("加载 Skill: %s", skill_name)

    async def _setup_mcp(self) -> None:
        """初始化 MCP 连接"""
        if not self.config.mcp_servers:
            return

        from app.agent.mcp.plugin import MCPPlugin

        for server_config in self.config.mcp_servers:
            try:
                plugin = MCPPlugin(server_config)
                await self.plugin_manager.register(plugin, self)
                logger.info(f"加载 MCP 服务器: {server_config.get('name', 'unknown')}")
            except Exception as e:
                logger.error(f"加载 MCP 服务器失败: {e}")

    async def run(
        self,
        message: str,
        images: list[str] | None = None
    ) -> AsyncIterator[AgentEvent]:
        """运行 Agent

        Args:
            message: 用户消息
            images: 图片列表（data URL 格式）

        Yields:
            AgentEvent: 事件流
        """
        await self.initialize()
        runtime_context = RuntimeContext.capture()

        # 1. 加载或创建状态
        state = await self.state_manager.load()

        if state.is_interrupted():
            interrupt_data = state.interrupt_data or {}
            cancelled_ids = {
                message.get("tool_call_id")
                for message in state.messages
                if message.get("role") == "tool"
            }
            interrupted_id = interrupt_data.get("tool_call_id", "")
            interrupted_name = interrupt_data.get("tool_name", "")
            if interrupted_id and interrupted_id not in cancelled_ids:
                state.add_tool_message(
                    content=USER_REJECTED_INTERRUPTED_TOOL_RESULT,
                    tool_name=interrupted_name,
                    tool_call_id=interrupted_id,
                )
                cancelled_ids.add(interrupted_id)

            for pending in state.pending_actions:
                pending_call = ToolCall.from_dict(pending)
                if pending_call.id in cancelled_ids:
                    continue
                state.add_tool_message(
                    content=USER_CANCELLED_PENDING_TOOL_RESULT,
                    tool_name=pending_call.name,
                    tool_call_id=pending_call.id,
                )
                cancelled_ids.add(pending_call.id)

            state.clear_interrupt()
            state.clear_pending_tool_calls()
            await self.state_manager.save(state, checkpoint_type="completed")

        # 上次普通工具链若异常中止，为未完成调用补齐结果，避免自动重试副作用。
        pending_tool_calls = state.get_pending_tool_calls()
        if pending_tool_calls:
            for tool_call in pending_tool_calls:
                state.add_tool_message(
                    content=INTERRUPTED_TOOL_RESULT,
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                )
            state.clear_pending_tool_calls()
            await self.state_manager.save(state, checkpoint_type="completed")

        # 每轮起始重置一次性的记忆上下文（由 MemoryPlugin 在 BEFORE_LLM 重新注入）
        state.memory_context = None

        # 2. 构建用户消息
        if images:
            content = [ContentPart.text_part(message)]
            for img in images:
                content.append(ContentPart.image_part(img))
            state.add_user_message(content)
        else:
            state.add_user_message(message)
        state.increment_summary_counter()
        await self.state_manager.save(state, checkpoint_type="intermediate")

        # 3. 执行管道
        errored = False
        commit_context: dict = {}
        async for event in self.pipeline.execute(
            state,
            checkpoint=self.state_manager.save,
            commit_context=commit_context,
            runtime_context=runtime_context,
        ):
            if event.type == EventType.ERROR:
                # 出错时不写最终 checkpoint，已经提交的工具进度继续保留。
                errored = True
                yield event
                break

            if event.type == EventType.INTERRUPT:
                # Pipeline 已先保存中断状态，再向上游发送事件。
                yield event
                return

            if event.type == EventType.DONE:
                continue

            yield event

        if errored:
            logger.warning(
                "本轮执行出错，已保留最近工具进度，未写入最终 checkpoint: %s",
                self.config.session_id,
            )
            return

        # 4. 保存最终状态
        await self.state_manager.save(state, checkpoint_type="completed")
        await self.plugin_manager.run_hooks(
            PluginHook.AFTER_RESPONSE_COMMIT,
            state,
            data=commit_context,
        )
        yield AgentEvent(EventType.DONE, None)

    async def resume(
        self,
        resume_data: dict
    ) -> AsyncIterator[AgentEvent]:
        """从中断恢复

        Args:
            resume_data: 恢复数据（用户确认结果）

        Yields:
            AgentEvent: 事件流
        """
        await self.initialize()
        runtime_context = RuntimeContext.capture()

        # 1. 加载状态
        state = await self.state_manager.load()

        # 2. 检查是否有中断状态
        if not state.is_interrupted():
            logger.warning("没有中断状态需要恢复")
            yield AgentEvent(EventType.ERROR, "没有中断状态需要恢复")
            return

        # 3. 恢复执行
        errored = False
        commit_context: dict = {}
        async for event in self.pipeline.resume_tools(
            state,
            resume_data,
            checkpoint=self.state_manager.save,
            commit_context=commit_context,
            runtime_context=runtime_context,
        ):
            if event.type == EventType.ERROR:
                errored = True
                yield event
                break

            # 检查新的中断
            if event.type == EventType.INTERRUPT:
                # Pipeline 已先保存新的中断状态，再向上游发送事件。
                yield event
                return

            if event.type == EventType.DONE:
                continue

            yield event

        if errored:
            logger.warning(
                "恢复执行出错，已保留最近工具进度，未写入最终 checkpoint: %s",
                self.config.session_id,
            )
            return

        # 4. 保存最终状态
        await self.state_manager.save(state, checkpoint_type="completed")
        await self.plugin_manager.run_hooks(
            PluginHook.AFTER_RESPONSE_COMMIT,
            state,
            data=commit_context,
        )
        yield AgentEvent(EventType.DONE, None)

    # ==================== 运行时操作 ====================

    def register_tool(self, tool: BaseTool) -> None:
        """运行时注册工具"""
        self.tool_manager.register(tool)

    def unregister_tool(self, name: str) -> bool:
        """运行时移除工具"""
        return self.tool_manager.unregister(name)

    async def register_plugin(self, plugin: BasePlugin) -> None:
        """运行时注册插件"""
        await self.plugin_manager.register(plugin, self)

    async def unregister_plugin(self, name: str) -> bool:
        """运行时移除插件"""
        return await self.plugin_manager.unregister(name)

    def get_tools(self) -> list[str]:
        """获取所有工具名称"""
        return self.tool_manager.list_tools()

    def get_plugins(self) -> list[str]:
        """获取所有插件名称"""
        return self.plugin_manager.list_plugins()

    # ==================== 状态操作 ====================

    async def get_state(self) -> AgentState:
        """获取当前状态"""
        await self.initialize()
        return await self.state_manager.load()

    async def clear_state(self) -> int:
        """清空状态"""
        return await self.state_manager.clear_session()

    # ==================== 生命周期 ====================

    async def close(self) -> None:
        """关闭 Agent"""
        await self.plugin_manager.close()
        await self.llm_client.close()
        await self.state_manager.close()
        logger.info(f"Agent 已关闭: {self.config.session_id}")

    async def __aenter__(self) -> "Agent":
        await self.initialize()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# ==================== 工厂函数 ====================

async def create_agent(
    session_id: str,
    model_name: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    temperature: float = 0.7,
    system_prompt: str = "",
    tools: list[str] | None = None,
    plugins: list[str] | None = None,
    mcp_servers: list[dict] | None = None
) -> Agent:
    """创建 Agent 的便捷函数"""
    config = AgentConfig(
        session_id=session_id,
        model_name=model_name,
        api_key=api_key,
        context_strategy=ContextStrategyConfig(),
        base_url=base_url,
        temperature=temperature,
        system_prompt=system_prompt,
        tools=tools or [],
        plugins=plugins or [],
        mcp_servers=mcp_servers or []
    )
    agent = Agent(config)
    await agent.initialize()
    return agent
