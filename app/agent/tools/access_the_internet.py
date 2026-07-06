"""access_the_internet 工具 - 通过 Tavily 进行互联网检索"""
import os
from pathlib import Path
from typing import Annotated

from dotenv import dotenv_values

from app.agent.tools.decorator import tool
from app.agent.utils.infra.log import shorten_for_log

# 项目根目录下的 .env（access_the_internet.py 位于 app/agent/tools/ 下，向上 3 级即根）
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _load_tavily_api_key() -> str | None:
    """读取 Tavily API Key。

    优先从项目根 .env 读取，再回退到进程环境变量。
    （系统环境变量可能缺少该键或包含过期值，因此显式加载 .env。）
    """
    key = ""
    if _ENV_PATH.exists():
        key = (dotenv_values(_ENV_PATH).get("TAVILY_API_KEY") or "").strip()
    if not key:
        key = (os.getenv("TAVILY_API_KEY") or "").strip()
    return key or None


def _format_search_output(data) -> str:
    """把搜索结果整理成紧凑可读文本。"""
    if isinstance(data, str):
        text = data.strip()
        return text if text else "未检索到相关互联网信息。"

    lines: list[str] = []
    if isinstance(data, dict):
        answer = str(data.get("answer") or "").strip()
        if answer:
            lines.append(f"综合结论: {shorten_for_log(answer, max_len=1200)}")
        results = data.get("results") or []
    elif isinstance(data, list):
        results = data
    else:
        results = []

    for idx, item in enumerate(results[:5], start=1):
        if isinstance(item, dict):
            title = str(item.get("title") or "无标题").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or item.get("snippet") or "").strip()
            content = shorten_for_log(content.replace("\n", " "), max_len=400)
        else:
            title = f"结果 {idx}"
            url = ""
            content = shorten_for_log(str(item), max_len=400)

        lines.append(f"{idx}. {title}")
        if url:
            lines.append(f"   链接: {url}")
        if content:
            lines.append(f"   摘要: {content}")

    if not lines:
        return "未检索到相关互联网信息。"
    return "互联网检索结果:\n" + "\n".join(lines)


@tool
async def access_the_internet(
    query: Annotated[str, "你的搜索问题或关键词等。"],
) -> str:
    """访问互联网，搜索你想要的信息。当用户提及你不知道的信息，或你想上网查询时使用。"""
    if not query or not query.strip():
        return "错误: query不能为空。"

    api_key = _load_tavily_api_key()
    if not api_key:
        return "错误: 未找到 Tavily API Key。请设置环境变量 TAVILY_API_KEY。"

    try:
        import httpx
    except ModuleNotFoundError:
        return "错误: 缺少 httpx 依赖，请先安装: pip install httpx"

    # 直接调用 Tavily REST API（POST https://api.tavily.com/search），不依赖任何 SDK。
    payload = {
        "query": query.strip(),
        "search_depth": "basic",
        "topic": "general",
        "max_results": 5,
        "include_answer": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException:
        return "错误: Tavily检索超时。"
    except httpx.HTTPError as e:
        return f"错误: Tavily检索请求失败: {e}"

    if response.status_code != 200:
        detail = shorten_for_log(response.text.replace("\n", " "), max_len=300)
        return f"错误: Tavily检索失败 (HTTP {response.status_code}): {detail}"

    try:
        data = response.json()
    except ValueError:
        return "错误: Tavily返回的响应无法解析为JSON。"

    return _format_search_output(data)
