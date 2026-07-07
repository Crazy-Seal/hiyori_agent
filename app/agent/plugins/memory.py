"""记忆插件。

处理图片描述、记忆检索、对话保存和长期记忆抽取。
"""

import asyncio
import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.agent.context import BasePlugin, PluginHook, HookContext
from app.agent.memory.manager import get_memory_manager
from app.agent.message import (
    is_real_human_message,
    messages_from_openai_format,
)
from app.agent.models.vlm import generate_multiple_image_descriptions
from app.agent.utils.infra.background_tasks import create_background_task
from app.agent.utils.domain.images import (
    ImageTaskResult,
    cancel_task,
    clear_task,
    get_image_task,
    has_image_content,
    set_image_task,
)
from app.agent.utils.domain.text import extract_text, get_last_human_text, split_context

logger = logging.getLogger(__name__)


class MemoryPluginConfig(BaseModel):
    enable_diary: bool = Field(default=True, description="是否启用日记/摘要记忆。")
    enable_episodic: bool = Field(default=True, description="是否启用情景记忆。")
    enable_semantic: bool = Field(default=True, description="是否启用语义记忆。")
    summary_every_human_messages: int = Field(
        default=10,
        ge=1,
        description="每多少轮真实用户消息触发长期记忆总结/抽取。",
    )


MEMORY_PREAMBLE = (
    "以下文本是你的记忆，其中，[你的历史日记和摘要]是你对前段时间和当前对话的记忆，"
    "[相关情景记忆]和[相关语义知识]是系统根据用户输入检索到的，你记忆的更早之前的事情。"
)


class MemoryPlugin(BasePlugin):
    name = "memory"
    description = "检索和沉淀长期记忆，并处理图片记忆描述。"
    inherent = True
    config_model = MemoryPluginConfig
    version = "1.0.0"
    priority = 100

    def __init__(self, **config: Any) -> None:
        self.config = MemoryPluginConfig(**config)
        self._task_keys: set[str] = set()

    @property
    def hooks(self) -> list[PluginHook]:
        return [
            PluginHook.ON_INVOKE,
            PluginHook.BEFORE_LLM,
            PluginHook.BEFORE_RESPONSE,
        ]

    def _mm(self, state):
        return get_memory_manager(state.session_id)

    async def execute(self, context: HookContext) -> HookContext:
        state = context.agent_state
        if context.hook == PluginHook.ON_INVOKE:
            self._start_image_description(state)
        elif context.hook == PluginHook.BEFORE_LLM:
            await self._inject_context(state)
        elif context.hook == PluginHook.BEFORE_RESPONSE:
            await self._finalize(state)
        return context

    def _start_image_description(self, state) -> None:
        target = next(
            (msg for msg in reversed(state.messages) if is_real_human_message(msg)),
            None,
        )
        if target is None:
            return

        content = target.get("content")
        if not has_image_content(content):
            return

        images = [
            part["image_url"]["url"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "image_url"
            and part.get("image_url")
        ]
        if not images:
            return

        text = extract_text(content)
        key = uuid.uuid4().hex
        task = asyncio.create_task(generate_multiple_image_descriptions(images, text, 200))
        set_image_task(key, task)
        self._task_keys.add(key)
        state.extra["image_task_key"] = key
        logger.info("[MemoryPlugin] 启动图片描述任务: %s (%d 张)", key, len(images))

    async def on_unregister(self) -> None:
        for key in self._task_keys:
            cancel_task(key)
        self._task_keys.clear()

    async def _inject_context(self, state) -> None:
        if state.memory_context is not None:
            return
        query = get_last_human_text(state.messages)
        try:
            ctx = await self._mm(state).get_context(
                query=query,
                include_diary=self.config.enable_diary,
                include_episodic=self.config.enable_episodic,
                include_semantic=self.config.enable_semantic,
            )
        except Exception as e:
            logger.warning("[MemoryPlugin] 记忆检索失败: %s", e)
            ctx = ""
        state.memory_context = f"{MEMORY_PREAMBLE}\n\n{ctx}" if ctx and ctx.strip() else ""

    async def _finalize(self, state) -> None:
        state.summary_counter += 1
        next_counter = state.summary_counter

        image_description, image_filenames = await self._await_image(state)
        self._annotate_latest_image_message(state, image_description, image_filenames)
        mm = self._mm(state)

        last_human = get_last_human_text(state.messages)
        ai_messages = self._extract_new_ai_messages(state.messages)
        has_text = any(m.get("content") for m in ai_messages)

        if last_human and ai_messages and has_text:
            create_background_task(
                mm.try_summary(
                    last_human,
                    ai_messages,
                    image_description,
                    image_filenames,
                    enable_diary=self.config.enable_diary,
                ),
                logger=logger,
                task_name="memory.try_summary",
            )
        elif not has_text:
            logger.warning("[MemoryPlugin] AI 无有效文本输出，跳过保存本轮对话")

        if next_counter >= self.config.summary_every_human_messages:
            history_msgs, recent_msgs = split_context(
                state.messages,
                later_human_count=self.config.summary_every_human_messages,
                previous_human_count=5,
            )
            if self.config.enable_episodic or self.config.enable_semantic:
                create_background_task(
                    self._persist(mm, recent_msgs, history_msgs),
                    logger=logger,
                    task_name="memory.persist",
                )
            state.summary_counter = 0

    async def _persist(self, mm, recent_dicts: list[dict], history_dicts: list[dict]) -> None:
        recent = messages_from_openai_format(recent_dicts)
        history = messages_from_openai_format(history_dicts)
        await mm.add(
            recent,
            history,
            enable_episodic=self.config.enable_episodic,
            enable_semantic=self.config.enable_semantic,
        )

    async def _await_image(self, state):
        key = state.extra.get("image_task_key")
        if not key:
            return None, None
        task = get_image_task(key)
        if task is None:
            self._task_keys.discard(key)
            state.extra.pop("image_task_key", None)
            return None, None
        try:
            result: ImageTaskResult = await task
            desc, files = result.description, result.filenames
            logger.info("[MemoryPlugin] 获取图片描述: %s", desc)
        except Exception as e:
            logger.warning("[MemoryPlugin] 图片描述任务失败: %s", e)
            desc, files = "图片", []
        finally:
            clear_task(key)
            self._task_keys.discard(key)
            state.extra.pop("image_task_key", None)
        return desc, files

    def _annotate_latest_image_message(
        self,
        state,
        image_description: str | None,
        image_filenames: list[str] | None,
    ) -> None:
        if not image_description:
            return

        target = next(
            (msg for msg in reversed(state.messages) if is_real_human_message(msg)),
            None,
        )
        if target is None:
            return

        content = target.get("content")
        if not has_image_content(content):
            return

        target["image_description"] = image_description
        target["image_filenames"] = image_filenames or []

    def _extract_new_ai_messages(self, messages: list[dict]) -> list[dict]:
        """提取最后一条真实人类消息之后的 assistant 消息。"""
        last_human_idx = -1
        for index in range(len(messages) - 1, -1, -1):
            if is_real_human_message(messages[index]):
                last_human_idx = index
                break
        if last_human_idx < 0:
            return []

        result: list[dict] = []
        for msg in messages[last_human_idx + 1:]:
            if msg.get("role") != "assistant":
                continue
            tool_calls = [
                {"name": (tc.get("function") or {}).get("name", "未知工具")}
                for tc in (msg.get("tool_calls") or [])
            ]
            content = extract_text(msg.get("content"))
            if not content and not tool_calls:
                continue
            result.append({"content": content, "tool_calls": tool_calls})
        return result
