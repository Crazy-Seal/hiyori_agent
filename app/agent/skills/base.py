"""Skill 基类。

能力包：把「提示词片段 + 工具集 + 插件集」打成一个可按会话开关的单元，
复用框架已有的 tool/plugin 加载原语。
"""

from abc import ABC
from typing import Any


class BaseSkill(ABC):
    """能力包基类。

    子类通过类属性声明能力：
        class ExampleSkill(BaseSkill):
            name = "example"
            system_prompt_fragment = "你可以使用特定工具……"
            tools = ["access_the_internet"]
            plugins = []
    """

    name: str
    version: str = "1.0.0"
    # 追加到系统提示词末尾的片段
    system_prompt_fragment: str = ""
    # 该能力包引入的工具名（从 ToolRegistry 解析）
    tools: list[str] = []
    # 该能力包引入的插件名（从 PluginRegistry 解析）
    plugins: list[str] = []

    async def on_load(self, agent: Any) -> None:
        """加载时的可选初始化钩子。"""
        pass
