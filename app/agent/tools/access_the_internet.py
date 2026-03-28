from pathlib import Path
import os

import yaml
from langchain.tools import tool
from langchain_tavily import TavilySearch

from app.agent.utils.log import log_tool_call, shorten_for_log


SETTINGS_FILE = Path(__file__).resolve().parents[3] / "config" / "settings.yaml"


def _load_tavily_api_key() -> str | None:
    """读取 Tavily API Key：环境变量优先，配置文件兜底。"""
    env_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if env_key:
        return env_key

    if not SETTINGS_FILE.exists():
        return None

    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except Exception:
        return None

    key = (
        (raw.get("tavily", {}) or {}).get("api_key")
        or ""
    )
    key = str(key).strip()
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
@log_tool_call()
def access_the_internet(query: str) -> str:
    """
    访问互联网，搜索你想要的信息。

    Args:
        query: 你的搜索问题或关键词等。
    """
    if not query or not query.strip():
        return "错误: query不能为空。"

    api_key = _load_tavily_api_key()
    if not api_key:
        return "错误: 未找到 Tavily API Key。请设置环境变量 TAVILY_API_KEY 或在 config/settings.yaml 中配置。"

    # 仅在当前进程设置环境变量，供 langchain-tavily 底层客户端读取。
    os.environ["TAVILY_API_KEY"] = api_key

    try:
        search_tool = TavilySearch(
            max_results=5,
            search_depth="advanced",
            include_answer=True,
        )
        result = search_tool.invoke({"query": query.strip()})
        return _format_search_output(result)
    except ModuleNotFoundError:
        return "错误: 缺少 langchain-tavily 依赖，请先安装: pip install langchain-tavily"
    except Exception as e:
        return f"错误: Tavily检索失败: {e}"
