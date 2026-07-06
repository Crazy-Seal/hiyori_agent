"""VLM 服务 - 屏幕定位与图片描述

- generate_multiple_image_descriptions(images, context, max_length)：多图描述并落盘
- VLMService.locate(intent, image_data_url) -> bbox：在截图中定位元素并返回 2D 边界框
  （为未来的屏幕操纵工具 control_screen 预留）

"""

import json
import logging
import os
import re
from typing import Any, cast

from openai import AsyncOpenAI

from app.agent.utils.domain.images import ImageTaskResult, save_multiple_images

logger = logging.getLogger(__name__)

VLM_DEFAULT_MODEL = "qwen3-vl-plus"
VLM_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

_LOCATE_SYSTEM_PROMPT = (
    "你是一个PC屏幕视觉分析助手。你的任务是根据用户的文字描述，"
    "在提供的截图中定位目标元素，并以JSON格式返回该元素的2D边界框。"
    "返回格式必须是 {\"bbox_2d\": [x1, y1, x2, y2]}，不要输出Markdown格式或其他内容。"
)


def _vlm_config() -> tuple[str, str, str]:
    api_key = os.getenv("VLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少VLM_API_KEY环境变量。")
    base_url = os.getenv("VLM_BASE_URL", VLM_DEFAULT_BASE_URL).strip()
    model = os.getenv("VLM_MODEL", VLM_DEFAULT_MODEL).strip()
    return api_key.strip(), base_url, model


async def generate_multiple_image_descriptions(
    images: list[str],
    context: str = "",
    max_length: int = 200,
) -> ImageTaskResult:
    """使用视觉模型生成多张图片描述，并保存图片到磁盘。

    Args:
        images: 图片数据列表，可以是完整 data URL 或纯 base64
        context: 用户消息文本，帮助理解图片上下文
        max_length: 描述最大长度（字数）

    Returns:
        ImageTaskResult 包含描述字符串和文件名列表
    """
    filenames: list[str] = []

    client: AsyncOpenAI | None = None
    try:
        # 保存所有图片到磁盘
        filenames = save_multiple_images(images)
        if not filenames:
            return ImageTaskResult(description="图片", filenames=[])

        api_key, base_url, model = _vlm_config()

        client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=3)

        # 构建多图消息内容
        content: list[dict] = []

        # 添加所有图片
        for image_data in images:
            # 如果已经是完整的 data URL，直接使用；否则添加前缀
            if image_data.startswith("data:image"):
                image_url = image_data
            else:
                image_url = f"data:image/png;base64,{image_data}"
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        # 添加文本提示
        prompt = ("你是一个视觉信息总结专家，擅长总结提取图片包含的主要内容，并用一段流畅的中文进行表达。\n"
                  "这些图片是从用户和AI助手的聊天记录片段中截取出来的，与之对应的用户文字输入也会被提供给你，请重点关注用户强调的部分的信息（如有）。\n"
                  "如有多张图片，请按顺序描述每张图片，格式例如：\"共有3张图片。第1张图片......。第2张图片......。第3张图片......。\"等。\n"
                  "注意：你的结果不应包含任何图片内容以外的信息。如图片中含有大量文字，无需详细提取，大体总结即可")
        if context:
            prompt += f"\n对应的用户文字输入：{context}"
        prompt += f"\n请开始总结图片包含的内容（{max_length}字以内）："
        content.append({"type": "text", "text": prompt})

        messages = [
            {
                "role": "user",
                "content": content,
            },
        ]

        response = await client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            stream=False,
            temperature=0.1,
        )

        if response.choices and response.choices[0].message:
            description = response.choices[0].message.content or ""
            # 截断过长的描述
            if len(description) > max_length:
                description = description[:max_length] + "..."
            logger.info("[ImageDescription] 生成图片描述: %s", description)
            return ImageTaskResult(description=description.strip(), filenames=filenames)

        return ImageTaskResult(description="图片", filenames=filenames)

    except Exception as e:
        logger.warning("[ImageDescription] 图片描述生成失败: %s", e)
        return ImageTaskResult(description="图片", filenames=filenames)
    finally:
        if client is not None:
            await client.close()


def extract_bbox(content: Any) -> list[int]:
    """从 VLM 文本响应中解析 bbox_2d [x1,y1,x2,y2]（容错 JSON 提取）。"""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    text = str(content or "").strip()
    if not text:
        raise ValueError("视觉模型未返回可解析内容。")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"{[\s\S]*}", text)
        if not match:
            raise ValueError(f"模型返回不是JSON: {text[:200]}")
        parsed = json.loads(match.group(0))

    bbox = parsed.get("bbox_2d") if isinstance(parsed, dict) else None
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError(f"缺少合法bbox_2d字段: {parsed}")
    try:
        x1, y1, x2, y2 = [int(float(v)) for v in bbox]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bbox_2d坐标不是数字: {bbox}") from exc
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"bbox_2d范围无效: {bbox}")
    return [x1, y1, x2, y2]


def clamp_bbox(bbox: list[int], width: int, height: int) -> list[int]:
    """把 bbox 夹到图像范围内。"""
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(1, min(x2, width))
    y2 = max(1, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox超出屏幕有效范围。")
    return [x1, y1, x2, y2]


class VLMService:
    """视觉模型服务。无状态，按需读取 VLM_* 环境变量。"""

    async def locate(self, intent: str, image_data_url: str) -> list[int]:
        """在截图中定位元素，返回 bbox_2d。

        Args:
            intent: 元素描述，如"屏幕中间的确定按钮"
            image_data_url: 完整 data URL（data:image/...;base64,...）
        """
        api_key, base_url, model = _vlm_config()
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _LOCATE_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": intent.strip()},
                    ]},
                ],
                stream=False,
                temperature=0,
            )
            content = ""
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
            return extract_bbox(content)
        finally:
            await client.close()
