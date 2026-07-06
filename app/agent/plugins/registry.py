"""
插件注册表

支持延迟加载，避免循环依赖。
"""

from typing import Callable, Type, Any
import logging

from app.agent.context import BasePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """插件注册表 - 支持延迟加载"""

    # 插件注册表：名称 -> 插件类
    _plugins: dict[str, Type[BasePlugin]] = {}

    # 延迟加载注册表：名称 -> "模块路径:符号名"
    _lazy_plugins: dict[str, str] = {}

    @classmethod
    def register(cls, name: str | None = None) -> Callable[[Type[BasePlugin]], Type[BasePlugin]]:
        """注册插件的装饰器

        Usage:
            @PluginRegistry.register()
            class MyPlugin(BasePlugin):
                name = "my_plugin"
                ...

            @PluginRegistry.register("custom_name")
            class MyPlugin(BasePlugin):
                ...
        """
        def decorator(plugin_class: Type[BasePlugin]) -> Type[BasePlugin]:
            plugin_name = name or plugin_class.name
            cls._plugins[plugin_name] = plugin_class
            logger.debug(f"注册插件: {plugin_name}")
            return plugin_class
        return decorator

    @classmethod
    def register_lazy(cls, name: str, spec: str) -> None:
        """延迟注册插件

        Args:
            name: 插件名称
            spec: "模块路径:符号名" 格式的规范字符串
        """
        cls._lazy_plugins[name] = spec
        logger.debug(f"延迟注册插件: {name} -> {spec}")

    @classmethod
    def get(cls, name: str) -> Type[BasePlugin] | None:
        """获取插件类

        Args:
            name: 插件名称

        Returns:
            插件类，如果不存在返回 None
        """
        # 先检查已加载的插件
        if name in cls._plugins:
            return cls._plugins[name]

        # 检查延迟加载
        if name in cls._lazy_plugins:
            plugin_class = cls._resolve_lazy(name)
            if plugin_class:
                cls._plugins[name] = plugin_class
                return plugin_class

        return None

    @classmethod
    def _resolve_lazy(cls, name: str) -> Type[BasePlugin] | None:
        """解析延迟加载的插件"""
        from importlib import import_module

        spec = cls._lazy_plugins.get(name)
        if not spec:
            return None

        try:
            module_path, symbol = spec.split(":", 1)
            module = import_module(module_path)
            plugin_class = getattr(module, symbol)
            logger.info(f"延迟加载插件: {name}")
            return plugin_class
        except Exception as e:
            logger.error(f"延迟加载插件 '{name}' 失败: {e}")
            return None

    @classmethod
    def list_plugins(cls) -> list[str]:
        """列出所有插件名称"""
        all_names = set(cls._plugins.keys()) | set(cls._lazy_plugins.keys())
        return sorted(all_names)

    @classmethod
    def has(cls, name: str) -> bool:
        """检查插件是否存在"""
        return name in cls._plugins or name in cls._lazy_plugins

    @classmethod
    def clear(cls) -> None:
        """清空注册表"""
        cls._plugins.clear()
        cls._lazy_plugins.clear()


# ==================== 预注册的延迟加载插件 ====================

# 在这里添加需要延迟加载的插件
LAZY_PLUGINS = {
    "memory": "app.agent.plugins.memory:MemoryPlugin",
    "context_window": "app.agent.plugins.context_window:ContextWindowPlugin",
}

for name, spec in LAZY_PLUGINS.items():
    PluginRegistry.register_lazy(name, spec)
