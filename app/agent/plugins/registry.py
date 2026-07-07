"""插件注册表。

插件清单由自动扫描 plugins/ 目录生成，按文件名延迟加载。
"""

import logging
import os
import pkgutil
from typing import Type

from app.agent.context import BasePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """插件注册表 - 自动发现插件并延迟加载。"""

    _plugins: dict[str, Type[BasePlugin]] = {}
    _lazy_plugins: dict[str, str] = {}

    @classmethod
    def register_lazy(cls, name: str, spec: str) -> None:
        """延迟注册插件。spec 支持模块路径或 模块路径:符号名。"""
        cls._lazy_plugins[name] = spec
        logger.debug("延迟注册插件: %s -> %s", name, spec)

    @classmethod
    def get(cls, name: str) -> Type[BasePlugin] | None:
        if name in cls._plugins:
            return cls._plugins[name]

        if name in cls._lazy_plugins:
            plugin_class = cls._resolve_lazy(name)
            if plugin_class:
                cls._plugins[name] = plugin_class
                return plugin_class

        return None

    @classmethod
    def _resolve_lazy(cls, name: str) -> Type[BasePlugin] | None:
        from importlib import import_module

        spec = cls._lazy_plugins.get(name)
        if not spec:
            return None

        try:
            if ":" in spec:
                module_path, symbol = spec.split(":", 1)
                module = import_module(module_path)
                plugin_class = getattr(module, symbol)
            else:
                module = import_module(spec)
                plugin_class = cls._find_plugin_class(module, name)
            if plugin_class is None:
                logger.error("延迟加载插件 '%s' 失败：模块内未找到 BasePlugin 子类", name)
                return None
            logger.info("延迟加载插件: %s", name)
            return plugin_class
        except Exception as e:
            logger.error("延迟加载插件 '%s' 失败: %s", name, e)
            return None

    @staticmethod
    def _find_plugin_class(module, name: str) -> Type[BasePlugin] | None:
        candidates = [
            obj for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, BasePlugin) and obj is not BasePlugin
        ]
        for obj in candidates:
            if getattr(obj, "name", None) == name:
                return obj
        return candidates[0] if len(candidates) == 1 else None

    @classmethod
    def list_plugins(cls) -> list[str]:
        all_names = set(cls._plugins.keys()) | set(cls._lazy_plugins.keys())
        return sorted(all_names)

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._plugins or name in cls._lazy_plugins

    @classmethod
    def clear(cls) -> None:
        cls._plugins.clear()
        cls._lazy_plugins.clear()


_NON_PLUGIN_MODULES = {"registry", "base", "__init__"}


def _discover_plugins() -> None:
    plugins_dir = os.path.dirname(__file__)
    for module_info in pkgutil.iter_modules([plugins_dir]):
        mod_name = module_info.name
        if mod_name.startswith("_") or mod_name in _NON_PLUGIN_MODULES:
            continue
        PluginRegistry.register_lazy(mod_name, f"app.agent.plugins.{mod_name}")


_discover_plugins()
