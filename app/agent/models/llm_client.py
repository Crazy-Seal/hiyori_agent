"""
LLM API 客户端

基于官方 openai SDK（AsyncOpenAI）实现。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

from openai import AsyncOpenAI

from app.agent.message import ToolCall

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM 配置"""
    model: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


@dataclass
class LLMResponse:
    """LLM 响应（非流式）"""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length" | ...

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """流式响应块"""
    content: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None

    @property
    def is_done(self) -> bool:
        return self.finish_reason is not None


class LLMClient:
    """LLM API 客户端（AsyncOpenAI 后端）"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=3
        )

    async def close(self) -> None:
        """关闭客户端"""
        await self._client.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    # ==================== 内部工具 ====================

    def _base_payload(self, messages: list[dict], **kwargs) -> dict:
        """构造公共请求参数"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            **kwargs,
        }
        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens
        return payload

    @staticmethod
    def _accumulate_tool_call(
        acc: list[dict],
        active_by_index: dict[int, int],
        tc_delta: Any,
    ) -> None:
        """按 call id 聚合工具 delta，并兼容网关重复使用同一 index。"""
        idx = tc_delta.index if tc_delta.index is not None else 0
        incoming_id = tc_delta.id or ""

        slot_position: int | None = None
        if incoming_id:
            slot_position = next(
                (
                    position for position, candidate in enumerate(acc)
                    if candidate["id"] == incoming_id
                ),
                None,
            )

        if slot_position is None:
            active_position = active_by_index.get(idx)
            if active_position is not None and not incoming_id:
                slot_position = active_position
            elif (
                active_position is not None
                and not acc[active_position]["id"]
            ):
                slot_position = active_position
            else:
                slot_position = len(acc)
                acc.append({
                    "id": "",
                    "name": "",
                    "arguments": "",
                    "extra_content": None,
                })

        active_by_index[idx] = slot_position
        slot = acc[slot_position]
        if tc_delta.id:
            slot["id"] = tc_delta.id
        if tc_delta.function:
            if tc_delta.function.name:
                slot["name"] = tc_delta.function.name
            if tc_delta.function.arguments:
                slot["arguments"] += tc_delta.function.arguments
        extra_content = getattr(tc_delta, "extra_content", None)
        if extra_content:
            if hasattr(extra_content, "model_dump"):
                extra_content = extra_content.model_dump(exclude_none=True, mode="json")
            slot["extra_content"] = extra_content

    @staticmethod
    def _parse_tool_arguments(raw_arguments: str) -> dict:
        """解析单个完整的 JSON 对象形式工具参数。"""
        if not raw_arguments.strip():
            return {}

        try:
            value = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            logger.warning(
                "工具参数解析失败（长度=%d，错误位置=%d）",
                len(raw_arguments),
                exc.pos,
            )
            raise ValueError("工具参数解析失败：不是单个完整的 JSON 对象") from exc

        if not isinstance(value, dict):
            logger.warning("工具参数解析失败：顶层类型=%s", type(value).__name__)
            raise ValueError("工具参数解析失败：必须是 JSON 对象")

        return value

    @classmethod
    def _build_tool_call(cls, slot: dict) -> ToolCall:
        """从累积的工具调用 slot 构造 ToolCall。"""
        args = cls._parse_tool_arguments(slot["arguments"])
        return ToolCall(
            id=slot["id"],
            name=slot["name"],
            args=args,
            extra_content=slot.get("extra_content"),
        )

    # ==================== 流式调用 ====================

    async def astream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 LLM

        Yields:
            StreamChunk: 文本 delta 即时产出；工具调用在流末一次性产出（避免重复发射）。
        """
        payload = self._base_payload(messages, stream=True, **kwargs)
        if tools:
            payload["tools"] = tools

        # 按 call id 累积工具调用，index 仅用于路由缺少 id 的后续分片。
        tool_acc: list[dict] = []
        active_tool_by_index: dict[int, int] = {}
        final_reason: str | None = None

        try:
            stream = await self._client.chat.completions.create(**payload)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta and delta.content:
                    yield StreamChunk(content=delta.content)

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        self._accumulate_tool_call(
                            tool_acc,
                            active_tool_by_index,
                            tc_delta,
                        )

                if choice.finish_reason:
                    final_reason = choice.finish_reason

            # 流结束：一次性产出完整工具调用
            for slot in tool_acc:
                yield StreamChunk(tool_call=self._build_tool_call(slot))

            yield StreamChunk(finish_reason=final_reason or "stop")

        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
            raise

    # ==================== 非流式调用 ====================

    async def ainvoke(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """非流式调用 LLM"""
        payload = self._base_payload(messages, stream=False, **kwargs)
        if tools:
            payload["tools"] = tools

        try:
            completion = await self._client.chat.completions.create(**payload)
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            raise

        choice = completion.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = self._parse_tool_arguments(tc.function.arguments or "")
                extra_content = getattr(tc, "extra_content", None)
                if extra_content and hasattr(extra_content, "model_dump"):
                    extra_content = extra_content.model_dump(exclude_none=True, mode="json")
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=args,
                    extra_content=extra_content,
                ))

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )

    # ==================== 结构化输出 ====================

    async def ainvoke_structured(
        self,
        messages: list[dict],
        schema: dict,
        **kwargs,
    ) -> dict:
        """结构化输出调用 LLM（json_schema 强约束）"""
        max_attempts = 2
        payload = self._base_payload(
            messages,
            stream=False,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": schema,
                },
            },
            **kwargs,
        )

        for attempt in range(1, max_attempts + 1):
            try:
                completion = await self._client.chat.completions.create(**payload)
            except Exception as e:
                logger.error("LLM 结构化输出调用失败: %s", e)
                raise

            choice = completion.choices[0]
            finish_reason = choice.finish_reason or "unknown"
            content = choice.message.content or ""
            content_length = len(content)

            if finish_reason != "stop":
                logger.warning(
                    "LLM 结构化输出未正常结束: model=%s, attempt=%d/%d, "
                    "finish_reason=%s, content_length=%d",
                    self.config.model,
                    attempt,
                    max_attempts,
                    finish_reason,
                    content_length,
                )
                if attempt < max_attempts:
                    continue
                raise RuntimeError(
                    "LLM 结构化输出未正常结束: "
                    f"finish_reason={finish_reason}, attempts={max_attempts}"
                )

            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "LLM 结构化输出 JSONDecodeError: model=%s, attempt=%d/%d, "
                    "finish_reason=%s, content_length=%d, line=%d, column=%d, "
                    "position=%d",
                    self.config.model,
                    attempt,
                    max_attempts,
                    finish_reason,
                    content_length,
                    exc.lineno,
                    exc.colno,
                    exc.pos,
                )
                if attempt < max_attempts:
                    continue
                raise

            if attempt > 1:
                logger.info(
                    "LLM 结构化输出重试成功: model=%s, attempt=%d/%d",
                    self.config.model,
                    attempt,
                    max_attempts,
                )
            return result

        raise RuntimeError("LLM 结构化输出重试流程异常结束")


def create_llm_client(
    model: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> LLMClient:
    """创建 LLM 客户端的便捷函数"""
    config = LLMConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return LLMClient(config)
