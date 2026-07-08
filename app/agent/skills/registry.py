"""Skill 注册表 - 支持延迟加载（仿 ToolRegistry）。"""

import logging
from importlib import import_module
from typing import Callable, Type

from app.agent.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """能力包注册表。"""

    _skills: dict[str, Type[BaseSkill]] = {}
    _lazy_skills: dict[str, str] = {}

    @classmethod
    def register(cls, name: str | None = None) -> Callable[[Type[BaseSkill]], Type[BaseSkill]]:
        def decorator(skill_class: Type[BaseSkill]) -> Type[BaseSkill]:
            skill_name = name or skill_class.name
            cls._skills[skill_name] = skill_class
            logger.debug("注册 Skill: %s", skill_name)
            return skill_class
        return decorator

    @classmethod
    def register_lazy(cls, name: str, spec: str) -> None:
        cls._lazy_skills[name] = spec

    @classmethod
    def get(cls, name: str) -> Type[BaseSkill] | None:
        if name in cls._skills:
            return cls._skills[name]
        if name in cls._lazy_skills:
            skill_class = cls._resolve_lazy(name)
            if skill_class:
                cls._skills[name] = skill_class
                return skill_class
        return None

    @classmethod
    def _resolve_lazy(cls, name: str) -> Type[BaseSkill] | None:
        spec = cls._lazy_skills.get(name)
        if not spec:
            return None
        try:
            module_path, symbol = spec.split(":", 1)
            module = import_module(module_path)
            return getattr(module, symbol)
        except Exception as e:
            logger.error("延迟加载 Skill '%s' 失败: %s", name, e)
            return None

    @classmethod
    def list_skills(cls) -> list[str]:
        return sorted(set(cls._skills) | set(cls._lazy_skills))

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._skills or name in cls._lazy_skills

    @classmethod
    def clear(cls) -> None:
        cls._skills.clear()
        cls._lazy_skills.clear()


# 预注册的延迟加载能力包（在此登记）
LAZY_SKILLS: dict[str, str] = {
}

for _name, _spec in LAZY_SKILLS.items():
    SkillRegistry.register_lazy(_name, _spec)
